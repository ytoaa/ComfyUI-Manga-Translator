"""Whole-component ownership from bubble interiors, before OCR.

Rectangles are not ownership certificates. Every input mask pixel must belong
to one complete bubble component; ambiguous/unsupported observations stay intact.
No OCR strings are compared, trimmed or reconstructed here.
"""
import numpy as np
from scipy import ndimage
from .mask_nodes import _decode_mask, _mask_metadata
from .limits import MAX_REGION_PIXELS, MAX_SOURCE_PIXELS
from .region_boundaries import encode_mask, intersection


def _local(raw, bounds, width, height):
    """Project a bounded RLE into another local frame, never a page allocation."""
    x, y, w, h = bounds
    values = np.zeros((h, w), bool)
    a, b, c, d = _mask_metadata(raw, width, height)[0]
    left, top, right, bottom = max(x, a), max(y, b), min(x+w, a+c), min(y+h, b+d)
    if left < right and top < bottom:
        if c*d > MAX_REGION_PIXELS:
            raise ValueError('Source owner mask exceeds 16 Mi pixels')
        decoded, _ = _decode_mask(raw, width, height)
        values[top-y:bottom-y, left-x:right-x] = decoded[top-b:bottom-b, left-a:right-a] > .5
    return values


def partition_by_bubbles(items, bubbles, width, height):
    if not items:return [], []
    from .lettering.bubble_constraints import _merge
    owners = []
    # Repeated full/detail observations must not create separate owners.
    for bubble in bubbles:
        raw = bubble.get('mask')
        if raw is None or bubble.get('tile_provenance', {}).get('clipped_edges'):
            continue
        bounds, _ = _mask_metadata(raw, width, height)
        if bounds[2]*bounds[3] > MAX_REGION_PIXELS:
            continue
        pixels, _ = _decode_mask(raw, width, height)
        if not (pixels > .5).any():
            continue
        if int((pixels > .5).sum()) > width*height*.7:
            # Page/panel-sized false bubble labels cannot unify paragraphs.
            continue
        _merge(owners, {'bounds': list(bounds), 'mask': pixels > .5, 'source': 'detector'})
        if len(owners) > 512 or sum(o['mask'].size for o in owners) > MAX_SOURCE_PIXELS:
            return items, [{'status':'unavailable','reason':'source_owner_working_set_budget'}]
    for i, owner in enumerate(owners):
        x, y, _, _ = owner['bounds']
        owner['raw'], _ = encode_mask(owner['mask'], x, y)
        owner['pixels'] = int(owner['mask'].sum())
        owner['id'] = f'b{i+1}'
    result, audit = [], []
    for item in items:
        raw = item.get('mask')
        if item['label'] not in ('text','onomatopoeia') or raw is None:
            result.append(item); continue
        bounds, _ = _mask_metadata(raw, width, height)
        if bounds[2]*bounds[3] > MAX_REGION_PIXELS:
            raise ValueError('Source partition mask exceeds 16 Mi pixels')
        possible = [o for o in owners if intersection(item['bbox'],
                    [o['bounds'][0], o['bounds'][1], o['bounds'][0]+o['bounds'][2], o['bounds'][1]+o['bounds'][3]])]
        if not possible:
            result.append(item); continue
        pixels, _ = _decode_mask(raw, width, height); pixels = pixels > .5
        labels, count = ndimage.label(pixels, np.ones((3, 3), bool))
        if not count or count > 32768:
            result.append(item); continue
        areas = np.bincount(labels.ravel(), minlength=count+1)
        memberships = []
        for owner in possible:
            local = _local(owner['raw'], bounds, width, height)
            hits = np.bincount(labels[local].ravel(), minlength=count+1)
            memberships.append(hits == areas)
        from .source_ownership import mask_overlap
        nesting = {}
        def nested(a, b):
            key = tuple(sorted((a, b)))
            if key not in nesting:
                support = mask_overlap(possible[a]['raw'], possible[b]['raw'])
                nesting[key] = bool(support and support['smaller_coverage'] >= .99)
            return nesting[key]
        assigned = np.full(count+1, -1, np.int32)
        for label in range(1, count+1):
            matches = [i for i, member in enumerate(memberships) if member[label]]
            if not matches: break
            best = min(matches, key=lambda i: possible[i]['pixels'])
            # Nested page-sized interiors are not rival owners. Non-nested
            # overlapping bubbles cannot decide ownership of a shared glyph.
            if any(not nested(best, i) for i in matches if i != best):
                break
            assigned[label] = best
        if (assigned[1:] < 0).any():
            result.append(item); continue
        parts = []
        x, y, _, _ = bounds
        for owner_index in sorted(set(assigned[1:].tolist())):
            selected = pixels & (assigned[labels] == owner_index)
            encoded, ink = encode_mask(selected, x, y)
            owner = possible[owner_index]
            split = len(set(assigned[1:].tolist())) > 1
            competing = any(other is not item and intersection(item['bbox'], other['bbox']) > 0 for other in items)
            # Tighten competing observations to their owned ink. The exact
            # positive source mask survives in one and only one part.
            box = [max(0, ink[0]-2), max(0, ink[1]-2), min(width, ink[2]+2), min(height, ink[3]+2)] if split or competing else item['bbox']
            parts.append({**item, 'bbox': box, 'mask': encoded, '_ink_bbox': ink,
                          '_identity_bbox':item.get('_identity_bbox',item['bbox']),
                          '_owned_frame':split or competing,
                          'bubble_owner': owner['id'], 'ocr_owner_mask': owner['raw']})
        if sum(sum(p['mask']['runs'][1::2]) for p in parts) != int(pixels.sum()):
            raise ValueError('Source owner partition changed source pixels')
        result.extend(parts)
        audit.append({'detector_ids': item.get('source_detector_ids', []), 'parts': len(parts),
                      'source_ink_pixels': int(pixels.sum()), 'owners': [p['bubble_owner'] for p in parts]})
        if len(result) > 512:
            raise ValueError('Source owner partition exceeds 512 candidates')
    return result, audit


def isolate_crop(crop, raw, bounds, width, height):
    """Neutralize pixels outside the verified owner in an OCR copy only."""
    x, y, right, bottom = bounds
    allowed = _local(raw, (x, y, right-x, bottom-y), width, height)
    # Whole source components were certified inside this exact interior.
    # Expanding it admits neighboring ink at touching edges and fills small
    # holes, invalidating that certificate. Keep the OCR copy strictly bounded.
    if not allowed.any(): raise ValueError('OCR owner does not intersect its crop')
    pixels = crop.detach().cpu().numpy()[0]
    rim = allowed & ~ndimage.binary_erosion(allowed, iterations=2)
    color = np.median(pixels[rim if rim.any() else allowed], axis=0)
    import torch
    output = crop.clone()
    output[0, torch.as_tensor(~allowed, device=crop.device)] = torch.as_tensor(color, dtype=crop.dtype, device=crop.device)
    return output, allowed
