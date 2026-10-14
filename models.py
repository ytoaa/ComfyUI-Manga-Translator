"""Standalone ComfyUI model wrappers using attributed local inference adapters."""
from pathlib import Path
import logging
import numpy as np
from PIL import Image

_MODELS = {}


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
        image = pil_image(images)
        try:
            result = model.ocr(image,options,max_patches=max_patches)
        except HayaiOutputError as exc:
            if exc.code!='ocr_repetition_loop' or not retry_on_repetition or repetition_penalty>=2:
                raise
            retry_penalty = min(2.,max(1.1,repetition_penalty+0.1))
            retry = OcrOptions(max_new_tokens=max_new_tokens,repetition_penalty=retry_penalty)
            logging.getLogger(__name__).warning('Retrying one repeated OCR crop with penalty %.2f',retry_penalty)
            result = model.ocr(image,retry,max_patches=max_patches)
        return (result['text'],)


NODE_CLASS_MAPPINGS = {cls.__name__:cls for cls in (MangaDetectorLoader,MangaOCRLoader,MangaDetector,MangaOCR)}
NODE_DISPLAY_NAME_MAPPINGS = {
    'MangaDetectorLoader':'글자 검출 모델 · RF-DETR', 'MangaOCRLoader':'OCR 모델 · Hayai',
    'MangaDetector':'글자 위치 검출', 'MangaOCR':'영역별 원문 읽기',
}
