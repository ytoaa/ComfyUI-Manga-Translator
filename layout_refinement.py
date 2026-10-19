"""Conservative page-column ownership before recognition, not OCR confidence.

Only a repeated multi-column detector layout with overlapping cross-column
boxes is changed. Pixel gaps must corroborate the detector's column anchors.
Analysis ignores small specks/rulings; recognition always uses original RGB.
"""
import math

import numpy as np
from scipy import ndimage


def _runs(active):
    indices = np.flatnonzero(active)
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1)+1)
    return [[int(g[0]), int(g[-1])+1] for g in groups if len(g)]


def _foreground(image, both=False):
    gray = np.asarray(image.convert('L'), np.float32)
    detail = gray-ndimage.uniform_filter(gray, 31, mode='reflect')
    positive, negative = float(np.percentile(detail, 99)), -float(np.percentile(detail, 1))
    foreground = np.abs(detail) > 24 if both else detail > 24 if positive > negative*1.2 else detail < -24
    labels, count = ndimage.label(foreground, structure=np.ones((3, 3), bool))
    if count > 65536:
        raise ValueError('Page layout analysis exceeds component limit')
    keep = np.bincount(labels.ravel(), minlength=count+1) >= 8
    keep[0] = False
    for index, slices in enumerate(ndimage.find_objects(labels), 1):
        if slices is None:
            continue
        y, x = slices
        w, h = x.stop-x.start, y.stop-y.start
        if (h <= 3 and w > image.width*.5) or (w <= 3 and h > 30):
            keep[index] = False
    return keep[labels]


def _anchors(boxes, width):
    groups = []
    for row, box in sorted(boxes, key=lambda pair: pair[1][2]-pair[1][0]):
        x, _, right, _ = box
        span = right-x
        if span > width*.4:
            continue
        match = next((g for g in groups if min(right, g['right'])-max(x, g['left'])
                      >= min(span, g['right']-g['left'])*.75), None)
        if match is None:
            groups.append({'left': x, 'right': right, 'members': [(row, box)]})
        else:
            match['left'], match['right'] = min(x, match['left']), max(right, match['right'])
            match['members'].append((row, box))
    anchors = []
    for group in groups:
        members = group['members']
        anchors.append({'left': int(np.median([b[0] for _, b in members])),
                        'right': int(np.median([b[2] for _, b in members])),
                        'members': [r['id'] for r, _ in members]})
    return sorted(anchors, key=lambda a: a['left'])


def _covers(box, anchor):
    return (min(box[2], anchor['right'])-max(box[0], anchor['left'])
            >= (anchor['right']-anchor['left'])*.65)


def _bands(foreground):
    found = []
    for top, bottom in _runs(foreground.any(axis=1)):
        if found and top-found[-1][1] < 4:
            found[-1][1] = bottom
        else:
            found.append([top, bottom])
    # Tiny isolated remnants cannot establish a row. They remain in RGB crops.
    return [(a, b) for a, b in found if b-a >= 6]


def _horizontal(foreground, bands):
    good = 0
    for top, bottom in bands:
        row = foreground[top:bottom]
        _, count = ndimage.label(row, structure=np.ones((3, 3), bool))
        good += np.count_nonzero(row.any(axis=0)) >= 3*(bottom-top) and count >= 3
    return len(bands) >= 3 and good >= math.ceil(len(bands)*.75)


def _join_auxiliary_rows(image, bands, left_width, right_start, coverage):
    """A light section number in a gutter must never be split between rows."""
    auxiliary = _foreground(image, both=True)
    auxiliary &= coverage
    auxiliary[:, left_width:right_start] = False
    labels, _ = ndimage.label(auxiliary, structure=np.ones((3, 3), bool))
    spans = []
    for slices in ndimage.find_objects(labels):
        if slices is None:
            continue
        y, x = slices
        w, h = x.stop-x.start, y.stop-y.start
        if w >= 4 and h >= 6 and h <= max(40, w*4):
            spans.append((y.start, y.stop))
    merged = []
    for top, bottom in bands:
        if merged:
            cut = (merged[-1][1]+top)//2
            if any(a < cut < b and a < bottom and merged[-1][0] < b for a, b in spans):
                merged[-1] = (merged[-1][0], bottom)
                continue
        merged.append((top, bottom))
    return merged


def refine_columns(image, data):
    """Return new logical regions + pixel ownership, or the original unchanged.

    No decoded words are used to decide layout. Refined regions must be read
    again. Cuts have bounded work and ambiguous layouts retain the legacy path.
    """
    width, height = image.size
    unchanged = (data, {})
    if (data.get('origin') != 'rfdetr' or len(data['regions']) < 5
            or any(row.get('kind', 'text') != 'text' for row in data['regions'])):
        return unchanged
    boxes = [(row, [math.floor(row['bbox'][0]*width/1000),
                    math.floor(row['bbox'][1]*height/1000),
                    math.ceil(row['bbox'][2]*width/1000),
                    math.ceil(row['bbox'][3]*height/1000)]) for row in data['regions']]
    anchors = _anchors(boxes, width)
    auxiliary = []
    if len(anchors) >= 4:
        typical = float(np.median([a['right']-a['left'] for a in anchors]))
        body = [a for a in anchors if a['right']-a['left'] >= typical*.55]
        extra = [(r,b) for r,b in boxes if not any(_covers(b,a) for a in body)]
        core = [(r,b) for r,b in boxes if any(_covers(b,a) for a in body)]
        if (len(body) >= 3 and extra and
                all(b[2] <= min(b[0] for _,b in core)-8 or
                    b[0] >= max(b[2] for _,b in core)+8 for _,b in extra)):
            auxiliary = extra
            ids = {r['id'] for r,_ in extra}
            boxes = [(r,b) for r,b in boxes if r['id'] not in ids]
            anchors = body
    if not 3 <= len(anchors) <= 8 or not any(len(a['members']) >= 3 for a in anchors):
        return unchanged
    if any(b['left']-a['right'] < 8 for a, b in zip(anchors, anchors[1:])):
        return unchanged
    if any(not any(_covers(box, anchor) for anchor in anchors) for _, box in boxes):
        # Never discard a selected small label just because it cannot establish
        # a recurring column. Ambiguity keeps the complete original layout.
        return unchanged
    crossing = [(row, box) for row, box in boxes if sum(_covers(box, a) for a in anchors) >= 2]
    if len(crossing) < 2:
        return unchanged
    left_aux = [b[2] for _,b in auxiliary if b[2] <= anchors[0]['left']-8]
    right_aux = [b[0] for _,b in auxiliary if b[0] >= anchors[-1]['right']+8]
    cuts = [(max(left_aux)+min(b[0] for _,b in boxes))//2 if left_aux else 0]
    for left, right in zip(anchors, anchors[1:]):
        relevant = [b for _, b in crossing if _covers(b, left) and _covers(b, right)]
        if not relevant:
            return unchanged
        a, b = left['right'], right['left']
        occupied = np.zeros(b-a, bool)
        for box in relevant:
            # Gutter cuts must also respect light glyphs on dark markers.
            foreground = _foreground(image.crop((a, box[1], b, box[3])), both=True)
            occupied |= foreground.any(axis=0)
        # Require two adjacent clear columns in the observed gutter.
        clear = ~occupied
        choices = np.flatnonzero(clear & np.r_[clear[1:], False])
        if not len(choices):
            return unchanged
        cut = a+int(choices[np.argmin(np.abs(choices-(b-a)/2))])+1
        cuts.append(cut)
    cuts.append((max(b[2] for _,b in boxes)+min(right_aux))//2 if right_aux else width)
    panes = []
    verified = 0
    for index, anchor in enumerate(anchors):
        left, right = cuts[index:index+2]
        members = [(r, [max(left, b[0]), b[1], min(right, b[2]), b[3]])
                   for r, b in boxes if _covers(b, anchor)]
        if not members:
            return unchanged
        x0, x1 = min(b[0] for _, b in members), max(b[2] for _, b in members)
        y0, y1 = min(b[1] for _, b in members), max(b[3] for _, b in members)
        # Limit the analysis to the recurring column core. Auxiliary gutter
        # graphics cannot bridge every body row, but stay in recognition RGB.
        ax, bx = max(x0, anchor['left']), min(x1, anchor['right'])
        foreground = _foreground(image.crop((ax, y0, bx, y1)))
        selected = np.zeros(foreground.shape, bool)
        for _, box in members:
            selected[box[1]-y0:box[3]-y0, max(0, box[0]-ax):min(bx-ax, box[2]-ax)] = True
        foreground &= selected
        bands = _bands(foreground)
        if not bands or len(bands) > 128:
            return unchanged
        verified += _horizontal(foreground, bands)
        coverage = np.zeros((y1-y0, x1-x0), bool)
        for _, box in members:
            coverage[box[1]-y0:box[3]-y0, box[0]-x0:box[2]-x0] = True
        bands = _join_auxiliary_rows(image.crop((x0, y0, x1, y1)), bands, ax-x0, bx-x0, coverage)
        panes.append((members, [x0, y0, x1, y1], [(a+y0, b+y0) for a, b in bands]))
    if verified < 2:
        return unchanged
    rows, plans = [], {}
    for column, (members, extent, bands) in enumerate(panes):
        typical = float(np.median([b-a for a, b in bands]))
        groups = []
        for band in bands:
            # Paragraph gaps, headings and bounded eight-row recognition units.
            if (not groups or band[0]-groups[-1][-1][1] >= max(8, typical*1.25)
                    or (band[1]-band[0] > typical*3) != (groups[-1][-1][1]-groups[-1][-1][0] > typical*3)):
                groups.append([])
            groups[-1].append(band)
        # Balance bounded chunks: a nine-row paragraph becomes five + four,
        # not eight rows and an orphan with a tiny lettering frame.
        groups = [list(chunk) for group in groups
                  for chunk in np.array_split(np.asarray(group), math.ceil(len(group)/8))]
        groups = [[(int(a), int(b)) for a, b in group] for group in groups]
        borders = [0, *[(a[-1][1]+b[0][0])//2 for a, b in zip(groups, groups[1:])], height]
        for part, group in enumerate(groups):
            ident = f'c{column+1}p{part+1}'
            top, bottom = group[0][0], group[-1][1]
            active = [(r, box) for r, box in members if box[1] < bottom and top < box[3]]
            owners = [r['id'] for r, _ in active]
            # A wide detection crossing one row must not widen every paragraph
            # in that column and introduce previously unselected gutter text.
            box = [min(b[0] for _, b in active), top, max(b[2] for _, b in active), bottom]
            rows.append({'id': ident, 'kind': 'text', 'bbox': [box[i]*1000/[width, height, width, height][i] for i in range(4)],
                         'layout_sources': owners, 'layout_column': column+1})
            plans[ident] = {'bounds_pixels': box, 'ownership_pixels': [cuts[column], borders[part], cuts[column+1], borders[part+1]],
                            'row_bands_pixels': [[box[0], a, box[2], b] for a, b in group]}
    for row, box in auxiliary:
        if row['id'] in plans:
            return unchanged
        owner = [0,0,cuts[0],height] if box[2] <= cuts[0] else [cuts[-1],0,width,height]
        rows.append({**row,'layout_auxiliary':True})
        plans[row['id']] = {'bounds_pixels':box,'ownership_pixels':owner}
    if len(rows) > 64:
        raise ValueError('Refined page exceeds 64 logical regions; review detector regions')
    refined = {**data, 'regions': rows, 'layout_refinement': {
        'strategy': 'verified_page_columns', 'input_regions': len(boxes)+len(auxiliary), 'output_regions': len(rows),
        'auxiliary_region_ids': [r['id'] for r,_ in auxiliary],
        'column_cuts_pixels': cuts, 'anchors': anchors, 'overlapping_cross_column_regions': [r['id'] for r, _ in crossing],
        'max_rows_per_region': 8, 'analysis_min_component_pixels': 8,
        'scope': 'layout_only_not_recognition_accuracy'}}
    return refined, plans


def crop_plan(ident, geometry, crop):
    bands = geometry['row_bands_pixels']
    borders = [crop[1], *[(a[3]+b[1])//2 for a, b in zip(bands, bands[1:])], crop[3]]
    return {'strategy': 'verified_page_rows', 'region_id': ident,
            'source_size': [crop[2]-crop[0], crop[3]-crop[1]],
            'rows': [[0, a-crop[1], crop[2]-crop[0], b-crop[1]] for a, b in zip(borders, borders[1:])]}


def planned_inputs(image, value):
    """Validate an explicit per-region row plan; it must partition the RGB crop."""
    if value.get('strategy') != 'verified_page_rows':
        raise ValueError('Unsupported OCR region plan')
    rows = value.get('rows')
    if (value.get('source_size') != list(image.size) or not isinstance(value.get('region_id'), str)
            or not isinstance(rows, list) or not 1 <= len(rows) <= 8):
        raise ValueError('OCR region plan does not match crop size or row limit')
    previous = 0
    for box in rows:
        if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box)
                or box[0] != 0 or box[2] != image.width or box[1] != previous
                or not box[1] < box[3] <= image.height):
            raise ValueError('OCR region plan must partition the complete crop')
        previous = box[3]
    if previous != image.height:
        raise ValueError('OCR region plan must partition the complete crop')
    return [image.crop(box) for box in rows]
