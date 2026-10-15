"""Standalone ComfyUI model wrappers using attributed local inference adapters."""
from pathlib import Path
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


def load(kind, model_name):
    available = catalog(kind)
    if model_name not in available:
        raise ValueError('Select an existing complete model bundle from models/manga_translator/'+kind)
    folder = available[model_name]
    key = (kind,str(folder))
    if key not in _MODELS:
        if kind=='detection':
            from .adapters.model import Backend
        else:
            from .adapters.hayai import Backend
        _MODELS[key] = Backend(folder)
    return _MODELS[key]


def pil_image(images):
    if images.ndim!=4 or images.shape[0]!=1 or images.shape[-1]!=3:
        raise ValueError('Expected one RGB image')
    pixels = np.clip(images[0].detach().cpu().numpy()*255,0,255).round().astype(np.uint8)
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


def _ocr_line_images(image):
    """Split one detector crop into reading-order line crops like the proven Koharu path.

    This stays internal to the OCR node so the workflow does not need custom
    splitter/joiner nodes. Ambiguous or weak crops remain unchanged.
    """
    from scipy import ndimage

    width,height = image.size
    direction = 'auto'
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

    if width >= height*1.25:
        direction = 'horizontal'
    elif height >= width*1.25:
        direction = 'vertical_rtl'

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


def _ocr_once(model,image,options,max_patches,repetition_penalty,retry_on_repetition):
    from .adapters.options import OcrOptions
    from .adapters.hayai import HayaiOutputError
    try:
        return model.ocr(image,options,max_patches=max_patches)['text']
    except HayaiOutputError as exc:
        if exc.code!='ocr_repetition_loop' or not retry_on_repetition or repetition_penalty>=2:
            raise
        retry_penalty=min(2.,max(1.1,repetition_penalty+0.1))
        retry=OcrOptions(max_new_tokens=options.max_new_tokens,repetition_penalty=retry_penalty)
        LOG.warning('Retrying one repeated OCR crop with penalty %.2f',retry_penalty)
        return model.ocr(image,retry,max_patches=max_patches)['text']


class MangaDetectorLoader:
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


class MangaOCRAdaptive:
    DESCRIPTION = '영역을 행/열로 분리하고 여백을 줄인 뒤 작은 글씨에 더 큰 Hayai patch budget을 자동 배정합니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images':('IMAGE',),'model':('MANGA_OCR_MODEL',),
            'max_new_tokens':('INT',{'default':256,'min':1,'max':2048}),
            'base_patches':([256,512,1024],{'default':512}),
            'small_text_patches':([512,1024],{'default':1024}),
            'small_text_px':('INT',{'default':48,'min':8,'max':256}),
            'line_split':('BOOLEAN',{'default':True}),
            'tight_crop':('BOOLEAN',{'default':False}),
            'repetition_penalty':('FLOAT',{'default':1.,'min':1.,'max':2.,'step':0.01}),
            'retry_on_repetition':('BOOLEAN',{'default':True})}}
    RETURN_TYPES=('STRING',)
    FUNCTION='read'
    CATEGORY='Manga Translator/OCR'
    def read(self,images,model,max_new_tokens=256,base_patches=512,small_text_patches=1024,small_text_px=48,
             line_split=True,tight_crop=False,repetition_penalty=1.,retry_on_repetition=True):
        from .adapters.options import OcrOptions
        if type(base_patches) is not int or base_patches not in (256,512,1024):
            raise ValueError('Invalid base OCR patch budget')
        if type(small_text_patches) is not int or small_text_patches not in (512,1024):
            raise ValueError('Invalid small-text OCR patch budget')
        if type(small_text_px) is not int or not 8 <= small_text_px <= 256:
            raise ValueError('Invalid small-text pixel threshold')
        if any(type(value) is not bool for value in (line_split,tight_crop,retry_on_repetition)):
            raise ValueError('Invalid adaptive OCR switches')
        options=OcrOptions(max_new_tokens=max_new_tokens,repetition_penalty=repetition_penalty)
        source=pil_image(images)
        crops=_ocr_line_images(source) if line_split else [source]
        if tight_crop:
            crops=[_tight_ocr_image(image) for image in crops]
        texts=[]
        for image in crops:
            short=min(image.size)
            patches=max(base_patches,small_text_patches) if short <= small_text_px else base_patches
            LOG.info('Adaptive OCR input: crop=%sx%s short=%s patch_budget=%s',image.width,image.height,short,patches)
            texts.append(_ocr_once(model,image,options,patches,repetition_penalty,retry_on_repetition))
        return ('\n'.join(texts),)


NODE_CLASS_MAPPINGS = {cls.__name__:cls for cls in
    (MangaDetectorLoader,MangaOCRLoader,MangaDetector,MangaDetectorDetail,MangaOCR,MangaOCRAdaptive)}
NODE_DISPLAY_NAME_MAPPINGS = {
    'MangaDetectorLoader':'글자 검출 모델 · RF-DETR', 'MangaOCRLoader':'OCR 모델 · Hayai',
    'MangaDetector':'글자 위치 검출', 'MangaDetectorDetail':'글자 위치 검출 · 작은 글씨 보강',
    'MangaOCR':'영역별 원문 읽기', 'MangaOCRAdaptive':'원문 OCR · 작은 글씨 자동 고해상도',
}
