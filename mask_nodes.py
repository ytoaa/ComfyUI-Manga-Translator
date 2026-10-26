"""Bridge RF-DETR local RLE masks to ordinary ComfyUI MASK values."""
import numpy as np
from . import boundary_review


def _mask_metadata(raw,page_width,page_height):
    if not isinstance(raw,dict):
        raise ValueError('Detection does not contain a segmentation mask')
    x,y,width,height=(raw.get(key) for key in ('x','y','width','height'))
    if any(type(value) is not int for value in (x,y,width,height)) or min(x,y) < 0 or min(width,height) <= 0:
        raise ValueError('Invalid detector mask bounds')
    if x+width > page_width or y+height > page_height:
        raise ValueError('Detector mask exceeds source page')
    runs=raw.get('runs')
    if not isinstance(runs,list) or not runs or any(type(value) is not int or value < 0 for value in runs):
        raise ValueError('Invalid detector mask RLE')
    if sum(runs) != width*height:
        raise ValueError('Detector mask RLE length mismatch')
    return (x,y,width,height),runs


def _decode_mask(raw,page_width,page_height):
    (x,y,width,height),runs=_mask_metadata(raw,page_width,page_height)
    values=np.repeat(np.arange(len(runs),dtype=np.uint32)%2,runs).astype(np.float32)
    return values.reshape(height,width),(x,y,width,height)


class MangaDetectionMask:
    DESCRIPTION = 'RF-DETR의 실제 segmentation 픽셀을 ComfyUI MASK로 변환합니다. 이후 확대/합성은 GrowMask·ImageCompositeMasked 같은 기본 노드를 사용하세요.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'result': ('MANGA_DETECTION',),
            'include_sfx': ('BOOLEAN', {'default': False}),
        }}
    RETURN_TYPES=('MASK',)
    RETURN_NAMES=('text_pixel_mask',)
    FUNCTION='make'
    CATEGORY='Manga Translator/Detection'

    def make(self,result,include_sfx=False):
        import torch
        if not isinstance(result,dict) or result.get('protocol') != 1 or not isinstance(result.get('detections'),list):
            raise ValueError('Invalid detector response')
        width,height=result.get('image_width'),result.get('image_height')
        if type(width) is not int or type(height) is not int or min(width,height) <= 0:
            raise ValueError('Invalid detector page size')
        if type(include_sfx) is not bool:
            raise ValueError('include_sfx must be boolean')
        labels={'text','onomatopoeia'} if include_sfx else {'text'}
        page=np.zeros((height,width),dtype=np.float32)
        fragments = result.get('mask_fragments', [])
        if not isinstance(fragments, list):
            raise ValueError('Invalid detector mask fragments')
        for item in result['detections'] + fragments:
            if item.get('label') not in labels:
                continue
            raw=item.get('mask')
            if raw is None:
                # Some synthetic/manual test detections have boxes only. The
                # production RF-DETR contract includes masks; do not fabricate
                # a rectangular pixel mask here.
                continue
            local,(x,y,w,h)=_decode_mask(raw,width,height)
            np.maximum(page[y:y+h,x:x+w],local,out=page[y:y+h,x:x+w])
        boundary_review.clear(page,boundary_review.boxes(result,width,height))
        return (torch.from_numpy(page[None]),)


NODE_CLASS_MAPPINGS={'MangaDetectionMask':MangaDetectionMask}
NODE_DISPLAY_NAME_MAPPINGS={'MangaDetectionMask':'검출 결과 → 실제 글자 픽셀 마스크'}
