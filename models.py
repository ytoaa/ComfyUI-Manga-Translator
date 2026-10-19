"""Standalone ComfyUI model wrappers using attributed local inference adapters."""
from pathlib import Path
import json
import logging
import math
import numpy as np
from PIL import Image

_MODELS = {}
LOG = logging.getLogger(__name__)
_DETECTOR_NATIVE_SIZE = 1152


def catalog(kind):
    import folder_paths
    category = 'manga_detection' if kind == 'detection' else 'manga_ocr'
    folder_paths.add_model_folder_path(category,str(Path(folder_paths.models_dir)/'manga_translator'/kind))
    roots = list(folder_paths.get_folder_paths(category))
    # Read-only compatibility lookup for existing bundles. No old plugin import.
    roots.append(str(Path(folder_paths.models_dir)/'koharu'/kind))
    legacy = 'koharu_detection' if kind=='detection' else 'koharu_ocr'
    if legacy in folder_paths.folder_names_and_paths:
        roots.extend(folder_paths.get_folder_paths(legacy))
    markers = ('model.safetensors','load_model.py','inference_config.json') if kind=='detection' else ('model.safetensors','modeling_hayai.py','config.json')
    found, seen = {}, set()
    for root in roots:
        root = Path(root)
        pending = [root]
        while pending:
            directory = pending.pop()
            if not directory.is_dir():
                continue
            resolved = directory.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if all((directory/name).is_file() for name in markers):
                name = directory.relative_to(root).as_posix()
                found.setdefault(directory.name if name=='.' else name,resolved)
            else:
                pending.extend(sorted((child for child in directory.iterdir() if child.is_dir()),reverse=True))
    return dict(sorted(found.items()))


def _bundle_generation(folder):
    from .stage_cache import file_identity
    return tuple((p.name,file_identity(p)) for p in sorted(folder.iterdir()) if p.is_file())


class _GenerationBoundBackend:
    """Do not label resident inference with files replaced during execution."""
    def __init__(self,backend,folder,generation):
        self._backend,self._folder,self._generation=backend,folder,generation
        self.cache_identity={'folder':str(folder),'files':dict(generation)}
    def __getattr__(self,name):
        value=getattr(self._backend,name)
        if name not in ('detect','ocr') or not callable(value):return value
        def infer(*args,**kwargs):
            self._verify()
            result=value(*args,**kwargs)
            self._verify()
            return result
        return infer
    def _verify(self):
        if _bundle_generation(self._folder)!=self._generation:
            raise ValueError('Resident model bundle changed; reload the model before inference')


def load(kind, model_name):
    available = catalog(kind)
    if model_name not in available:
        raise ValueError('Select an existing complete model bundle from models/manga_translator/'+kind)
    folder = available[model_name]
    generation=_bundle_generation(folder)
    key = (kind,str(folder),generation)
    if key not in _MODELS:
        if kind=='detection':
            from .adapters.model import Backend
        else:
            from .adapters.hayai import Backend
        backend=Backend(folder)
        if generation!=_bundle_generation(folder):
            raise ValueError('Model bundle changed during loading; retry with a stable bundle')
        for old in list(_MODELS):
            if old[:2]==key[:2]:del _MODELS[old]
        _MODELS[key] = _GenerationBoundBackend(backend,folder,generation)
    return _MODELS[key]


def _rgb_array(images):
    if images.ndim!=4 or images.shape[0]!=1 or images.shape[-1]!=3:
        raise ValueError('Expected one RGB image')
    array=images[0].detach().cpu().numpy()
    if not array.size or not np.isfinite(array).all() or array.min()<0 or array.max()>1:
        raise ValueError('Expected finite RGB pixels within [0, 1]')
    return array


def pil_image(images):
    array=_rgb_array(images)
    pixels = (array*255).round().astype(np.uint8)
    return Image.fromarray(pixels).convert('RGB')


def _validate_thresholds(thresholds):
    if any(not isinstance(v,(int,float)) or not np.isfinite(v) or not 0<=v<=1 for v in thresholds.values()):
        raise ValueError('Invalid detection thresholds')


def _bands(profile, min_gap=4, min_extent=8):
    indices = np.flatnonzero(profile)
    if not len(indices):
        return []
    cuts = np.flatnonzero(np.diff(indices) > 1) + 1
    groups = []
    for values in np.split(indices,cuts):
        start,end = int(values[0]),int(values[-1])+1
        if groups and start-groups[-1][1] < min_gap:
            groups[-1][1] = end
        else:
            groups.append([start,end])
    return [group for group in groups if group[1]-group[0] >= min_extent]


def _ocr_line_images(image, direction='auto'):
    """Split one detector crop into reading-order line crops like the proven Koharu path.

    This stays internal to the OCR node so the workflow does not need custom
    splitter/joiner nodes. Ambiguous or weak crops remain unchanged.
    """
    from scipy import ndimage

    width,height = image.size
    if direction not in ('auto','horizontal','vertical_rtl','vertical_ltr'):
        raise ValueError('Invalid OCR text direction')
    background_window = 31
    contrast = 16.0
    ink_fraction = 0.002
    min_gap = 4
    min_line_extent = 8
    padding = 2
    max_lines = 32

    def unchanged(reason):
        LOG.info('OCR line segmentation: source=%sx%s, crops=1, direction=unchanged, reason=%s',
                 width,height,reason)
        return [image]

    pixels = np.asarray(image.convert('RGB'),dtype=np.float32)
    if not np.isfinite(pixels).all():
        raise ValueError('OCR source contains nonfinite pixels')
    gray = pixels @ np.array([0.299,0.587,0.114],dtype=np.float32)
    detail = gray-ndimage.uniform_filter(gray,size=background_window,mode='reflect')
    positive = float(np.percentile(detail,99))
    negative = -float(np.percentile(detail,1))
    if max(positive,negative) < contrast:
        return unchanged('low_contrast')
    polarity = 'bright' if positive>negative*1.2 else 'dark' if negative>positive*1.2 else 'both'
    foreground = (detail>contrast if polarity=='bright' else
                  detail < -contrast if polarity=='dark' else np.abs(detail)>contrast)

    def candidate(horizontal):
        cross = width if horizontal else height
        projection = foreground.sum(axis=1 if horizontal else 0) >= max(2,math.ceil(cross*ink_fraction))
        return _bands(projection,min_gap,min_line_extent)

    if direction == 'auto':
        choices = []
        for name,horizontal in [('horizontal',True),('vertical_rtl',False)]:
            proposed = candidate(horizontal)
            if 2 <= len(proposed) <= max_lines:
                # Shape alone confuses a tall horizontal paragraph with
                # vertical writing. Require actual elongated text rows/columns.
                # Individual letters of one horizontal line are not columns.
                elongated=0
                for start,end in proposed:
                    indices=np.flatnonzero(foreground[start:end,:].any(axis=0) if horizontal
                                           else foreground[:,start:end].any(axis=1))
                    if len(indices) and indices[-1]-indices[0]+1 >= 3*(end-start):
                        elongated+=1
                if elongated < math.ceil(len(proposed)*.75):
                    continue
                gaps = sum(right[0]-left[1] for left,right in zip(proposed,proposed[1:]))
                span = proposed[-1][1]-proposed[0][0]
                choices.append((gaps/span,name))
        choices.sort(reverse=True)
        if not choices:
            return unchanged('no_separated_rows_or_columns')
        if len(choices)==2 and (choices[0][0] < choices[1][0]*1.5 or choices[0][0]-choices[1][0] < 0.05):
            return unchanged('ambiguous_rows_and_columns')
        direction = choices[0][1]

    horizontal = direction == 'horizontal'
    found = candidate(horizontal)
    if not 2 <= len(found) <= max_lines:
        return unchanged('insufficient_bands')

    # Cuts stay inside detected gaps. Every source pixel belongs to one line;
    # the small overlap added by padding only supplies OCR context.
    extent = height if horizontal else width
    cuts = [0]+[(left[1]+right[0])//2 for left,right in zip(found,found[1:])]+[extent]
    crops = []
    for start,end in zip(cuts,cuts[1:]):
        start,end = max(0,start-padding),min(extent,end+padding)
        box = (0,start,width,end) if horizontal else (start,0,end,height)
        crops.append(image.crop(box))
    if direction == 'vertical_rtl':
        crops.reverse()
    LOG.info('OCR line segmentation: source=%sx%s, crops=%s, direction=%s',
             width,height,len(crops),direction)
    return crops


def _tight_ocr_image(image, padding=4, contrast=12.0):
    """Trim detector/line whitespace so Hayai spends more NaFlex patches on glyphs."""
    from scipy import ndimage

    width,height = image.size
    if min(width,height) < 4:
        return image
    pixels = np.asarray(image.convert('RGB'),dtype=np.float32)
    gray = pixels @ np.array([0.299,0.587,0.114],dtype=np.float32)
    detail = gray-ndimage.uniform_filter(gray,size=31,mode='reflect')
    foreground = np.abs(detail) >= contrast
    labels,count = ndimage.label(foreground)
    if count:
        sizes = np.bincount(labels.ravel(),minlength=count+1)
        minimum = max(2,int(math.ceil(width*height*0.0002)))
        keep = sizes >= minimum
        keep[0] = False
        # Large components locate the text body; small punctuation/dakuten
        # still belong to its crop. Do not discard them when choosing bounds.
        if not keep[labels].any():
            return image
    ys,xs = np.nonzero(foreground)
    if not len(xs):
        return image
    left=max(0,int(xs.min())-padding); top=max(0,int(ys.min())-padding)
    right=min(width,int(xs.max())+1+padding); bottom=min(height,int(ys.max())+1+padding)
    # Do not accept a pathological tiny crop from one isolated component.
    if right-left < 4 or bottom-top < 4:
        return image
    result=image.crop((left,top,right,bottom))
    LOG.info('OCR tight crop: source=%sx%s, tight=%sx%s',width,height,result.width,result.height)
    return result


def _axis_windows(length, parts, overlap):
    if parts <= 1:
        return [(0,length,0,length)]
    edges=[round(i*length/parts) for i in range(parts+1)]
    windows=[]
    for index in range(parts):
        core_start,core_end=edges[index],edges[index+1]
        start=max(0,core_start-overlap)
        end=min(length,core_end+overlap)
        windows.append((start,end,core_start,core_end))
    return windows


def _detail_parts(width,height,mode):
    if mode == 'off':
        grid=1
    elif mode == '2x':
        grid=2
    elif mode == '3x':
        grid=3
    elif mode == 'auto':
        longest=max(width,height)
        grid=1 if longest <= 1280 else 2 if longest <= 3200 else 3
    else:
        raise ValueError('Invalid detector detail mode')
    cols=grid if width > _DETECTOR_NATIVE_SIZE else 1
    rows=grid if height > _DETECTOR_NATIVE_SIZE else 1
    return cols,rows


def _offset_detection(item,left,top,page_width,page_height):
    box=item.get('bbox')
    if not isinstance(box,list) or len(box)!=4:
        raise ValueError('Detail detector returned an invalid box')
    shifted={**item,'bbox':[float(box[0])+left,float(box[1])+top,float(box[2])+left,float(box[3])+top]}
    raw=item.get('mask')
    if raw is not None:
        if not isinstance(raw,dict) or any(type(raw.get(key)) is not int for key in ('x','y','width','height')):
            raise ValueError('Detail detector returned an invalid mask')
        shifted['mask']={**raw,'x':raw['x']+left,'y':raw['y']+top}
    shifted['bbox']=[max(0.,min(float(page_width),value)) if index%2==0 else max(0.,min(float(page_height),value))
                     for index,value in enumerate(shifted['bbox'])]
    return shifted


def _detail_detect(image,model,thresholds,detail_mode='auto',detail_overlap=64):
    """Full-page RF-DETR plus a center-owned tiled pass for small lettering.

    Global upscaling is intentionally not used: the backend always resizes its
    input to 1152x1152, so enlarging the whole page is cancelled by that resize.
    Cropping into tiles actually increases the glyph scale seen by the model.
    """
    full=model.detect(image,thresholds)
    width,height=image.size
    if (full.get('image_width'),full.get('image_height')) != (width,height):
        raise ValueError('Detector result dimensions differ from source image')
    if type(detail_overlap) is not int or not 0 <= detail_overlap <= 384:
        raise ValueError('Detector detail overlap must be 0..384 pixels')
    cols,rows=_detail_parts(width,height,detail_mode)
    if cols==1 and rows==1:
        return {**full,'detail_detection':{'mode':detail_mode,'grid':[1,1],'tiles':0,'detail_regions':0}}

    x_windows=_axis_windows(width,cols,detail_overlap)
    y_windows=_axis_windows(height,rows,detail_overlap)
    recovered=[]; tile_count=0
    for y0,y1,core_y0,core_y1 in y_windows:
        for x0,x1,core_x0,core_x1 in x_windows:
            tile_count += 1
            tile=image.crop((x0,y0,x1,y1))
            result=model.detect(tile,thresholds)
            for item in result.get('detections',[]):
                box=item.get('bbox')
                if not isinstance(box,list) or len(box)!=4:
                    raise ValueError('Detail detector returned an invalid box')
                cx=(float(box[0])+float(box[2]))/2+x0
                cy=(float(box[1])+float(box[3]))/2+y0
                # Each detection belongs to exactly one non-overlapped core.
                if not (core_x0 <= cx < core_x1 or (core_x1==width and cx<=core_x1)):
                    continue
                if not (core_y0 <= cy < core_y1 or (core_y1==height and cy<=core_y1)):
                    continue
                recovered.append(_offset_detection(item,x0,y0,width,height))
    if len(full.get('detections',[]))+len(recovered) > 512:
        raise ValueError('Detail detector produced too many regions; lower detail mode or thresholds')
    LOG.info('RF-DETR detail pass: source=%sx%s grid=%sx%s tiles=%s full=%s detail=%s',
             width,height,cols,rows,tile_count,len(full.get('detections',[])),len(recovered))
    return {**full,'detections':list(full.get('detections',[]))+recovered,
            'detail_detection':{'mode':detail_mode,'grid':[cols,rows],'tiles':tile_count,'detail_regions':len(recovered)}}


def _ocr_once(model,image,options,max_patches,repetition_penalty,retry_on_repetition,
              retry_on_token_limit=False,diagnostics=None):
    from .adapters.hayai import HayaiOutputError
    used_repetition=used_tokens=False
    current=options
    for _ in range(3):
        record={'max_new_tokens':current.max_new_tokens,'repetition_penalty':current.repetition_penalty}
        try:
            text=model.ocr(image,current,max_patches=max_patches)['text']
        except HayaiOutputError as exc:
            record['status']=exc.code
            if diagnostics is not None:diagnostics.append(record)
            if (exc.code=='ocr_repetition_loop' and retry_on_repetition and not used_repetition
                    and current.repetition_penalty<2):
                used_repetition=True
                penalty=min(2.,max(1.1,current.repetition_penalty+.1))
                current=current.model_copy(update={'repetition_penalty':penalty})
                LOG.warning('Retrying one repeated OCR crop with penalty %.2f',penalty)
            elif (exc.code=='ocr_token_limit' and retry_on_token_limit and not used_tokens
                  and current.max_new_tokens<2048):
                used_tokens=True
                budget=min(2048,current.max_new_tokens*2)
                LOG.warning('Retrying token-limited OCR crop=%sx%s with tokens=%s->%s',
                            image.width,image.height,current.max_new_tokens,budget)
                current=current.model_copy(update={'max_new_tokens':budget})
            else:
                raise
        else:
            record['status']='accepted'
            if diagnostics is not None:diagnostics.append(record)
            return text
    raise RuntimeError('OCR retry bound exceeded')


class MangaDetectorLoader:
    @classmethod
    def IS_CHANGED(cls,model_name):
        from .stage_cache import model_identity
        return model_identity('MangaDetectorLoader',{'model_name':model_name})
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'model_name': (list(catalog('detection')) or ['(no models found)'],)}}
    RETURN_TYPES = ('MANGA_DETECTOR_MODEL',)
    FUNCTION = 'select'
    CATEGORY = 'Manga Translator/Models'
    def select(self, model_name):
        return (load('detection',model_name),)


class MangaOCRLoader:
    @classmethod
    def IS_CHANGED(cls,model_name):
        from .stage_cache import model_identity
        return model_identity('MangaOCRLoader',{'model_name':model_name})
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'model_name': (list(catalog('ocr')) or ['(no models found)'],)}}
    RETURN_TYPES = ('MANGA_OCR_MODEL',)
    FUNCTION = 'select'
    CATEGORY = 'Manga Translator/Models'
    def select(self, model_name):
        return (load('ocr',model_name),)


class MangaDetector:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images':('IMAGE',),'model':('MANGA_DETECTOR_MODEL',),
            **{key:('FLOAT',{'default':value,'min':0.,'max':1.,'step':0.01}) for key,value in
               {'text':0.25,'onomatopoeia':0.20,'bubble':0.50,'panel':0.50}.items()}}}
    RETURN_TYPES = ('MANGA_DETECTION',)
    FUNCTION = 'detect'
    CATEGORY = 'Manga Translator/Detection'
    def detect(self, images, model, **thresholds):
        _validate_thresholds(thresholds)
        return (model.detect(pil_image(images),thresholds),)


class MangaDetectorDetail:
    DESCRIPTION = '전체 페이지 검출 뒤 큰 페이지를 겹친 타일로 다시 검출해 작은 글씨 누락을 줄입니다. 전역 업스케일 대신 실제 모델 입력에서 글자를 크게 보이게 합니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images':('IMAGE',),'model':('MANGA_DETECTOR_MODEL',),
            **{key:('FLOAT',{'default':value,'min':0.,'max':1.,'step':0.01}) for key,value in
               {'text':0.25,'onomatopoeia':0.20,'bubble':0.50,'panel':0.50}.items()},
            'detail_mode':(['auto','off','2x','3x'],{'default':'auto'}),
            'detail_overlap':('INT',{'default':64,'min':0,'max':384,'step':16})}}
    RETURN_TYPES=('MANGA_DETECTION',)
    FUNCTION='detect'
    CATEGORY='Manga Translator/Detection'
    def detect(self,images,model,detail_mode='auto',detail_overlap=64,**thresholds):
        _validate_thresholds(thresholds)
        return (_detail_detect(pil_image(images),model,thresholds,detail_mode,detail_overlap),)


class MangaOCR:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images':('IMAGE',),'model':('MANGA_OCR_MODEL',),
            'max_new_tokens':('INT',{'default':512,'min':1,'max':2048}),
            'max_patches':([256,512,1024],{'default':1024}),
            'repetition_penalty':('FLOAT',{'default':1.,'min':1.,'max':2.,'step':0.01}),
            'retry_on_repetition':('BOOLEAN',{'default':True})}}
    RETURN_TYPES = ('STRING',)
    FUNCTION = 'read'
    CATEGORY = 'Manga Translator/OCR'
    def read(self, images, model, max_new_tokens=512, max_patches=1024, repetition_penalty=1., retry_on_repetition=True):
        from .adapters.options import OcrOptions
        if type(max_patches) is not int or max_patches not in (256,512,1024) or type(retry_on_repetition) is not bool:
            raise ValueError('Invalid OCR settings')
        options=OcrOptions(max_new_tokens=max_new_tokens,repetition_penalty=repetition_penalty)
        lines=_ocr_line_images(pil_image(images))
        text='\n'.join(_ocr_once(model,image,options,max_patches,repetition_penalty,retry_on_repetition) for image in lines)
        return (text,)


def _empty_ocr_page(images, manifest_json):
    if manifest_json is None:
        return False
    from .nodes import layout
    data = layout(manifest_json)
    if data['regions']:
        return False
    if (data.get('crop_passthrough') is not True or images.ndim != 4 or images.shape[0] != 1
            or images.shape[-1] != 3
            or (data.get('image_width'),data.get('image_height')) != (images.shape[2],images.shape[1])):
        raise ValueError('Empty-page OCR requires the matching MangaRegionCrops manifest and page preview')
    _rgb_array(images)
    return True


def _uniform_ocr_crop(images):
    return all(low==high for low,high in pil_image(images).getextrema())


def _unverified_ocr_input(image):
    """Recognize weak pixel evidence, without certifying absence of language.

    A rule can be a sound mark and an impulse a tiny period. Preserve these for
    review, rather than inventing OCR text. Coherent faint strokes remain eligible.
    """
    gray=np.asarray(image,dtype=np.float32).mean(axis=2)
    height,width=gray.shape
    if min(height,width)<2:return {'method':'insufficient_text_evidence','reason':'degenerate_crop'}
    for values in (gray,gray.T):
        changes=np.diff(values[0])
        if (np.all(values==values[:1]) and np.max(np.abs(changes))<=1
                and (np.all(changes>=0) or np.all(changes<=0))):
            return {'method':'insufficient_text_evidence','reason':'smooth_pixels'}
    background=float(np.median(gray));ink=np.abs(gray-background)>max(1,float(np.ptp(gray))*.35)
    ys,xs=np.nonzero(ink)
    if 0<len(xs)<=2:
        return {'method':'insufficient_text_evidence','reason':'isolated_pixels'}
    if len(xs) and ((ys.max()==ys.min() and xs.max()-xs.min()>=width*.95)
                    or (xs.max()==xs.min() and ys.max()-ys.min()>=height*.95)):
        return {'method':'insufficient_text_evidence','reason':'edge_spanning_rule'}
    if gray.size>=4096 and np.ptp(gray)<=3:
        correlations=[]
        for a,b in ((gray[:,:-1],gray[:,1:]),(gray[:-1],gray[1:]),
                    (gray[:-1,:-1],gray[1:,1:]),(gray[:-1,1:],gray[1:,:-1])):
            if a.std() and b.std():correlations.append(float(np.corrcoef(a.ravel(),b.ravel())[0,1]))
        if correlations and max(correlations)<.1:
            return {'method':'insufficient_text_evidence','reason':'uncorrelated_low_contrast_pixels'}
    return None


def _save_ocr_failure(source, image, diagnostic):
    """Keep inspectable inputs even though a failed node cannot emit previews."""
    try:
        import folder_paths
        import uuid
        folder=Path(folder_paths.get_output_directory())/'manga_translator'/'ocr_failures'
        folder.mkdir(parents=True,exist_ok=True)
        prefix='ocr_'+uuid.uuid4().hex
        source_path=folder/(prefix+'_source.png')
        input_path=folder/(prefix+'_input.png')
        report_path=folder/(prefix+'.json')
        source.save(source_path);image.save(input_path)
        report={**diagnostic,'source_size':list(source.size),'input_size':list(image.size),
                'source_image':str(source_path),'failed_input_image':str(input_path)}
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        LOG.error('OCR failure inputs saved: %s',report_path)
        return str(report_path)
    except Exception as exc:
        LOG.warning('Could not save OCR failure inputs: %s',type(exc).__name__)
        return None


class MangaOCRAdaptive:
    DESCRIPTION = '영역을 행/열로 분리하고 여백을 줄인 뒤 작은 글씨에 더 큰 Hayai patch budget을 자동 배정합니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images':('IMAGE',),'model':('MANGA_OCR_MODEL',{'lazy':True}),
            'max_new_tokens':('INT',{'default':256,'min':1,'max':2048}),
            'base_patches':([256,512,1024],{'default':512}),
            'small_text_patches':([512,1024],{'default':1024}),
            'small_text_px':('INT',{'default':48,'min':8,'max':256}),
            'line_split':('BOOLEAN',{'default':True}),
            'tight_crop':('BOOLEAN',{'default':False}),
            'repetition_penalty':('FLOAT',{'default':1.,'min':1.,'max':2.,'step':0.01}),
            'retry_on_repetition':('BOOLEAN',{'default':True})},
            'optional': {
                'manifest_json': ('STRING', {'forceInput':True,
                    'tooltip':'MangaRegionCrops의 페이지 명세. 0개 영역은 OCR 모델을 로드하지 않고 건너뜁니다.'}),
                'region_plan_json': ('STRING', {'forceInput':True,
                    'tooltip':'MangaRegionCrops의 ocr_region_plans. 검증된 페이지 본문 행을 실패 전부터 분리해 읽습니다.'}),
                'split_long_lines': ('BOOLEAN', {'default':False, 'tooltip':'긴 가로 행을 글자 사이 빈 공간에서만 나눠 읽습니다. 기존 그래프는 원래 입력을 유지합니다.'}),
                'quality_guard': ('BOOLEAN', {'default':False, 'tooltip':'짧은 반복·과도한 누락 의심 시 다른 patch 설정으로 1회 재시도. 선택한 입력 재분할 복구도 실패하면 번역 전에 중단. 정확도 보증은 아닙니다.'}),
                'text_direction': (['auto','horizontal','vertical_rtl','vertical_ltr'], {'default':'auto',
                    'tooltip':'OCR 행/열 분할 방향. 세로로 긴 가로 본문은 horizontal로 지정할 수 있습니다. 식자 방향과 별도입니다.'}),
                'retry_on_token_limit': ('BOOLEAN', {'default':False,
                    'tooltip':'토큰 한도에 닿으면 요청 한도를 2배(최대 2048)로 한 번 재시도합니다. 잘린 결과는 반환하지 않습니다.'}),
                'retry_on_layout_failure': ('BOOLEAN', {'default':False,
                    'tooltip':'품질 재시도도 실패하면 검증된 행/열 간격에서 입력을 한 번 다시 나눕니다. 계속 실패하면 입력 PNG/진단 JSON을 저장하고 중단합니다.'})}}
    RETURN_TYPES=('STRING','STRING','IMAGE')
    RETURN_NAMES=('text','ocr_report_json','ocr_inputs')
    OUTPUT_IS_LIST=(False,False,True)
    FUNCTION='read'
    CATEGORY='Manga Translator/OCR'
    def check_lazy_status(self, images, model=None, manifest_json=None, **options):
        if _empty_ocr_page(images,manifest_json) or _uniform_ocr_crop(images):
            return []
        if options.get('quality_guard',False) and _unverified_ocr_input(pil_image(images)):return []
        return ['model'] if model is None else []

    def read(self,images,model=None,max_new_tokens=256,base_patches=512,small_text_patches=1024,small_text_px=48,
             line_split=True,tight_crop=False,repetition_penalty=1.,retry_on_repetition=True,
             split_long_lines=False,quality_guard=False,text_direction='auto',retry_on_token_limit=False,
             manifest_json=None,retry_on_layout_failure=False,region_plan_json=None):
        if _empty_ocr_page(images,manifest_json):
            LOG.info('Adaptive OCR skipped: no_text_detected')
            return ('',json.dumps({'status':'no_text_detected','ocr_skipped':True,
                                  'preview':'unchanged_page_not_ocr_input'}),[images])
        from .adapters.options import OcrOptions
        from .ocr_policy import plan_line, text_problem, join_chunks, recovery_parts, dot_punctuation
        from .adapters.hayai import preprocess_size
        preprocess_size=getattr(model,"input_size",preprocess_size)
        from .text_contract import ocr_problem
        import torch
        if type(base_patches) is not int or base_patches not in (256,512,1024):
            raise ValueError('Invalid base OCR patch budget')
        if type(small_text_patches) is not int or small_text_patches not in (512,1024):
            raise ValueError('Invalid small-text OCR patch budget')
        if type(small_text_px) is not int or not 8 <= small_text_px <= 256:
            raise ValueError('Invalid small-text pixel threshold')
        if any(type(value) is not bool for value in (line_split,tight_crop,retry_on_repetition,split_long_lines,quality_guard,retry_on_token_limit,retry_on_layout_failure)):
            raise ValueError('Invalid adaptive OCR switches')
        if text_direction not in ('auto','horizontal','vertical_rtl','vertical_ltr'):
            raise ValueError('Invalid OCR text direction')
        options=OcrOptions(max_new_tokens=max_new_tokens,repetition_penalty=repetition_penalty)
        source=pil_image(images)
        runtime={'line_split':line_split,'text_direction':text_direction,'tight_crop':tight_crop,
                 'split_long_lines':split_long_lines,'quality_guard':quality_guard,
                 'retry_on_layout_failure':retry_on_layout_failure,'max_new_tokens':max_new_tokens,
                 'base_patches':base_patches,'small_text_patches':small_text_patches,
                 'retry_on_token_limit':retry_on_token_limit,'repetition_penalty':repetition_penalty,
                 'retry_on_repetition':retry_on_repetition}
        region_plan = json.loads(region_plan_json) if region_plan_json is not None else {}
        if not isinstance(region_plan,dict):
            raise ValueError('Invalid OCR region plan object')
        if region_plan and (not line_split or text_direction not in ('auto','horizontal')):
            raise ValueError('Verified page rows require line_split and horizontal/auto OCR direction')
        if region_plan:
            if region_plan.get('strategy')=='mask_supported_deskew_rows':
                from .text_geometry import planned_inputs
            else:
                from .layout_refinement import planned_inputs
            crops = planned_inputs(source,region_plan)
        else:
            crops=(_ocr_line_images(source) if text_direction=='auto' else _ocr_line_images(source,text_direction)) if line_split else [source]
        runtime['region_plan'] = {k:region_plan[k] for k in ('strategy','region_id','correction_degrees',
                                 'source_angle','coordinate_frame','rectified_size') if k in region_plan}
        if tight_crop:
            crops=[_tight_ocr_image(image) for image in crops]
        texts, records, previews = [], [], []
        if len(crops) > 32:
            raise ValueError('OCR line count exceeds limit=32')
        planned = [plan_line(image) if split_long_lines else [(image,[0,0,*image.size])] for image in crops]
        if sum(len(parts) for parts in planned) > 128:
            raise ValueError('OCR chunk count exceeds limit=128 per region')
        work_count=sum(len(parts) for parts in planned)
        if all(low==high for low,high in source.getextrema()):
            report={'status':'empty_crop','ocr_skipped':True,
                    'empty_crop_verified':{'method':'uniform_rgb_pixels'},'region_plan':region_plan}
            return ('',json.dumps(report),[images])
        evidence=_unverified_ocr_input(source) if quality_guard else None
        if evidence:
            report={'status':'unverified_input','ocr_skipped':True,'needs_review':True,
                    'input_evidence':evidence,'region_plan':region_plan}
            return ('',json.dumps(report),[images])
        def recognize(image,line_index,box):
            attempts=[];generation=[]
            try:
                dots=dot_punctuation(image) if quality_guard else None
                if dots:
                    LOG.info('OCR source punctuation: %s dots=%s; preserving observed count',dots['axis'],dots['count'])
                    return dots['text'],[{'strategy':'source_dot_punctuation','characters':dots['count'],
                        'issue':None,'model_called':False,'quality_evidence':{'verified_punctuation':dots}}],None
                short=min(image.size)
                patches=max(base_patches,small_text_patches) if short <= small_text_px else base_patches
                LOG.info('Adaptive OCR input: line=%s box=%s crop=%sx%s patch_budget=%s',line_index,box,image.width,image.height,patches)
                generation=[]
                text=_ocr_once(model,image,options,patches,repetition_penalty,retry_on_repetition,
                               retry_on_token_limit,generation)
                quality_evidence={}
                issue=text_problem(text,image,quality_evidence) if quality_guard else ocr_problem(text)
                attempts=[{'patch_budget':patches,'model_size':list(preprocess_size(image.size,patches)),
                           'characters':len(text),'issue':issue,'generation_attempts':generation,
                           **({'quality_evidence':quality_evidence} if quality_evidence else {})}]
                if issue:
                    alternate=256 if patches != 256 else 512
                    LOG.warning('OCR quality retry: reason=%s line=%s box=%s patches=%s->%s',issue,line_index,box,patches,alternate)
                    generation=[]
                    text=_ocr_once(model,image,options,alternate,repetition_penalty,retry_on_repetition,
                                   retry_on_token_limit,generation)
                    quality_evidence={}
                    issue=text_problem(text,image,quality_evidence) if quality_guard else ocr_problem(text)
                    attempts.append({'patch_budget':alternate,'model_size':list(preprocess_size(image.size,alternate)),
                                     'characters':len(text),'issue':issue,'generation_attempts':generation,
                                     **({'quality_evidence':quality_evidence} if quality_evidence else {})})
                return text,attempts,issue
            except Exception as exc:
                path=_save_ocr_failure(source,image,{'code':getattr(exc,'code',type(exc).__name__),
                    'line':line_index,'line_local_bbox':box,'attempts':attempts,
                    'runtime_settings':runtime,'layout_recovery':{'strategy':'adapter_error_before_layout_recovery'},
                    'generation_attempts':generation})
                if path and hasattr(exc,'add_note'):exc.add_note('OCR diagnostic: '+path)
                raise

        def reject(image,line_index,box,attempts,issue,recovery=None,text=None):
            path=_save_ocr_failure(source,image,{'code':issue,'line':line_index,'line_local_bbox':box,
                                               'attempts':attempts,'layout_recovery':recovery,
                                               'runtime_settings':runtime,
                                               'rejected_text':text})
            recovery_summary={key:recovery[key] for key in ('strategy','rejected') if recovery and key in recovery}
            raise ValueError(f'OCR 품질 검사 실패 ({issue}); line={line_index}, box={box}, attempts={attempts}. '
                             f'line_split={line_split}, retry_on_layout_failure={retry_on_layout_failure}, '
                             f'layout_recovery={recovery_summary}. '
                             f'진단={path or "저장 불가"}. 원본 OCR 크롭과 Hayai 로그를 확인하세요. '
                             '번역할 원문을 확정하지 않았습니다.')

        for line_index, parts in enumerate(planned):
            chunks=[]
            for image, box in parts:
                text,attempts,issue=recognize(image,line_index,box)
                recovery=({'strategy':'disabled_by_retry_option'} if not retry_on_layout_failure else
                          {'strategy':'disabled_by_line_split'} if not line_split else None)
                if issue and retry_on_layout_failure and line_split:
                    alternative,recovery=recovery_parts(image,text_direction)
                    if alternative and work_count+len(alternative)<=128:
                        LOG.warning('OCR layout recovery: line=%s crop=%s parts=%s strategy=%s',
                                    line_index,image.size,len(alternative),recovery['strategy'])
                        work_count+=len(alternative)
                        values=[];children=[];child_previews=[]
                        for part,local_box in alternative:
                            value,child_attempts,child_issue=recognize(part,line_index,local_box)
                            if child_issue:reject(part,line_index,local_box,child_attempts,child_issue,recovery,value)
                            values.append(value)
                            children.append({'parent_local_bbox':local_box,'input_size':list(part.size),
                                             'attempts':child_attempts})
                            child_previews.append(torch.from_numpy(np.asarray(part,dtype=np.float32)/255)[None])
                        text='\n'.join(values) if recovery['separator']=='\n' else join_chunks(values)
                        recovery={**recovery,'chunks':children}
                        combined_issue=text_problem(text,image)
                        if combined_issue:reject(image,line_index,box,attempts,combined_issue,recovery,text)
                        previews.extend(child_previews)
                        issue=None
                    elif alternative:
                        recovery={**recovery,'rejected':'region_work_limit=128'}
                if issue:reject(image,line_index,box,attempts,issue,recovery,text)
                if not recovery or 'chunks' not in recovery:
                    previews.append(torch.from_numpy(np.asarray(image,dtype=np.float32)/255)[None])
                chunks.append(text)
                records.append({'line':line_index,'line_local_bbox':box,'input_size':list(image.size),
                                **({'region_local_bbox':region_plan['rows'][line_index],
                                    'region_coordinate_frame':region_plan.get('coordinate_frame','source_crop_pixels')}
                                   if region_plan else {}),
                                'attempts':attempts,**({'layout_recovery':recovery}
                                    if recovery and 'chunks' in recovery else {})})
            texts.append(join_chunks(chunks))
        recovered_lines=sum(len(r['layout_recovery']['chunks'])-1 for r in records
            if r.get('layout_recovery',{}).get('strategy') in ('verified_rows','verified_columns','verified_multicolumn_rows')
            and 'chunks' in r['layout_recovery'])
        leaf_count=sum(len(r['layout_recovery']['chunks']) if 'chunks' in r.get('layout_recovery',{}) else 1
                       for r in records)
        report={'source_size':list(source.size),'line_count':len(crops)+recovered_lines,'chunk_count':leaf_count,
                'initial_line_count':len(crops),'initial_chunk_count':len(records),
                'line_split':line_split,'tight_crop':tight_crop,'split_long_lines':split_long_lines,
                'text_direction':text_direction,'retry_on_token_limit':retry_on_token_limit,
                'quality_guard':quality_guard,'retry_on_layout_failure':retry_on_layout_failure,
                'recognition_work_items':work_count,'chunks':records,'line_texts':texts,
                **({'engine':model.engine} if hasattr(model,'engine') else {}),
                **({'region_plan':region_plan} if region_plan else {}),
                'quality_scope':'heuristic_checks_only_not_recognition_accuracy'}
        dots=dot_punctuation(source) if quality_guard else None
        if dots and ''.join(texts)==dots['text']:report['verified_punctuation']=dots
        return ('\n'.join(texts),json.dumps(report,ensure_ascii=False),previews)


NODE_CLASS_MAPPINGS = {cls.__name__:cls for cls in
    (MangaDetectorLoader,MangaOCRLoader,MangaDetector,MangaDetectorDetail,MangaOCR,MangaOCRAdaptive)}
NODE_DISPLAY_NAME_MAPPINGS = {
    'MangaDetectorLoader':'글자 검출 모델 · RF-DETR', 'MangaOCRLoader':'OCR 모델 · Hayai',
    'MangaDetector':'글자 위치 검출', 'MangaDetectorDetail':'글자 위치 검출 · 작은 글씨 보강',
    'MangaOCR':'영역별 원문 읽기', 'MangaOCRAdaptive':'원문 OCR · 작은 글씨 자동 고해상도',
}
