"""Page-owned cleanup brush edits, independent of any external editor code.

Coordinates are original-page pixels. Brush permission never exceeds the saved
edit owner or defeats preservation; detector source ink cannot be subtracted.
"""
import base64
import hashlib
import io
import json

import numpy as np
from PIL import Image, ImageDraw

from .document import digest, review_identity, review_revision


def select(data, original, source, cleanup, edits_json, context_json, policy, legacy, tensor_sha256):
    if not isinstance(edits_json, str) or len(edits_json.encode()) > 1024*1024:
        raise ValueError('Cleanup review edits exceed 1 MiB')
    value = json.loads(edits_json)
    if not isinstance(value, dict) or set(value)-{'pages', 'identities'}:
        raise ValueError('Cleanup review needs pages and identities objects')
    pages, owners = value.get('pages', {}), value.get('identities', {})
    if (not isinstance(pages, dict) or len(pages) > 256 or not isinstance(owners, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in owners.items())):
        raise ValueError('Invalid cleanup review page identities')
    height, width = source.shape
    if (original.size != (width, height) or cleanup.shape != source.shape
            or not np.isfinite(source).all() or not np.isfinite(cleanup).all()):
        raise ValueError('Cleanup review page and masks differ or contain nonfinite pixels')
    rgb_sha = hashlib.sha256(original.convert('RGB').tobytes()).hexdigest()
    # Standalone nodes can safely own edits by exact RGB. Folder workflows add
    # the project/page identity so identical scanned pages remain independent.
    identity = review_identity(context_json) or {'page_key': 'image/'+rgb_sha, 'input_sha256': rgb_sha}
    evidence = {'source_rgb_sha256': rgb_sha, 'source_tensor_sha256':tensor_sha256,
                'source_mask_sha256': hashlib.sha256((source > .5).tobytes()).hexdigest(),
                'cleanup_mask_sha256': hashlib.sha256((cleanup > .5).tobytes()).hexdigest()}
    revision = digest({'document': review_revision(data, identity, 'target'), 'evidence': evidence,
                       'source_review_policy': policy, 'legacy_actions': legacy,
                       'safety':{'boundary_review':data.get('boundary_review'),
                                 'source_ownership':[r.get('source_ownership') for r in data['regions']]}})
    selected = pages.get(revision, {}) if owners.get(revision) == identity['page_key'] else {}
    if not isinstance(selected, dict) or set(selected)-{r['id'] for r in data['regions']}:
        raise ValueError('Cleanup review needs existing region IDs')
    points = 0
    for patch in selected.values():
        if not isinstance(patch, dict) or set(patch)-{'action', 'strokes'}:
            raise ValueError('Invalid cleanup review region fields')
        if patch.get('action', 'auto') not in ('auto', 'replace', 'preserve'):
            raise ValueError('Invalid cleanup review action')
        strokes = patch.get('strokes', [])
        if not isinstance(strokes, list) or len(strokes) > 128:
            raise ValueError('Cleanup review supports at most 128 strokes per region')
        for stroke in strokes:
            if (not isinstance(stroke, dict) or set(stroke) != {'mode', 'radius', 'points'}
                    or stroke['mode'] not in ('add', 'erase') or type(stroke['radius']) is not int
                    or not 1 <= stroke['radius'] <= 32 or not isinstance(stroke['points'], list)
                    or not 1 <= len(stroke['points']) <= 256):
                raise ValueError('Invalid cleanup review brush stroke')
            for point in stroke['points']:
                if (not isinstance(point, list) or len(point) != 2
                        or any(type(v) is not int for v in point)):
                    raise ValueError('Cleanup brush needs integer page-pixel points')
            points += len(stroke['points'])
    if points > 4096:
        raise ValueError('Cleanup review exceeds 4096 brush points per page')
    stale = [key for key in pages if key != revision and owners.get(key) == identity['page_key']]
    warnings = []
    if stale:
        warnings.append('입력·원문·번역·마스크·정책이 달라진 이전 편집은 적용하지 않았습니다. 확인 후 다시 저장하세요.')
    if any(key not in owners for key in pages):
        warnings.append('페이지 소유권이 없는 이전 편집은 적용하지 않았습니다.')
    return {'schema': 1, 'input_revision': revision, 'page_identity': identity['page_key'],
            **evidence, 'selected_edits': selected, 'warnings': warnings}


def paint(data, source, cleanup, selected):
    """Apply ordered local strokes, then retain source ink and all protections."""
    from .page_edit import masks, validate
    height, width = source.shape
    plan = validate(data, width, height)
    result = (cleanup > .5).copy()
    counts = []
    for row in plan['regions']:
        strokes = selected.get(row['id'], {}).get('strokes', [])
        a, b, c, d = row['bbox_pixels']
        # Validate even preserved strokes, rather than silently accepting stale
        # coordinates which could acquire permission after a later action edit.
        if any(not a <= x < c or not b <= y < d for s in strokes for x, y in s['points']):
            raise ValueError('Cleanup brush point is outside its region edit owner')
        if not strokes or row['action'] != 'replace':
            continue
        before = result[b:d, a:c].copy()
        local = Image.fromarray(before.astype('uint8')*255)
        draw = ImageDraw.Draw(local)
        for stroke in strokes:
            radius = stroke['radius']; fill = 255 if stroke['mode'] == 'add' else 0
            points = [(x-a, y-b) for x, y in stroke['points']]
            if len(points) > 1:
                draw.line(points, fill=fill, width=2*radius+1)
            for x, y in points:
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill)
        # Erasing a brush halo cannot exempt detector ink from cleanup checks.
        after = (np.asarray(local) > 0) | (source[b:d, a:c] > .5)
        result[b:d, a:c] = after
        counts.append({'id': row['id'], 'strokes': len(strokes),
                       'added_pixels': int((after & ~before).sum()),
                       'removed_pixels': int((before & ~after).sum())})
    raw, result = masks(data, source, result)
    return raw, result, counts


def cards(original, data, source, cleanup):
    """Small bounded PNG pairs for the node panel; never paths or HTML."""
    result = []
    for row, decision in zip(data['regions'], data['page_edit_plan']['regions']):
        a, b, c, d = decision['bbox_pixels']
        image = original.crop((a, b, c, d)); image.thumbnail((320, 192))
        def thumb(mask):
            return np.asarray(Image.fromarray((mask[b:d, a:c] > .5).astype('uint8')).resize(image.size, Image.Resampling.NEAREST)) > 0
        overlay = np.zeros((image.height, image.width, 4), np.uint8)
        overlay[thumb(cleanup)] = (255, 96, 32, 115)
        overlay = Image.fromarray(overlay)
        ink = np.zeros((image.height, image.width, 4), np.uint8)
        ink[thumb(source)] = (25, 210, 255, 155)
        def uri(picture):
            stream = io.BytesIO(); picture.save(stream, format='PNG')
            return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')
        result.append({'id': row['id'], 'source': row['source'], 'target': row['target'],
                       **decision, 'image': uri(image), 'overlay': uri(overlay), 'source_overlay':uri(Image.fromarray(ink)),
                       'preview_size': list(image.size)})
    return result
