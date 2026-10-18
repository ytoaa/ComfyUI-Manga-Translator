# 단계별 디버그 v0.5.2

## 이번 프로필 카드 사례에서 확인한 것

사용자가 제공한 JSON에서 input_regions=1, resolved_regions=1, grouped_lines=0이다. 문단 병합이 여러 항목을 합친 것이 아니라 경계 복구의 native_centered 재검출이 54.13,947.15–658,1160px의 큰 text 박스 한 개를 반환했다. OCR은 612×221px 크롭을 한 작업으로 읽고 400×160px 모델 입력으로 축소했다. line_count=1, chunk_count=1, issue=null이며 supported_projection_bands=1이다. MY PROFILE 오독과 서번트 부분의 반복이 원문 JSON에 이미 들어 있다. 번역은 그 원문을 전달받았으며 page_edit_plan은 r1 하나를 replace로 승인했다. 이 승인은 인식 정확도 판정이 아니다.

include_sfx=false에서 onomatopoeia 관측 31회가 제외됐다. 이 수는 타일/복구 중복을 포함한다. 기존 JSON에는 제외 위치가 없으므로 하단 스킬 설명이 전부 효과음으로 오분류됐다고 확정할 수 없다. 원본·결과의 실제 픽셀 차이는 카드 상단 edit_bbox에 한정되고 하단 스킬 부분에는 없다. 밝은 얼룩은 식자 직전 배경과 글자 알파·외곽선 수치를 비교해야 제거와 식자 중 발생 단계를 구분할 수 있다.

이번 릴리스는 이 사례를 분석할 관측 경로를 추가한다. 자동 기울기 보정, OCR 정확도 향상, 카드 항목 자동 분리나 외곽선 추정 개선을 구현한 릴리스는 아니다.

## 워크플로우에서 보기

코드를 업데이트하고 ComfyUI를 재시작한 뒤 새 통합 08 JSON을 가져온다. 입력과 모델 설정을 확인하고 워크플로우 하단의 디버그 행을 본다. 6개 단계 노드의 단계_디버그_JSON은 각각 기본 PreviewAny(미리보기 아무거나)에 연결되어 있다.

| 단계 | 확인할 정보 | 함께 볼 이미지 |
| --- | --- | --- |
| detection | 선택한 논리 영역, 분류별 원시 관측 수, 효과음 제외 후보의 점수·원본 좌표·추론 단계 | 초록=선택 영역, 주황=제외 후보 |
| ocr | 크롭 크기, 모델 입력 크기, 줄/조각 수, 재시도, issue와 quality_evidence | 기존 OCR 크롭 및 OCR 행/조각 미리보기 |
| cleanup_plan | 단색 보완, 타일 박스·개수, 원문/제거 마스크 계획 | 기존 제거 대상 마스크 |
| cleanup | 타일 합성·잔존 원문 검사 | 기존 식자 직전 전체 배경 |
| letter_plan | 원문 크기 추정, 방향, 배치, style_analysis의 색·outline_width·sample_pixels·texture_std, rotation/shear/bend | 원문 스타일 참조 마스크 |
| letter_render | 실제 폰트 크기, 줄바꿈, 축소 비율, 사용한 외곽선과 배치 결과 | 새 글자 알파(흰색=새 글자/효과가 차지하는 범위) |

미리보기 아무거나는 STRING JSON을 받는다. 내부 MANGA_LETTER_PLAN 객체나 RLE 마스크 전체를 연결하는 대신 보고서 출력을 연결한다. OCR은 크롭별로 실행되므로 같은 미리보기 노드에 여러 보고서가 표시될 수 있다. 마스크 미리보기는 검사용 흑백 복제이며 원본이나 제거 마스크를 수정하지 않는다.

## 기존 캔버스에 직접 연결

새 MangaDebugInspect(단계 디버그) 노드의 stage를 고르고 다음을 연결한다. report_json은 forceInput STRING이다. 단계_디버그_JSON → 미리보기 아무거나.source, 단계_검수_이미지 → 이미지 미리보기.images에 연결한다.

- detection: 검출 영역 정리의 layout_json → report_json, 글자 위치 검출의 result → detection_result, 원본 → preview_image.
- ocr: MangaOCRAdaptive.ocr_report_json → report_json.
- cleanup_plan: MangaInpaintPlan.plan_report → report_json.
- cleanup: MangaInpaintAssemble.cleanup_report → report_json.
- letter_plan: MangaLetterPlan.계획_보고서 → report_json, MangaLetterPrepare.원문_스타일_참조_마스크 → preview_mask.
- letter_render: MangaLetterApply.식자_보고서 → report_json, MangaLetterApply.새_글자_알파 → preview_mask.

보고서 STRING은 디버그 노드를 거치지 않고 바로 미리보기 아무거나에 연결해도 된다. 새 노드는 단계와 관측 범위를 공통 형식으로 표시한다.

## 호환성·한계

기존 처리 노드 ID와 연결은 유지한다. 새 디버그 노드와 그 PreviewAny/PreviewImage만으로 끝나는 가지를 프로젝트 fingerprint에서 제외하므로 v0.5.1 프로젝트 이름을 그대로 사용할 수 있다. 디버그 출력이 실제 처리 노드의 입력으로 연결되면 이 예외를 적용하지 않는다. 실제 이전 릴리스 API 그래프와 새 그래프의 fingerprint 일치도 확인한다.

제외 후보는 마스크를 복제하지 않고 좌표·분류·점수·단계만 최대 256회 관측까지 보관한다. 제외 전체 수와 저장하지 못한 수를 별도로 보고하며 중복을 고유 영역 수로 세지 않는다. 전체·상세 타일·복구 모두 원본 페이지 좌표로 복원한다. 이전 detector 결과는 수만 있으므로 주황 위치는 새 검출 실행이 필요하다. 새로 만드는 검출 오버레이와 마스크 검수는 긴 변 2048px 이하의 샘플로 제한하며 JSON의 좌표는 계속 원본 해상도다.

이 미리보기들은 각 단계가 정상 반환한 보고서다. 한 단계나 앞 단계가 실패하면 해당/후속 미리보기는 나오지 않을 수 있고, 다른 가지가 먼저 중단되어 이전 단계의 별도 미리보기도 실행되지 않을 수 있다. OCR/번역 실패는 기존 진단 파일과 콘솔을 사용한다. 서버 이력이 지워지면 미리보기 이력도 유지되지 않으며 이 릴리스에서 별도 디버그 아카이브를 자동 생성하지 않는다.

issue=null, coverage=1.0, replace, completed는 각각 검사 통과·경계 지지·편집 허용·실행 완료를 뜻한다. OCR/번역 정확도나 빠진 글자가 없음을 보증하지 않는다. 효과음 포함 스위치를 켜면 그림 속 장식 글자도 대상이 될 수 있으므로 제외 오분류를 확인하지 않은 채 일괄 해결책으로 사용하지 않는다.
