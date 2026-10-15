"""Bounded cleanup plans; native ComfyUI nodes crop, resize and mask each tile.

Design follows Koharu's 512px owned cores with 128px context, not a whole-page
Qwen call. No model loading or HTTP bridge lives here. See THIRD_PARTY_NOTICES.
"""
import json
import math

import numpy as np
from scipy import ndimage

from .lettering.nodes import image, mask, tensor


def _bounds(binary):
    ys, xs = np.nonzero(binary)
    return [int(xs.min()), int(ys.min()), int(xs.max())+1, int(ys.max())+1] if len(xs) else None


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _area(box):
    return (box[2]-box[0])*(box[3]-box[1])


def _ring_color(original, selected):
    ring = ndimage.binary_dilation(selected, iterations=6) & ~ndimage.binary_dilation(selected, iterations=2)
    samples = original[ring]
    if len(samples) < 16:
        return None
    color = np.median(samples, axis=0)
    spread = np.quantile(np.max(np.abs(samples-color), axis=1), .98)
    return color if spread <= .018 else None


def make_plan(original, source_mask, cleanup_mask, tile_size=512, context=128, max_tiles=64, uniform_fill=True):
    if type(tile_size) is not int or not 64 <= tile_size <= 512:
        raise ValueError('Cleanup core size must be 64..512 pixels')
    if type(context) is not int or not 16 <= context <= 256:
        raise ValueError('Cleanup context must be 16..256 pixels')
    if type(max_tiles) is not int or not 1 <= max_tiles <= 256 or type(uniform_fill) is not bool:
        raise ValueError('Invalid cleanup planning options')
    height, width = original.shape[:2]
    if width*height > 16*1024*1024 or source_mask.shape != (height, width) or cleanup_mask.shape != (height, width):
        raise ValueError('Cleanup page/mask dimensions differ or exceed 16 Mi pixels')
    if not np.isfinite(original).all() or not np.isfinite(source_mask).all() or not np.isfinite(cleanup_mask).all():
        raise ValueError('Cleanup input contains nonfinite pixels')
    pending = cleanup_mask > .5
    raw = source_mask > .5
    if np.any(raw & ~pending):
        raise ValueError('Cleanup mask must cover every source-mask pixel')
    base = original.copy()
    labels, count = ndimage.label(pending, structure=np.ones((3, 3), bool))
    if count > 4096:
        raise ValueError('Cleanup mask has too many disconnected components; refine the mask or split the page')
    objects = ndimage.find_objects(labels)
    components = []
    filled = 0
    for label, slices in enumerate(objects, 1):
        if slices is None:
            continue
        ys, xs = slices
        box = [xs.start, ys.start, xs.stop, ys.stop]
        # Evaluate background only in a bounded neighborhood of this component.
        left, top = max(0, box[0]-8), max(0, box[1]-8)
        right, bottom = min(width, box[2]+8), min(height, box[3]+8)
        selected = labels[top:bottom, left:right] == label
        color = _ring_color(original[top:bottom, left:right], selected) if uniform_fill else None
        if color is not None:
            reference = raw[top:bottom, left:right] & selected
            contrast = np.max(np.abs(original[top:bottom, left:right]-color), axis=2)
            # Require actual contrasting source ink, not an empty/background mask.
            if np.count_nonzero(reference & (contrast > .08)) >= 8:
                base[top:bottom, left:right][selected] = color
                pending[top:bottom, left:right][selected] = False
                filled += 1
                continue
        components.append((label, box))

    grouped, split = [], []
    for label, box in components:
        if box[2]-box[0] <= tile_size and box[3]-box[1] <= tile_size:
            choices = []
            for index, group in enumerate(grouped):
                bounds = _union(group['core'], box)
                if bounds[2]-bounds[0] <= tile_size and bounds[3]-bounds[1] <= tile_size:
                    choices.append((_area(bounds)-_area(group['core']), index, bounds))
            if choices:
                _, index, bounds = min(choices)
                grouped[index]['labels'].append(label)
                grouped[index]['core'] = bounds
            else:
                grouped.append({'labels': [label], 'core': box})
        else:
            for top in range(box[1], box[3], tile_size):
                for left in range(box[0], box[2], tile_size):
                    core = [left, top, min(left+tile_size, box[2]), min(top+tile_size, box[3])]
                    if np.any(labels[core[1]:core[3], core[0]:core[2]] == label):
                        split.append({'labels': [label], 'core': core})
    groups = sorted(grouped+split, key=lambda row: (row['core'][1], row['core'][0]))
    if len(groups) > max_tiles:
        raise ValueError(f'Cleanup needs {len(groups)} tiles, exceeding max_tiles={max_tiles}; split the page')
    tiles = []
    coverage = np.zeros((height, width), np.uint8)
    for group in groups:
        left, top, right, bottom = group['core']
        owned = np.isin(labels[top:bottom, left:right], group['labels']) & pending[top:bottom, left:right]
        bounds = _bounds(owned)
        if bounds is None:
            continue
        crop = [max(0, left+bounds[0]-context), max(0, top+bounds[1]-context),
                min(width, left+bounds[2]+context), min(height, top+bounds[3]+context)]
        x0, y0, x1, y1 = crop
        local = np.zeros((y1-y0, x1-x0), bool)
        bx0, by0, bx1, by1 = bounds
        local[top+by0-y0:top+by1-y0, left+bx0-x0:left+bx1-x0] = owned[by0:by1, bx0:bx1]
        coverage[top:bottom, left:right] += owned
        tiles.append({'crop': crop, 'mask': local})
    if not np.array_equal(coverage, pending.astype(np.uint8)):
        raise ValueError('Cleanup tile ownership does not cover the pending mask exactly once')
    report = {'schema': 1, 'method': 'bounded_mask_tiles', 'page_size': [width, height],
              'tile_core': tile_size, 'context': context, 'tile_count': len(tiles),
              'source_components': count, 'uniform_filled_components': filled,
              'source_mask_pixels': int(raw.sum()), 'cleanup_mask_pixels': int((cleanup_mask > .5).sum()),
              'qwen_mask_pixels': int(pending.sum()), 'tile_boxes': [t['crop'] for t in tiles],
              'coverage': 'each pending mask pixel owned exactly once',
              'limitation': 'undetected text outside the source mask is not automatically certified or erased'}
    return {'version': 1, 'original': original.copy(), 'base': base, 'source_mask': raw,
            'cleanup_mask': cleanup_mask > .5, 'tiles': tiles, 'report': report}


def assemble(plan, generated, strict_cleanup=True):
    if not isinstance(plan, dict) or plan.get('version') != 1:
        raise ValueError('Expected an inpaint tile plan')
    if len(generated) != len(plan['tiles']):
        raise ValueError('Generated tile count differs from plan; no partial page was accepted')
    output = plan['base'].copy()
    checks = []
    for index, (tile, candidate) in enumerate(zip(plan['tiles'], generated)):
        x0, y0, x1, y1 = tile['crop']
        if candidate.shape != (y1-y0, x1-x0, 3):
            raise ValueError('Restore each Qwen tile with native ImageScale before assembly')
        if not np.isfinite(candidate).all():
            raise ValueError('Generated tile contains nonfinite pixels')
        owned = tile['mask']
        reference = plan['original'][y0:y1, x0:x1]
        gray = reference @ np.array([.299, .587, .114], np.float32)
        detail = np.abs(gray-ndimage.median_filter(gray, size=15))
        ink = owned & plan['source_mask'][y0:y1, x0:x1] & (detail > .07)
        changed = np.max(np.abs(candidate-reference), axis=2) >= .045
        fraction = float(changed[ink].mean()) if ink.sum() >= 8 else None
        unchanged = fraction is not None and fraction < .10
        checks.append({'tile': index+1, 'source_ink_samples': int(ink.sum()),
                       'changed_ink_fraction': fraction, 'unchanged_source_warning': unchanged})
        if strict_cleanup and unchanged:
            raise ValueError(f'Cleanup tile {index+1} retained nearly all source ink; lettering was stopped. '
                             'Inspect the tile or change the native sampler seed. This is a pixel check, not OCR certification.')
        output[y0:y1, x0:x1][owned] = candidate[owned]
    if not np.array_equal(output[~plan['cleanup_mask']], plan['original'][~plan['cleanup_mask']]):
        raise ValueError('Cleanup changed pixels outside the permitted mask')
    report = {**plan['report'], 'tile_checks': checks,
              'outside_mask_unchanged': True,
              'quality_check': 'unchanged source-ink heuristic; not a guarantee of text-free output'}
    return output, json.dumps(report, ensure_ascii=False, indent=2)


class MangaInpaintPlan:
    DESCRIPTION = '512px 코어+128px 문맥으로 원문 마스크를 분할합니다. 좌표는 기본 ImageCrop/ImageScale에 공유하고 Qwen은 타일만 처리합니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'original': ('IMAGE',), 'source_mask': ('MASK',), 'cleanup_mask': ('MASK',),
            'tile_size': ('INT', {'default': 512, 'min': 64, 'max': 512}),
            'context': ('INT', {'default': 128, 'min': 16, 'max': 256}),
            'max_tiles': ('INT', {'default': 64, 'min': 1, 'max': 256}),
            'uniform_fill': ('BOOLEAN', {'default': True})}}
    RETURN_TYPES = ('IMAGE', 'INT', 'INT', 'INT', 'INT', 'MASK', 'MANGA_INPAINT_PLAN', 'STRING')
    RETURN_NAMES = ('base_page', 'x', 'y', 'width', 'height', 'owned_tile_masks', 'plan', 'plan_report')
    OUTPUT_IS_LIST = (False, True, True, True, True, True, False, False)
    FUNCTION = 'prepare'
    CATEGORY = 'Manga Translator/Cleanup'
    def prepare(self, original, source_mask, cleanup_mask, **options):
        plan = make_plan(image(original), mask(source_mask), mask(cleanup_mask), **options)
        boxes = plan['report']['tile_boxes']
        return (tensor(plan['base']), [b[0] for b in boxes], [b[1] for b in boxes],
                [b[2]-b[0] for b in boxes], [b[3]-b[1] for b in boxes],
                [tensor(t['mask']) for t in plan['tiles']], plan,
                json.dumps(plan['report'], ensure_ascii=False, indent=2))


class MangaInpaintAssemble:
    DESCRIPTION = '기본 노드가 복원·마스크 합성한 타일을 한 페이지로 모읍니다. 균일 배경만 있으면 Qwen 경로를 생략하고, 제거되지 않은 원문은 식자 전에 중단합니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'plan': ('MANGA_INPAINT_PLAN',),
                             'strict_cleanup': ('BOOLEAN', {'default': True})},
                'optional': {'generated': ('IMAGE', {'lazy': True})}}
    INPUT_IS_LIST = True
    RETURN_TYPES = ('IMAGE', 'STRING')
    RETURN_NAMES = ('cleaned_page', 'cleanup_report')
    FUNCTION = 'finish'
    CATEGORY = 'Manga Translator/Cleanup'
    def check_lazy_status(self, plan, strict_cleanup, generated=None):
        # ComfyUI represents an unresolved lazy link as (None,), not only None.
        missing = generated is None or not generated or generated[0] is None
        return ['generated'] if plan[0]['tiles'] and missing else []
    def finish(self, plan, strict_cleanup, generated=None):
        if len(plan) != 1 or len(strict_cleanup) != 1:
            raise ValueError('Assemble exactly one page at a time')
        missing = generated is None or not generated or generated[0] is None
        result, report = assemble(plan[0], [] if missing else [image(t) for t in generated], strict_cleanup[0])
        return tensor(result), report


NODE_CLASS_MAPPINGS = {'MangaInpaintPlan': MangaInpaintPlan, 'MangaInpaintAssemble': MangaInpaintAssemble}
NODE_DISPLAY_NAME_MAPPINGS = {'MangaInpaintPlan': '원문 제거 · 타일 계획',
                            'MangaInpaintAssemble': '원문 제거 · 타일 복원·검사'}
