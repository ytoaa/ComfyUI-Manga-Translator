"""Conservative source identity and edit review; never an OCR confidence score."""
import numpy as np
from .mask_nodes import _decode_mask
from .limits import MAX_REGION_PIXELS


def mask_overlap(left, right):
    """Compare local masks in original pixels without allocating a page mask."""
    if not all(isinstance(raw, dict) for raw in (left, right)):
        return None
    try:
        if any(raw['width'] * raw['height'] > MAX_REGION_PIXELS for raw in (left, right)):
            return None
        width = max(raw['x'] + raw['width'] for raw in (left, right))
        height = max(raw['y'] + raw['height'] for raw in (left, right))
        a, ab = _decode_mask(left, width, height)
        b, bb = _decode_mask(right, width, height)
    except (KeyError, TypeError, ValueError):
        return None
    a, b = a > .5, b > .5
    na, nb = int(a.sum()), int(b.sum())
    if not min(na, nb):
        return None
    x, y = max(ab[0], bb[0]), max(ab[1], bb[1])
    end_x, end_y = min(ab[0]+ab[2], bb[0]+bb[2]), min(ab[1]+ab[3], bb[1]+bb[3])
    common = int((a[y-ab[1]:end_y-ab[1], x-ab[0]:end_x-ab[0]] &
                  b[y-bb[1]:end_y-bb[1], x-bb[0]:end_x-bb[0]]).sum()) if end_x > x and end_y > y else 0
    return {'intersection': common, 'left_pixels': na, 'right_pixels': nb,
            'smaller_coverage': common/min(na, nb), 'larger_coverage': common/max(na, nb),
            'iou': common/(na+nb-common)}


def cross_label_alias(a, b):
    # Matching rectangles alone can contain separate caption/effect layers.
    # Keep the exact original frame requirement as well as mutual ink support.
    if {a['label'], b['label']} != {'text', 'onomatopoeia'} or a['bbox'] != b['bbox']:
        return False
    overlap = mask_overlap(a.get('mask'), b.get('mask'))
    return bool(overlap and overlap['smaller_coverage'] >= .92 and overlap['larger_coverage'] >= .70)


def bubble_verified(item, bubbles):
    for bubble in bubbles:
        if not isinstance(bubble.get('mask'), dict):
            continue
        a, b = item['bbox'], bubble['bbox']
        if not (b[0] <= a[0] and b[1] <= a[1] and b[2] >= a[2] and b[3] >= a[3]):
            continue
        overlap = mask_overlap(item.get('mask'), bubble['mask'])
        if overlap and overlap['intersection']/overlap['left_pixels'] >= .95:
            return True
    return False


def review_reason(row, width, height):
    """Require review of ambiguous isolated sources; not a non-text classifier.

    Only new detector-owned regions opt into this contract. Manual documents
    keep their existing permission semantics. Explicit replace overrides this
    conservative review, but never overrides protected neighbours.
    """
    evidence = row.get('source_ownership')
    if not isinstance(evidence, dict) or evidence.get('schema') != 1:
        return None
    if evidence.get('review_reason') in ('ambiguous_cross_label_source','ambiguous_source_overlap'):
        return evidence['review_reason']
    if evidence.get('bubble_verified') is True:
        return None
    source = ''.join(c for c in row.get('source', '') if not c.isspace())
    if len(source) <= 1:
        return 'ambiguous_isolated_source'
    rows = row.get('line_bboxes_pixels', [])
    if len(rows) > 1 and all((box[2]-box[0]) >= 3*(box[3]-box[1]) for box in rows):
        return None
    lines = row.get('ocr_diagnostics', {}).get('line_count', 1)
    if type(lines) is int and 2 <= lines <= 64:
        return None
    a, b, c, d = row['bbox']
    w, h = (c-a)*width/1000, (d-b)*height/1000
    if (h >= height*.32 and h >= w*1.8) or (w >= width*.4 and h >= height*.10):
        return 'unverified_display_text'
    return None
