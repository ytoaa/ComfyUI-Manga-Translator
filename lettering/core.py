"""CPU lettering primitives. No model, network, ComfyUI or torch import here.

Style analysis is a measured approximation, not learned font reconstruction.
All text is shaped from the supplied Unicode string and an actual font.
"""
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import math
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from ..text_contract import ocr_problem

from ..limits import (MAX_SOURCE_PIXELS, MAX_REGION_PIXELS, MAX_RASTER_PIXELS,
                      MAX_TYPOGRAPHY_PIXELS, MAX_LETTERING_REGIONS, MAX_DOCUMENT_BYTES)

# Backward-compatible name used by older tests/extensions.  Page acceptance is
# deliberately distinct from region/raster budgets below.
MAX_PIXELS = MAX_SOURCE_PIXELS
MAX_TEXT = 2048
FONT_DIR = Path(__file__).with_name('fonts')


def rgb(value):
    value = np.asarray(value, dtype=np.float32)
    if (value.ndim != 3 or value.shape[2] != 3 or min(value.shape[:2]) < 1
            or value.shape[0] * value.shape[1] > MAX_SOURCE_PIXELS
            or not np.isfinite(value).all() or value.min() < 0 or value.max() > 1):
        raise ValueError('Expected a finite RGB image in [0, 1], at most 64 Mi pixels')
    return value


def mask_array(mask, shape):
    mask = np.asarray(mask, dtype=np.float32)
    if mask.shape != shape or not np.isfinite(mask).all() or mask.min() < 0 or mask.max() > 1:
        raise ValueError('Mask dimensions and range must match the source image; no implicit resize')
    return mask


def finite(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}')
    return value


def integer(value, low, high, name):
    if type(value) is not int:
        raise ValueError(f'{name} must be an integer')
    return finite(value, low, high, name)


def bbox(value, shape):
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError('bbox must be [x, y, width, height] in original page pixels')
    x = integer(value[0], 0, max(0, shape[1]-1), 'bbox')
    y = integer(value[1], 0, max(0, shape[0]-1), 'bbox')
    w = integer(value[2], 1, min(16384, shape[1]), 'bbox')
    h = integer(value[3], 1, min(16384, shape[0]), 'bbox')
    if x + w > shape[1] or y + h > shape[0] or w * h > MAX_REGION_PIXELS:
        raise ValueError('Region is outside the page or exceeds 16 Mi pixels')
    return x, y, w, h


def crop_region(original, cleaned, source_mask, bounds):
    original, cleaned = rgb(original), rgb(cleaned)
    if original.shape != cleaned.shape:
        raise ValueError('Original and cleaned page dimensions must match')
    source_mask = mask_array(source_mask, original.shape[:2])
    x, y, w, h = bbox(bounds, original.shape)
    return (original[y:y+h, x:x+w].copy(), cleaned[y:y+h, x:x+w].copy(),
            source_mask[y:y+h, x:x+w].copy(),
            {'version': 1, 'bbox_xywh': [x, y, w, h],
             'page_size': [original.shape[1], original.shape[0]]})


def _color(values):
    return np.median(values, axis=0).astype(np.float32)


def _texture(reference, fill_mask):
    """Extend only the measured fill pigment, never copy source glyph outlines."""
    interior = ndimage.binary_erosion(fill_mask, iterations=1)
    if interior.sum() < 12:
        interior = fill_mask
    if interior.sum() < 4:
        return np.zeros((32, 32), np.float32)
    luminance = reference @ np.array([.2126, .7152, .0722], np.float32)
    # A glyph's blank exterior is excluded before computing the residual.
    nearest = ndimage.distance_transform_edt(~interior, return_distances=False, return_indices=True)
    pigment = luminance[tuple(nearest)]
    residual = pigment - ndimage.gaussian_filter(pigment, 2.0)
    scale = min(1., 64 / max(residual.shape))
    target = (max(8, round(residual.shape[1] * scale)), max(8, round(residual.shape[0] * scale)))
    tile = np.array(Image.fromarray(residual).resize(target, Image.Resampling.BILINEAR), dtype=np.float32)
    tile -= float(np.median(tile))
    return np.clip(tile, -.2, .2)


def analyze_style(reference, cleaned, source_mask, polarity='auto', difference_threshold=.07):
    reference, cleaned = rgb(reference), rgb(cleaned)
    if reference.shape != cleaned.shape or reference.shape[0] * reference.shape[1] > MAX_REGION_PIXELS:
        raise ValueError('Style reference must be aligned and at most 16 Mi pixels')
    source_mask = mask_array(source_mask, reference.shape[:2])
    finite(difference_threshold, .005, .5, 'difference_threshold')
    if polarity not in ('auto', 'dark', 'light'):
        raise ValueError('Invalid polarity')
    support = source_mask > .1
    changed = support & (np.max(np.abs(reference - cleaned), axis=2) >= difference_threshold)
    if changed.sum() < 8:
        raise ValueError('Too few text pixels. Check the region, source mask, cleaned page and contrast threshold')
    lum = reference @ np.array([.2126, .7152, .0722], np.float32)
    delta = (reference - cleaned) @ np.array([.2126, .7152, .0722], np.float32)
    if polarity == 'auto':
        dark = float(np.maximum(-delta[changed], 0).sum())
        light = float(np.maximum(delta[changed], 0).sum())
        polarity = 'dark' if dark >= light else 'light'
    # Only the darkest/lightest pigment samples determine foreground color.
    q = np.quantile(lum[changed], .35 if polarity == 'dark' else .65)
    selected = changed & ((lum <= q) if polarity == 'dark' else (lum >= q))
    foreground = _color(reference[selected])
    color_distance = np.max(np.abs(reference - foreground), axis=2)
    fill_mask = changed & (color_distance < .18)
    if fill_mask.sum() < 4:
        fill_mask = selected
    to_fill = ndimage.distance_transform_edt(~fill_mask)
    outline_mask = changed & ~fill_mask & (to_fill <= 12) & (color_distance >= .25)
    has_outline = outline_mask.sum() >= max(8, .06 * fill_mask.sum())
    outline = _color(reference[outline_mask]) if has_outline else np.array([1., 1., 1.], np.float32)
    outline_width = float(np.clip(np.quantile(to_fill[outline_mask], .65), 0, 10)) if has_outline else 0.
    inside = ndimage.distance_transform_edt(fill_mask)
    stroke = float(np.quantile(inside[fill_mask], .7) * 2)
    texture = _texture(reference, fill_mask)
    style = {'version': 1, 'size': [reference.shape[1], reference.shape[0]],
             'foreground': foreground.tolist(), 'outline_color': outline.tolist(),
             'outline_width': outline_width, 'stroke_width': stroke,
             'polarity': polarity, 'texture': texture,
             'texture_strength': 1., 'weight_px': 0., 'shadow_x': 0., 'shadow_y': 0.,
             'shadow_blur': 0., 'shadow_color': [0., 0., 0.],
             'sample_pixels': int(changed.sum()),
             'measurement': 'heuristic pigment/outline/texture; font and shadow are user-selected'}
    report = {k: v for k, v in style.items() if k != 'texture'}
    report['texture_std'] = float(texture.std())
    return style, json.dumps(report, ensure_ascii=False, indent=2)


def hex_color(value):
    if not isinstance(value, str):
        raise ValueError('Color must be #RRGGBB')
    text = value.strip().lstrip('#')
    if len(text) != 6 or any(c not in '0123456789abcdefABCDEF' for c in text):
        raise ValueError('Color must be #RRGGBB')
    return [int(text[i:i+2], 16) / 255 for i in (0, 2, 4)]


def adjust_style(style, foreground='auto', outline_color='auto', outline_width=-1.,
                 weight_px=0., texture_strength=1., shadow_x=0., shadow_y=0.,
                 shadow_blur=0., shadow_color='#000000'):
    validate_style(style)
    values = dict(style)
    for key, value in (('foreground', foreground), ('outline_color', outline_color)):
        if value.strip().lower() != 'auto':
            values[key] = hex_color(value)
    finite(outline_width, -1, 32, 'outline_width')
    if outline_width >= 0:
        values['outline_width'] = outline_width
    for key, val, lo, hi in [('weight_px', weight_px, -8, 16), ('texture_strength', texture_strength, 0, 2),
                             ('shadow_x', shadow_x, -64, 64), ('shadow_y', shadow_y, -64, 64),
                             ('shadow_blur', shadow_blur, 0, 32)]:
        values[key] = finite(val, lo, hi, key)
    values['shadow_color'] = hex_color(shadow_color)
    return values


def validate_style(style):
    if not isinstance(style, dict) or style.get('version') != 1:
        raise ValueError('Expected a style from MangaLetterAnalyze')
    for key in ('foreground', 'outline_color', 'shadow_color'):
        value = np.asarray(style.get(key), np.float32)
        if value.shape != (3,) or not np.isfinite(value).all() or value.min() < 0 or value.max() > 1:
            raise ValueError('Invalid style color')
    size = style.get('size', [])
    if len(size) != 2:
        raise ValueError('Invalid style canvas')
    for v in size:
        integer(v, 1, 16384, 'style canvas')
    if size[0] * size[1] > MAX_REGION_PIXELS:
        raise ValueError('Style canvas exceeds 16 Mi pixels')
    for key, low, high in [('outline_width', 0, 32), ('weight_px', -8, 16), ('texture_strength', 0, 2),
                            ('shadow_x', -64, 64), ('shadow_y', -64, 64), ('shadow_blur', 0, 32)]:
        finite(style.get(key), low, high, key)
    texture = np.asarray(style.get('texture'), np.float32)
    if texture.ndim != 2 or max(texture.shape) > 256 or min(texture.shape) < 1 or not np.isfinite(texture).all():
        raise ValueError('Invalid style texture')


def fonts():
    result = {p.name: str(p) for p in sorted(FONT_DIR.glob('*.ttf'))}
    try:
        import folder_paths
        roots = [Path(folder_paths.models_dir) / 'fonts']
        for root in roots:
            if root.exists():
                for p in sorted(root.rglob('*')):
                    if p.suffix.lower() in ('.ttf', '.otf', '.ttc'):
                        result['models/fonts/' + p.relative_to(root).as_posix()] = str(p)
    except ImportError:
        pass
    return result


@lru_cache(maxsize=32)
def _font_coverage(path, mtime_ns, size):
    from fontTools.ttLib import TTFont
    font = TTFont(path, fontNumber=0, lazy=True)
    try:
        return frozenset(code for t in font['cmap'].tables if t.isUnicode() for code in t.cmap)
    finally:
        font.close()


class FontCoverageError(ValueError):
    """The requested text cannot be represented; never discard its characters."""
    def __init__(self,selection,missing):
        super().__init__('Font lacks requested characters: '+''.join(missing[:24])+'; choose a font covering the translation')
        self.diagnostic={'code':'font_missing_glyphs','requested_font':selection,
                         'missing_characters':missing[:24],
                         'missing_codepoints':[f'U+{ord(c):04X}' for c in missing[:24]],
                         'missing_count':len(missing),'text_preserved':True}


def font_path(selection, text):
    candidates = fonts()
    if selection not in candidates:
        raise ValueError(f'Font not found: {selection}. Put fonts in ComfyUI/models/fonts and restart')
    path = candidates[selection]
    stat = Path(path).stat()
    coverage = _font_coverage(path, stat.st_mtime_ns, stat.st_size)
    missing = sorted({c for c in text if not c.isspace() and ord(c) not in coverage})
    if missing:
        raise FontCoverageError(selection,missing)
    return path


def resolve_font(selection, text):
    """Choose one real font covering the entire region, without rewriting text."""
    available=fonts()
    if selection not in available:
        font_path(selection,text)  # Preserve the explicit missing-font error.
    try:
        font_path(selection,text)
        return selection, None
    except FontCoverageError as primary_error:
        preferred=['MangaSansKR-Fallback.ttf']
        alternatives=preferred+[name for name in available if name not in preferred and name!=selection]
        for name in alternatives:
            if name not in available or name==selection: continue
            try: font_path(name,text)
            except FontCoverageError: continue
            return name, {'requested_font':selection,'selected_font':name,
                          'reason':'requested_font_missing_glyphs','text_preserved':True}
        raise primary_error


def clean_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError('Translation must contain 1–2048 Unicode characters')
    if issue := ocr_problem(text):
        raise ValueError(issue + ': resolve the unreadable OCR span before lettering')
    text = unicodedata.normalize('NFC', text.replace('\r\n', '\n').replace('\r', '\n'))
    if any(unicodedata.category(c).startswith('C') and c != '\n' for c in text):
        raise ValueError('Translation contains unsupported control characters')
    return text


def _clusters(text):
    result = []
    for c in text:
        if unicodedata.combining(c) and result:
            result[-1] += c
        else:
            result.append(c)
    return result


def _advance(font, clusters, tracking):
    return sum(float(font.getlength(c)) for c in clusters) + max(0, len(clusters)-1) * tracking


def _word_units(paragraph):
    units = []
    closing = set('!?.,;:，。！？、…)]}」』】》〉')
    for char in _clusters(paragraph):
        latin = char.isascii() and (char.isalnum() or char in "'’")
        previous_latin = bool(units and all(c.isascii() and (c.isalnum() or c in "'’") for c in units[-1]))
        if units and ((latin and previous_latin) or (char in closing and not units[-1][-1].isspace())):
            units[-1].append(char)
        else:
            units.append([char])
    return units


def _layout(text, font, width, height, direction, spacing, tracking, effect_padding=0, vertical_policy='simple', wrap_policy='greedy'):
    ascent, descent = font.getmetrics()
    cell = ascent + descent
    # Reserve each line's outline/weight/shadow so auto-sized rows do not collide.
    line_step = max(1., cell * spacing, cell + 2*effect_padding + cell*.12)
    lines = []
    if direction == 'horizontal':
        for paragraph in text.split('\n'):
            if wrap_policy == 'balanced':
                from .linebreak import balanced
                wrapped = balanced(paragraph, font, width, tracking)
                if wrapped is not None:
                    lines.extend(wrapped)
                    continue
            line = []
            for unit in _word_units(paragraph):
                if line and _advance(font, line+unit, tracking) > width:
                    lines.append(line)
                    line = []
                if not line and all(c.isspace() for c in unit):
                    continue
                line.extend(unit)
            lines.append(line)
        widths = [_advance(font, line, tracking) for line in lines]
        extent = (max(widths, default=0), cell + (len(lines)-1)*line_step)
        return lines, extent, line_step, cell, widths
    if vertical_policy == 'typographic':
        from .vertical import layout
        return layout(text, font, width, height, spacing, tracking, effect_padding)
    columns = []
    step = max(1., cell + tracking)
    for paragraph in text.split('\n'):
        col = []
        for c in _clusters(paragraph):
            if col and (len(col)+1)*step - tracking > height:
                columns.append(col)
                col = []
            col.append(c)
        columns.append(col)
    extent = (cell+(len(columns)-1)*line_step, max((len(c)*step-tracking for c in columns), default=0))
    return columns, extent, line_step, cell, []


def _offset_alpha(alpha, dx, dy):
    return ndimage.shift(alpha, (dy, dx), order=1, mode='constant', cval=0, prefilter=False)


def render_text(text, style, font_name='NanumGothic-Bold.ttf', direction='horizontal',
                alignment='center', min_font=10, max_font=256, padding=8,
                line_spacing=1., tracking=0., rotation=0., shear=0., supersample=2, max_lines=0, vertical_policy='simple', wrap_policy='greedy'):
    text = clean_text(text)
    if wrap_policy not in ('greedy', 'balanced'):
        raise ValueError('Invalid wrap_policy')
    if vertical_policy not in ('simple', 'typographic'):
        raise ValueError('Invalid vertical_policy')
    validate_style(style)
    path = font_path(font_name, text)
    if direction not in ('horizontal', 'vertical_rtl', 'vertical_ltr') or alignment not in ('left', 'center', 'right'):
        raise ValueError('Invalid text direction or alignment')
    integer(min_font, 4, 512, 'min_font'); integer(max_font, min_font, 512, 'max_font')
    integer(padding, 0, 256, 'padding'); integer(supersample, 1, 4, 'supersample')
    integer(max_lines, 0, 64, 'max_lines')
    finite(line_spacing, .5, 3, 'line_spacing'); finite(tracking, -4, 32, 'tracking')
    finite(rotation, -180, 180, 'rotation'); finite(shear, -.6, .6, 'shear')
    w, h = style['size']
    requested_supersample = supersample
    while supersample > 1 and w*h*supersample**2 > MAX_RASTER_PIXELS:
        supersample -= 1
    if w*h*supersample**2 > MAX_RASTER_PIXELS:
        raise ValueError('Lettering region exceeds the 32 Mi-pixel raster budget even at supersample=1')
    # LANCZOS spreads coverage up to three output pixels beyond the high-res
    # glyph. Keep a clear pixel after that footprint. A fixed two-pixel left
    # origin otherwise touches the boundary at every font size after resize.
    raster_guard=4 if supersample>1 else 0
    effective_padding=max(padding,raster_guard)
    border = effective_padding + math.ceil(style['outline_width'] + max(0, style['weight_px']) +
                                  max(abs(style['shadow_x']), abs(style['shadow_y'])) + 3*style['shadow_blur'])
    available_w, available_h = w - 2*border, h - 2*border
    if min(available_w, available_h) < 4:
        raise ValueError('Padding, outline and shadow leave no space for text')
    chosen = None
    # A bounded exhaustive descending search handles line-wrap discontinuities.
    for size in range(max_font, min_font-1, -1):
        font = ImageFont.truetype(path, size * supersample)
        effect = math.ceil(style['outline_width'] + max(0, style['weight_px']) +
                           max(abs(style['shadow_x']), abs(style['shadow_y'])) + 3*style['shadow_blur'])
        layout = _layout(text, font, available_w*supersample, available_h*supersample,
                         direction, line_spacing, tracking*supersample, effect*supersample, vertical_policy, wrap_policy)
        ew, eh = layout[1]
        angle = math.radians(rotation)
        sheared_w = ew + abs(shear)*eh
        out_w = abs(math.cos(angle))*sheared_w + abs(math.sin(angle))*eh
        out_h = abs(math.sin(angle))*sheared_w + abs(math.cos(angle))*eh
        if out_w <= available_w*supersample and out_h <= available_h*supersample and (not max_lines or len(layout[0]) <= max_lines):
            chosen = size, font, layout
            break
    if chosen is None:
        raise ValueError('Translation does not fit at min_font; enlarge region or edit line breaks/minimum size')
    size, font, (lines, extent, line_step, cell, widths) = chosen
    s = supersample
    canvas = Image.new('L', (w*s, h*s))
    draw = ImageDraw.Draw(canvas)
    origin_y = (h*s-extent[1])/2
    origin_x = (w*s-extent[0])/2
    if direction == 'horizontal':
        for row, line in enumerate(lines):
            lw = widths[row]
            x = border*s if alignment == 'left' else ((w*s-lw)/2 if alignment == 'center' else w*s-border*s-lw)
            for char in line:
                draw.text((x, origin_y+row*line_step), char, font=font, fill=255, anchor='la')
                x += float(font.getlength(char)) + tracking*s
    elif vertical_policy == 'typographic':
        from .vertical import draw as draw_vertical
        stat = Path(path).stat()
        draw_vertical(canvas, lines, font, origin_x, origin_y, line_step, cell,
                      tracking*s, direction == 'vertical_rtl',
                      _font_coverage(path,stat.st_mtime_ns,stat.st_size))
    else:
        for column, chars in enumerate(lines):
            col = len(lines)-1-column if direction == 'vertical_rtl' else column
            cx = origin_x + col*line_step
            for row, char in enumerate(chars):
                cw = float(font.getlength(char))
                draw.text((cx+(cell-cw)/2, origin_y+row*(cell+tracking*s)), char,
                          font=font, fill=255, anchor='lt')
    if shear:
        canvas = canvas.transform(canvas.size, Image.Transform.AFFINE,
                                  (1, -shear, shear*h*s/2, 0, 1, 0), Image.Resampling.BICUBIC)
    if rotation:
        canvas = canvas.rotate(rotation, Image.Resampling.BICUBIC, expand=False)
    glyph = np.asarray(canvas, np.float32)/255
    weight = round(abs(style['weight_px'])*s)
    if weight:
        operation = ndimage.maximum_filter if style['weight_px'] > 0 else ndimage.minimum_filter
        glyph = operation(glyph, size=2*weight+1, mode='constant')
    if glyph.max() < .1:
        raise ValueError('Weight erosion removed all glyphs; increase weight_px')
    stroke = round(style['outline_width']*s)
    outlined = ndimage.maximum_filter(glyph, size=2*stroke+1, mode='constant') if stroke else glyph
    shadow = np.zeros_like(glyph)
    if style['shadow_x'] or style['shadow_y'] or style['shadow_blur']:
        shadow = _offset_alpha(outlined, style['shadow_x']*s, style['shadow_y']*s)
        if style['shadow_blur']:
            shadow = ndimage.gaussian_filter(shadow, style['shadow_blur']*s, mode='constant')
    premult = np.zeros((*glyph.shape, 3), np.float32)
    alpha = np.zeros_like(glyph)
    texture = np.asarray(style['texture'], np.float32)
    repeat = np.tile(texture, (math.ceil(h/texture.shape[0]), math.ceil(w/texture.shape[1])))[:h, :w]
    tex = np.asarray(Image.fromarray(repeat).resize((w*s, h*s), Image.Resampling.BILINEAR))
    foreground = np.clip(np.array(style['foreground'])[None, None, :] + tex[..., None]*style['texture_strength'], 0, 1)
    # Disabled outlines must contribute no antialiased coverage.
    outline_alpha = outlined if stroke else np.zeros_like(glyph)
    for a, color in ((shadow, style['shadow_color']), (outline_alpha, style['outline_color']), (glyph, foreground)):
        premult = np.asarray(color, np.float32)*a[..., None] + premult*(1-a[..., None])
        alpha = a + alpha*(1-a)
    # Downsample premultiplied RGB to avoid black/white fringes around antialiasing.
    if s > 1:
        alpha = np.asarray(Image.fromarray(alpha).resize((w, h), Image.Resampling.LANCZOS))
        premult = np.stack([np.asarray(Image.fromarray(premult[..., c]).resize((w, h), Image.Resampling.LANCZOS)) for c in range(3)], axis=-1)
    # Unpremultiply before clipping Lanczos overshoot to preserve pigment.
    layer = np.divide(premult, alpha[..., None], out=np.zeros_like(premult), where=alpha[..., None] > 1e-6)
    alpha = np.clip(alpha, 0, 1)
    layer = np.clip(layer, 0, 1).astype(np.float32)
    report = {'text': text, 'font': font_name, 'font_size': size, 'direction': direction,
              'requested_padding':padding,'effective_padding':effective_padding,'raster_guard_px':raster_guard,
              'requested_supersample':requested_supersample,'supersample':s,
              'wrap_policy': wrap_policy, 'vertical_policy': vertical_policy, 'line_count': len(lines), 'line_step_px': line_step/s, 'rotation': rotation, 'shear': shear,
              'glyph_geometry': 'font-rendered; no generative rewriting',
              'font_identification': 'user selection, not inferred original font'}
    return layer, alpha.astype(np.float32), json.dumps(report, ensure_ascii=False, indent=2)


def composite(cleaned, layer, alpha, placement, opacity=1.):
    cleaned, layer = rgb(cleaned), rgb(layer)
    alpha = mask_array(alpha, layer.shape[:2])
    finite(opacity, 0, 1, 'opacity')
    if not isinstance(placement, dict) or placement.get('version') != 1:
        raise ValueError('Expected placement from MangaLetterRegion')
    if placement.get('page_size') != [cleaned.shape[1], cleaned.shape[0]]:
        raise ValueError('Placement belongs to a different page size')
    x, y, w, h = bbox(placement.get('bbox_xywh'), cleaned.shape)
    if layer.shape[:2] != (h, w):
        raise ValueError('Lettering layer dimensions differ from placement; no implicit resize')
    result = cleaned.copy()
    a = alpha*opacity
    local = result[y:y+h, x:x+w]
    composed = layer*a[..., None] + local*(1-a[..., None])
    active = a > 0
    local[active] = composed[active]
    page_alpha = np.zeros(cleaned.shape[:2], np.float32)
    page_alpha[y:y+h, x:x+w] = a
    return result, page_alpha


def apply_candidate_texture(layer, alpha, candidate, strength=.35, max_shift=.12, radius=2.):
    """Borrow bounded pigment variation; always keep the exact rendered glyph alpha.

    This does not accept the AI candidate's letter shapes or claim OCR validation.
    """
    layer, candidate = rgb(layer), rgb(candidate)
    if candidate.shape != layer.shape:
        raise ValueError('Candidate and rendered layer must match; crop/resize explicitly first')
    alpha = mask_array(alpha, layer.shape[:2])
    finite(strength, 0, 1, 'strength'); finite(max_shift, 0, .3, 'max_shift'); finite(radius, .5, 16, 'radius')
    # Normalize within actual letter coverage so background edges do not become pigment.
    interior = ndimage.binary_erosion(alpha > .98, iterations=2)
    result = layer.copy()
    if interior.sum() < 8 or strength == 0:
        return result, alpha.copy()
    weights = ndimage.gaussian_filter(interior.astype(np.float32), radius)
    coefficient = np.array([.2126, .7152, .0722], np.float32)
    lum = candidate @ coefficient
    average = np.divide(ndimage.gaussian_filter(lum*interior, radius), weights,
                        out=lum.copy(), where=weights > 1e-5)
    residual = np.clip(lum-average, -max_shift, max_shift)*strength
    valid = interior & (weights > .1)
    result[valid] = np.clip(layer[valid] + residual[valid, None], 0, 1)
    return result, alpha.copy()


def parse_regions(document, shape):
    if not isinstance(document, str) or len(document.encode('utf-8')) > MAX_DOCUMENT_BYTES:
        raise ValueError('Regions JSON exceeds shared transport budget')
    data = json.loads(document)
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('coordinate_format') != 'xywh':
        raise ValueError('Expected schema=1 and coordinate_format="xywh"')
    if data.get('page_size') != [shape[1], shape[0]]:
        raise ValueError('Regions page_size does not match input; restore original coordinates first')
    regions = data.get('regions')
    if not isinstance(regions, list) or not 0 <= len(regions) <= MAX_LETTERING_REGIONS:
        raise ValueError('Expected 0–64 translated regions')
    ids = set()
    for item in regions:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in ids:
            raise ValueError('Every region needs a unique nonempty string id')
        ids.add(item['id'])
        bbox(item.get('bbox'), shape)
        clean_text(item.get('text'))
        if set(item)-{'id', 'bbox', 'text', 'source_text', 'font', 'layout', 'style','frame_quad','parent_id','block_id','role','source_edit_bbox'}:
            raise ValueError('Unknown region field')
        if 'source_edit_bbox' in item:
            a,b,w,h=bbox(item['source_edit_bbox'],shape);x,y,c,d=bbox(item['bbox'],shape)
            if (not isinstance(item.get('parent_id'),str) or not item['parent_id'] or
                    not (a<=x and b<=y and x+c<=a+w and y+d<=b+h)):
                raise ValueError('Paragraph restore frame must enclose its child within the parent edit frame')
        if not isinstance(item.get('layout', {}), dict) or not isinstance(item.get('style', {}), dict):
            raise ValueError('layout and style must be objects')
    if sum(r['bbox'][2]*r['bbox'][3] for r in regions) > MAX_TYPOGRAPHY_PIXELS:
        raise ValueError('Total region area exceeds 32 Mi pixels')
    owners=data.get('source_owners',{})
    if not isinstance(owners,dict) or set(owners)-ids:raise ValueError('Invalid source owner IDs')
    from ..mask_nodes import _mask_metadata
    for raw in owners.values():
        (_,_,w,h),_=_mask_metadata(raw,shape[1],shape[0])
        if w*h>MAX_REGION_PIXELS:raise ValueError('Source owner mask exceeds 16 Mi pixels')
    return data


def preserved_punctuation_boxes(data,shape):
    values=data.get('preserved_punctuation',[])
    if not isinstance(values,list) or len(values)>64:
        raise ValueError('Invalid preserved punctuation list')
    output=[];ids=set()
    for item in values:
        if not isinstance(item,dict):raise ValueError('Invalid preserved punctuation')
        count=item.get('count');ident=item.get('id')
        if (type(count) is not int or not 3<=count<=24 or item.get('text')!='・'*count
                or not isinstance(ident,str) or not ident or ident in ids):
            raise ValueError('Invalid preserved punctuation')
        ids.add(ident)
        x,y,w,h=bbox(item.get('bbox'),shape)
        output.append([x,y,x+w,y+h])
    return output


def source_preservation_boxes(data,shape):
    # Previously saved prepared documents are read at this one boundary. New
    # processing uses generic edit decisions rather than punctuation flags.
    if 'source_preservation' not in data:
        return preserved_punctuation_boxes(data,shape)
    values=data['source_preservation']
    if not isinstance(values,list) or len(values)>1024:
        raise ValueError('Invalid source preservation list')
    output=[];ids=set()
    active={row['id'] for row in data['regions']}
    for row in values:
        if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']
                or row['id'] in ids or row['id'] in active or not isinstance(row.get('reason'),str)):
            raise ValueError('Invalid source preservation region')
        ids.add(row['id'])
        box=row.get('bbox')
        if not isinstance(box,list) or len(box)!=4:
            raise ValueError('Invalid source preservation bounds')
        x,y,w,h=box
        integer(x,0,shape[1]-1,'preserved x');integer(y,0,shape[0]-1,'preserved y')
        integer(w,1,shape[1]-x,'preserved width');integer(h,1,shape[0]-y,'preserved height')
        output.append([x,y,x+w,y+h])
    return output


def render_page(original, cleaned, source_mask, document, default_font='NanumGothic-Bold.ttf',
                texture_strength=1.):
    original, cleaned = rgb(original), rgb(cleaned)
    source_mask = mask_array(source_mask, original.shape[:2])
    if original.shape != cleaned.shape:
        raise ValueError('Original and cleaned page must match')
    data = parse_regions(document, original.shape)
    result = cleaned.copy()
    page_alpha = np.zeros(cleaned.shape[:2], np.float32)
    reports = []
    preserved=source_preservation_boxes(data,original.shape)
    for a,b,c,d in preserved:result[b:d,a:c]=original[b:d,a:c]
    # All references come from original/cleaned snapshots, never the cumulative result.
    for item in data['regions']:
        ref, clean, mask, place = crop_region(original, cleaned, source_mask, item['bbox'])
        if item['id'] in data.get('source_owners',{}):
            from ..source_partition import _local
            mask=mask*_local(data['source_owners'][item['id']],item['bbox'],original.shape[1],original.shape[0])
        style, measured = analyze_style(ref, clean, mask)
        style = adjust_style(style, texture_strength=texture_strength, **item.get('style', {})) if 'texture_strength' not in item.get('style', {}) else adjust_style(style, **item['style'])
        layer, alpha, report = render_text(item['text'], style,
                                         font_name=item.get('font', default_font), **item.get('layout', {}))
        result, changed = composite(result, layer, alpha, place)
        page_alpha = changed + page_alpha*(1-changed)
        reports.append({'id': item['id'], 'analysis': json.loads(measured), 'render': json.loads(report)})
    for a,b,c,d in preserved:
        if page_alpha[b:d,a:c].any():raise ValueError('Lettering overlaps preserved source')
    return result, page_alpha, json.dumps({'schema': 1, 'regions': reports,
        'preserved_punctuation':data.get('preserved_punctuation',[]),
        'source_preservation':data.get('source_preservation',[]),
        'style_method': 'measured colors/outline/pigment + selected font; no trained style-transfer model'}, ensure_ascii=False, indent=2)


def reference_prompt(text, source_text=''):
    text = clean_text(text)
    return ('Image 1 is the ORIGINAL comic lettering style reference. Image 2 is the required '
            'translated lettering with correct glyphs and layout. Preserve the exact characters and '
            'layout of Image 2. Borrow only the ink texture, stroke finish, outline and visual mood '
            'from Image 1. Do not add letters, symbols, artwork or a new background. '
            'The required translated text is: ' + json.dumps(text, ensure_ascii=False) +
            ('. Original text for reference only: ' + json.dumps(source_text, ensure_ascii=False) if source_text else ''))
