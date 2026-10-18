"""Bounded cleanup plans; native ComfyUI nodes crop, resize and mask each tile.

Design follows Koharu's 512px owned cores with 128px context, not a whole-page
Qwen call. No model loading or HTTP bridge lives here. See THIRD_PARTY_NOTICES.
"""
import json
import math

import numpy as np
from scipy import ndimage

from .limits import MAX_SOURCE_PIXELS
from . import boundary_review
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


def _recover_uniform_regions(original, raw, pending, document):
    """Recover sparse missed glyph pixels only inside declared text rectangles.

    This is deliberately not a page-wide brightness filter: both the external
    background ring and the region interior must support one flat color, with
    existing detector ink providing substantial corroborating evidence.
    """
    from .nodes import layout, pixel_box
    height,width=raw.shape
    data=layout(document)
    if (data.get('image_width'),data.get('image_height')) != (width,height):
        raise ValueError('Uniform cleanup regions belong to a different page size')
    base=original.copy(); recovered=raw.copy(); remaining=pending.copy(); permitted=pending.copy()
    reports=[]
    for row in data['regions']:
        if row.get('kind','text') != 'text':
            continue
        x0,y0,x1,y1=pixel_box(row['bbox'],width,height,2)
        left,top,right,bottom=max(0,x0-10),max(0,y0-10),min(width,x1+10),min(height,y1+10)
        ring=np.ones((bottom-top,right-left),bool)
        ring[y0-top:y1-top,x0-left:x1-left]=False
        ring &= ~pending[top:bottom,left:right]
        samples=original[top:bottom,left:right][ring]
        report={'id':row['id'],'bbox':[x0,y0,x1,y1],'accepted':False}
        if len(samples)<32:
            report['reason']='too_few_background_samples';reports.append(report);continue
        color=np.median(samples,axis=0)
        if np.quantile(np.max(np.abs(samples-color),axis=1),.98)>.018:
            report['reason']='nonuniform_surroundings';reports.append(report);continue
        local=original[y0:y1,x0:x1]
        delta=np.max(np.abs(local-color),axis=2)
        contrast=delta>.035
        support=raw[y0:y1,x0:x1] & contrast
        if np.mean(delta<=.025)<.65 or support.sum()<8 or support.sum()<contrast.sum()*.15:
            report['reason']='insufficient_uniform_or_detector_support';reports.append(report);continue
        selected=ndimage.binary_dilation(contrast,iterations=1) | pending[y0:y1,x0:x1]
        missing=contrast & ~raw[y0:y1,x0:x1]
        expanded=selected & ~permitted[y0:y1,x0:x1]
        recovered[y0:y1,x0:x1] |= contrast
        permitted[y0:y1,x0:x1] |= selected
        base[y0:y1,x0:x1][selected]=color
        remaining[y0:y1,x0:x1][selected]=False
        report.update(accepted=True,background_color=color.tolist(),
                      recovered_ink_pixels=int(missing.sum()),expanded_cleanup_pixels=int(expanded.sum()),
                      filled_pixels=int(selected.sum()))
        reports.append(report)
    return base,recovered,remaining,permitted,reports


def _empty_plan(original, raw, pending, cleanup_mask, tile_size, context):
    """Cheap no-text/no-cleanup page plan; never run full-page component labeling."""
    height,width=raw.shape
    snapshot=original.copy()
    report={'schema':1,'method':'bounded_mask_tiles','page_size':[width,height],
            'cleanup_skipped':True,'skip_reason':'empty_masks','tile_core':tile_size,'context':context,
            'tile_count':0,'source_components':0,'uniform_filled_components':0,
            'source_mask_pixels':0,'cleanup_mask_pixels':0,'effective_cleanup_mask_pixels':0,
            'uniform_region_recovery':[],'qwen_mask_pixels':0,'tile_boxes':[],
            'coverage':'empty mask; no tile ownership required',
            'limitation':'undetected text outside the source mask is not automatically certified or erased'}
    return {'version':1,'original':snapshot,'base':snapshot,'source_mask':raw,
            'cleanup_mask':pending,'tiles':[],'report':report}


def make_plan(original, source_mask, cleanup_mask, tile_size=512, context=128, max_tiles=64, uniform_fill=True,
              regions_json=None,recover_uniform_ink=False):
    if type(tile_size) is not int or not 64 <= tile_size <= 512:
        raise ValueError('Cleanup core size must be 64..512 pixels')
    if type(context) is not int or not 16 <= context <= 256:
        raise ValueError('Cleanup context must be 16..256 pixels')
    if (type(max_tiles) is not int or not 1 <= max_tiles <= 256 or type(uniform_fill) is not bool
            or type(recover_uniform_ink) is not bool):
        raise ValueError('Invalid cleanup planning options')
    height, width = original.shape[:2]
    if width*height > MAX_SOURCE_PIXELS or source_mask.shape != (height, width) or cleanup_mask.shape != (height, width):
        raise ValueError('Cleanup page/mask dimensions differ or exceed the 64 Mi-pixel source-page ceiling')
    if not np.isfinite(original).all() or not np.isfinite(source_mask).all() or not np.isfinite(cleanup_mask).all():
        raise ValueError('Cleanup input contains nonfinite pixels')
    pending = cleanup_mask > .5
    raw = source_mask > .5
    document = json.loads(regions_json) if regions_json is not None else None
    edit_plan = None
    if document is not None and 'page_edit_plan' in document:
        from . import page_edit
        edit_plan = page_edit.validate(document,width,height)
        raw,pending = page_edit.masks(document,raw,pending)
        document = page_edit.cleanup_document(document,width,height)
    protected = (edit_plan['protected_boxes_pixels'] if edit_plan is not None else
                 boundary_review.boxes(document,width,height) if document is not None else [])
    boundary_review.clear(raw,protected)
    boundary_review.clear(pending,protected)
    if np.any(raw & ~pending):
        raise ValueError('Cleanup mask must cover every source-mask pixel')
    # no_text_detected pages are common in books.  Return before ndimage.label,
    # full-page coverage allocation, or any Qwen dependency.
    if not raw.any() and not pending.any():
        plan=_empty_plan(original,raw,pending,cleanup_mask,tile_size,context)
        plan['report']['protected_boxes_pixels']=protected
        if edit_plan is not None: plan['report']['page_edit_plan']=edit_plan
        return plan
    base = original.copy()
    permitted=pending.copy()
    recovery=[]
    if recover_uniform_ink and uniform_fill:
        if regions_json is None:
            raise ValueError('Connect text regions before recovering uniform-background ink')
        base,raw,pending,permitted,recovery=_recover_uniform_regions(original,raw,pending,json.dumps(document))
        boundary_review.restore(base,original,protected)
        for value in (raw,pending,permitted): boundary_review.clear(value,protected)
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
        color = _ring_color(base[top:bottom, left:right], selected) if uniform_fill else None
        if color is not None:
            reference = raw[top:bottom, left:right] & selected
            contrast = np.max(np.abs(original[top:bottom, left:right]-color), axis=2)
            # After verified region filling, the old GrowMask halo can be an
            # empty flat-color component. It requires no model generation.
            if not reference.any() and np.all(contrast[selected] <= .018):
                pending[top:bottom, left:right][selected] = False
                filled += 1
                continue
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
              'protected_boxes_pixels':protected,
              **({'page_edit_plan':edit_plan} if edit_plan is not None else {}),
              **({'cleanup_skipped':True,'skip_reason':'empty_masks'}
                 if not raw.any() and not permitted.any() else {}),
              'tile_core': tile_size, 'context': context, 'tile_count': len(tiles),
              'source_components': count, 'uniform_filled_components': filled,
              'source_mask_pixels': int(raw.sum()), 'cleanup_mask_pixels': int((cleanup_mask > .5).sum()),
              'effective_cleanup_mask_pixels':int(permitted.sum()),
              'uniform_region_recovery':recovery,
              'qwen_mask_pixels': int(pending.sum()), 'tile_boxes': [t['crop'] for t in tiles],
              'coverage': 'each pending mask pixel owned exactly once',
              'limitation': 'undetected text outside the source mask is not automatically certified or erased'}
    return {'version': 1, 'original': original.copy(), 'base': base, 'source_mask': raw,
            'cleanup_mask': permitted, 'tiles': tiles, 'report': report}


def _blend_cleanup_halo(original,output,cleanup,source,width):
    """Bounded page-coordinate fades, shared by flat fills and model tiles."""
    # Axis projections avoid allocating two page-sized coordinate arrays for
    # a dense 64 MP mask. EDT allocations below remain bounded per core.
    xs=np.flatnonzero(cleanup.any(axis=0));ys=np.flatnonzero(cleanup.any(axis=1))
    bounds=[int(xs[0]),int(ys[0]),int(xs[-1])+1,int(ys[-1])+1] if len(xs) else None
    total=0
    if bounds is not None:
        x0,y0,x1,y1=bounds;h,w=cleanup.shape
        for top in range(y0,y1,512):
            for left in range(x0,x1,512):
                bottom,right=min(top+512,y1),min(left+512,x1)
                if not cleanup[top:bottom,left:right].any():continue
                a,b=max(0,left-width-1),max(0,top-width-1)
                c,d=min(w,right+width+1),min(h,bottom+width+1)
                distance=ndimage.distance_transform_edt(np.pad(cleanup[b:d,a:c],1))[1:-1,1:-1]
                alpha=np.minimum(distance[top-b:bottom-b,left-a:right-a]/width,1).astype(np.float32)
                alpha[source[top:bottom,left:right]]=1
                selected=cleanup[top:bottom,left:right] & (alpha<1)
                old=original[top:bottom,left:right];new=output[top:bottom,left:right]
                new[selected]=old[selected]+(new[selected]-old[selected])*alpha[selected,None]
                total+=int(selected.sum())
    return {'method':'source_protected_halo','width':width,'blended_halo_pixels':total,
            'source_pixels_unattenuated':True}


def assemble(plan, generated, strict_cleanup=True, blend_width=0):
    if not isinstance(plan, dict) or plan.get('version') != 1:
        raise ValueError('Expected an inpaint tile plan')
    if len(generated) != len(plan['tiles']):
        raise ValueError('Generated tile count differs from plan; no partial page was accepted')
    if type(blend_width) is not int or not 0<=blend_width<=32:
        raise ValueError('Cleanup blend width must be 0..32 pixels')
    if not plan['tiles'] and plan.get('report',{}).get('cleanup_skipped'):
        report = {**plan['report'], 'tile_checks': [], 'outside_mask_unchanged': True,
                  'quality_check': 'cleanup skipped because both source and cleanup masks are empty'}
        return plan['original'].copy(), json.dumps(report, ensure_ascii=False, indent=2)
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
    edge_blend=(_blend_cleanup_halo(plan['original'],output,plan['cleanup_mask'],plan['source_mask'],blend_width)
                if blend_width else {'method':'hard_mask','width':0})
    changed_outside = np.any(output != plan['original'], axis=2) & ~plan['cleanup_mask']
    if np.any(changed_outside):
        raise ValueError('Cleanup changed pixels outside the permitted mask')
    report = {**plan['report'], 'tile_checks': checks,'edge_blend':edge_blend,
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
            'uniform_fill': ('BOOLEAN', {'default': True})},
            'optional':{'regions_json':('STRING',{'forceInput':True}),
                        'recover_uniform_ink':('BOOLEAN',{'default':False,
                            'tooltip':'주변/내부의 단색 조건과 기존 검출 획이 확인된 text 영역에서 누락된 획/잔점을 보완합니다. 실효 마스크를 검수하세요.'})}}
    RETURN_TYPES = ('IMAGE', 'INT', 'INT', 'INT', 'INT', 'MASK', 'MANGA_INPAINT_PLAN', 'STRING','MASK','MASK')
    RETURN_NAMES = ('base_page', 'x', 'y', 'width', 'height', 'owned_tile_masks', 'plan', 'plan_report',
                    'effective_cleanup_mask','recovered_source_mask')
    OUTPUT_IS_LIST = (False, True, True, True, True, True, False, False,False,False)
    FUNCTION = 'prepare'
    CATEGORY = 'Manga Translator/Cleanup'
    def prepare(self, original, source_mask, cleanup_mask, **options):
        plan = make_plan(image(original), mask(source_mask), mask(cleanup_mask), **options)
        boxes = plan['report']['tile_boxes']
        return (tensor(plan['base']), [b[0] for b in boxes], [b[1] for b in boxes],
                [b[2]-b[0] for b in boxes], [b[3]-b[1] for b in boxes],
                [tensor(t['mask']) for t in plan['tiles']], plan,
                json.dumps(plan['report'], ensure_ascii=False, indent=2),
                tensor(plan['cleanup_mask']),tensor(plan['source_mask']))


class MangaInpaintAssemble:
    DESCRIPTION = '기본 노드가 복원·마스크 합성한 타일을 한 페이지로 모읍니다. 균일 배경만 있으면 Qwen 경로를 생략하고, 제거되지 않은 원문은 식자 전에 중단합니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'plan': ('MANGA_INPAINT_PLAN',),
                             'strict_cleanup': ('BOOLEAN', {'default': True})},
                'optional': {'generated': ('IMAGE', {'lazy': True}),
                             'blend_width':('INT',{'default':0,'min':0,'max':32,
                                 'tooltip':'검출 원문 픽셀은 온전히 제거하고 마스크 여유 부분만 부드럽게 합성합니다. 0=기존 경계. 배경 무늬 자체를 복원하는 옵션은 아닙니다.'})}}
    INPUT_IS_LIST = True
    RETURN_TYPES = ('IMAGE', 'STRING')
    RETURN_NAMES = ('cleaned_page', 'cleanup_report')
    FUNCTION = 'finish'
    CATEGORY = 'Manga Translator/Cleanup'
    def check_lazy_status(self, plan, strict_cleanup, generated=None, blend_width=None):
        # ComfyUI represents an unresolved lazy link as (None,), not only None.
        missing = generated is None or not generated or generated[0] is None
        return ['generated'] if plan[0]['tiles'] and missing else []
    def finish(self, plan, strict_cleanup, generated=None, blend_width=None):
        if len(plan) != 1 or len(strict_cleanup) != 1:
            raise ValueError('Assemble exactly one page at a time')
        missing = generated is None or not generated or generated[0] is None
        if blend_width is not None and len(blend_width)!=1:raise ValueError('Expected one cleanup blend width')
        result, report = assemble(plan[0], [] if missing else [image(t) for t in generated], strict_cleanup[0],
                                 blend_width[0] if blend_width is not None else 0)
        return tensor(result), report


NODE_CLASS_MAPPINGS = {'MangaInpaintPlan': MangaInpaintPlan, 'MangaInpaintAssemble': MangaInpaintAssemble}
NODE_DISPLAY_NAME_MAPPINGS = {'MangaInpaintPlan': '원문 제거 · 타일 계획',
                            'MangaInpaintAssemble': '원문 제거 · 타일 복원·검사'}
