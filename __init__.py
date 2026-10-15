"""ComfyUI Manga Translator: model-independent OCR and translation workflow."""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .models import NODE_CLASS_MAPPINGS as MODEL_NODES, NODE_DISPLAY_NAME_MAPPINGS as MODEL_NAMES

NODE_CLASS_MAPPINGS.update(MODEL_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(MODEL_NAMES)

from .detection_policy import MangaDetectorDetailResolved
NODE_CLASS_MAPPINGS['MangaDetectorDetail'] = MangaDetectorDetailResolved
NODE_DISPLAY_NAME_MAPPINGS['MangaDetectorDetail'] = '글자 위치 검출 · native sliding 보강'

from .region_policy import MangaDetectionRegionsResolved
NODE_CLASS_MAPPINGS['MangaDetectionRegions'] = MangaDetectionRegionsResolved
NODE_DISPLAY_NAME_MAPPINGS['MangaDetectionRegions'] = '검출 영역 정리 · 문단 중복 해소'

from .mask_nodes import NODE_CLASS_MAPPINGS as MASK_NODES, NODE_DISPLAY_NAME_MAPPINGS as MASK_NAMES
NODE_CLASS_MAPPINGS.update(MASK_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(MASK_NAMES)

from .inpaint_tiles import NODE_CLASS_MAPPINGS as INPAINT_NODES, NODE_DISPLAY_NAME_MAPPINGS as INPAINT_NAMES
NODE_CLASS_MAPPINGS.update(INPAINT_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(INPAINT_NAMES)

from .lettering.nodes import NODE_CLASS_MAPPINGS as LETTERING_NODES, NODE_DISPLAY_NAME_MAPPINGS as LETTERING_NAMES
NODE_CLASS_MAPPINGS.update(LETTERING_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(LETTERING_NAMES)

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
