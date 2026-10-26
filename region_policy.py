"""Region policy for full-page + detail-tile RF-DETR results.

The detector can report the same logical text region at different extents from
full-page and tiled passes. IoU alone is a poor duplicate test for nested boxes:
a half-width detail box can be almost completely contained in a full-page box
while their IoU is only ~0.5. This policy keeps the existing ComfyUI node type
and adds containment-aware, transitive merging before OCR/translation.
"""
from .nodes import MangaDetectionRegions as _BaseDetectionRegions
from .nodes import _detector_region, encode, layout, iou
from . import boundary_review

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
    if min(aw, bw, ah, bh) <= 0 or min(aw/ah,bw/bh)<3 or min(ah, bh)/max(ah, bh) < .65:
        return False
    vertical = max(0., min(a[3], b[3])-max(a[1], b[1]))/min(ah, bh)
    horizontal = max(0., min(a[2], b[2])-max(a[0], b[0]))/min(aw, bw)
    return vertical >= .8 and horizontal >= .1


def _identical_cross_label_source(a, b):
    """One segmentation may be classified as both text and an effect.

    Overlap alone cannot distinguish a caption from the effect behind it.
    Identical original bounds and near-contained, nonempty ink support identify
    this narrow alias; maskless or merely overlapping rectangles remain.
    """
    from .source_ownership import cross_label_alias
    return cross_label_alias(a, b)


def merge_detector_regions(candidates, iou_threshold, containment_threshold=_CONTAINMENT_OVERLAP, barriers=(),width=None,height=None):
    """Merge duplicates transitively without dropping detected extent.

    A pair is considered the same logical region when either ordinary IoU is
    high enough or at least 90% of the smaller rectangle is contained in the
    larger rectangle. The latter handles full-page/detail-tile duplicates.
    Repeating until stable also collapses chains such as left-half -> full ->
    right-half into one logical text region.
    """
    items = [dict(item) for item in sorted(candidates, key=lambda row: row['score'], reverse=True)]
    from .region_boundaries import compatible,union_masks
    import math
    width=width or math.ceil(max((r['bbox'][2] for r in items),default=1))
    height=height or math.ceil(max((r['bbox'][3] for r in items),default=1))
    alias_phase = False
    while True:
        merged = False
        for left in range(len(items)):
            for right in range(left + 1, len(items)):
                a, b = items[left], items[right]
                if a.get('bubble_owner') and b.get('bubble_owner') and a['bubble_owner'] != b['bubble_owner']:
                    continue
                certified = None
                if bool(a.get('bubble_owner')) != bool(b.get('bubble_owner')):
                    from .source_ownership import mask_overlap
                    certified,other=(a,b) if a.get('bubble_owner') else (b,a)
                    covered=mask_overlap(other.get('mask'),certified['ocr_owner_mask'])
                    if not covered or covered['intersection']!=covered['left_pixels']:
                        # An unresolved spanning observation must not become a
                        # transitive bridge joining two established owners.
                        continue
                if barriers and not compatible(a,b,barriers):
                    # A separator may cut across a duplicate observation's bbox.
                    # Shared original ink is stronger evidence than bbox sides.
                    from .source_ownership import mask_overlap
                    overlap=mask_overlap(a.get('mask'),b.get('mask'))
                    if not (a['label']==b['label'] and containment_overlap(a['bbox'],b['bbox'])>=.9
                            and overlap and overlap['smaller_coverage']>=.92):continue
                alias = alias_phase and _identical_cross_label_source(a, b)
                if a['label'] != b['label'] and not alias:
                    continue
                from .source_ownership import mask_overlap
                owned_overlap = (mask_overlap(a.get('mask'), b.get('mask'))
                                 if a.get('bubble_owner') and a.get('bubble_owner') == b.get('bubble_owner') else None)
                if owned_overlap and not owned_overlap['intersection']:
                    continue
                same = (alias or bool(owned_overlap and owned_overlap['intersection']) or iou(a['bbox'], b['bbox']) >= iou_threshold or
                        containment_overlap(a['bbox'], b['bbox']) >= containment_threshold or
                        _same_line_fragments(a['bbox'], b['bbox']))
                if not same:
                    continue
                winner = a if a['score'] >= b['score'] else b
                union = [min(a['bbox'][0], b['bbox'][0]), min(a['bbox'][1], b['bbox'][1]),
                         max(a['bbox'][2], b['bbox'][2]), max(a['bbox'][3], b['bbox'][3])]
                combined=union_masks(a,b,width,height)
                ink_box=([combined['x'],combined['y'],combined['x']+combined['width'],combined['y']+combined['height']]
                         if combined is not None else union)
                items[left] = {**winner, 'bbox': union,'mask':combined,'_ink_bbox':ink_box,
                    'source_detector_ids': sorted(set(a.get('source_detector_ids', [])) | set(b.get('source_detector_ids', []))),
                    'source_labels': sorted(set(a.get('source_labels', [a['label']])) | set(b.get('source_labels', [b['label']]))),
                    'cross_label_alias': bool(alias or a.get('cross_label_alias') or b.get('cross_label_alias'))}
                if certified:
                    items[left].update(bubble_owner=certified['bubble_owner'],ocr_owner_mask=certified['ocr_owner_mask'])
                if items[left].get('bubble_owner') and (a.get('_owned_frame') or b.get('_owned_frame')):
                    items[left].update(_owned_frame=True,bbox=[max(0,ink_box[0]-2),max(0,ink_box[1]-2),
                        min(width,ink_box[2]+2),min(height,ink_box[3]+2)])
                identities=[r.get('_identity_bbox',r['bbox']) for r in (a,b)]
                items[left]['_identity_bbox']=[min(q[k] for q in identities) if k<2 else max(q[k] for q in identities) for k in range(4)]
                items.pop(right)
                merged = True
                break
            if merged:
                break
        if not merged:
            if not alias_phase:
                alias_phase = True
                continue
            return items


def group_adjacent_lines(items, bubbles, panels=()):
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
    def panel_owner(item):
        enclosing = [(i, panel) for i, panel in enumerate(panels)
                     if _intersection(item['bbox'], panel['bbox']) / _area(item['bbox']) >= .95]
        if not enclosing:
            return ('ambiguous', id(item)) if any(_intersection(item['bbox'], p['bbox']) for p in panels) else ()
        # Nested page/panel boxes are normal; overlapping unrelated panels are not.
        index, inner = min(enclosing, key=lambda pair: _area(pair[1]['bbox']))
        if any(_intersection(inner['bbox'], p['bbox']) / _area(inner['bbox']) < .99 for _, p in enclosing):
            return ('ambiguous', id(item))
        return (index,)
    groups = []
    for row in rows:
        a = row['bbox']; aw, ah = a[2]-a[0], a[3]-a[1]
        matches = []
        for index, group in enumerate(groups):
            last = group[-1]; b = last['bbox']; bw, bh = b[2]-b[0], b[3]-b[1]
            if (row['label'] != 'text' or last['label'] != 'text' or not single[id(row)] or not single[id(last)] or
                    row.get('bubble_owner') != last.get('bubble_owner') or
                    min(aw/ah, bw/bh) < 3 or min(ah,bh)/max(ah,bh) < .65 or
                    not 0 <= a[1]-b[3] <= .55*min(ah,bh) or
                    abs(a[0]-b[0]) > .6*min(ah,bh) or
                    min(aw,bw)/max(aw,bw) < .2 or owner(row) != owner(last) or
                    len(owner(row)) > 1 or panel_owner(row) != panel_owner(last)):
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
        combined=group[0].get('mask')
        if len(group)>1:
            from .region_boundaries import union_masks
            import math
            width,height=math.ceil(box[2]),math.ceil(box[3])
            for row in group[1:]:combined=union_masks({'mask':combined},row,width,height)
        output.append({**group[0], 'bbox': box,'mask':combined,
                       'source_detector_ids': sorted({v for row in group for v in row.get('source_detector_ids', [])}),
                       'source_labels': sorted({v for row in group for v in row.get('source_labels', [row['label']])}),
                       'cross_label_alias': any(row.get('cross_label_alias', False) for row in group),
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
            'tooltip': '가깝고 왼쪽이 정렬된 가로 행을 문단으로 묶습니다. 말풍선·컷이 다르거나 소유권이 애매하면 분리 유지.'}),
            'protected_overlap_policy': (['preserve_review','stop'], {'default':'preserve_review',
            'tooltip':'보호 영역에 닿는 연결 원문만 제외·보존하고 독립 영역은 계속 처리합니다. stop은 페이지를 중단합니다.'})}
        return schema

    def convert(self, result, include_sfx=False, dedupe_iou=0.75, reading_order='top_to_bottom', merge_adjacent_lines=False,
                protected_overlap_policy='preserve_review'):
        if protected_overlap_policy not in ('preserve_review', 'stop'):
            raise ValueError('Invalid protected overlap policy')
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
        candidates = [{**_detector_region(item, width, height), 'source_detector_ids': [f'd{i+1}'],
                       'source_labels': [item['label']]}
                      for i, item in enumerate(result['detections']) if item.get('label') in labels]
        bubbles = [_detector_region(item, width, height) for item in result['detections'] if item.get('label') == 'bubble']
        panels = [_detector_region(item, width, height) for item in result['detections'] if item.get('label') == 'panel']
        from .region_boundaries import separators,partition
        barriers=separators(panels+bubbles)
        input_count=len(candidates)
        from .source_partition import partition_by_bubbles
        candidates,owner_partitions=partition_by_bubbles(candidates,bubbles,width,height)
        candidates,partitions=partition(candidates,barriers,width,height)
        selected = merge_detector_regions(candidates, dedupe_iou,barriers=barriers,width=width,height=height)
        before_grouping = len(selected)
        if merge_adjacent_lines:
            selected = group_adjacent_lines(selected, bubbles, panels)
        protected = boundary_review.boxes(result,width,height)
        overlaps = any(boundary_review.intersects(item['bbox'],box) for item in selected for box in protected)
        if overlaps and protected_overlap_policy == 'stop':
            raise ValueError('Resolved text overlaps preserved boundary region; review detection geometry')
        local_review = []
        if overlaps:
            from .page_edit import pixel_bounds
            active = list(selected)
            changed = True
            while changed:
                changed = False
                for item in list(active):
                    if any(boundary_review.intersects(item['bbox'], box) for box in protected):
                        box = pixel_bounds(item['bbox'], width, height)
                        if box not in protected:protected.append(box)
                        local_review.append({'detector_ids':item.get('source_detector_ids', []), 'bbox_pixels':box,
                                             'reason':'protected_region_overlap'})
                        active.remove(item);changed = True
            if len(protected) > 512:raise ValueError('Resolved region protection exceeds limit=512; split/review page')
            selected = active
        selected.sort(key=(lambda row: (row['bbox'][1], row['bbox'][0]))
                      if reading_order == 'top_to_bottom'
                      else (lambda row: (-row['bbox'][0], row['bbox'][1])))
        from .source_ownership import bubble_verified
        from .source_ownership import mask_overlap
        ambiguous = {}
        ambiguity_reasons = {}
        for i, a in enumerate(selected):
            for j, b in enumerate(selected[i+1:], i+1):
                if _intersection(a['bbox'], b['bbox']) <= 0:
                    continue
                support = mask_overlap(a.get('mask'), b.get('mask'))
                same_label=a['label']==b['label']
                if support and ((same_label and support['smaller_coverage']>=.25) or
                        (not same_label and iou(a['bbox'],b['bbox'])>=.5 and
                         support['smaller_coverage']>=.85 and support['larger_coverage']>=.65)):
                    reason='ambiguous_source_overlap' if same_label else 'ambiguous_cross_label_source'
                    ambiguity_reasons[i]=reason;ambiguity_reasons[j]=reason
                    ambiguous.setdefault(i, []).append(f'r{j+1}')
                    ambiguous.setdefault(j, []).append(f'r{i+1}')
        rows = [{'id': f'r{i+1}',
                 'kind': 'sfx' if item['label'] == 'onomatopoeia' else 'text',
                 'bbox': [item['bbox'][0] / width * 1000,
                          item['bbox'][1] / height * 1000,
                          item['bbox'][2] / width * 1000,
                          item['bbox'][3] / height * 1000],
                 'source_ownership': {'schema': 1, 'detector_ids': item.get('source_detector_ids', []),
                     'labels': item.get('source_labels', [item['label']]), 'cross_label_alias': item.get('cross_label_alias', False),
                     'bubble_verified': bool(item.get('bubble_owner')) or bubble_verified(item, bubbles),
                     **({'bubble_owner':item['bubble_owner'],'ocr_owner_mask':item['ocr_owner_mask'],
                         'style_ink_mask':item.get('mask')}
                        if item.get('bubble_owner') else {}),
                     **({'boundary_partition':item['boundary_partition']} if item.get('boundary_partition') else {}),
                     **({'review_reason':ambiguity_reasons[i],'related_region_ids':ambiguous[i]} if i in ambiguous else {})},
                 **({'line_bboxes_pixels': item['line_bboxes']} if 'line_bboxes' in item else {})}
                for i, item in enumerate(selected)]
        value = encode({'regions': rows, 'origin': 'rfdetr',
                        **({'needs_review':True,'review_reason':('ambiguous_source_overlap' if 'ambiguous_source_overlap' in ambiguity_reasons.values() else 'ambiguous_cross_label_source')} if ambiguous else {}),
                        **({'needs_review':True,'review_reason':'unresolved_detection_boundary',
                            'boundary_review':{**result.get('boundary_review', {}), 'schema':1,
                                'protected_boxes_pixels':protected}} if protected else {}),
                        **({'region_preservation':local_review} if local_review else {}),
                        **({'page_status':'no_text_detected'} if not rows else {}),
                        **({'needs_review':True,'no_text_reason':'excluded_onomatopoeia_present'}
                           if not rows and result.get('detection_audit',{}).get('excluded_onomatopoeia_detections',0) else {}),
                        **({'no_text_reason':'unresolved_detection_boundary'} if protected and not rows else {}),
                        'image_width': width, 'image_height': height,
                        'region_resolution': {
                            'input_regions': input_count,
                            'partitioned_candidates':len(candidates),
                            'source_owner_partition':{'schema':1,'observations':owner_partitions,
                                'scope':'whole_source_components_in_verified_bubble_interiors'},
                            'boundary_partition':{'schema':1,'split_observations':len(partitions),'observations':partitions,
                                'separator_count':len(barriers),'scope':'detector_frames_and_empty_mask_strips_not_semantic_ownership'},
                            'resolved_regions': len(selected),
                            'grouped_lines': before_grouping-len(selected),
                            'dedupe_iou': dedupe_iou,
                            'containment_overlap': _CONTAINMENT_OVERLAP,
                            'boundary_recovery': result.get('detail_detection', {}).get('boundary_recovery'),
                            'detection_audit':result.get('detection_audit'),
                        }})
        layout(value)
        return (value,)
