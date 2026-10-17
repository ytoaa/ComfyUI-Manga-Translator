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


def group_adjacent_lines(items, bubbles):
    """Conservative horizontal paragraph grouping, before IDs are assigned.

    Compare original rows, never growing paragraph boxes: otherwise a chain
    could swallow the next paragraph as its height and allowed gap increase.
    Different/ambiguous bubble ownership and multi-row blocks stay separate.
    """
    rows = sorted(items, key=lambda item: (item['bbox'][1], item['bbox'][0]))
    def single_row(item):
        raw = item.get('mask')
        if raw is None:
            return True
        import numpy as np
        from .mask_nodes import _decode_mask
        pixels, _ = _decode_mask(raw, raw['x']+raw['width'],raw['y']+raw['height'])
        active = np.flatnonzero((pixels>.5).sum(axis=1) >= 2)
        if not len(active):
            return False
        bands = np.split(active,np.flatnonzero(np.diff(active)>max(3,min(8,round(pixels.shape[0]*.08))))+1)
        return sum(group[-1]-group[0]+1 >= max(2,pixels.shape[0]*.1) for group in bands) == 1
    single = {id(row): single_row(row) for row in rows}
    def owner(item):
        found = [i for i, bubble in enumerate(bubbles)
                 if _intersection(item['bbox'], bubble['bbox']) / _area(item['bbox']) >= .95]
        return tuple(found)
    groups = []
    for row in rows:
        a = row['bbox']; aw, ah = a[2]-a[0], a[3]-a[1]
        matches = []
        for index, group in enumerate(groups):
            last = group[-1]; b = last['bbox']; bw, bh = b[2]-b[0], b[3]-b[1]
            if (row['label'] != 'text' or last['label'] != 'text' or not single[id(row)] or not single[id(last)] or
                    min(aw/ah, bw/bh) < 3 or min(ah,bh)/max(ah,bh) < .65 or
                    not 0 <= a[1]-b[3] <= .55*min(ah,bh) or
                    abs(a[0]-b[0]) > .6*min(ah,bh) or
                    min(aw,bw)/max(aw,bw) < .2 or owner(row) != owner(last) or
                    len(owner(row)) > 1):
                continue
            matches.append(index)
        if len(matches) == 1:
            groups[matches[0]].append(row)
        else:
            groups.append([row])
    output = []
    for group in groups:
        box = [min(row['bbox'][k] for row in group) if k < 2 else
               max(row['bbox'][k] for row in group) for k in range(4)]
        output.append({**group[0], 'bbox': box,
                       'line_bboxes': [row['bbox'] for row in group]})
    return output


class MangaDetectionRegionsResolved(_BaseDetectionRegions):
    DESCRIPTION = ('RF-DETR 전체/상세 타일의 중복 검출을 논리 문단으로 정리합니다. '
                   'IoU뿐 아니라 작은 박스가 큰 박스에 포함되는 비율도 사용해 '
                   'detail pass의 반쪽 문단이 별도 번역문으로 내려가는 것을 막습니다.')

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema['optional'] = {'merge_adjacent_lines': ('BOOLEAN', {'default': False,
            'tooltip': '가깝고 왼쪽이 정렬된 가로 행을 문단으로 묶습니다. 말풍선이 다르거나 애매하면 분리 유지.'})}
        return schema

    def convert(self, result, include_sfx=False, dedupe_iou=0.75, reading_order='top_to_bottom', merge_adjacent_lines=False):
        if type(merge_adjacent_lines) is not bool:
            raise ValueError('Invalid paragraph grouping switch')
        if not isinstance(result, dict) or result.get('protocol') != 1 or not isinstance(result.get('detections'), list):
            raise ValueError('Invalid detector response')
        width, height = result.get('image_width'), result.get('image_height')
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ValueError('Invalid detector image dimensions')
        if type(include_sfx) is not bool or not isinstance(dedupe_iou, (int, float)) or not 0.1 <= dedupe_iou <= 1 or reading_order not in ('top_to_bottom', 'right_to_left'):
            raise ValueError('Invalid region selection options')

        labels = {'text', 'onomatopoeia'} if include_sfx else {'text'}
        if any(item.get('tile_provenance', {}).get('clipped_edges')
               for item in result['detections'] if item.get('label') in labels):
            raise ValueError('Unresolved clipped text cannot enter OCR; run detail boundary recovery first')
        candidates = [_detector_region(item, width, height)
                      for item in result['detections'] if item.get('label') in labels]
        selected = merge_detector_regions(candidates, dedupe_iou)
        before_grouping = len(selected)
        if merge_adjacent_lines:
            bubbles = [_detector_region(item, width, height) for item in result['detections']
                       if item.get('label') == 'bubble']
            selected = group_adjacent_lines(selected, bubbles)
        selected.sort(key=(lambda row: (row['bbox'][1], row['bbox'][0]))
                      if reading_order == 'top_to_bottom'
                      else (lambda row: (-row['bbox'][0], row['bbox'][1])))
        rows = [{'id': f'r{i+1}',
                 'kind': 'sfx' if item['label'] == 'onomatopoeia' else 'text',
                 'bbox': [item['bbox'][0] / width * 1000,
                          item['bbox'][1] / height * 1000,
                          item['bbox'][2] / width * 1000,
                          item['bbox'][3] / height * 1000],
                 **({'line_bboxes_pixels': item['line_bboxes']} if 'line_bboxes' in item else {})}
                for i, item in enumerate(selected)]
        value = encode({'regions': rows, 'origin': 'rfdetr',
                        **({'page_status':'no_text_detected'} if not rows else {}),
                        **({'needs_review':True,'no_text_reason':'excluded_onomatopoeia_present'}
                           if not rows and result.get('detection_audit',{}).get('excluded_onomatopoeia_detections',0) else {}),
                        'image_width': width, 'image_height': height,
                        'region_resolution': {
                            'input_regions': len(candidates),
                            'resolved_regions': len(selected),
                            'grouped_lines': before_grouping-len(selected),
                            'dedupe_iou': dedupe_iou,
                            'containment_overlap': _CONTAINMENT_OVERLAP,
                            'boundary_recovery': result.get('detail_detection', {}).get('boundary_recovery'),
                            'detection_audit':result.get('detection_audit'),
                        }})
        layout(value)
        return (value,)
