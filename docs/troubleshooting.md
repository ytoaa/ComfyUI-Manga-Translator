# 문제 해결과 중간 결과

[목차](README.md) · [상태·재시도](usage.md) · [설정](configuration.md)

## 먼저 구분할 것

`completed`는 실행 완료, `replace`는 편집 허용, `coverage=1.0`은 추적한 조각에 대한 기하 지지, `issue=null`은 현재 OCR 휴리스틱 통과입니다. 모두 의미 정확도나 페이지 전체 검출 성공과 다릅니다.

`regions=[]`, `ocr_skipped=true`, `translation_skipped=true`이면 그 실행에서 번역한 영역이 없습니다. `preserved_region_ids`와 `review_reason`을 확인합니다. 기하 보존 결과를 번역 완료나 빈 페이지로 판단하지 않습니다.

## 오류·검수 사유

| 증상 / 코드 | 확인과 대응 |
| --- | --- |
| no_text_detected_not_verified_blank | 선택 검출 0개. 원본·선택/제외 후보를 확인합니다. 글자가 없는 페이지로 확정한 것이 아닙니다. |
| excluded_onomatopoeia_present | 효과음/표지 글자가 제외됨. 후보 위치를 보고 포함 스위치를 결정합니다. 관측 개수를 고유 글줄 수로 세지 않습니다. |
| unresolved_detection_boundary | 복구 불가 검출 경계. 기본 정책은 접촉 영역 원본 보존·검수, strict는 중단입니다. |
| unverified_ocr_geometry / source_crop_cuts_glyphs | 원본 문맥 복구·행 검증이 실패함. ocr_geometry_recovery와 ocr_geometry_review의 원래/문맥 좌표와 사유를 확인합니다. |
| ocr_unrecognized_span | 모델이 명시적으로 미인식 표시를 출력함. 표시를 지우거나 검사만 끄지 말고 실제 입력 크롭과 행 경계를 봅니다. |
| short_repetition / ocr_repetition_loop | 같은 문자열 반복. 잘못 자른 입력·작은 글자·모델 오독을 구분합니다. 토큰/패치 증가만으로 해결되지 않을 수 있습니다. |
| ocr_token_limit | EOS/PAD 없이 한도 도달. 문장 밀도·줄 분할과 실제 생성 기록을 확인합니다. |
| possible_omission | 누락 의심 휴리스틱. 입력 글자 수와 실제 원문을 대조합니다. 정답 판정이 아닙니다. |
| invalid/incomplete JSON | 번역 응답 원문·종료 사유·response_format을 확인합니다. finish_reason=stop만으로 완전한 JSON이라고 판단하지 않습니다. |
| Font lacks requested characters | 선택 폰트·동봉 대체 폰트의 실제 글리프 범위를 확인합니다. 누락 문자를 삭제하지 않습니다. |
| no safe lettering fit / collision | 보고된 영역의 번역·방향·줄바꿈·허용 공간을 확인합니다. 프레임만 무작정 늘리면 그림/이웃 침범이 생길 수 있습니다. |
| Project model/workflow settings changed | 같은 프로젝트의 처리 설정이 달라짐. 이전 결과를 보존하고 새 project_name으로 실행합니다. |
| 이전 prompt가 큐·이력에 없음 | 실행 신원 미확정으로 중지. 같은 캔버스에서 명시적 실패 재시도로 큐·이력을 재대조합니다. 상태 JSON만 수동으로 지우지 않습니다. |

v0.6.3에서 보존된 needs_review 페이지는 업데이트 뒤 **실패·검수 재시도**로 다시 선택합니다. 기존 실패 재시도는 failed만 선택합니다.

## 진단 파일

`ComfyUI/output/manga_translator/` 아래:

| 폴더 | 내용 |
| --- | --- |
| detection_failures | 경계 문맥 PNG·검출 시도 JSON |
| ocr_failures | 원본/실패 입력 PNG·옵션·재시도·거부 원문 JSON |
| translation_failures | 실패 응답·종료 사유·토큰·계약 오류 JSON |
| workflow_projects/<project_name> | 페이지별 시도 상태·수집 결과·요약·export |

번역 진단에는 API 키·인증 헤더를 저장하지 않습니다. 원문·응답 내용은 들어갈 수 있으므로 공유 전에 확인합니다. 진단 파일 저장 실패는 원래 처리 오류를 대체하지 않습니다.

## 미리보기 아무거나 연결

새 08에는 OCR/번역 JSON과 하단 단계 디버그가 연결되어 있습니다. 기존 캔버스에 추가할 때는 다음 **STRING 보고서**를 `PreviewAny.source`에 연결합니다.

| 노드 / 출력 | 확인할 정보 |
| --- | --- |
| MangaRegionCrops.manifest_json | 크롭·행 좌표, ocr_geometry_recovery/ocr_geometry_review, 원본 보존 |
| MangaCollectOCR.ocr_json | 영역 ID별 source와 OCR 진단 |
| MangaTranslate.translated_json | 같은 ID의 source/target, 번역 정규화 진단 |
| MangaInpaintPlan.plan_report | 실효 마스크·타일·단색 보완 |
| MangaInpaintAssemble.cleanup_report | 합성·잔존 원문 검사 |
| MangaLetterPlan.계획_보고서 | 방향·원문 크기 추정·수평 작업 범위·회전·스타일 |
| MangaLetterApply.식자_보고서 | 실제 글자 크기·줄바꿈·알파·사용한 배치 단계 |

디버그 노드 `MangaDebugInspect`는 읽기 전용입니다. `단계_디버그_JSON` → 미리보기 아무거나, `단계_검수_이미지` → 이미지 미리보기에 연결합니다. 검출 stage에는 원본·영역 JSON·검출 결과가 함께 필요합니다. 내부 plan 객체나 마스크 RLE 전체보다 보고서 STRING을 연결합니다.

오류가 난 단계와 후속 미리보기는 실행되지 않을 수 있습니다. 그 경우 콘솔과 저장된 실패 진단을 봅니다. 서버 이력이 지워지면 과거 미리보기 이력도 유지되지 않을 수 있습니다.
