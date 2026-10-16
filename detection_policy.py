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

import math
import numpy as np

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


def _covered(fragment, trusted, width, height):
    """Require 98% support from same-label, unclipped regions, before merging.

    For a multi-row strip, segmentation support matters: blank line gaps must
    not prevent separate complete rows from replacing one erroneous strip.
    With no mask, use the entire bounding rectangle conservatively.
    """
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
    if not support.any():
        return False
    covered = np.zeros((h, w), dtype=bool)
    for item in candidates:
        a, b, c, d = item['bbox']
        left, top = max(0, math.floor(a)-x), max(0, math.floor(b)-y)
        right, bottom = min(w, math.ceil(c)-x), min(h, math.ceil(d)-y)
        if right > left and bottom > top:
            covered[top:bottom, left:right] = True
    return np.count_nonzero(covered & support) >= .98 * np.count_nonzero(support)


def _recovery_window(fragment, width, height, attempt):
    a, b, c, d = fragment['bbox']
    x0, y0, x1, y1 = fragment['tile_provenance']['window']
    edges = fragment['tile_provenance']['clipped_edges']
    # Preserve detail scale on the other axis. A long horizontal paragraph is
    # re-detected as a wide, short crop rather than another shrunken whole page.
    px = max(64, (c-a)*.15)
    py = max(64, (d-b)*.15)
    dx, dy = max(256, x1-x0) * 2**attempt, max(256, y1-y0) * 2**attempt
    return (max(0, math.floor(a-(dx if 'left' in edges else px))),
            max(0, math.floor(b-(dy if 'top' in edges else py))),
            min(width, math.ceil(c+(dx if 'right' in edges else px))),
            min(height, math.ceil(d+(dy if 'bottom' in edges else py))))


def _recover_boundaries(image, model, thresholds, detections):
    width, height = image.size
    clipped = [item for item in detections
               if item.get('tile_provenance', {}).get('clipped_edges')]
    trusted = [item for item in detections
               if not item.get('tile_provenance', {}).get('clipped_edges')]
    calls, recovered, seen, raw_count = [], 0, set(), len(detections)
    for fragment in clipped:
        if _covered(fragment, trusted, width, height):
            continue
        for attempt in range(3):
            window = _recovery_window(fragment, width, height, attempt)
            if window in seen:
                continue
            if len(calls) >= _MAX_RECOVERY_CALLS:
                raise ValueError('검출 타일 경계 복구 한도 초과 (boundary recovery limit=16); '
                                 '페이지를 나누거나 검출 설정을 조정하세요. OCR은 실행하지 않았습니다.')
            seen.add(window)
            calls.append(list(window))
            result = model.detect(image.crop(window), thresholds)
            items = _window_detections(result, window, width, height, 'recovery')
            raw_count += len(items)
            if raw_count > _MAX_REGIONS:
                raise ValueError('Detail detector produced too many regions during boundary recovery (limit=512)')
            complete = [item for item in items if not item['tile_provenance']['clipped_edges']]
            trusted.extend(complete)
            recovered += len(complete)
            if _covered(fragment, trusted, width, height):
                break
        if not _covered(fragment, trusted, width, height):
            raise ValueError('검출 타일 경계 복구 실패 (unresolved clipped text) '
                             f"bbox={fragment['bbox']}, edges={fragment['tile_provenance']['clipped_edges']}; "
                             '잘린 영역의 OCR/번역을 중단했습니다. 상세 검출을 조정해 다시 실행하세요.')
    return trusted, {'clipped_regions': len(clipped), 'recovery_calls': len(calls),
                     'recovered_regions': recovered, 'windows': calls, 'unresolved_regions': 0}


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


def detail_detect(image, model, thresholds, detail_mode='auto', detail_overlap=64):
    full = model.detect(image, thresholds)
    width, height = image.size
    if (full.get('image_width'), full.get('image_height')) != (width, height):
        raise ValueError('Detector result dimensions differ from source image')
    if type(detail_overlap) is not int or not 0 <= detail_overlap <= 384:
        raise ValueError('Detector detail overlap must be 0..384 pixels')
    if detail_mode == 'off':
        return {**full, 'detail_detection': {
            'mode': detail_mode, 'strategy': 'off', 'tiles': 0, 'detail_regions': 0}}

    tile = _tile_size(detail_mode)
    x_windows = _sliding_windows(width, tile, detail_overlap) if width > tile else [(0, width)]
    y_windows = _sliding_windows(height, tile, detail_overlap) if height > tile else [(0, height)]

    # If the page already fits a single native-size window in auto mode, the
    # full-page inference is the detail inference; do not run it twice.
    if detail_mode == 'auto' and len(x_windows) == 1 and len(y_windows) == 1:
        return {**full, 'detail_detection': {
            'mode': detail_mode, 'strategy': 'native_sliding',
            'tile_size': tile, 'windows': [[0, width, 0, height]],
            'tiles': 0, 'detail_regions': 0}}

    windows = [[x0, x1, y0, y1] for y0, y1 in y_windows for x0, x1 in x_windows]
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
        result = model.detect(image.crop((x0, y0, x1, y1)), thresholds)
        recovered.extend(_window_detections(result, (x0, y0, x1, y1), width, height, 'detail'))
        if len(full.get('detections', [])) + len(recovered) > 512:
            raise ValueError('Detail detector produced too many regions; lower detail mode or raise confidence thresholds')

    if len(full.get('detections', [])) + len(recovered) > 512:
        raise ValueError('Detail detector produced too many regions; lower detail mode or raise confidence thresholds')
    complete, recovery = _recover_boundaries(image, model, thresholds, list(full.get('detections', [])) + recovered)
    return {**full,
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
                'boundary_recovery': recovery,
            }}


class MangaDetectorDetailResolved(_BaseDetectorDetail):
    DESCRIPTION = ('전체 페이지 검출 뒤 RF-DETR native 크기의 겹친 sliding tile을 다시 검출합니다. '
                   '경계에서 잘린 글자는 넓은 문맥으로 재검출한 뒤 OCR에 전달하며 복구 실패 시 중단합니다. '
                   '중복 결과는 다음 MangaDetectionRegions 단계가 containment 기준으로 정리합니다.')

    def detect(self, images, model, detail_mode='auto', detail_overlap=64, **thresholds):
        _validate_thresholds(thresholds)
        return (detail_detect(pil_image(images), model, thresholds, detail_mode, detail_overlap),)
