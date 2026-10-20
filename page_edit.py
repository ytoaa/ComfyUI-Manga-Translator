"""One page edit decision shared by cleanup, lettering and project collection.

Detection geometry is evidence, not permission to erase. Only translated,
selected regions authorize cleanup. Preserved and unassigned source ink remain
protected through compositing. JSON is the ComfyUI boundary, not mutable state.
"""
from dataclasses import asdict, dataclass
import hashlib
import json

if __package__:
    from . import boundary_review
    from .limits import MAX_LETTERING_REGIONS, MAX_REGION_PIXELS, MAX_TYPOGRAPHY_PIXELS
else:  # The durable project collector also has a standalone CLI entry point.
    import boundary_review
    from limits import MAX_LETTERING_REGIONS, MAX_REGION_PIXELS, MAX_TYPOGRAPHY_PIXELS


@dataclass(frozen=True)
class RegionEdit:
    id: str
    bbox_pixels: tuple
    action: str
    reason: str

    def json(self):
        return {**asdict(self), 'bbox_pixels': list(self.bbox_pixels)}


def _digest(data):
    observed = {key: data.get(key) for key in ('image_width', 'image_height', 'regions', 'boundary_review', 'source_review_policy', 'page_edit_review')}
    return hashlib.sha256(json.dumps(observed, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def pixel_bounds(box, width, height):
    import math
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
            or not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height):
        raise ValueError('Invalid page edit pixel bounds')
    return [math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])]


def build(data, width, height, actions=None, source_mask=None, padding=12, source_review_policy='conservative'):
    from .nodes import layout, encode, pixel_box, verified_dot_text
    from .document import validate_target
    data = layout(encode(data))
    if any(data.get(key, expected) != expected
           for key, expected in (('image_width', width), ('image_height', height))):
        raise ValueError('Page edit coordinates belong to a different page size')
    if source_review_policy not in ('conservative', 'legacy'):
        raise ValueError('Invalid source review policy')
    data = {**data, 'image_width': width, 'image_height': height, 'source_review_policy': source_review_policy}
    if type(padding) is not int or not 0 <= padding <= 128:
        raise ValueError('Invalid page edit padding')
    ids = {row['id'] for row in data['regions']}
    actions = {} if actions is None else actions
    if (not isinstance(actions, dict) or set(actions)-ids
            or any(value not in ('replace', 'preserve') for value in actions.values())):
        raise ValueError('Region actions need existing IDs and replace/preserve values')
    decisions = []
    for row in data['regions']:
        validate_target(row)
        if not isinstance(row.get('source'), str) or not row['source'].strip():
            raise ValueError('Page edit planning needs collected source OCR text')
        box = pixel_bounds(row.get('edit_bbox_pixels', pixel_box(row['bbox'], width, height, padding)), width, height)
        dots = verified_dot_text(row)
        unchanged = dots is not None and row['target'] == dots
        from .source_ownership import review_reason
        uncertain = review_reason(row, width, height) if source_review_policy == 'conservative' else None
        action = actions.get(row['id'], 'preserve' if unchanged or uncertain else 'replace')
        reason = ('manual_source_preservation' if action == 'preserve' and row['id'] in actions else
                  'verified_source_punctuation' if unchanged and action == 'preserve' else
                  uncertain if uncertain and action == 'preserve' else
                  'manual_source_replacement' if row['id'] in actions else 'translated_region')
        decisions.append(RegionEdit(row['id'], tuple(box), action, reason))

    # Cheap source-space preflight, before any erase/model work. Distinct ink
    # layers sharing one edit frame are not permission to remove each other.
    coincident = {row.id for row in decisions if row.action == 'replace'
                  and any(other.id != row.id and other.action == 'replace' and other.bbox_pixels == row.bbox_pixels
                          for other in decisions)} if source_review_policy == 'conservative' else set()
    decisions = [RegionEdit(row.id, row.bbox_pixels, 'preserve', 'coincident_edit_frames')
                 if row.id in coincident and row.id not in actions and
                 any(r['id'] == row.id and r.get('source_ownership', {}).get('schema') == 1 for r in data['regions'])
                 else row for row in decisions]

    protected = boundary_review.boxes(data, width, height)
    unassigned = []
    if source_mask is not None:
        import numpy as np
        from scipy import ndimage
        if source_mask.shape != (height, width) or not np.isfinite(source_mask).all():
            raise ValueError('Page edit source mask dimensions differ or contain nonfinite pixels')
        unknown = source_mask > .5
        boundary_review.clear(unknown, protected + [list(row.bbox_pixels) for row in decisions])
        if unknown.any():
            labels, count = ndimage.label(unknown)
            if count > 512:
                raise ValueError('Unassigned source ink exceeds 512 components; review region geometry')
            for slices in ndimage.find_objects(labels):
                if slices is not None:
                    y, x = slices
                    unassigned.append([x.start, y.start, x.stop, y.stop])
    protected += unassigned + [list(row.bbox_pixels) for row in decisions if row.action == 'preserve']
    # A neighbouring editable rectangle must not erase or letter over preserved
    # source. Close the set before any uniform filling or model inference.
    changed = True
    while changed:
        changed = False
        for index, row in enumerate(decisions):
            if row.action == 'replace' and any(boundary_review.intersects(row.bbox_pixels, box) for box in protected):
                decisions[index] = RegionEdit(row.id, row.bbox_pixels, 'preserve', 'protected_region_overlap')
                protected.append(list(row.bbox_pixels))
                changed = True
    edit_review = bool(unassigned) or any(row.reason in ('protected_region_overlap', 'ambiguous_isolated_source', 'unverified_display_text', 'coincident_edit_frames', 'ambiguous_cross_label_source') for row in decisions)
    review = bool(data.get('needs_review')) or edit_review
    plan = {'schema': 1, 'coordinate_format': 'xyxy_pixels', 'page_size': [width, height], 'region_padding':padding,
            'input_sha256': _digest(data), 'regions': [row.json() for row in decisions],
            'unassigned_boxes_pixels': unassigned, 'protected_boxes_pixels': protected,
            'needs_review': review}
    result = {**data, 'page_edit_plan': plan,
              **({'needs_review': True, 'review_reason': 'source_edit_plan_requires_review'} if edit_review else {})}
    validate(result,width,height)
    return result


def validate(data, width, height):
    """Reject stale or altered decisions instead of silently rebuilding them."""
    plan = data.get('page_edit_plan')
    if (not isinstance(plan, dict) or plan.get('schema') != 1
            or plan.get('coordinate_format') != 'xyxy_pixels' or plan.get('page_size') != [width, height]
            or plan.get('input_sha256') != _digest(data)):
        raise ValueError('Page edit plan is stale or belongs to a different document')
    rows = plan.get('regions')
    if (not isinstance(rows, list) or [r.get('id') for r in rows if isinstance(r, dict)] != [r['id'] for r in data['regions']]
            or len(rows) != len(data['regions'])):
        raise ValueError('Page edit plan region identity differs')
    for row in rows:
        pixel_bounds(row.get('bbox_pixels'), width, height)
        if any(type(value) is not int for value in row['bbox_pixels']):
            raise ValueError('Page edit plan needs integer pixel bounds')
        if row.get('action') not in ('replace', 'preserve') or not isinstance(row.get('reason'), str):
            raise ValueError('Invalid page edit action')
    active=[row for row in rows if row['action']=='replace']
    areas=[(r['bbox_pixels'][2]-r['bbox_pixels'][0])*(r['bbox_pixels'][3]-r['bbox_pixels'][1]) for r in active]
    if len(active)>MAX_LETTERING_REGIONS or any(area>MAX_REGION_PIXELS for area in areas) or sum(areas)>MAX_TYPOGRAPHY_PIXELS:
        raise ValueError('Page edit plan exceeds active lettering region/area limits; split the page or preserve regions')
    padding=plan.get('region_padding')
    if type(padding) is not int or not 0<=padding<=128:
        raise ValueError('Invalid page edit padding')
    import math
    for source,decision in zip(data['regions'],rows):
        a,b,c,d=source['bbox']
        expected=source.get('edit_bbox_pixels',[max(0,math.floor(a*width/1000)-padding),
            max(0,math.floor(b*height/1000)-padding),min(width,math.ceil(c*width/1000)+padding),
            min(height,math.ceil(d*height/1000)+padding)])
        if decision['bbox_pixels']!=pixel_bounds(expected,width,height):
            raise ValueError('Page edit geometry differs from translated region')
    for name in ('protected_boxes_pixels', 'unassigned_boxes_pixels'):
        if not isinstance(plan.get(name), list) or len(plan[name]) > 1024:
            raise ValueError('Invalid page edit protection list')
        for box in plan[name]:
            pixel_bounds(box, width, height)
            if any(type(value) is not int for value in box):
                raise ValueError('Page edit protection needs integer pixel bounds')
    expected = (boundary_review.boxes(data, width, height) + plan['unassigned_boxes_pixels'] +
                [row['bbox_pixels'] for row in rows if row['action'] == 'preserve'])
    if {tuple(box) for box in expected} != {tuple(box) for box in plan['protected_boxes_pixels']}:
        raise ValueError('Page edit protection is missing or altered')
    if any(boundary_review.intersects(row['bbox_pixels'], box)
           for row in rows if row['action'] == 'replace' for box in expected):
        raise ValueError('Editable region overlaps preserved source')
    return plan


def cleanup_document(data, width, height):
    """A bounded view for ink recovery, not a second canonical page document."""
    plan = validate(data, width, height)
    active = {row['id'] for row in plan['regions'] if row['action'] == 'replace'}
    return {'image_width': width, 'image_height': height,
            'regions': [row for row in data['regions'] if row['id'] in active]}


def masks(data, source, cleanup):
    import numpy as np
    height, width = source.shape
    plan = validate(data, width, height)
    if cleanup.shape != source.shape or not np.isfinite(source).all() or not np.isfinite(cleanup).all():
        raise ValueError('Invalid page edit cleanup mask')
    permitted = np.zeros((height, width), bool)
    for row in plan['regions']:
        if row['action'] == 'replace':
            a, b, c, d = row['bbox_pixels']
            permitted[b:d, a:c] = True
    boundary_review.clear(permitted, plan['protected_boxes_pixels'])
    return (source > .5) & permitted, (cleanup > .5) & permitted


class MangaPageEditPlan:
    CATEGORY = 'Manga Translator/Editing'
    DESCRIPTION = '번역 후 영역별 교체·원본 보존을 결정합니다. 제거 마스크·식자·폴더 검증이 같은 계획을 사용하며 미배정 원문 획은 보존·검수합니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'original': ('IMAGE',), 'translated_json': ('STRING', {'forceInput': True}),
                             'source_mask': ('MASK',), 'cleanup_mask': ('MASK',)},
                'optional': {'region_actions_json': ('STRING', {'default': '{}', 'multiline': True,
                    'tooltip': '영역별 원본 보존/교체. 예: {"r1":"preserve"}. 검수 후 replace로 명시하면 문자성 검수만 해제하며 보호 교차는 유지합니다. 폴더에서는 매 페이지의 같은 ID에 적용합니다.'}),
                    'source_review_policy': (['conservative','legacy'], {'default':'conservative',
                    'tooltip':'conservative: 검증된 말풍선 밖 짧은 독립 문자·큰 제목은 원본 보존·검수. 실제 문자 판별 보증은 아닙니다. legacy는 기존 교체 정책입니다.'}),
                    'review_edits_json': ('STRING', {'default':'{}','multiline':True,
                    'tooltip':'아래 영역 검수·브러시가 페이지/입력 revision별로 저장됩니다. 수정 후 Run합니다. 같은 ID의 다른 페이지에 적용하지 않습니다.'}),
                    'page_context_json': ('STRING', {'forceInput':True})}}
    RETURN_TYPES = ('STRING', 'MASK', 'MASK', 'IMAGE', 'STRING')
    RETURN_NAMES = ('편집_명세_JSON', '교체할_원문_마스크', '교체할_제거_마스크', '편집_검수', '편집_보고서')
    FUNCTION = 'plan'

    def plan(self, original, translated_json, source_mask, cleanup_mask, region_actions_json='{}', source_review_policy='conservative', review_edits_json='{}', page_context_json='{}'):
        import numpy as np
        from .nodes import layout, decode, encode
        from .lettering.nodes import image, mask, tensor
        from PIL import Image, ImageDraw
        pixels = image(original)
        height, width = pixels.shape[:2]
        source, cleanup = mask(source_mask), mask(cleanup_mask)
        document=layout(translated_json)
        from .source_recovery import recover_masks
        original_image=Image.fromarray((pixels*255).round().astype('uint8'))
        source,cleanup=recover_masks(original_image,document,source,cleanup)
        from . import edit_review
        actions=decode(region_actions_json)
        if not isinstance(actions,dict):raise ValueError('Region actions need an object')
        review=edit_review.select(document,original_image,source,cleanup,review_edits_json,page_context_json,source_review_policy,actions,
                                  hashlib.sha256(pixels.tobytes()).hexdigest())
        for ident,patch in review['selected_edits'].items():
            if patch.get('action','auto')!='auto':actions[ident]=patch['action']
        document={**document,'page_edit_review':review}
        if review['warnings']:
            document.update(needs_review=True,review_reason='stale_page_edit_review')
        data = build(document, width, height, actions, source, source_review_policy=source_review_policy)
        # Cards retain original detector ink and the unmodified brush base.
        # Rendering pending edits in the browser then exactly mirrors the run.
        cards=edit_review.cards(original_image,data,source,cleanup)
        source,cleanup,brush_report=edit_review.paint(data,source,cleanup,review['selected_edits'])
        plan = data['page_edit_plan']
        preview = Image.fromarray((pixels*255).round().astype('uint8'))
        draw = ImageDraw.Draw(preview)
        for row in plan['regions']:
            a, b, c, d = row['bbox_pixels']
            draw.rectangle((a, b, c-1, d-1), outline=(40, 210, 90) if row['action'] == 'replace' else (255, 80, 80), width=2)
        for box in plan['unassigned_boxes_pixels']:
            a, b, c, d = box
            draw.rectangle((a, b, c-1, d-1), outline=(255, 80, 80), width=2)
        report = {**plan, 'replace_regions': sum(row['action'] == 'replace' for row in plan['regions']),
                  'preserve_regions': sum(row['action'] == 'preserve' for row in plan['regions']),
                  'legend': 'green=replace; red=preserve', 'quality_scope': 'edit_permission_not_recognition_accuracy',
                  'brush_edits':brush_report,'review_revision':review['input_revision'],'warnings':review['warnings']}
        snapshot={**review,'regions':cards}
        return {'ui':{'manga_edit_review':[snapshot],
                      'manga_status':[{'state':'needs_review' if plan['needs_review'] or review['warnings'] else 'completed',
                                       'message':f"교체 {report['replace_regions']} · 원본 보존 {report['preserve_regions']} · 브러시 {len(brush_report)}영역"}]},
                'result':(encode(data), tensor(source), tensor(cleanup), tensor(np.asarray(preview)/255), encode(report))}
