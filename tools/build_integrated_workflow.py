"""Build the integrated tiled-cleanup GUI/API graph without model inference."""
import json
from workflow_graph import Graph, CORE_SCHEMAS, CORE_RETURNS, ROOT
CORE_SCHEMAS.update({'GrowMask': {'required': {'mask': ('MASK',), 'expand': ('INT', {'default': 8}), 'tapered_corners': ('BOOLEAN', {'default': True})}}, 'MaskToImage': {'required': {'mask': ('MASK',)}}})
CORE_SCHEMAS['PreviewAny'] = {'required': {'source': ('*',)}}
CORE_SCHEMAS['PrimitiveBoolean'] = {'required': {'value': ('BOOLEAN', {'default': False})}}
CORE_RETURNS.update({'GrowMask': ('MASK',), 'MaskToImage': ('IMAGE',), 'PreviewAny': ('STRING',), 'PrimitiveBoolean': ('BOOLEAN',)})

def build():
    template = json.loads((ROOT / 'tools/integrated_model_nodes.json').read_text(encoding='utf-8'))
    g = Graph()
    original = g.add('MangaWorkflowInput', {'image': ''}, (0, 50), '① 워크플로우 입력 · 이미지 한 장 / 폴더 프로젝트')
    g.nodes[original - 1]['size'] = [420, 560]
    direction = g.add('MangaLetteringDirection', pos=(420, -200), title='번역문 방향 · 폴더 전체 가로 / 세로 통일')
    detector_model = g.import_model_node(template, 24, (0, 700))
    detector = g.add('MangaDetectorDetail', {'include_sfx': False, 'boundary_policy':'preserve_review'}, pos=(420, 50), title='② 전체+작은 타일 검출 · 미복구 영역 원본 보존·검수')
    g.connect(original, 0, detector, 'images')
    g.connect(detector_model, 0, detector, 'model')
    regions = g.add('MangaDetectionRegions', {'merge_adjacent_lines': True,'protected_overlap_policy':'preserve_review'}, pos=(840, 50), title='③ 원문 중복 통합 · 말풍선·컷 경계 유지')
    g.connect(detector, 0, regions, 'result')
    raw_mask = g.add('MangaDetectionMask', pos=(840, 400), title='원문 글자 마스크')
    g.connect(detector, 0, raw_mask, 'result')
    mask_slot = 0
    grown = g.add('GrowMask', pos=(1260, 400), title='제거 여유 · 기본 GrowMask')
    g.connect(raw_mask, 0, grown, 'mask')
    crops = g.add('MangaRegionCrops', {'allow_empty_page': True, 'refine_page_columns': True,'auto_deskew':True,'geometry_policy':'preserve_review'}, pos=(1260, 50), title='④ OCR 전 단·회전 보정 · 원본 문맥 복구·검수')
    g.connect(original, 0, crops, 'images')
    g.connect(regions, 0, crops, 'layout_json')
    ocr_model = g.add('MangaOCRModel',pos=(1260,-300),title='OCR 엔진 · 누락 모델 자동 다운로드')
    ocr = g.add('MangaOCRAdaptive', {'tight_crop': False, 'base_patches': 256, 'small_text_patches': 512, 'split_long_lines': True, 'quality_guard': True, 'retry_on_token_limit': True, 'retry_on_layout_failure': True, 'failure_policy': 'preserve_review'}, (1680, 50), '⑤ OCR · 반복 시 입력 재분할')
    g.connect(crops, 0, ocr, 'images')
    g.connect(ocr_model, 0, ocr, 'model')
    collect = g.add('MangaCollectOCR', pos=(2100, 50))
    g.connect(ocr, 0, collect, 'text')
    g.connect(crops, 1, collect, 'manifest_json')
    g.connect(ocr, 1, collect, 'ocr_report_json')
    source_save = g.add('MangaSaveReview', {'filename_prefix': 'manga_translator/ocr'}, (2520, 50), 'OCR JSON 저장')
    g.connect(collect, 0, source_save, 'translated_json')
    translate = g.add('MangaTranslate', pos=(2940, 50), title='⑥ 번역 · 영역 ID 유지')
    g.connect(source_save, 0, translate, 'ocr_json')
    edits = g.add('MangaPageEditPlan', {'source_review_policy':'conservative'}, pos=(3360, -2100), title='⑥-2 삭제 전 원문 검수 · 교체 / 원본 보존 / 마스크 브러시')
    g.connect(original, 0, edits, 'original')
    g.connect(translate, 0, edits, 'translated_json')
    g.connect(raw_mask, mask_slot, edits, 'source_mask')
    g.connect(grown, 0, edits, 'cleanup_mask')
    g.nodes[edits-1]['size']=[420,1200]
    target_save = g.add('MangaSaveReview', {'filename_prefix': 'manga_translator/translation'}, (3780, 50), '번역·편집 계획 JSON 저장')
    g.connect(edits, 0, target_save, 'translated_json')
    plan = g.add('MangaInpaintPlan', {'recover_uniform_ink': True}, pos=(1680, 650), title='⑦ 단색 잔상 보완 · 제거 타일 계획')
    g.connect(original, 0, plan, 'original')
    g.connect(edits, 1, plan, 'source_mask')
    g.connect(edits, 2, plan, 'cleanup_mask')
    g.connect(target_save, 0, plan, 'regions_json')
    tile_crop = g.add('ImageCrop', pos=(2100, 650), title='영역 자르기 · 기본 ImageCrop')
    g.connect(plan, 0, tile_crop, 'image')
    for field, slot in [('x', 1), ('y', 2), ('width', 3), ('height', 4)]:
        g.connect(plan, slot, tile_crop, field)
    q = {}
    for old, pos in [(1, (1680, 1050)), (2, (1680, 1250)), (3, (1680, 1450)), (4, (2520, 650)), (5, (2100, 1050)), (6, (2520, 1150)), (7, (2520, 1350)), (8, (2940, 650)), (9, (3360, 650))]:
        q[old] = g.import_model_node(template, old, pos)
    g.nodes[q[4] - 1]['title'] = '⑧ Qwen · 페이지가 아닌 타일 원문 제거'
    for src, slot, dst, field in [(q[1], 0, q[5], 'model'), (q[2], 0, q[4], 'clip'), (q[3], 0, q[4], 'vae'), (tile_crop, 0, q[4], 'images.image_1'), (q[5], 0, q[8], 'model'), (q[4], 0, q[8], 'positive'), (q[4], 1, q[8], 'negative'), (q[6], 0, q[8], 'sampler'), (q[7], 0, q[8], 'sigmas'), (q[4], 2, q[8], 'latent_image'), (q[8], 0, q[9], 'samples'), (q[3], 0, q[9], 'vae')]:
        g.connect(src, slot, dst, field)
    restore = g.add('ImageScale', pos=(3780, 650), title='타일 원래 크기 복원 · 기본 ImageScale')
    g.connect(q[9], 0, restore, 'image')
    g.connect(plan, 3, restore, 'width')
    g.connect(plan, 4, restore, 'height')
    local_comp = g.add('ImageCompositeMasked', pos=(4200, 650), title='타일 소유 마스크 합성 · 기본 노드')
    g.connect(tile_crop, 0, local_comp, 'destination')
    g.connect(restore, 0, local_comp, 'source')
    g.connect(plan, 5, local_comp, 'mask')
    assemble = g.add('MangaInpaintAssemble', {'blend_width':8}, pos=(4620, 650), title='⑨ 전체 좌표 복원 · 경계 완화 · 잔존 원문 검사')
    g.connect(plan, 6, assemble, 'plan')
    g.connect(local_comp, 0, assemble, 'generated')
    prepare = g.add('MangaLetterPrepare', pos=(4620, 50), title='⑩ 번역문과 원문 스타일 연결')
    g.connect(original, 0, prepare, 'original')
    g.connect(target_save, 0, prepare, 'translated_json')
    g.connect(plan, 9, prepare, 'text_pixel_mask')
    typography_values = {'mode':'bubble','line_breaks': 'reflow', 'fit_policy': 'readable', 'respect_bubbles': True,'oriented_fit':True,'bubble_failure_policy':'preserve_review','fit_failure_policy':'preserve_review'}
    typography = g.add('MangaLetterPlan', typography_values, pos=(5040, 50), title='⑪ 실제 말풍선 경계 검사 · 가독 크기 맞춤')
    g.connect(original, 0, typography, 'original')
    g.connect(assemble, 0, typography, 'cleaned')
    g.connect(prepare, 1, typography, 'source_mask')
    g.connect(prepare, 0, typography, 'regions_json')
    g.connect(detector, 0, typography, 'detection_result')
    g.connect(direction, 0, typography, 'page_direction')
    lettering = g.add('MangaLetterApply', pos=(5460, 50), title='⑫ 방향별 식자 · 비례 스타일 · 충돌 검사')
    g.connect(typography, 0, lettering, 'plan')
    save = g.add('SaveImage', {'filename_prefix': 'manga_translator/integrated_tiles'}, (5880, 50), '⑬ 통합 결과 저장')
    g.connect(lettering, 0, save, 'images')
    for destination, slot in ((save, 3), (source_save, 4), (target_save, 5)):
        g.connect(original, slot, destination, 'filename_prefix')
    clean_preview = g.add('PreviewImage', pos=(5040, 650), title='검수 · 식자 직전 전체 배경')
    g.connect(assemble, 0, clean_preview, 'images')
    mask_image = g.add('MaskToImage', pos=(1260, 1050), title='마스크 → 이미지 · 기본 노드')
    g.connect(plan, 8, mask_image, 'mask')
    preview = g.add('PreviewImage', pos=(1260, 1250), title='검수 · 제거 대상 마스크')
    g.connect(mask_image, 0, preview, 'images')
    typography_preview = g.add('PreviewImage', pos=(5460, 650), title='검수 · 원문 프레임과 확장 가능 공간')
    g.connect(typography, 1, typography_preview, 'images')
    ocr_preview = g.add('PreviewImage', pos=(2100, -350), title='검수 · OCR 행/조각 (글자 없으면 원본)')
    g.connect(ocr, 2, ocr_preview, 'images')
    original_crops = g.add('PreviewImage', pos=(1260, -550), title='검수 · OCR 크롭 (글자 없으면 원본)')
    g.connect(crops, 0, original_crops, 'images')
    g.connect(crops, 1, ocr, 'manifest_json')
    g.note('선택한 글자 검출이 0개면 no_text_detected로 기록하고 원본 그대로 저장합니다. OCR/번역/Qwen/식자를 생략합니다.\n다단 본문의 단 사이 여백이 확인되면 OCR 전에 중복 영역을 정리합니다. 행별 OCR과 번역·제거·식자가 같은 명세를 사용합니다.\n검출 0개는 실제 글자 없음의 보증이 아닙니다. 미복구 경계는 주변 문단까지 원본 보존·needs_review로 기록합니다. boundary_policy=strict는 페이지를 중단합니다. 검출/모델 실행 오류는 계속 중단합니다. OCR 품질 재시도 실패는 해당 영역 전체를 원본 보존·검수하며 failure_policy=stop은 중단합니다.\n원문 크기 상한에서 가용 폭을 먼저 사용. 단일 줄바꿈은 자동 재배치하고 빈 줄 문단은 유지합니다.\nline_breaks=preserve로 수동 줄바꿈 유지. strict/세로쓰기에서는 원래 줄바꿈을 유지합니다.\n단색이 확인된 OCR 영역 안에서 누락된 획/잔점을 제거 범위에 보완합니다. 실효 마스크를 미리보기로 확인하세요.\nbubble은 검출된 실제 말풍선 마스크 또는 직접 연결한 내부 마스크에서 확장합니다. 말풍선 소유권이 불확실하면 해당 영역과 겹친 이웃을 원본 복원·검수합니다. bubble_failure_policy=stop은 페이지를 중단합니다. 최소 크기에서도 배치할 수 없으면 연결된 편집 영역을 원본 복원·검수합니다. fit_failure_policy=stop 또는 strict는 중단합니다.\n영역별 폰트·방향·회전·수동 곡선은 식자 계획 노드의 JSON으로 지정합니다.\n효과음·표지 큰 글자 포함 스위치 하나가 검출·영역·마스크를 함께 설정합니다. 기본은 제외. 표지는 포함 설정도 검토하세요.\n긴 가로 행은 빈 열에서 분할. OCR 반복/누락 의심은 patch 변경·선택한 재분할 후 계속 실패하면 원본 보존·검수합니다.\nOCR JSON에 영역별 입력 크기/분할/재시도 진단을 저장합니다. 휴리스틱 통과는 인식 정확도 보증이 아닙니다.\n한 번 실행: 검출→줄별 OCR→번역→타일별 제거→좌표 복원→식자.\nQwen은 512px 코어+128px 문맥 타일만 처리합니다. 단색 배경은 보수적 색 채우기를 먼저 시도합니다.\n이미지 크롭/크기 복원/마스크 확대/타일 합성/미리보기/저장은 기본 노드입니다.\n원문이 거의 그대로인 타일은 식자 전에 중단합니다. 픽셀 검사이며 OCR 품질 보증은 아닙니다.\n마스크 밖 누락 글씨는 자동 삭제되지 않습니다. 마스크 미리보기와 OCR JSON으로 확인하세요.\n반복이 지속되면 확인된 행/열 간격에서 한 번 다시 분할합니다. 실패 입력은 output/manga_translator/ocr_failures에 저장합니다.\nfit_policy=readable은 원문 비율 제한으로 맞지 않을 때 min_font까지 추가 축소합니다. strict/명시적 최소 크기는 유지합니다.\n확인된 말풍선은 실제 마스크 내부로 글자 알파 전체를 제한합니다. 초록색은 안전한 내부 사각형, 빨간색은 원본 보존·검수 영역입니다.\n통합 모의 실행 결과와 실제 GPU 품질 검증은 구분합니다.', (3360, 1150))
    for source, pos, title in [(source_save, (2520, 250), 'OCR 저장 JSON · 미리보기 아무거나'), (target_save, (3360, 250), '번역 저장 JSON · 미리보기 아무거나')]:
        preview = g.add('PreviewAny', pos=pos, title=title)
        g.nodes[preview - 1]['size'] = [400, 260]
        g.nodes[preview - 1]['properties']['cnr_id'] = 'comfy-core'
        g.connect(source, 0, preview, 'source')
    edit_preview = g.add('PreviewImage', pos=(2940, -2100), title='검수 · 초록 교체 / 빨강 원본 보존')
    g.connect(edits, 3, edit_preview, 'images')
    edit_report = g.add('PreviewAny', pos=(3780, -1700), title='교체·보존 이유 · 미리보기 아무거나')
    g.connect(edits, 4, edit_report, 'source')
    g.note('입력 옆 번역문 방향: 가로 / 세로 통일 / 원문 따라 자동. OCR 읽기 방향은 바꾸지 않습니다.\n삭제 전 원문 검수 노드에서 영역별 보존·교체를 선택하고 제거 마스크를 브러시로 보정합니다.\n주황은 제거 범위, 파랑은 원문 획입니다. 지우기는 파란 획을 제외할 수 없습니다.\n수정 뒤 Run하면 제거·식자가 같은 편집 계획을 사용합니다. 원본 보존·미배정 획과 겹친 이웃은 함께 보존합니다.\n편집은 페이지/원본/원문/번역/마스크에 묶이며 변경된 입력에는 자동 적용하지 않습니다.\n폴더에서는 이 페이지 편집만 다시 처리합니다. region_actions_json은 기존 공통 설정이므로 모든 페이지의 같은 ID에 적용됩니다.\n브러시는 지정 편집 사각형 안에서만 동작합니다. 미검출 글자 추가·좌표 수정·자동 효과음 완성은 아닙니다.', (3780, -2100))
    scope = g.add('PrimitiveBoolean', {'value': False}, pos=(0, 950), title='효과음·표지 큰 글자 포함 · 공통 스위치')
    g.nodes[scope - 1]['properties']['cnr_id'] = 'comfy-core'
    for node in (detector, regions, raw_mask):
        g.connect(scope, 0, node, 'include_sfx')
    name = '08-integrated-tiled-cleanup-lettering'
    status = g.add('PreviewAny', pos=(0, -350), title='프로젝트 진행·실패·결과 위치 · 미리보기 아무거나')
    g.nodes[status - 1]['size'] = [420, 300]
    g.nodes[status - 1]['properties']['cnr_id'] = 'comfy-core'
    g.connect(original, 2, status, 'source')
    g.note('폴더 처리도 이 워크플로우 안에서 실행합니다. 입력 노드의 input_mode=폴더 프로젝트로 설정하세요.\ninput_folder는 ComfyUI/input 아래의 원본 폴더, project_name은 결과·재개 기록의 이름입니다.\n한 페이지가 현재 Run에서 검출부터 저장까지 실행됩니다. 다음 페이지는 캔버스가 기본 Run 큐로 이어갑니다.\n입력 노드 안에서 현재 페이지·실행 노드·진행률을 실시간 확인합니다. 기본 중지는 현재 페이지에 적용됩니다.\n연속 처리 중지는 다음 페이지 제출을 멈춥니다. 브라우저를 닫으면 다음 페이지는 자동 실행하지 않습니다.\n설정을 바꾸면 이전 시도를 보존하고 영향받은 단계부터 새 시도로 처리합니다. 실행 중인 이전 작업은 먼저 끝내세요.\n이미지를 한꺼번에 텐서 목록으로 합치지 않습니다. OCR/타일 집계는 페이지마다 독립 실행합니다.', (420, -550))
    g.connect(crops, 3, ocr, 'region_plan_json')
    g.connect(raw_mask,0,crops,'text_pixel_mask')
    # Add read-only observer branches after all legacy IDs. They do not feed
    # inference/cleanup/lettering, and do not change existing project identity.
    inspections=[('detection',regions,0,original,0,None,'검출 · 초록 선택 / 주황 제외'),
                 ('ocr',ocr,1,None,0,None,'OCR · 입력 크기 / 분할 / 품질 검사'),
                 ('cleanup_plan',plan,7,None,0,None,'제거 계획 · 단색 보완 / 타일 / 마스크'),
                 ('cleanup',assemble,1,None,0,None,'제거 결과 · 잔존 원문 검사'),
                 ('letter_plan',typography,2,None,0,(prepare,1),'식자 계획 · 원문 크기 / 색 / 외곽선'),
                 ('letter_render',lettering,2,None,0,(lettering,1),'식자 결과 · 최종 크기 / 줄바꿈 / 알파')]
    for i,(stage,report_node,report_slot,image_node,image_slot,mask_source,title) in enumerate(inspections):
        x=i*850
        inspector=g.add('MangaDebugInspect',{'stage':stage},pos=(x,2050),title='디버그 · '+title)
        g.connect(report_node,report_slot,inspector,'report_json')
        if stage=='detection':g.connect(detector,0,inspector,'detection_result')
        if image_node:g.connect(image_node,image_slot,inspector,'preview_image')
        if mask_source:g.connect(mask_source[0],mask_source[1],inspector,'preview_mask')
        details=g.add('PreviewAny',pos=(x,2250),title=title+' · 미리보기 아무거나')
        g.nodes[details-1]['size']=[780,350]
        g.nodes[details-1]['properties']['cnr_id']='comfy-core'
        g.connect(inspector,0,details,'source')
        if stage in ('detection','letter_plan','letter_render'):
            view=g.add('PreviewImage',pos=(x,2650),title=title+' · 이미지 검수')
            g.connect(inspector,1,view,'images')
    g.note('하단 디버그 행은 검출→OCR→제거 계획→제거 결과→식자 계획→식자 결과 순서입니다.\n미리보기 아무거나는 JSON, 이미지 검수는 선택/제외 박스·원문 스타일 마스크·새 글자 알파를 표시합니다.\n밝은 얼룩은 식자 직전 배경과 새 글자 알파를 비교해 제거 단계/식자 단계 중 어디서 생겼는지 확인하세요.\nOCR issue=null은 정확한 인식 보증이 아닙니다. 제외 후보는 타일 중복을 포함한 추론 관측입니다.\n단계 실행이 실패하면 해당 단계와 후속 미리보기는 나오지 않을 수 있습니다. OCR/번역 실패 진단 파일과 콘솔 오류를 확인하세요.\n이 노드는 읽기 전용이며 모델 설정·편집 허용 범위·완료 판정을 바꾸지 않습니다.',(5100,2050))
    # Checkpoints sit before every observer branch as well as semantic consumers.
    def intercept(source,slot,checkpoint):
        for link in list(g.links):
            if link[1:3]==[source,slot]:
                destination=link[3];field=g.nodes[destination-1]['inputs'][link[4]]['name']
                g.connect(checkpoint,0,destination,field)
        g.connect(source,slot,checkpoint,'value')
        g.connect(original,0,checkpoint,'original')
    detection_cache=g.add('MangaDetectionCheckpoint',pos=(420,450),title='검출 재사용 · 원본+검출 설정')
    intercept(detector,0,detection_cache)
    source_review=g.add('MangaReviewDocument',{'stage':'source'},pos=(2520,-750),title='원문 검수 · 고친 뒤 다시 실행')
    g.connect(collect,0,source_review,'document_json')
    g.connect(original,2,source_review,'page_context_json')
    g.connect(source_review,0,source_save,'translated_json')
    context=g.add('MangaTranslationContext',pos=(2940,-750),title='책 용어집 · 말투 · 확정된 앞 페이지')
    g.connect(source_save,0,context,'ocr_json');g.connect(original,2,context,'project_report')
    g.connect(context,0,translate,'context_json');g.connect(context,2,translate,'target_language')
    translation_cache=g.add('MangaTextCheckpoint',pos=(3360,-750),title='번역 재사용 · 확정 원문과 문맥')
    intercept(translate,0,translation_cache)
    g.connect(context,0,translation_cache,'dependency_json')
    target_review=g.add('MangaReviewDocument',{'stage':'target'},pos=(3780,-750),title='번역 검수 · 수정 / 이 페이지 확정')
    g.connect(translation_cache,0,target_review,'document_json');g.connect(target_review,0,edits,'translated_json')
    g.connect(original,2,target_review,'page_context_json')
    cleanup_cache=g.add('MangaCleanupCheckpoint',pos=(4620,1100),title='지운 배경 재사용 · 실효 마스크+Qwen 설정')
    intercept(assemble,0,cleanup_cache);g.connect(plan,6,cleanup_cache,'cleanup_plan')
    g.connect(assemble,1,cleanup_cache,'report_json')
    # Reading the cached report must not pull the image model back into execution.
    for link in list(g.links):
        if link[1:3]==[assemble,1] and link[3]!=cleanup_cache:
            field=g.nodes[link[3]-1]['inputs'][link[4]]['name'];g.connect(cleanup_cache,1,link[3],field)
    for i,node in enumerate((detection_cache,translation_cache,cleanup_cache,context)):
        details=g.add('PreviewAny',pos=(i*850,3150),title='단계 재사용 / 문맥 · 미리보기 아무거나')
        g.connect(node,1,details,'source');g.nodes[details-1]['size']=[780,300]
    for node in (detection_cache,source_review,context,translation_cache,target_review,cleanup_cache,ocr_model):
        g.nodes[node-1]['size']=[420,520 if node in (source_review,target_review) else 380 if node==context else 270]
    g.note('원문/번역 검수 노드에서 텍스트를 고친 뒤 Run합니다. 수정은 페이지 revision별로 워크플로우에 저장됩니다.\n번역 확정은 사람이 확인한 페이지에만 사용하세요. 용어집과 확정된 이전 페이지를 번역 문맥으로 보냅니다.\n재사용 노드의 reuse=검증된 저장 결과, refresh=다시 계산, off=저장 없이 계산. 폰트/방향 수정은 검출/OCR/번역을 유지합니다.\n파란 다각형은 회전한 식자 프레임입니다. 제목/본문은 검증된 글줄 높이 차이가 있을 때 분리됩니다.\nOCR 엔진 선택은 정확도를 보장하지 않습니다. Manga OCR은 일본어용이며 자동 설치는 모델 파일에 한정합니다.',(0,3550))
    g.connect(original,2,edits,'page_context_json')
    g.save(name)
    for suffix in ('.json', '.api.json'):
        path = ROOT / 'lettering/example_workflows' / (name + suffix)
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
    return g
if __name__ == '__main__':
    from argparse import ArgumentParser
    ArgumentParser(description=__doc__).parse_args()
    build()
