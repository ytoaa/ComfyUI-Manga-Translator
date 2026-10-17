"""Improved detail-detection policy for manga text.

Equal page partitions magnify small glyphs but can cut long text rows exactly at
the tile boundary. Auto mode instead uses overlapping RF-DETR-native-size
windows. Detections touching an internal crop edge must be supported by an
unclipped detection or recovered with wider context before the region resolver.
A clipped vertical strip must never become a logical OCR paragraph.
"""
from .models import MangaDetectorDetail as _BaseDetectorDetail
from .models import _DETECTOR_NATIVE_SIZE, _offset_detection, _validate_thresholds, pil_image
from .nodes import _detector_region
from .mask_nodes import _decode_mask

import json
import logging
import math
import numpy as np

from .adapters.model import rle

LOG = logging.getLogger(__name__)

_TEXT_LABELS = {'text', 'onomatopoeia'}
_MAX_REGIONS = 512
_MAX_RECOVERY_CALLS = 16
_EDGE_TOLERANCE = 3


def _window_detections(result, window, width, height, stage):
    x0, y0, x1, y1 = window
    if (result.get('image_width'), result.get('image_height')) != (x1-x0, y1-y0):
        raise ValueError('Detail detector result dimensions differ from crop')
    output = []
    for item in result.get('detections', []):
        local = _detector_region(item, x1-x0, y1-y0)
        a, b, c, d = local['bbox']
        edges = []
        if item.get('label') in _TEXT_LABELS:
            if x0 > 0 and a <= _EDGE_TOLERANCE: edges.append('left')
            if y0 > 0 and b <= _EDGE_TOLERANCE: edges.append('top')
            if x1 < width and c >= x1-x0-_EDGE_TOLERANCE: edges.append('right')
            if y1 < height and d >= y1-y0-_EDGE_TOLERANCE: edges.append('bottom')
        shifted = _offset_detection(local, x0, y0, width, height)
        shifted['tile_provenance'] = {'stage': stage, 'window': list(window), 'clipped_edges': edges}
        output.append(shifted)
    return output


def _coverage(fragment, trusted, width, height):
    """Fraction of fragment support contained by same-label complete boxes."""
    candidates = [item for item in trusted if item['label'] == fragment['label']]
    raw = fragment.get('mask')
    if raw is not None:
        support, (x, y, w, h) = _decode_mask(raw, width, height)
        support = support > .5
    else:
        a, b, c, d = fragment['bbox']
        x, y = math.floor(a), math.floor(b)
        w, h = math.ceil(c)-x, math.ceil(d)-y
        support = np.ones((h, w), dtype=bool)
    count = np.count_nonzero(support)
    if not count:
        return 0.0
    covered = np.zeros((h, w), dtype=bool)
    for item in candidates:
        a, b, c, d = item['bbox']
        left, top = max(0, math.floor(a)-x), max(0, math.floor(b)-y)
        right, bottom = min(w, math.ceil(c)-x), min(h, math.ceil(d)-y)
        if right > left and bottom > top:
            covered[top:bottom, left:right] = True
    return float(np.count_nonzero(covered & support) / count)


def _covered(fragment, trusted, width, height):
    return _coverage(fragment, trusted, width, height) >= .98


def _stitch_fragments(fragments, width, height):
    """Certify overlapping, aligned pieces using observed outer endpoints.

    A chain is complete only when both outer ends were seen away from crop
    edges. Matching source windows must differ along the clipped axis, and
    line/block thickness must agree. A tall cross-row strip cannot bridge
    several ordinary horizontal rows. No box is enlarged into unobserved text.
    """
    stitched = []
    for axis, allowed in ((0, {'left', 'right'}), (1, {'top', 'bottom'})):
        ends = ('left', 'right') if axis == 0 else ('top', 'bottom')
        eligible = [item for item in fragments
                    if set(item['tile_provenance']['clipped_edges']) <= allowed
                    and set(item['tile_provenance']['clipped_edges']) & allowed]
        groups = []
        for candidate in eligible:
            related = []
            a = candidate['bbox']
            for i, group in enumerate(groups):
                for other in group:
                    b = other['bbox']
                    if candidate['label'] != other['label']:
                        continue
                    wa, wb = candidate['tile_provenance']['window'], other['tile_provenance']['window']
                    if (wa[axis], wa[axis+2]) == (wb[axis], wb[axis+2]):
                        continue
                    transverse = 1-axis
                    at, bt = a[transverse+2]-a[transverse], b[transverse+2]-b[transverse]
                    along_a, along_b = a[axis+2]-a[axis], b[axis+2]-b[axis]
                    cross = max(0., min(a[transverse+2],b[transverse+2])-max(a[transverse],b[transverse]))
                    overlap = max(0., min(a[axis+2],b[axis+2])-max(a[axis],b[axis]))
                    if (min(at,bt)/max(at,bt) >= .65 and cross/min(at,bt) >= .8
                            and overlap >= max(3., .1*min(along_a,along_b))):
                        related.append(i)
                        break
            # Prevent a chain of gradually thicker boxes from connecting a
            # single row to a multi-row strip through intermediate heights.
            members = [candidate] + [row for i in related for row in groups[i]]
            thicknesses = [row['bbox'][3-axis]-row['bbox'][1-axis] for row in members]
            if min(thicknesses)/max(thicknesses) < .65:
                related = []
            if not related:
                groups.append([candidate])
            else:
                members = [candidate]
                for i in reversed(related): members.extend(groups.pop(i))
                groups.append(members)
        for group in groups:
            low = min(item['bbox'][axis] for item in group)
            high = max(item['bbox'][axis+2] for item in group)
            # Endpoint evidence must be at the actual outer extent, not just an
            # interior member whose end happens to be visible in another tile.
            if not any(abs(item['bbox'][axis]-low) <= 1e-4 and
                       ends[0] not in item['tile_provenance']['clipped_edges'] for item in group):
                continue
            if not any(abs(item['bbox'][axis+2]-high) <= 1e-4 and
                       ends[1] not in item['tile_provenance']['clipped_edges'] for item in group):
                continue
            box = [min(item['bbox'][k] for item in group) if k < 2
                   else max(item['bbox'][k] for item in group) for k in range(4)]
            merged = {'label': group[0]['label'], 'score': max(item['score'] for item in group),
                      'bbox': box, 'tile_provenance': {'stage': 'stitched', 'clipped_edges': [],
                         'source_windows': [item['tile_provenance']['window'] for item in group]}}
            masks = [item['mask'] for item in group if item.get('mask') is not None]
            if masks:
                x,y = math.floor(box[0]),math.floor(box[1])
                w,h = math.ceil(box[2])-x,math.ceil(box[3])-y
                if w*h > 64*1024*1024:
                    raise ValueError('Stitched detector mask exceeds memory contract')
                pixels = np.zeros((h,w), dtype=bool)
                for raw in masks:
                    local,(mx,my,mw,mh) = _decode_mask(raw,width,height)
                    pixels[my-y:my-y+mh,mx-x:mx-x+mw] |= local > .5
                runs = rle(pixels)
                if len(runs) > 4_000_000:
                    raise ValueError('Stitched detector mask exceeds RLE contract')
                merged['mask'] = {'x':x,'y':y,'width':w,'height':h,'runs':runs}
            stitched.append(merged)
    return stitched


def _recovery_window(fragment, width, height, attempt):
    a, b, c, d = fragment['bbox']
    x0, y0, x1, y1 = fragment['tile_provenance']['window']
    edges = fragment['tile_provenance']['clipped_edges']
    # Preserve detail scale on the other axis. A long horizontal paragraph is
    # re-detected as a wide, short crop rather than another shrunken whole page.
    px = max(64, (c-a)*.15) * 2**attempt
    py = max(64, (d-b)*.15) * 2**attempt
    dx, dy = max(256, x1-x0) * 2**attempt, max(256, y1-y0) * 2**attempt
    return (max(0, math.floor(a-(dx if 'left' in edges else px))),
            max(0, math.floor(b-(dy if 'top' in edges else py))),
            min(width, math.ceil(c+(dx if 'right' in edges else px))),
            min(height, math.ceil(d+(dy if 'bottom' in edges else py))))


def _compact_recovery_window(fragment, width, height):
    """Move a detail-size window off the seam without stretching one axis.

    Expanded context is still tried first. This alternative encloses the whole
    observed fragment with padding, rather than extending a narrow strip to
    the page end. Oversized fragments keep the existing wide-context policy.
    """
    a,b,c,d=fragment['bbox']
    span=max(_DETECTOR_NATIVE_SIZE//2,math.ceil(c-a+128),math.ceil(d-b+128))
    if span>_DETECTOR_NATIVE_SIZE:
        return None
    w,h=min(width,span),min(height,span)
    x=max(0,min(width-w,math.floor((a+c-w)/2)))
    y=max(0,min(height-h,math.floor((b+d-h)/2)))
    return (x,y,x+w,y+h)


def _native_recovery_window(fragment, width, height, directed=False):
    """Shift a square model-size context off a large-page seam before stretching strips."""
    span=_DETECTOR_NATIVE_SIZE
    a,b,c,d=fragment['bbox']
    if min(width,height)<span or max(c-a,d-b)>span-128: return None
    cx,cy=(a+c)/2,(b+d)/2
    if directed:
        edges=fragment['tile_provenance']['clipped_edges']
        cx+=span*.2*(('right' in edges)-('left' in edges))
        cy+=span*.2*(('bottom' in edges)-('top' in edges))
    x=max(0,min(width-span,math.floor(cx-span/2)))
    y=max(0,min(height-span,math.floor(cy-span/2)))
    if not (x<=a and y<=b and c<=x+span and d<=y+span): return None
    return (x,y,x+span,y+span)


def _save_recovery_failure(image, diagnostic):
    """Persist bounded context and exact recovery results when a node cannot preview."""
    try:
        from pathlib import Path
        import uuid
        import folder_paths
        root=Path(folder_paths.get_output_directory())/'manga_translator'/'detection_failures'
        root.mkdir(parents=True,exist_ok=True)
        stem='boundary_'+uuid.uuid4().hex
        fragment={'bbox':diagnostic['bbox'],'tile_provenance':{'clipped_edges':diagnostic['edges']}}
        window=_native_recovery_window(fragment,*image.size) or _compact_recovery_window(fragment,*image.size)
        if window is None:
            a,b,c,d=diagnostic['bbox'];span=_DETECTOR_NATIVE_SIZE
            x=max(0,min(image.width-span,math.floor((a+c-span)/2)))
            y=max(0,min(image.height-span,math.floor((b+d-span)/2)))
            window=(x,y,min(image.width,x+span),min(image.height,y+span))
        preview=root/(stem+'_context.png')
        image.crop(window).save(preview)
        path=root/(stem+'.json')
        path.write_text(json.dumps({'schema':1,'image_size':list(image.size),
            **diagnostic,'context_window':list(window),'context_image':str(preview)},
            ensure_ascii=False,indent=2),encoding='utf-8')
        LOG.error('Manga boundary recovery inputs saved: %s',path)
        return str(path)
    except (ImportError,OSError,ValueError,AttributeError) as exc:
        LOG.warning('Could not save boundary recovery inputs: %s',type(exc).__name__)
        return None


def _recover_boundaries(image, model, thresholds, detections):
    width, height = image.size
    clipped = [item for item in detections
               if item.get('tile_provenance', {}).get('clipped_edges')]
    trusted = [item for item in detections
               if not item.get('tile_provenance', {}).get('clipped_edges')]
    pool = list(clipped)
    stitched = _stitch_fragments(pool,width,height)
    trusted.extend(stitched)
    stitch_keys = {(item['label'],tuple(item['bbox'])) for item in stitched}
    calls, attempts, recovered, seen, raw_count = [], [], 0, set(), len(detections)
    budget_exhausted = False
    def probe(fragment,window,strategy):
        nonlocal budget_exhausted,raw_count,recovered
        if window in seen:
            return False
        if len(calls)>=_MAX_RECOVERY_CALLS:
            budget_exhausted=True
            return False
        seen.add(window)
        calls.append(list(window))
        result=model.detect(image.crop(window),thresholds)
        items=_window_detections(result,window,width,height,'recovery')
        raw_count+=len(items)
        if raw_count>_MAX_REGIONS:
            raise ValueError('Detail detector produced too many regions during boundary recovery (limit=512)')
        complete=[item for item in items if not item['tile_provenance']['clipped_edges']]
        pool.extend(item for item in items if item['tile_provenance']['clipped_edges'])
        trusted.extend(complete)
        recovered+=len(complete)
        for item in _stitch_fragments(pool,width,height):
            key=(item['label'],tuple(item['bbox']))
            if key not in stitch_keys:
                trusted.append(item)
                stitch_keys.add(key)
        diagnostic = {'fragment_bbox':fragment['bbox'],'fragment_label':fragment['label'],
                          'fragment_score':fragment['score'],'window':list(window),'complete_regions':len(complete),
                          'strategy':strategy,
                          'clipped_regions':len(items)-len(complete),
                          'coverage':round(_coverage(fragment,trusted,width,height),4),
                          'detections':[{'bbox':item['bbox'],'label':item['label'],
                                         'edges':item['tile_provenance']['clipped_edges']} for item in items
                                        if item['label']==fragment['label']]}
        attempts.append(diagnostic)
        LOG.info('Manga boundary recovery: %s',json.dumps(diagnostic,ensure_ascii=False))
        return _covered(fragment,trusted,width,height)

    # Large native tiles can still cut a bubble or vertical text column. Try
    # balanced, shifted contexts at the original model scale for each fragment
    # before magnifying a narrow strip to several thousand pixels in one axis.
    initial_windows={tuple(item['tile_provenance']['window']) for item in detections
                     if item.get('tile_provenance',{}).get('window')}
    for directed in (False,True):
        for fragment in clipped:
            if budget_exhausted or _covered(fragment,trusted,width,height): continue
            window=_native_recovery_window(fragment,width,height,directed)
            if window is not None and window not in initial_windows:
                probe(fragment,window,'native_shifted' if directed else 'native_centered')
    for fragment in clipped:
        if _covered(fragment, trusted, width, height):
            continue
        for attempt in range(3):
            if probe(fragment,_recovery_window(fragment,width,height,attempt),'expanded_context'):
                break
            if budget_exhausted:
                break
        if budget_exhausted:
            break
    # Give every fragment its original context attempts before spending the
    # same shared budget on a different crop shape. Never rerun an input that
    # was already seen by detail/full inference or another recovery attempt.
    prior_windows={tuple(item['tile_provenance']['window']) for item in detections
                   if item.get('tile_provenance',{}).get('window')}
    prior_windows.add((0,0,width,height))
    for fragment in clipped:
        if budget_exhausted or _covered(fragment,trusted,width,height):
            continue
        window=_compact_recovery_window(fragment,width,height)
        if window is not None and window not in prior_windows:
            probe(fragment,window,'compact_context')
    # A later fragment may yield a complete region covering an earlier failed
    # crop. Judge the collected evidence once the recovery pass is finished.
    unresolved = [fragment for fragment in clipped if not _covered(fragment,trusted,width,height)]
    if unresolved:
        fragment = unresolved[0]
        diagnostic = {'bbox':fragment['bbox'], 'label':fragment['label'],'score':fragment['score'],
                      'edges':fragment['tile_provenance']['clipped_edges'],
                      'coverage':round(_coverage(fragment,trusted,width,height),4),
                      'unresolved_regions':len(unresolved),'budget_exhausted':budget_exhausted,
                      'attempts':attempts}
        LOG.error('Manga boundary recovery failed: %s',json.dumps(diagnostic,ensure_ascii=False))
        failure_path=_save_recovery_failure(image,diagnostic)
        reason = ('검출 타일 경계 복구 한도 초과 (boundary recovery limit=16; unresolved clipped text) '
                  if budget_exhausted else '검출 타일 경계 복구 실패 (unresolved clipped text) ')
        raise ValueError(reason +
                         f"bbox={fragment['bbox']}, edges={fragment['tile_provenance']['clipped_edges']}, "
                         f"coverage={diagnostic['coverage']:.1%}, recovery_windows={calls}; "
                         f'진단={failure_path or "저장 불가"}; 상세 재검출 결과는 Manga boundary recovery 로그를 확인하세요. OCR/번역은 중단했습니다.')
    if len(trusted) > _MAX_REGIONS:
        raise ValueError('Resolved detector produced too many regions (limit=512)')
    return trusted, {'clipped_regions':len(clipped),'recovery_calls':len(calls),
                     'stitched_regions':len(stitch_keys),'recovered_regions':recovered,
                     'windows':calls,'attempts':attempts,'unresolved_regions':0}


def _sliding_windows(length, tile_size, overlap):
    tile_size = min(int(tile_size), int(length))
    if tile_size <= 0 or length <= 0:
        raise ValueError('Invalid detail tile geometry')
    if tile_size >= length:
        return [(0, length)]
    # A supported UI value must never turn into a one-pixel inference stride.
    overlap = min(int(overlap), tile_size // 2)
    stride = max(1, tile_size - overlap)
    starts = list(range(0, max(1, length - tile_size + 1), stride))
    last = length - tile_size
    if not starts or starts[-1] != last:
        starts.append(last)
    return [(start, start + tile_size) for start in starts]


def _tile_size(mode):
    if mode == 'auto':
        return _DETECTOR_NATIVE_SIZE
    if mode == '2x':
        return _DETECTOR_NATIVE_SIZE // 2
    if mode == '3x':
        return _DETECTOR_NATIVE_SIZE // 3
    if mode == 'off':
        return None
    raise ValueError('Invalid detector detail mode')


def detail_detect(image, model, thresholds, detail_mode='auto', detail_overlap=64, include_sfx=True):
    if type(include_sfx) is not bool:
        raise ValueError('Invalid detector include_sfx switch')
    # Selection must precede boundary certification: an intentionally excluded
    # effect must neither stop dialogue OCR nor contribute cleanup pixels.
    ignored_sfx = 0
    counts={}
    def selected(result,stage='detail'):
        nonlocal ignored_sfx
        if (not isinstance(result,dict) or not isinstance(result.get('detections'),list)
                or any(not isinstance(item,dict) for item in result['detections'])):
            raise ValueError('Invalid detector response; expected an explicit detections list')
        stage_counts=counts.setdefault(stage,{})
        for item in result['detections']:
            label=item.get('label','unknown')
            stage_counts[label]=stage_counts.get(label,0)+1
        if include_sfx:
            return result
        detections = result.get('detections', [])
        kept = [item for item in detections if item.get('label') != 'onomatopoeia']
        ignored_sfx += len(detections)-len(kept)
        return {**result, 'detections': kept}

    def finish(result):
        audit={'include_sfx':include_sfx,'raw_counts_by_stage':counts,
               'excluded_onomatopoeia_detections':ignored_sfx,
               'selected_text_detections':sum(item.get('label') in
                    ({'text','onomatopoeia'} if include_sfx else {'text'}) for item in result['detections']),
               'counts_scope':'raw inference counts; duplicate detections across windows are included'}
        LOG.info('Manga detection selection: %s',audit)
        return {**result,'detection_audit':audit}

    full = selected(model.detect(image, thresholds),'full')
    width, height = image.size
    if (full.get('image_width'), full.get('image_height')) != (width, height):
        raise ValueError('Detector result dimensions differ from source image')
    if type(detail_overlap) is not int or not 0 <= detail_overlap <= 384:
        raise ValueError('Detector detail overlap must be 0..384 pixels')
    if detail_mode == 'off':
        return finish({**full, 'detail_detection': {
            'mode': detail_mode, 'strategy': 'off', 'tiles': 0, 'detail_regions': 0}})

    tile = _tile_size(detail_mode)
    x_windows = _sliding_windows(width, tile, detail_overlap) if width > tile else [(0, width)]
    y_windows = _sliding_windows(height, tile, detail_overlap) if height > tile else [(0, height)]

    # If the page already fits a single native-size window in auto mode, the
    # full-page inference is the detail inference; do not run it twice.
    single_native=detail_mode=='auto' and len(x_windows)==1 and len(y_windows)==1
    empty_selected=not any(item.get('label') in {'text','onomatopoeia'} for item in full['detections'])
    retry_small=single_native and empty_selected and max(width,height)>_DETECTOR_NATIVE_SIZE//2
    if single_native and not retry_small:
        return finish({**full, 'detail_detection': {
            'mode': detail_mode, 'strategy': 'native_sliding',
            'tile_size': tile, 'windows': [[0, width, 0, height]],
            'tiles': 0, 'detail_regions': 0}})

    windows = [] if retry_small else [[x0, x1, y0, y1] for y0, y1 in y_windows for x0, x1 in x_windows]
    # On large pages auto also checks compact crops. A single native-width pass
    # can still miss tiny paragraphs; these are actual extra detector calls,
    # not a claim that every text region is guaranteed to be recovered.
    if detail_mode == 'auto':
        native_windows = list(windows)
        # Keep large supported pages usable: trade detail scale for the fixed
        # inference budget rather than creating hundreds of compact windows.
        for compact in (_DETECTOR_NATIVE_SIZE // 2, 768):
            proposed = list(native_windows)
            for y0, y1 in _sliding_windows(height, compact, detail_overlap):
                for x0, x1 in _sliding_windows(width, compact, detail_overlap):
                    box = [x0, x1, y0, y1]
                    if box not in proposed:
                        proposed.append(box)
            if len(proposed) <= 64:
                windows = proposed
                break
    if len(windows) > 64:
        raise ValueError(f'Detail detection requires {len(windows)} windows; split the page (limit=64)')
    recovered = []
    for x0, x1, y0, y1 in windows:
        result = selected(model.detect(image.crop((x0, y0, x1, y1)), thresholds))
        recovered.extend(_window_detections(result, (x0, y0, x1, y1), width, height, 'detail'))
        if len(full.get('detections', [])) + len(recovered) > 512:
            raise ValueError('Detail detector produced too many regions; lower detail mode or raise confidence thresholds')

    if len(full.get('detections', [])) + len(recovered) > 512:
        raise ValueError('Detail detector produced too many regions; lower detail mode or raise confidence thresholds')
    # Recovery can itself discover excluded effects; apply the same selection
    # to every recovery response rather than only the initial detail pass.
    class RecoveryModel:
        def detect(self, crop, options):
            return selected(model.detect(crop, options),'recovery')
    complete, recovery = _recover_boundaries(image, RecoveryModel(), thresholds, list(full.get('detections', [])) + recovered)
    recovery['include_sfx'] = include_sfx
    recovery['ignored_sfx_detections'] = ignored_sfx
    return finish({**full,
            'detections': complete,
            # Do not send fragment geometry to OCR, but retain its segmentation
            # pixels for cleanup even if a complete detection has a sparser mask.
            'mask_fragments': [item for item in recovered
                               if item['tile_provenance']['clipped_edges']],
            'detail_detection': {
                'mode': detail_mode,
                'strategy': 'native_sliding',
                'tile_size': tile,
                'windows': windows,
                'tiles': len(windows),
                'detail_regions': len(recovered),
                'zero_selected_compact_retry':retry_small,
                'boundary_recovery': recovery,
            }})


class MangaDetectorDetailResolved(_BaseDetectorDetail):
    DESCRIPTION = ('전체 페이지 검출 뒤 RF-DETR native 크기의 겹친 sliding tile을 다시 검출합니다. '
                   '경계에서 잘린 글자는 넓은 문맥으로 재검출한 뒤 OCR에 전달하며 복구 실패 시 중단합니다. '
                   '중복 결과는 다음 MangaDetectionRegions 단계가 containment 기준으로 정리합니다.')

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema['optional'] = {'include_sfx': ('BOOLEAN', {'default': True,
            'tooltip': '효과음 검출을 복구·OCR·제거 대상으로 포함. 제외할 때 영역/마스크 노드도 함께 끄세요. 기존 그래프는 포함을 유지합니다.'})}
        return schema

    def detect(self, images, model, detail_mode='auto', detail_overlap=64, include_sfx=True, **thresholds):
        _validate_thresholds(thresholds)
        return (detail_detect(pil_image(images), model, thresholds, detail_mode, detail_overlap, include_sfx),)
