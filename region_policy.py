"""Region policy for full-page + detail-tile RF-DETR results.

The detector can report the same logical text region at different extents from
full-page and tiled passes. IoU alone is a poor duplicate test for nested boxes:
a half-width detail box can be almost completely contained in a full-page box
while their IoU is only ~0.5. This policy keeps the existing ComfyUI node type
and adds containment-aware, transitive merging before OCR/translation.
"""
from .nodes import MangaDetectionRegions as _BaseDetectionRegions
from .nodes import _detector_region, encode, layout, iou

_CONTAINMENT_OVERLAP = 0.90


def _area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def containment_overlap(a, b):
    """Intersection divided by the smaller box area."""
    smaller = min(_area(a), _area(b))
    return _intersection(a, b) / smaller if smaller > 0 else 0.0


def _same_line_fragments(a, b):
    """Overlapping sliding windows may return complementary halves of one row."""
    ah, bh = a[3]-a[1], b[3]-b[1]
    aw, bw = a[2]-a[0], b[2]-b[0]
    if min(aw, bw, ah, bh) <= 0 or min(ah, bh)/max(ah, bh) < .65:
        return False
    vertical = max(0., min(a[3], b[3])-max(a[1], b[1]))/min(ah, bh)
    horizontal = max(0., min(a[2], b[2])-max(a[0], b[0]))/min(aw, bw)
    return vertical >= .8 and horizontal >= .1


def merge_detector_regions(candidates, iou_threshold, containment_threshold=_CONTAINMENT_OVERLAP):
    """Merge same-label duplicates transitively without dropping detected extent.

    A pair is considered the same logical region when either ordinary IoU is
    high enough or at least 90% of the smaller rectangle is contained in the
    larger rectangle. The latter handles full-page/detail-tile duplicates.
    Repeating until stable also collapses chains such as left-half -> full ->
    right-half into one logical text region.
    """
    items = [dict(item) for item in sorted(candidates, key=lambda row: row['score'], reverse=True)]
    while True:
        merged = False
        for left in range(len(items)):
            for right in range(left + 1, len(items)):
                a, b = items[left], items[right]
                if a['label'] != b['label']:
                    continue
                same = (iou(a['bbox'], b['bbox']) >= iou_threshold or
                        containment_overlap(a['bbox'], b['bbox']) >= containment_threshold or
                        _same_line_fragments(a['bbox'], b['bbox']))
                if not same:
                    continue
                winner = a if a['score'] >= b['score'] else b
                union = [min(a['bbox'][0], b['bbox'][0]), min(a['bbox'][1], b['bbox'][1]),
                         max(a['bbox'][2], b['bbox'][2]), max(a['bbox'][3], b['bbox'][3])]
                items[left] = {**winner, 'bbox': union}
                items.pop(right)
                merged = True
                break
            if merged:
                break
        if not merged:
            return items


class MangaDetectionRegionsResolved(_BaseDetectionRegions):
    DESCRIPTION = ('RF-DETR 전체/상세 타일의 중복 검출을 논리 문단으로 정리합니다. '
                   'IoU뿐 아니라 작은 박스가 큰 박스에 포함되는 비율도 사용해 '
                   'detail pass의 반쪽 문단이 별도 번역문으로 내려가는 것을 막습니다.')

    def convert(self, result, include_sfx=False, dedupe_iou=0.75, reading_order='top_to_bottom'):
        if not isinstance(result, dict) or result.get('protocol') != 1 or not isinstance(result.get('detections'), list):
            raise ValueError('Invalid detector response')
        width, height = result.get('image_width'), result.get('image_height')
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ValueError('Invalid detector image dimensions')
        if type(include_sfx) is not bool or not isinstance(dedupe_iou, (int, float)) or not 0.1 <= dedupe_iou <= 1 or reading_order not in ('top_to_bottom', 'right_to_left'):
            raise ValueError('Invalid region selection options')

        labels = {'text', 'onomatopoeia'} if include_sfx else {'text'}
        candidates = [_detector_region(item, width, height)
                      for item in result['detections'] if item.get('label') in labels]
        selected = merge_detector_regions(candidates, dedupe_iou)
        selected.sort(key=(lambda row: (row['bbox'][1], row['bbox'][0]))
                      if reading_order == 'top_to_bottom'
                      else (lambda row: (-row['bbox'][0], row['bbox'][1])))
        rows = [{'id': f'r{i+1}',
                 'kind': 'sfx' if item['label'] == 'onomatopoeia' else 'text',
                 'bbox': [item['bbox'][0] / width * 1000,
                          item['bbox'][1] / height * 1000,
                          item['bbox'][2] / width * 1000,
                          item['bbox'][3] / height * 1000]}
                for i, item in enumerate(selected)]
        value = encode({'regions': rows, 'origin': 'rfdetr',
                        'image_width': width, 'image_height': height,
                        'region_resolution': {
                            'input_regions': len(candidates),
                            'resolved_regions': len(selected),
                            'dedupe_iou': dedupe_iou,
                            'containment_overlap': _CONTAINMENT_OVERLAP,
                        }})
        layout(value)
        return (value,)
