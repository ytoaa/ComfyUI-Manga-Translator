"""Build the integrated tiled-cleanup GUI/API graph without model inference."""
import json
from build_lettering_examples import Graph, CORE_SCHEMAS, CORE_RETURNS, ROOT

CORE_SCHEMAS.update({
    'GrowMask': {'required': {'mask': ('MASK',), 'expand': ('INT', {'default': 8}),
                              'tapered_corners': ('BOOLEAN', {'default': True})}},
    'MaskToImage': {'required': {'mask': ('MASK',)}}})
CORE_SCHEMAS['PreviewAny']={'required':{'source':('*',)}}
CORE_SCHEMAS['PrimitiveBoolean']={'required':{'value':('BOOLEAN',{'default':False})}}
CORE_RETURNS.update({'GrowMask': ('MASK',), 'MaskToImage': ('IMAGE',),'PreviewAny':('STRING',),
                     'PrimitiveBoolean':('BOOLEAN',)})


def build(manual=False):
    template = json.loads((ROOT/'lettering/example_workflows/07-rfdetr-detail-adaptive-ocr-cleanup-lettering.json').read_text(encoding='utf-8'))
    g = Graph()
    original = g.add('LoadImage' if manual else 'MangaWorkflowInput', {'image': ''}, (0, 50), '① 원본 페이지' if manual else '① 워크플로우 입력 · 이미지 한 장 / 폴더 프로젝트')
    if not manual:g.nodes[original-1]['size']=[400,270]
    if manual:
        # One editable JSON is authoritative for crops, cleanup and lettering.
        # These are human-selected frames for the reported 800x1125 cover,
        # not detector results or guessed transcriptions.
        layout={'origin':'manual','selection':'human_supplied_regions','regions':[
            {'id':'location','kind':'text','bbox':[858,24,954,61]},
            {'id':'booth','kind':'text','bbox':[423,57,970,170]},
            {'id':'title','kind':'text','bbox':[44,300,284,970]}]}
        crops=g.add('MangaRegionCrops',{'layout_json':json.dumps(layout,ensure_ascii=False,indent=2),
            'allow_empty_page':False,'edit_margin':0},pos=(840,50),title='② 수동 영역 JSON · 표지 예시 좌표를 검수하세요')
        g.connect(original,0,crops,'images')
        raw_mask,mask_slot=crops,2
        regions,regions_slot=crops,1
        grown=g.add('GrowMask',{'expand':0},pos=(1260,400),title='사각형 제거 범위 · 기본 GrowMask (기본 확대 0)')
        g.connect(raw_mask,mask_slot,grown,'mask')
    else:
        detector_model = g.import_model_node(template, 24, (0, 400))
        detector = g.add('MangaDetectorDetail', {'include_sfx':False}, pos=(420, 50), title='② 전체+작은 타일 검출 · 공통 글자 선택')
        g.connect(original, 0, detector, 'images'); g.connect(detector_model, 0, detector, 'model')
        regions = g.add('MangaDetectionRegions', {'merge_adjacent_lines':True}, pos=(840, 50), title='③ 중복 해소 · 가까운 행을 문단으로')
        g.connect(detector, 0, regions, 'result')
        raw_mask = g.add('MangaDetectionMask', pos=(840, 400), title='원문 글자 마스크')
        g.connect(detector, 0, raw_mask, 'result')
        mask_slot,regions_slot=0,0
        grown = g.add('GrowMask', pos=(1260, 400), title='제거 여유 · 기본 GrowMask')
        g.connect(raw_mask, 0, grown, 'mask')
        crops = g.add('MangaRegionCrops', {'allow_empty_page':True,'refine_page_columns':True}, pos=(1260, 50), title='④ OCR 전 단·문단 정리 · 글자 없으면 원본 통과')
        g.connect(original, 0, crops, 'images'); g.connect(regions, 0, crops, 'layout_json')
    ocr_model = g.import_model_node(template, 13, (1260, -220))
    ocr = g.add('MangaOCRAdaptive', {'tight_crop':False,'base_patches':256,'small_text_patches':512,
        'split_long_lines':True,'quality_guard':True,'retry_on_token_limit':True,
        'retry_on_layout_failure':True}, (1680, 50), '⑤ OCR · 반복 시 입력 재분할')
    g.connect(crops, 0, ocr, 'images'); g.connect(ocr_model, 0, ocr, 'model')
    collect = g.add('MangaCollectOCR', pos=(2100, 50))
    g.connect(ocr, 0, collect, 'text'); g.connect(crops, 1, collect, 'manifest_json')
    g.connect(ocr, 1, collect, 'ocr_report_json')
    source_save = g.add('MangaSaveReview', {'filename_prefix': 'manga_translator/ocr'}, (2520, 50), 'OCR JSON 저장')
    g.connect(collect, 0, source_save, 'translated_json')
    translate = g.add('MangaTranslate', pos=(2940, 50), title='⑥ 번역 · 영역 ID 유지')
    g.connect(source_save, 0, translate, 'ocr_json')
    target_save = g.add('MangaSaveReview', {'filename_prefix': 'manga_translator/translation'}, (3360, 50), '번역 JSON 저장')
    g.connect(translate, 0, target_save, 'translated_json')

    plan = g.add('MangaInpaintPlan', {'recover_uniform_ink':True}, pos=(1680, 650), title='⑦ 단색 잔상 보완 · 제거 타일 계획')
    g.connect(original, 0, plan, 'original'); g.connect(raw_mask, mask_slot, plan, 'source_mask')
    g.connect(grown, 0, plan, 'cleanup_mask')
    g.connect(crops, 1, plan, 'regions_json')
    tile_crop = g.add('ImageCrop', pos=(2100, 650), title='영역 자르기 · 기본 ImageCrop')
    g.connect(plan, 0, tile_crop, 'image')
    for field, slot in [('x', 1), ('y', 2), ('width', 3), ('height', 4)]:
        g.connect(plan, slot, tile_crop, field)

    q = {}
    for old, pos in [(1, (1680, 1050)), (2, (1680, 1250)), (3, (1680, 1450)),
                     (4, (2520, 650)), (5, (2100, 1050)), (6, (2520, 1150)),
                     (7, (2520, 1350)), (8, (2940, 650)), (9, (3360, 650))]:
        q[old] = g.import_model_node(template, old, pos)
    g.nodes[q[4]-1]['title'] = '⑧ Qwen · 페이지가 아닌 타일 원문 제거'
    for src, slot, dst, field in [
        (q[1], 0, q[5], 'model'), (q[2], 0, q[4], 'clip'), (q[3], 0, q[4], 'vae'),
        (tile_crop, 0, q[4], 'images.image_1'), (q[5], 0, q[8], 'model'),
        (q[4], 0, q[8], 'positive'), (q[4], 1, q[8], 'negative'),
        (q[6], 0, q[8], 'sampler'), (q[7], 0, q[8], 'sigmas'),
        (q[4], 2, q[8], 'latent_image'), (q[8], 0, q[9], 'samples'), (q[3], 0, q[9], 'vae')]:
        g.connect(src, slot, dst, field)
    restore = g.add('ImageScale', pos=(3780, 650), title='타일 원래 크기 복원 · 기본 ImageScale')
    g.connect(q[9], 0, restore, 'image')
    g.connect(plan, 3, restore, 'width'); g.connect(plan, 4, restore, 'height')
    local_comp = g.add('ImageCompositeMasked', pos=(4200, 650), title='타일 소유 마스크 합성 · 기본 노드')
    g.connect(tile_crop, 0, local_comp, 'destination'); g.connect(restore, 0, local_comp, 'source')
    g.connect(plan, 5, local_comp, 'mask')
    assemble = g.add('MangaInpaintAssemble', pos=(4620, 650), title='⑨ 전체 좌표 복원 · 잔존 원문 검사')
    g.connect(plan, 6, assemble, 'plan'); g.connect(local_comp, 0, assemble, 'generated')
    prepare = g.add('MangaLetterPrepare', pos=(4620, 50), title='⑩ 번역문과 원문 스타일 연결')
    g.connect(original, 0, prepare, 'original'); g.connect(target_save, 0, prepare, 'translated_json')
    g.connect(plan, 9, prepare, 'text_pixel_mask')
    typography_values={'line_breaks':'reflow','fit_policy':'readable','respect_bubbles':True}
    if manual:
        typography_values['region_options_json']=json.dumps({'title':{'direction':'vertical_rtl'},
            'location':{'direction':'horizontal'},'booth':{'direction':'horizontal'}},ensure_ascii=False)
    typography = g.add('MangaLetterPlan', typography_values,
                       pos=(5040, 50), title='⑪ 실제 말풍선 경계 검사 · 가독 크기 맞춤')
    g.connect(original, 0, typography, 'original'); g.connect(assemble, 0, typography, 'cleaned')
    g.connect(prepare, 1, typography, 'source_mask'); g.connect(prepare, 0, typography, 'regions_json')
    if not manual:g.connect(detector, 0, typography, 'detection_result')
    lettering = g.add('MangaLetterApply', pos=(5460, 50), title='⑫ 방향별 식자 · 비례 스타일 · 충돌 검사')
    g.connect(typography, 0, lettering, 'plan')
    save = g.add('SaveImage', {'filename_prefix': 'manga_translator/manual_tiles' if manual else 'manga_translator/integrated_tiles'}, (5880, 50), '⑬ 통합 결과 저장')
    g.connect(lettering, 0, save, 'images')
    clean_preview = g.add('PreviewImage', pos=(5040, 650), title='검수 · 식자 직전 전체 배경')
    g.connect(assemble, 0, clean_preview, 'images')
    mask_image = g.add('MaskToImage', pos=(1260, 1050), title='마스크 → 이미지 · 기본 노드')
    g.connect(plan, 8, mask_image, 'mask')
    preview = g.add('PreviewImage', pos=(1260, 1250), title='검수 · 제거 대상 마스크')
    g.connect(mask_image, 0, preview, 'images')
    typography_preview = g.add('PreviewImage', pos=(5460, 650), title='검수 · 원문 프레임과 확장 가능 공간')
    g.connect(typography, 1, typography_preview, 'images')
    ocr_preview = g.add('PreviewImage', pos=(2100,-350), title='검수 · OCR 행/조각 (글자 없으면 원본)')
    g.connect(ocr, 2, ocr_preview, 'images')
    original_crops = g.add('PreviewImage', pos=(1260,-550), title='검수 · OCR 크롭 (글자 없으면 원본)')
    g.connect(crops, 0, original_crops, 'images')
    g.connect(crops, 1, ocr, 'manifest_json')
    g.note('선택한 글자 검출이 0개면 no_text_detected로 기록하고 원본 그대로 저장합니다. OCR/번역/Qwen/식자를 생략합니다.\n'
           '다단 본문의 단 사이 여백이 확인되면 OCR 전에 중복 영역을 정리합니다. 행별 OCR과 번역·제거·식자가 같은 명세를 사용합니다.\n'
           '검출 0개는 실제 글자 없음의 보증이 아닙니다. 검출 오류/OCR 실패는 계속 중단합니다.\n'
           '원문 크기 상한에서 가용 폭을 먼저 사용. 단일 줄바꿈은 자동 재배치하고 빈 줄 문단은 유지합니다.\n'
           'line_breaks=preserve로 수동 줄바꿈 유지. strict/세로쓰기에서는 원래 줄바꿈을 유지합니다.\n'
           '단색이 확인된 OCR 영역 안에서 누락된 획/잔점을 제거 범위에 보완합니다. 실효 마스크를 미리보기로 확인하세요.\n'
           'bubble은 검출된 실제 말풍선 마스크 또는 직접 연결한 내부 마스크에서 확장합니다. 겹침/최소 크기 실패는 저장 전에 중단합니다.\n'
           '영역별 폰트·방향·회전·수동 곡선은 식자 계획 노드의 JSON으로 지정합니다.\n'
           '효과음·표지 큰 글자 포함 스위치 하나가 검출·영역·마스크를 함께 설정합니다. 기본은 제외. 표지는 포함 설정도 검토하세요.\n'
           '긴 가로 행은 빈 열에서 분할. OCR 반복/누락 의심은 patch 변경 1회 후 계속 실패하면 중단합니다.\n'
           'OCR JSON에 영역별 입력 크기/분할/재시도 진단을 저장합니다. 휴리스틱 통과는 인식 정확도 보증이 아닙니다.\n'
           '한 번 실행: 검출→줄별 OCR→번역→타일별 제거→좌표 복원→식자.\n'
           'Qwen은 512px 코어+128px 문맥 타일만 처리합니다. 단색 배경은 보수적 색 채우기를 먼저 시도합니다.\n'
           '이미지 크롭/크기 복원/마스크 확대/타일 합성/미리보기/저장은 기본 노드입니다.\n'
           '원문이 거의 그대로인 타일은 식자 전에 중단합니다. 픽셀 검사이며 OCR 품질 보증은 아닙니다.\n'
           '마스크 밖 누락 글씨는 자동 삭제되지 않습니다. 마스크 미리보기와 OCR JSON으로 확인하세요.\n'
           '반복이 지속되면 확인된 행/열 간격에서 한 번 다시 분할합니다. 실패 입력은 output/manga_translator/ocr_failures에 저장합니다.\n'
           'fit_policy=readable은 원문 비율 제한으로 맞지 않을 때 min_font까지 추가 축소합니다. strict/명시적 최소 크기는 유지합니다.\n'
           '확인된 말풍선은 실제 마스크 내부로 글자 알파 전체를 제한합니다. 초록색은 안전한 내부 사각형입니다.\n'
           '통합 모의 실행 결과와 실제 GPU 품질 검증은 구분합니다.', (3360, 1150))
    for source,pos,title in [(source_save,(2520,250),'OCR 저장 JSON · 미리보기 아무거나'),
                             (target_save,(3360,250),'번역 저장 JSON · 미리보기 아무거나')]:
        preview=g.add('PreviewAny',pos=pos,title=title)
        g.nodes[preview-1]['size']=[400,260]
        g.nodes[preview-1]['properties']['cnr_id']='comfy-core'
        g.connect(source,0,preview,'source')
    if manual:
        # Replace auto-specific guidance with the actual manual contract.
        note=next(n for n in g.nodes if n['type']=='Note')
        note['widgets_values']=['수동 경로: RF-DETR를 실행하지 않습니다. 자동 검출 성공을 의미하지 않습니다.\n'
            '원본을 선택하고 두 번째 노드의 layout_json을 검수하세요. bbox는 원본 가로/세로 각각 0..1000의 xyxy 좌표입니다.\n'
            '기본값은 보고된 800x1125 표지의 위쪽 두 표시와 왼쪽 세로 제목을 사람이 지정한 예시입니다.\n'
            '문자열은 하드코딩하지 않습니다. 지정 영역을 Hayai가 읽고 번역 서버에 전달합니다.\n'
            '사각형 전체가 제거 마스크입니다. 글자 획 segmentation이 아니므로 영역 안의 그림도 재생성될 수 있습니다.\n'
            'GrowMask 기본 확대 0, edit_margin=0. 제거 마스크와 식자 직전 배경 미리보기를 확인하세요.\n'
            '정밀 마스크가 있다면 source_mask와 GrowMask 입력을 그 마스크로 교체할 수 있습니다.\n'
            'title은 세로 식자, location/booth는 가로 식자로 지정했습니다. 다른 ID/이미지에서는 영역별 JSON도 수정하세요.\n'
            'RF-DETR bubble 마스크는 없습니다. source 모드의 지정 프레임 안에서 식자합니다.\n'
            'OCR/제거/식자 실패 검사는 유지합니다. 실제 Hayai/Qwen 결과는 사용자 환경에서 확인해야 합니다.']
        name='09-manual-regions-integrated-cleanup-lettering'
    else:
        scope=g.add('PrimitiveBoolean',{'value':False},pos=(0,650),title='효과음·표지 큰 글자 포함 · 공통 스위치')
        g.nodes[scope-1]['properties']['cnr_id']='comfy-core'
        for node in (detector,regions,raw_mask):g.connect(scope,0,node,'include_sfx')
        name='08-integrated-tiled-cleanup-lettering'
    if not manual:
        status=g.add('PreviewAny',pos=(0,-350),title='프로젝트 진행·실패·결과 위치 · 미리보기 아무거나')
        g.nodes[status-1]['size']=[420,300]
        g.nodes[status-1]['properties']['cnr_id']='comfy-core'
        g.connect(original,2,status,'source')
        g.note('폴더 처리도 이 워크플로우 안에서 실행합니다. 입력 노드의 input_mode=폴더 프로젝트로 설정하세요.\n'
               'input_folder는 ComfyUI/input 아래의 원본 폴더, project_name은 결과·재개 기록의 이름입니다.\n'
               'action=시작·재개로 실행하면 현재 08 설정을 저장하고 한 페이지씩 같은 그래프를 큐에 제출합니다.\n'
               '진행 보고서는 미리보기 아무거나에 표시합니다. 일시정지/상태 확인도 action을 바꾸고 실행하세요.\n'
               '일시정지는 현재 페이지를 마친 뒤 적용합니다. 실패 재시도는 실패 페이지에만 새 시도를 추가합니다.\n'
               '재개는 저장된 설정을 사용합니다. 모델·번역·식자 설정을 바꾼 새 실행은 새 project_name을 사용하세요.\n'
               '이미지를 한꺼번에 텐서 목록으로 합치지 않습니다. OCR/타일 집계는 페이지마다 독립 실행합니다.',(420,-550))
    g.connect(crops, 3, ocr, 'region_plan_json')
    g.save(name)
    # The committed 08 graph uses LF; keep regeneration byte-for-byte stable.
    for suffix in ('.json','.api.json'):
        path=ROOT/'lettering/example_workflows'/(name+suffix)
        path.write_bytes(path.read_bytes().replace(b'\r\n',b'\n'))
    return g


if __name__ == '__main__':
    from argparse import ArgumentParser
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--manual',action='store_true',help='Build manual region variant 09; leave 08 unchanged')
    args=parser.parse_args()
    build(args.manual)
