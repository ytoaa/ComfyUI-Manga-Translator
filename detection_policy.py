"""Improved detail-detection policy for manga text.

Equal page partitions magnify small glyphs but can cut long text rows exactly at
the tile boundary. Auto mode instead uses overlapping RF-DETR-native-size
windows and keeps all tile detections; the containment-aware region resolver
collapses duplicates afterwards.
"""
from .models import MangaDetectorDetail as _BaseDetectorDetail
from .models import _DETECTOR_NATIVE_SIZE, _offset_detection, _validate_thresholds, pil_image


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
        for item in result.get('detections', []):
            recovered.append(_offset_detection(item, x0, y0, width, height))
        if len(full.get('detections', [])) + len(recovered) > 512:
            raise ValueError('Detail detector produced too many regions; lower detail mode or thresholds')

    if len(full.get('detections', [])) + len(recovered) > 512:
        raise ValueError('Detail detector produced too many regions; lower detail mode or thresholds')
    return {**full,
            'detections': list(full.get('detections', [])) + recovered,
            'detail_detection': {
                'mode': detail_mode,
                'strategy': 'native_sliding',
                'tile_size': tile,
                'windows': windows,
                'tiles': len(windows),
                'detail_regions': len(recovered),
            }}


class MangaDetectorDetailResolved(_BaseDetectorDetail):
    DESCRIPTION = ('전체 페이지 검출 뒤 RF-DETR native 크기의 겹친 sliding tile을 다시 검출합니다. '
                   '긴 문장을 반쪽 타일 경계에서 자르지 않으면서 작은 글씨의 실제 모델 입력 크기를 키우고, '
                   '중복 결과는 다음 MangaDetectionRegions 단계가 containment 기준으로 정리합니다.')

    def detect(self, images, model, detail_mode='auto', detail_overlap=64, **thresholds):
        _validate_thresholds(thresholds)
        return (detail_detect(pil_image(images), model, thresholds, detail_mode, detail_overlap),)
