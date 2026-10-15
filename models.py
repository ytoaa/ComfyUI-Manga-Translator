"""Standalone ComfyUI model wrappers using attributed local inference adapters."""
from pathlib import Path
import logging
import math
import numpy as np
from PIL import Image

_MODELS = {}
LOG = logging.getLogger(__name__)


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
    """Split one detector crop into reading-order line crops like Koharu OCR.

    This stays internal to MangaOCR so the workflow does not need replacement
    nodes for preprocessing/joining. Ambiguous or weak crops remain unchanged.
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
        if any(not isinstance(v,(int,float)) or not np.isfinite(v) or not 0<=v<=1 for v in thresholds.values()):
            raise ValueError('Invalid detection thresholds')
        return (model.detect(pil_image(images),thresholds),)


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
        from .adapters.hayai import HayaiOutputError
        if type(max_patches) is not int or max_patches not in (256,512,1024) or type(retry_on_repetition) is not bool:
            raise ValueError('Invalid OCR settings')
        options = OcrOptions(max_new_tokens=max_new_tokens,repetition_penalty=repetition_penalty)

        def read_one(image):
            try:
                result = model.ocr(image,options,max_patches=max_patches)
            except HayaiOutputError as exc:
                if exc.code!='ocr_repetition_loop' or not retry_on_repetition or repetition_penalty>=2:
                    raise
                retry_penalty = min(2.,max(1.1,repetition_penalty+0.1))
                retry = OcrOptions(max_new_tokens=max_new_tokens,repetition_penalty=retry_penalty)
                LOG.warning('Retrying one repeated OCR crop with penalty %.2f',retry_penalty)
                result = model.ocr(image,retry,max_patches=max_patches)
            return result['text']

        lines = _ocr_line_images(pil_image(images))
        text = '\n'.join(read_one(image) for image in lines)
        return (text,)


NODE_CLASS_MAPPINGS = {cls.__name__:cls for cls in (MangaDetectorLoader,MangaOCRLoader,MangaDetector,MangaOCR)}
NODE_DISPLAY_NAME_MAPPINGS = {
    'MangaDetectorLoader':'글자 검출 모델 · RF-DETR', 'MangaOCRLoader':'OCR 모델 · Hayai',
    'MangaDetector':'글자 위치 검출', 'MangaOCR':'영역별 원문 읽기',
}
