# 검증 범위

## 2026-10-18 KST v0.6.1 일반 텍스트·미인식 표시

- 실제 첨부 JSON에서 OCR 원문에 `<br>`가 없고 개행이 있으며 번역문에 `<br>` 5개가 새로 생겼음을 확인했다. `<UNK_SPAN>`은 OCR 원문부터 존재한다. 사용자 자료와 이미지 자체는 Git에 넣지 않는다.
- 전체 CPU 회귀 **600 passed in 129.24s**. 번역기가 추가한 break 태그의 개행 변환과 원문 응답·개수 진단, 원문에 있는 태그/수동 override/일반 부등호·다른 태그·엔티티 보존, break-only 응답 거부를 검사했다. 일반 HTML 정제나 불완전 JSON 복구를 추가하지 않았다.
- 명시적 미인식 표시의 OCR 패치 재시도 성공·실패를 quality_guard의 양쪽 설정에서 검사했다. 실패 원문과 시도 기록 보존, 오래된 OCR 입력의 API 호출 전 거부, 검수된 override 허용, 번역 응답의 잘못된 표시 재생성 1회 제한과 실패 진단, 식자에서의 마지막 거부를 포함한다.
- 그래프·위젯 변경은 없다. 기존 네이티브 폴더 재개/재시도·편집 보존·통합 모의 실행·패키지 설치 회귀도 통과했다. 완료 페이지의 자동 재처리나 실제 GPU 재추론은 수행하지 않았다. 이 검증은 문자의 표시 규약과 실패 경로에 관한 것이며 카드의 남은 오독·효과음 누락·배경 복원 정확도 검증이 아니다. [사용법과 예외](docs/plain-text-v0.6.1.md).

## 2026-10-18 KST v0.6.0 회전 OCR·제거 경계

- 새 실제 자료에서 Skill1/2의 일부 좌표가 제외된 onomatopoeia 후보에 있음을 확인했다. 060258에는 한국어 식자 전부터 밝은 띠가 있으므로 제거/배경 복원 단계의 문제다. 그림만으로 단색 채우기와 Qwen 생성 중 어느 경로인지 확정하지 않는다. source의 오독/반복은 번역 전부터 존재한다.
- 최종 전체 CPU 회귀 **587 passed in 128.26s**. 실제 동봉 폰트로 만든 -17°, -8°, +13.5°, +21° 시험 글자에서 각도 오차 1° 이하 및 3행 분할, 수평/빈/세로/마스크 부재의 기존 경로 유지, 계획 크기/각도/좌표계/행 틈 변조 거부, 극단적 종횡비의 회전 전 래스터 한도를 검사했다.
- 원본 크롭→계획→모의 OCR→집계→식자 준비→실제 CPU 폰트 렌더링에서 같은 각도·좌표계를 전달하고 원문 크기 상한을 측정함을 검사했다. 모의 OCR은 실제 모델의 인식 정확도 검증이 아니다. 기존 반복/토큰/누락 검사는 유지한다.
- 경계 완화는 마스크 밖 픽셀 동일성, 검출 원문 픽셀의 제거 강도 유지, 타일 소유 경계에 fade를 만들지 않음, 단색 채우기의 lazy 모델 우회 유지로 검증했다. 전체 mask의 좌표 배열 대신 축 투영을 쓰고 EDT는 문맥을 포함한 512px 코어로 제한한다. 전체 회귀에는 기존 편집/보존·말풍선·폴더·실패 재시도·빈 페이지·패키지 및 GUI/API 위젯 검사가 포함된다.
- 첨부 612×221px 크롭의 변경 픽셀을 지지 범위로 사용하는 별도 기하 분석에서는 -13.5°, 집중도 비 1.4507, 네 조각을 관측했다. 실제 RF-DETR 원문 마스크를 다시 얻은 것이 아니며 이 수치를 실제 Hayai 개선 결과로 부르지 않는다. 사용자 이미지와 지지 범위는 Git에 넣지 않는다.
- 새 08은 auto_deskew=true와 원문 마스크 입력, blend_width=8을 사용한다. 기존 생략 입력 false/0은 원래 동작을 유지한다. 처리 fingerprint가 달라 폴더 프로젝트는 새 project_name으로 실행한다. 일부 효과음 오분류, 카드 항목의 독립 편집 영역 재구성, 사라진 배경 무늬 복원과 실제 번역 정확도는 해결되었다고 주장하지 않는다. [설정·좌표·제한](docs/oriented-ocr-v0.6.0.md).

## 2026-10-18 KST v0.5.2 캔버스 단계별 진단

- 실제 프로필 카드 JSON은 input/resolved=1, grouped_lines=0이다. 검출 복구의 큰 한 영역과 612×221→400×160px, line/chunk=1, issue=null을 확인했다. 오독·반복은 OCR 원문에 이미 있고 번역은 이를 입력받았다. 효과음 제외 31회는 중복 포함 관측이며 이전 기록에는 위치가 없어 스킬 설명의 정확한 누락 원인을 확정하지 않는다.
- 전체 CPU 회귀 **570 passed in 45.89s**. 검출 좌표 복원, 효과음 후보 256개 저장 제한과 전체/생략 수 분리, 선택/제외 오버레이, 큰 페이지 검수 크기 제한, 읽기 전용 마스크·원본 보존, OCR null issue의 의미 범위, 무효/과대 JSON 거부를 검사했다.
- 통합 08 API 모의 실행에서 단계 디버그 6개와 연결된 PreviewAny 6개(기존 4개를 합쳐 10개), 검출·스타일 마스크·새 글자 알파의 PreviewImage 연결을 검사했다. OCR 크롭별 보고서는 동일 PreviewAny 노드에 여러 실행 결과로 표시된다. 전체 회귀에 네이티브 폴더·중지/재시도, GUI 위젯·재생성 일치, 패키지 설치 import를 포함했다.
- 실제 이전 v0.5.1 API 그래프와 새 그래프의 fingerprint가 c91207be40ba38853de17552cd12f3a099d308725054a35c70230880a3b2b1c9로 동일함을 확인했다. 읽기 전용 debug→native preview 가지를 제외하며 debug 출력이 실제 처리 입력에 연결되면 제외하지 않는 회귀도 검사했다. 기존 프로젝트를 새로 만들지 않고 디버그 화면을 추가할 수 있다.
- 새로운 진단 경로의 검증이며, 사용자 카드의 모델 재추론·OCR/배치 품질 개선 결과나 실제 ComfyUI 브라우저 조작으로 부르지 않는다. 단계 실패 시 별도 미리보기 가지가 실행되지 않을 수 있고, 영구적인 별도 디버그 아카이브는 만들지 않는다. [포트별 사용법과 한계](docs/debug-inspection-v0.5.2.md).

## 2026-10-18 KST v0.5.1 번역 구조화 출력·실패 응답 진단

- 사용자의 v0.5.0 실제 보고서는 completed 10 / needs_review 5 / unchanged_blank 2 / failed 1이다. 마지막 실패는 11_11.jpg의 MangaTranslate JSON 파싱이며 stop / 141 tokens / 304 characters였다. 실제 응답 원문이 없어 정확한 문법 오류 원인이나 토큰 부족을 확정하지 않는다.
- 전체 CPU 회귀 **559 passed in 49.49s**. 실제 모의 HTTP 전송에 json_schema가 포함됨, 페이지 요청 ID·개수 제약, 클라이언트 중복/누락 검사 유지, 한 번만 재생성, json_object/prompt_only 명시 선택, HTTP 오류 시 자동 모드 강등 금지를 검사했다.
- 두 거부 응답의 원문·종료 사유·토큰 수·계약 오류 진단, 200,000자 답변 제한, 자격 정보/헤더/추론 필드 제외, 파일 저장 실패가 원래 오류를 대체하지 않음을 검사했다. 완전한 JSON만 허용하며 불완전한 문자열 복구나 부분 번역 채택은 하지 않는다.
- 기존 v0.5.0 그래프의 생략된 optional 모드와 새 기본값의 fingerprint 일치를 검사했다. 같은 프로젝트에 완료 1장/번역 실패 1장을 만든 뒤 새 그래프로 네이티브 실패 재시도하여 실패 페이지만 선택되는 것을 확인했다. GUI/API 예제 위젯과 패키지 import 계약도 전체 회귀에 포함된다.
- 실제 사용자 번역 서버와 18페이지 GPU 재실행은 수행하지 않았다. 검수 상태 5페이지의 경계·미검출·효과음 제외 문제나 번역 의미 정확도가 해결되었다고 주장하지 않는다. [요청 모드와 재시도 방법](docs/translation-protocol-v0.5.1.md).

## 2026-10-18 KST v0.5.0 페이지 편집 계약·통일 방향

- 최종 전체 회귀: **549 passed**. 원문 보존 전 제거 제외, 미배정 획과 겹친 영역의 보존, 오래된 원문/번역/좌표/digest·비정수 좌표 거부, 빈 페이지 우회, 큰 원본 보존 영역의 별도 예산, 폴더의 실제 보존 픽셀 비교를 검사했다.
- 통합 08 전체 API 그래프는 실제 커스텀 노드와 모델 응답 대역으로 실행했다. OCR/번역 실패 시 제거·최종 저장 미실행, 새 편집 명세가 제거·식자에 동일하게 전달됨, 기본 이미지/JSON 미리보기와 네이티브 폴더 실행·중지·재개를 검증했다. 검출·OCR·번역·Qwen 실제 추론 결과로 부르지 않는다.
- 가로·세로 원문이 섞인 시험 이미지를 CPU의 실제 폰트 렌더러로 가로 통일/세로 통일하여 렌더링하고 육안 확인했다. 가로/세로 통일이 영역별 반대 방향을 덮어쓰는 경우, 자동 모드에서 영역별 방향을 유지하는 경우를 검사했다.
- `번역문 방향`은 별도 제어 노드다. 그래프 의존성 검사에서 이 설정이 검출·OCR·번역·제거의 조상이 아님을 확인했다. 방향 변경이 앞 단계의 캐시 의존성에 들어가지 않으며, 원문 OCR 방향은 변경하지 않는다.
- GUI/API 예제 재생성 일치, 위젯 직렬화, 설치 패키지의 새 노드 import, Node.js 캔버스 이벤트/큐 계약을 검사했다. 실제 DGX에서 새 08의 전체 모델 추론·18페이지 품질 비교나 실제 브라우저 GUI 조작은 이번 검증에 포함하지 않았다.
- 패키지는 ZIP 무결성과 파일별 SHA256을 확인한다. 새 그래프는 처리 fingerprint가 달라 기존 프로젝트를 덮어쓰지 않으며 새 `project_name`으로 실행한다. 기존 시도와 결과는 유지한다.
- 조사와 변경의 범위·설정 방법: [페이지 편집 계획 v0.5.0](docs/page-edit-plan-v0.5.0.md). 이번 릴리스는 인식 정확도 향상을 입증하는 릴리스가 아니다.

## 2026-10-18 KST v0.4.4 실제 점 나열 OCR 오류

- 실제 v0.4.3 결과는 completed 10 / needs_review 5 / unchanged_blank 2 / failed 1이었다. 남은 08의 34×268px OCR PNG와 진단 JSON을 대조해 원본 점 9개, Hayai 결과 길이 15/12, 최종 거부 문자열 `・` 12개를 확인했다. 모델의 개수 증식과 품질 검사의 실제 반복 기호 거부를 구분했다.
- 제한된 단일 축의 점 기하 판독을 quality_guard 경로에 추가했다. 전체 성분의 둥근 모양·채움·크기·정렬·간격·경계 여유와 배경 조건이 맞는 3~24개만 관측 개수로 기록한다. 일반 문자 반복, 구멍/사각형/선·잡점·혼합 입력·잘림·불규칙 입력·약한 대비와 개수 한도 거부를 검사했다. 원본 9개와 다른 12개 문자열도 계속 거부한다.
- 검증된 점은 번역에서 원래 ID·개수를 유지하고 모델 요청에서 제외한다. 식자 준비 명세는 원본 점의 픽셀 복원을 지정한다. 통합/기본 식자에서 원본 픽셀 동일성과 새 alpha 0, 통합 식자의 보존 영역 침범 금지를 유지한다. 수동 번역 override가 바꾸면 기존 식자 경로를 사용한다.
- 첨부 실제 PNG를 CPU 노드의 OCR→집계→번역→제거→식자에 넣어 9개 판독, Hayai 생성 호출 0회, 번역 API 0회, 최종 원본 픽셀 동일함을 확인했다. 제거 입력/배경은 CPU 검사이며 전체 페이지의 실제 모델 GPU 재추론 결과는 아니다. 첨부 원본과 진단은 Git에 포함하지 않는다.
- 전체 CPU 회귀 **520 passed in 43.77s**. 점 처리 관련 21개 검사와 기존 OCR 반복/누락·번역 계약·식자·프로젝트/캔버스·패키지 회귀를 통과했다. 통합 08 그래프와 처리 fingerprint는 유지한다. 같은 프로젝트의 실패 재시도는 남은 08만 새 시도로 처리하며 실제 페이지 후속 단계의 결과는 재시도 후 확인한다.

## 2026-10-18 KST v0.4.3 미확정 경계의 원본 보존

- 실제 v0.4.2 실행은 completed 10 / needs_review 2 / unchanged_blank 2 / failed 4였다. 사용자가 제공한 4개 JSON과 1152px 주변 PNG를 page 좌표로 대조했다. 04/09/11의 해당 좌표는 얼굴·귀의 그림 선, 08은 text로 분류된 효과음 일부였다. 첨부 이미지를 저장소에 포함하지 않는다.
- 통합 08과 캔버스 노드의 기본 preserve_review는 재검출 후에도 미복구인 조각과 접촉 문단을 보존하고 결과를 needs_review로 기록한다. strict의 기존 페이지 중단과 함수 단위 기본 strict를 유지한다. 점수 임계값·98% support 조건을 바꾸거나 복구 성공으로 판정하지 않는다.
- 네 보고 좌표의 기하 대역, 접촉 문단의 연쇄 제외, 미확정 마스크 제거, GrowMask 뒤 보호, 단색 잉크 보완 뒤 원본 복원, 실제 폰트 alpha의 보호 영역 침범 거부를 검사했다. OCR crop/edit 여백이 보호 영역에 걸릴 때도 중단한다. 원문→번역→식자 보호 명세와 폴더 수집 시 실제 PNG 픽셀을 검사하며, 명세 변경·픽셀 변경은 수집에서 거부한다.
- 제공 통합 08 전체 모의 실행에서 미복구 경계가 있는 페이지도 확인된 2개 영역의 OCR/번역/저장을 실행하고, 보류된 문단 전체의 원본 픽셀을 유지한다. 혼합 폴더 모의 실행은 completed 4 / failed 4 / needs_review 2 / unchanged_blank 1이며 재개 시 추가 제출 0회다. OCR·제거·식자·손상 입력 실패 격리와 strict에서 OCR 전 중단을 유지한다.
- 기존 main의 08 API와 새 08의 처리 fingerprint는 모두 `4bc14a3b227714570d22a5c46c43c070d60e5dd7b52f35524a6aace3a9adf2f3`이다. 선택값 생략/기본값 동등성을 검사하고 strict는 다른 설정으로 취급한다. 같은 기존 프로젝트의 실패 4페이지만 재시도할 수 있다.
- 최종 전체 CPU 회귀 **499 passed in 43.47s**, 보호 관련 21개 검사를 통과했다. 실제 첨부 픽셀의 시각 진단과 CPU 회귀이며, 이 네 원본 전체의 DGX RF-DETR/Hayai/Qwen 재추론을 수행한 결과는 아니다. needs_review 결과는 실제 실행 후 제외 범위·문장을 검수해야 한다.

## 2026-10-18 KST v0.4.2 실제 폴더의 8페이지 실패 경로 보완

- 제공 보고서는 completed 6, needs_review 2, unchanged_blank 2, failed 8이었다. 경계 복구 5건(04/08/09/11/14), 일본어 글리프 미지원 2건(06/17), 중첩 말풍선 1건(12)을 분리했다. 실제 8개 원본 이미지나 모델 출력은 제공되지 않았으므로 모든 페이지가 해결됐다고 판정하지 않는다.
- 경계 복구에 원래 모델 크기의 중심/방향 이동 정사각 문맥을 우선 추가했다. 로그의 다섯 bbox/edge를 사용한 4800×6030 기하 대역에서 완전 검출이 반환될 때 페이지 좌표와 coverage가 보존되는지 확인했다. 불완전 지지·복구 예산 초과 시 중단은 유지한다. 미복구 진단에는 bounded PNG와 재검출 JSON을 남긴다.
- 실제 글리프를 포함한 OFL 대체 폰트를 동봉했다. 한글/`ー`/`グルン`/한자가 섞인 문장을 Pillow로 렌더링하고 원래 Unicode·대체 보고를 확인했다. 기존 한글 폰트 선택과 미지원 emoji 오류도 유지한다. 폰트 원본 Git blob·SHA256, 파생 SHA256, 정적 생성/이름 변경 도구와 OFL을 보존한다.
- 중첩 마스크가 공통으로 허용하는 연결 내부가 원문 잉크 95% 이상을 포함할 때만 식자한다. 실제 렌더 alpha가 두 마스크 밖에 없는지 검사한다. 각 마스크가 잉크 95%씩 포함하나 교집합은 90%인 경우와 가독 크기에서 공통 공간이 부족한 경우는 계속 실패한다.
- 최종 전체 CPU 회귀 **477 passed in 92.78s**. 관련 경계·말풍선·식자 92개 재현/회귀에 더해 진단 JSON/PNG 저장과 저장 실패 시 원래 오류 보존도 확인했다. 모델 없는 기하 대역과 실제 CPU 폰트 렌더 검증이며 DGX RF-DETR/Hayai/Qwen 재추론 결과는 아니다.
- 통합 08 연결/설정은 바꾸지 않았다. 같은 프로젝트의 실패 재시도는 완료/검수/원본 유지 10페이지를 보존하고 실패 8페이지에만 새 시도를 만든다. 02 무검출과 18 효과음 제외를 자동 번역 완료로 바꾸지 않는다.

## 2026-10-18 KST v0.4.1 복구 동작 기록과 네이티브 미확정 시도 재시도

- 반복된 paused 보고서를 조사해, v0.4.0의 수동 Run이 복구 단계에서 막히면 기존 run의 `requested_action`을 그대로 표시하는 결함을 확인했다. 따라서 그 값만으로 사용자의 실제 선택을 판정한 안내는 부정확했다. 수동 Run의 동작·ID를 복구 전에 기록하고, 차단 시 재시도 선택 여부와 이전/현재 prompt·프로세스 시각을 `recovery_check`에 보존한다.
- 캔버스의 명시적 `실패 재시도`는 프로세스 재시작 증명 외에 현재 네이티브 실행 소유권을 근거로 미확정 시도를 정리할 수 있다. 현재 prompt가 실제 실행 큐에서 폴더 입력/실패 재시도 노드를 실행 중이고, 이전 prompt ID와 시도 토큰이 실행·대기 큐 모두에 없으며 추가 이력/큐 확인도 통과해야 한다. 이전 성공 여부는 추정하지 않고 `native_queue_outcome_lost`로 기록하며 이전 입력/시도 파일을 보존한다.
- 재현 검사는 보고된 3번째 시도와 시각을 사용해 OS 프로세스 시계가 없어도 현재 네이티브 실행으로 4번째 시도를 반환함을 확인한다. 일반 재개, 대기 중인 제어 작업, 이전 실행/대기 작업과 토큰 일치 작업은 재시도 근거가 되지 않는다. 이전 start 보고 뒤 실패 재시도를 선택했으나 또 차단되는 경우의 action/run ID/진단도 검사한다.
- 실제 프런트엔드 1.53.10에서 `실패 재시도` 선택을 직렬화해 일반 Run으로 제출했다. 프로세스 시계를 명시적 대역으로 제거한 상태에서 실제 네이티브 큐 소유권으로 `native_queue_outcome_lost` 복구·3→4번째 시도와 3페이지의 완료 2/실패 1을 확인했다. 모델과 실행 스케줄러는 기존 검증 대역이며 실제 DGX 모델 추론은 아니다.
- CPU 전체 회귀 **463 passed in 67.76s**. 관련 복구/캔버스 검사 40개와 프런트엔드 이벤트 계약 검사를 통과했다.
- 빠른 페이지 완료가 기존 `app.queuePrompt`의 UI 갱신 중에 발생하는 재진입 경쟁도 보완했다. 기존 제출 처리가 끝난 뒤 다음 기본 Run을 한 번만 제출하며, 대기 중 연속 중지 요청을 반영한다. 실제 브라우저에서 3→4 복구 후 중지·재개·품질 실패 격리와 숨은 자식 0건을 다시 확인했다.
- 통합 워크플로우 연결은 바꾸지 않았다. 이미 v0.4.0의 새 08을 가져온 경우 코드 업데이트·서버 재시작·브라우저 새로고침이 필요하다. 실제 DGX 모델 추론을 수행한 결과는 아니다.

## 2026-10-17 v0.4.0 현재 캔버스의 페이지 실행과 실시간 상태

- 기본 폴더 입력이 실제 페이지 이미지·마스크·시도별 저장 경로를 현재 prompt에 반환한다. 서버 프로젝트 작업자와 자식 prompt 제출 경로를 호출하지 않는다. 첫 노드 UI와 기본 PreviewAny가 페이지 집계를 표시하고, 네이티브 executing/progress 이벤트로 현재 단계를 갱신한다. 다음 페이지는 브라우저가 실제 완료 이력을 확인한 뒤 일반 `app.queuePrompt(0, 1)`로 제출한다.
- 실제 ComfyUI 프런트엔드 **1.53.10**과 Chromium에서 새 08 가져오기, 헬퍼 위젯 직렬화 제외, 실제 노드 강조 이벤트/진행, 3페이지의 `completed=2, failed=1`, 일반 prompt 정확히 3건·숨은 자식 0건, 완료 페이지 재실행 없음, 현재 페이지 이후 중지·재개, 최종 상태 갱신을 확인했다. 브라우저 pageerror는 0건이었다.
- 브라우저 검증 서버는 상류 PromptQueue 클래스와 `/prompt` 함수 원문을 사용했다. 전체 검증기·실행 스케줄러·모델은 명시적 대역이며 CPU 커스텀 노드, 실제 기록/저장·네이티브 LoadImage PIL 경로와 실제 확장 JS를 사용했다. 실제 DGX 모델 추론 검증으로 간주하지 않는다.
- CPU 회귀 및 JS 이벤트 계약 검사는 현재 prompt ID/저장 경로, 자식 제출 금지, 완료/오류 이력 경쟁, 중복 이벤트, 브라우저 연결 유실/프로젝트 변경, 조기 중지 요청, 알려진 품질 오류/메모리 오류/구현 오류/사용자 중지, 브라우저 종료 후 상태 수집, 누락 작업을 임의 실패로 처리하지 않음, 재시작 시각 공급을 포함한다. 전체 CPU 회귀는 **456 passed in 61.61s** (`python -m pytest tests -q --confcutdir=tests`)다.
- 통합 그래프 모의 실행 8개 시나리오를 재확인했다. 정상·무검출·경계 복구 6개는 저장하고, 미복구 경계와 원문 그대로인 Qwen 출력은 의도대로 중단한다. 실제 모델 가중치는 대역이다.
- 새 08의 결과/OCR/번역 저장 경로 세 연결 때문에 새 GUI JSON을 가져와야 한다. 기존 프로젝트/시도 기록과 명시적 재시작 복구는 보존한다. 자동 다음 페이지는 열린 브라우저가 담당하며 브라우저 종료 후에는 추가 제출하지 않는다.

## 2026-10-17 v0.3.20 재시작 전 active 시도의 워크플로우 복구

- 실제 보고의 첫 페이지 3번째 시도는 22:47:39 KST 생성·22:47:50 갱신 후 running으로 남았다. 재시작 후에는 큐가 비었고 22:48:46에 시작한 부모 작업의 성공 이력만 있었다. 기존 실행기는 미확정 작업의 중복 제출을 막았지만, 명시적 실패 재시도에서도 이 시도를 워크플로우 안에서 정리할 수 없었다.
- 같은 08의 `실패 재시도`에서만 현재 OS 프로세스 시작 시각, 이전 시도 생성·갱신 시각, 반복된 큐·이력 부재와 마지막 재확인을 근거로 이전 시도를 `server_restarted_outcome_lost`로 보존하고 새 시도를 허용한다. 새 제출에는 프로세스 시작 정보도 기록한다. 일반 재개·같은 프로세스·시각 불명확·HTTP 원격 경로는 기존 중복 제출 차단을 유지한다.
- CPU 회귀 **443 passed in 48.62s**: `python -m pytest tests -q --confcutdir=tests`. 새 21개 검사는 보고된 3→4번째 시도와 이전 기록/입력 보존, 프로세스 stamp 유무, 일반 재개·같은 프로세스·시각 오류·실행 중 작업 차단, 완료 이력·마지막 확인 경쟁, 다른 큐 작업 보존, 일시정지와 제거된 원본을 포함한다.
- OS 시각 공급 경로도 실제 `psutil.Process.create_time()`으로 검사한다. 이 라이브러리는 ComfyUI 코어 의존성이며 CPU CI 검증 의존성에도 추가했다. 확인할 수 없는 환경에서는 복구를 허용하지 않는다. 사용자에게 런타임 자동 설치를 수행하지 않는다.
- Python 컴파일, 폴더 업로드 JS 구문, 문서 링크, 설치 ZIP import·CRC·개별 SHA256, 통합 GUI/API 재생성 및 체크섬 정합성을 확인했다. 08 경로·설정·연결은 바꾸지 않았다.
- 실제 DGX 모델 추론은 별도로 확인해야 한다. 이전 시도의 실제 완료/실패를 꾸며 복원하지 않으며, 원래 자료와 ID·토큰을 보존하고 결과 유실 사유를 명시한다. 새 시도의 실제 오류 수집은 v0.3.19 정책을 유지한다.

## 2026-10-17 v0.3.19 네이티브 큐 실패 진단

- 실제 보고의 18페이지 `execution_failed` / 실패 노드 null을 조사해, ComfyUI 내부 이력의 `(event, data)` tuple을 수집기가 list 전용 검사로 누락하는 결함을 확인했다. 상류 `execution.py`의 `add_message`, `task_done`, `get_history`를 대조했다. 보고만으로 실제 18페이지의 모델 예외 원인을 확정하지 않는다.
- tuple/list에서 같은 실패 종류·메시지·노드/ID·traceback을 보존한다. 자원/구성/사용자 중지는 추가 제출을 멈추고, 분류 가능한 OCR/식자 품질 실패는 페이지별로 분리한다. 상세가 없는 오류는 원인 불명으로 일시정지하고 일반 재개에서도 조용히 건너뛰지 않는다.
- 기존 메시지 없는 실패는 원래 prompt 이력으로만 진단을 복원한다. 복원을 위해 새 prompt를 제출하지 않는다. 이력 유실/모순 시 중단하고 명시적 실패 재시도를 안내한다. 전체 실패 보고서에도 일반 재개와 실패 재시도의 차이를 표시한다.
- CPU 회귀 **422 passed in 46.28s**: `python -m pytest tests -q --confcutdir=tests`. 새 16개 검사는 native adapter의 tuple과 HTTP list, 품질 실패 계속 처리, 메모리/디스크/모델 누락/사용자 중지 차단, 상세 없는 오류의 반복 재개 차단, 이전 진단 복원과 이력 유실·이전 시도 보존을 포함한다.
- Python 컴파일, 폴더 업로드 JS 구문, 설치 ZIP import·CRC·개별 SHA256 및 통합 GUI/API 생성 후 체크섬 정합성을 확인했다. 통합 워크플로우 연결·설정은 바꾸지 않았다.
- 실제 DGX 추론을 다시 실행하지 않았다. 기존 첫 실패의 live history 또는 서버 traceback이 실제 모델/노드 오류 확인에 필요하다. 재시작 시 history가 사라질 수 있으므로 업데이트 전에 확보하도록 안내한다.

## 2026-10-17 v0.3.18 단일 통합 워크플로우

- 배포 예제를 통합 08 하나로 정리했다. 예전 10개 예제의 GUI/API 20개 파일과 이전 다중 예제 생성기를 제거했다. 기존 노드는 저장 그래프 호환을 위해 유지한다.
- 제공 08 GUI/API의 경로·노드·기본값·연결·바이트는 v0.3.17과 동일하다. 한 장/폴더 입력과 PC 폴더 업로드, OCR/번역 JSON 및 프로젝트 보고서 PreviewAny 연결을 유지한다.
- 예전 예제와 완성된 08이 없는 임시 폴더에서 모델 노드 선언만으로 생성하여 배포 파일과 바이트 단위로 비교했다. 설치 ZIP에도 이 GUI/API 쌍만 포함됨을 검사했다.
- CPU 전체 회귀 **406 passed in 46.47s**: `python -m pytest tests -q --confcutdir=tests`. 이전 예제에 대한 중복 매개변수 검사와 폐기된 수동 그래프 시뮬레이션은 제거하고, 현재 그래프의 기본 크롭/복원/합성·최종 식자·저장 및 단일 배포/재생성 검사로 바꿨다. 과거 `wait_for_dispatch`를 부르던 취소 회귀는 현재 `wait_for_parent_success`로 수정했다.
- 통합 CLI 모의 실행 8개 시나리오를 확인했다. 단색+Qwen, 전부 타일, Qwen 생략, 경계 재검출, 조각 연결, 무검출 페이지는 저장에 도달하고, 미복구 경계와 원문 그대로인 Qwen 결과는 예상대로 저장 전에 중단했다.
- Python 컴파일, 폴더 업로드 JS 구문, 문서 로컬 링크, ZIP 설치 import·CRC·파일별 SHA256, 배포 체크섬 및 생성 후 정합성을 검사했다.
- 실제 DGX RF-DETR/Hayai/번역/Qwen 추론과 ComfyUI 브라우저 실행은 이번 정리에서 재실행하지 않았다. 이하 문단은 당시 버전의 검증 기록이며 현재 사용법은 README를 따른다.

## 2026-10-17 v0.3.14 워크플로우 내부 폴더 프로젝트

- 사이드바와 별도 프로젝트 HTTP 경로/프런트엔드 JS를 제거했다. 같은 08의 첫 `MangaWorkflowInput` 노드에서 이미지 한 장/폴더 프로젝트, 원본 폴더, 프로젝트 이름, 시작·재개/실패 재시도/상태 확인/일시정지를 설정한다. 보고서는 기본 `PreviewAny`에 연결한다.
- 실제 ComfyUI 프런트엔드 **1.53.10**에서 새 08을 가져오고 이미지 선택/업로드 위젯·API 직렬화·기본 Run·기본 PreviewAny를 검사했다. 캔버스 직렬화와 저장 그래프 일치, 폴더 3페이지의 중간 OCR 반복 실패 후 `completed=2, failed=1`, 완료 재실행 없음, 현재 페이지 후 일시정지, 재개, 보고서 갱신을 확인했다. 사이드바 탭도 없다.
- 브라우저 검증 서버는 상류 `PromptQueue` 클래스와 `/prompt` 함수 원문을 사용했다. prompt 전체 검증기와 실행 스케줄러는 대역이며 실제 노드/CPU 텐서/폰트/마스크 및 모델 대역으로 08을 실행했다. 기본 LoadImage의 PIL 경로도 사용했지만 새 비디오 입력 구현은 대역이다. 실제 GPU ComfyUI 실행으로 간주하지 않는다.
- CPU 회귀 검사 **397 passed**. 워크플로우 프로젝트 28개 검사는 페이지별 실패 격리, 자원 오류/사용자 중지 시 추가 제출 차단, 현재 페이지 후 중지와 재개, 기존 그래프 재사용, 중복 시작, 잘못된 폴더/프로젝트 이름, 내부 업로드 재입력 방지, 코어 prompt 함수 호출/작업 ID/메타데이터 보존, 파일 경로/덮어쓰기 거부, 시작 작업 취소, 상태 조회 경쟁을 포함한다.
- 시작 상태 파일을 쓰는 순간의 동시 조회가 서버 재시작으로 오인되던 경쟁을 브라우저 검증에서 발견해 잠금으로 수정했다. 재현 검사도 포함한다. 취소 이력 대역을 이용해 페이지 중지 시 추가 제출 중단과, 폴더 시작 작업 취소 시 페이지 미제출도 검사했다.
- 설치 ZIP에 새 입력/큐 연결 모듈과 08을 포함하고 이전 사이드바 파일이 없음을 검사한다. ZIP import·CRC·파일별 SHA256을 확인한다. 모의 기본 SaveImage가 실제 보고한 출력 경로에도 PNG를 쓰도록 개선했다.
- 기존의 일부 표지 자동 검출, 숫자 칸·제목 의미 구분, OCR 의미 정확도, 페이지 간 용어 공유는 별도 개선 대상이다. 실제 DGX RF-DETR/Hayai/번역/Qwen 추론은 이 환경에서 실행하지 않았다.

## 2026-10-17 v0.3.13 ComfyUI 프로젝트 패널

- 기본 사용을 ComfyUI 안으로 옮겼다. `WEB_DIRECTORY` 확장으로 왼쪽 책 아이콘의 프로젝트 탭을 등록하고, 현재 08의 실제 `app.graphToPrompt()` 출력으로 프로젝트를 만든다. API JSON 내보내기나 CLI 실행은 필요 없다.
- 프런트엔드 **1.53.10**을 실제 Chromium에서 실행하고 실제 확장 JS와 aiohttp 경로를 연결했다. 서버 폴더 선택 → 실제 08 캔버스 직렬화 → 프로젝트 실행 → 숫자 순서 결과/이미지 미리보기 → 재개, 브라우저 폴더 업로드 → 하위 경로 보존 → 일시정지 → 재개를 클릭해 검사했다. 저장한 워크플로와 캔버스 직렬화가 같고, 완료 페이지의 시도 번호가 1로 유지되는 것을 확인했다. 모델·ComfyUI 실행 API 응답은 대역이다.
- CPU 회귀 검사 **386 passed**. 프로젝트 패널의 17개 검사는 중복 실행 방지, 기존 설정 재사용, 페이지 완료 후 중지, 실패 페이지만 재시도, 잘못된 폴더/결과 경로, 외부 심볼릭 링크, 빈 폴더, 재시작 상태 표시, 실제 HTTP 업로드·중복 덮어쓰기 거부·상태·결과 파일, 손상된 프로젝트 기록 분리, 수동 09 폴더 적용 거부, 내부 업로드 재입력 방지를 포함한다.
- ZIP에 새 서버 모듈과 `web/projects.js`를 포함하고 별도 설치 경로 import 및 ZIP CRC/개별 파일 SHA256을 검사한다. 이전 v0.3.12 처리 엔진의 실제 노드·CPU 모델 대역 통합 시뮬레이션도 회귀 검사에 포함한다.
- 백그라운드 실행은 ComfyUI가 실제로 사용하는 로컬 주소/포트의 API에 연결한다. 프록시·인증·TLS로 로컬 API 접근이 막힌 구성은 DGX 실환경 검증 대상이며, 연결 실패 시 프로젝트는 멈춘다. 서버 재시작으로 큐/히스토리가 유실되어 작업을 확인할 수 없을 때도 자동 재제출하지 않는다.
- 실제 DGX RF-DETR/Hayai/번역/Qwen 추론은 이 환경에서 실행하지 않았다. 일부 표지 자동 검출, 숫자 칸/제목 의미 구분, OCR 의미 정확도와 페이지 간 용어 공유는 이번 변경으로 해결한 것으로 간주하지 않는다.

## 2026-10-16 통합 타일 경로

- 최종 회귀 검사: **126 passed**. 실행 명령은 `python -m pytest tests -q --confcutdir=tests`다. 하이픈이 있는 설치 폴더의 루트 `__init__.py`를 pytest가 독립 테스트 패키지로 잘못 불러오지 않도록 범위를 지정한다.

- 기본 실행 그래프 08을 추가했다. 검출·OCR·번역·타일 계획·Qwen·크기/좌표 복원·식자·저장을 연결한다. Qwen 입력은 기본 ImageCrop으로 자른 제한된 타일이며, 기본 ImageScale·ImageCompositeMasked를 거쳐 페이지로 복원한다. 새 전용 노드는 가변 타일 계획과 한 페이지 집계 두 개다.
- 실제 커스텀 노드와 PyTorch CPU 텐서로 배포 API 그래프를 끝까지 모의 실행했다. 모델 응답은 합성 입력을 아는 대역이다. 실제 RF-DETR/Hayai/vLLM/Qwen 추론과 실제 ComfyUI 프런트엔드 실행 결과로 간주하지 않는다.
- 합성 입력의 6개 영역/8개 OCR 줄 대응, 전체 검출에서 빠뜨린 본문의 상세 창 복구, 마스크 밖 원본 픽셀 완전 보존을 확인했다. 단색 선처리+Qwen은 1타일, 선처리를 끈 경우 5타일, 모두 단색인 경우 0타일로 최종 저장에 도달했다. 원문을 그대로 반환한 제거 실패는 식자/최종 저장 전에 중단됐다.
- 타일 코어/문맥 상한, 픽셀 소유권의 중복/누락, 빈 pending 마스크의 lazy 생략, ComfyUI의 미해결 링크 `(None,)`, 잘못된 타일 수·크기·비유한 값 거부를 검사했다.
- 검출 overlap 최대값의 1px stride를 제거하고 사전 64창 제한을 추가했다. 작은 문장부호 보존, 외곽선 행간, 새 예제의 GUI/API 연결·위젯 값도 검사한다.
- ZIP 필수 모듈 누락을 수정하고, 생성 ZIP을 별도 폴더에 풀어 실제 확장 패키지 import와 새 노드 등록을 검사한다. checksum은 최종 패키지 생성 시 갱신한다.
- 주변 균일색 선처리와 원문 잔존 검사는 보수적 픽셀 휴리스틱이다. 누락된 검출을 항상 복구하거나 모든 원문이 지워졌음을 보증하지 않는다. 실제 사용자 원본과 DGX GPU에서의 품질·속도·VRAM은 아직 검증하지 않았다.

2026-10-14 Windows 로컬 환경에서 초기 소스 패키지를 검사했다.

- Python 구문 및 독립 노드 패키지 import 검사.
- 25개 로컬 계약 테스트 통과: 영역 좌표 검증, 검출 중복 제거, 영역/원문/번역 ID 대응, 누락/중복 번역 거부, 한국어 및 줄바꿈 보존, 수동 번역 시 서버 미호출, 로컬 HTTP 테스트 서버로 `/models` 및 `/chat/completions` 요청/응답 처리, JSON 파일 저장, Hayai 전처리 패치 수, 알려진 OCR 반복 오류의 제한된 재시도, GUI/API 워크플로우 연결 일치.
- 크롭·마스크 기하 테스트는 NumPy 기반 Tensor 대역을 사용했다. 실제 PyTorch/CUDA 연산 테스트는 아니다.
- ComfyUI의 현재 `nodes.py`, `comfy_extras/nodes_qwen.py`, `comfy_extras/nodes_mask.py`를 확인하여 참조 이미지 입력, resolution, cache, 저장 및 합성 노드 계약을 대조했다.
- 두 GUI 워크플로우와 두 API 워크플로우의 노드/슬롯/연결 타입을 검증했다.
- 가져온 여섯 모델 어댑터가 기록한 원본 파일과 바이트 단위로 같은지 검증한다.
- 소스에서 이전 개인 계정명, 개인 이메일, 사용자 절대 경로, Tailscale 주소 및 인증 키가 섞이지 않았는지 확인한다. 공개 프로젝트·모델 작성자와 저작권 이름은 출처로 보존한다.

재실행:

```text
python -m pytest tests --confcutdir=tests --import-mode=importlib -q
python -m compileall -q nodes.py models.py adapters
```

pytest의 `--confcutdir=tests`는 하이픈이 있는 ComfyUI 저장소 루트의 `__init__.py`를 pytest가 잘못된 일반 Python 모듈명으로 수집하지 않도록 한다. 테스트 실행에는 pytest, numpy, Pillow, pydantic이 필요하다.

미검증:

- 사용자의 실제 ComfyUI 버전에서 GUI JSON 가져오기·실행.
- NVIDIA GPU에서 이번 독립 패키지로 RF-DETR/Hayai 로드·추론.
- 사용자의 번역 LLM 서버 및 모델 프롬프트 호환성.
- Qwen 이미지 편집의 한국어 정확도, 원문 제거, 원본 그림 보존, 마스크 경계 품질.
- end-to-end 소요 시간 및 VRAM 사용량.

따라서 이 결과는 실행 가능한 소스/노드 연결의 로컬 검증이며 GPU 생성 결과의 품질을 보증하는 검증은 아니다. 이전 프로젝트의 실측 결과를 이번 독립 패키지의 실측으로 간주하지 않는다.
# 원본 참조 스타일 식자 0.1.0 추가 검증

- 기준 저장소: `ytoaa/ComfyUI-Manga-Translator`, base `da5cfb4e7a66ff03bd4ff00b0f4c5b4293ce9e6d`
- 전체 테스트: **48 passed**, 다음 명령으로 실행. 루트에 ComfyUI `__init__.py`가 있는
  저장소 구조 때문에 pytest의 탐색 경계를 tests로 명시한다.

```bash
python -m pytest --rootdir=tests --confcutdir=tests -q
python tools/build_lettering_fixture.py
python -m compileall -q lettering tools tests
```

- 추가 검증: 실제 동봉 한글 폰트 렌더링, 원본 색/외곽선 측정, 가로·세로 레이아웃,
  회전·기울기, 폰트 미지원 문자/넘치는 번역문 거부, 새 글자 알파 밖 원본 픽셀의 정확한 유지,
  원문과 다른 위치의 번역문 획 보존, 겹치는 영역에서 원본 참조 재사용, 후보 질감의 변화량과
  알파 보존, 기존 번역 JSON/좌표 어댑터, 원문 제거 프롬프트에 번역문 미포함,
  예제 6개의 UI/API 연결·필수 입력·순환 참조 검사.
- Python 모듈 등록: 기존 10개 + 스타일 식자 11개 = **21개**. 실제 torch 없이 import 가능.
- 노드 래퍼 검사는 NumPy 텐서 대역을 사용했고, 픽셀·폰트 계산은 실제 Pillow/NumPy/SciPy로 실행했다.
  전체 예제의 실제 ComfyUI executor/브라우저 가져오기 검증을 대체하지 않는다.
- 합성 테스트 비교 이미지 `lettering/examples/comparison.png`를 생성하고 시각 확인했다.
  코드로 만든 fixture이며 실물 만화·Qwen 생성 결과가 아니다.
- **미검증:** DGX/GB10, 실제 GPU 모델 추론, 새 그래프의 vLLM 실서버 번역,
  실제 ComfyUI UI/API 실행, 실물 만화의 손글씨/효과음 스타일 재현 품질.
- 원본 폰트 자동 식별/학습형 형태 전이와 자동 OCR 재검증은 구현 범위에 포함하지 않는다.

## 2026-10-15 워크플로 설정 복원 수정

- 기존 48개 검사는 API 연결과 Python/픽셀 계약을 확인했지만, 프런트엔드의
  위젯 생성·위치별 값 복원은 확인하지 못했다. 이 누락으로 연결 전용 STRING이
  숨은 위젯을 생성해 번역 설정을 한 칸씩 소비하는 오류가 남아 있었다.
- 기존 선언과 기존 05 JSON을 실제 ComfyUI 프런트엔드 **1.53.10**에서 불러와
  `model=Korean`, `target_language=MANGA_LLM_API_KEY`, `max_tokens=300`을 재현했다.
- 연결 전용 입력에는 `forceInput`을 선언하고, 편집 가능한 문자열을 연결한 경우에는
  숨은 위젯 자리와 변환 입력 메타데이터를 함께 보존한다. 업로드 버튼은
  `serialize:false`이므로 값 배열에서 제외한다.
- 기존 2개 + 식자 6개 = **8개 GUI 워크플로**를 실제 배포 프런트엔드에서 불러왔다.
  이름 기반 메타데이터 포함/제외의 **16개 경우**에서 설정을 대조하고, 캔버스에서
  생성한 API prompt 및 저장 후 재불러온 prompt의 모든 작성된 입력을 확인했다.
- 브라우저: Chromium 153.0.8010.0, 프런트엔드 배포 패키지 1.53.10.
  **object_info·모델 목록·서버 응답은 로컬 대역**이며 torch/CUDA 모델 실행은 하지 않았다.
  Qwen의 동적 이미지 입력도 이 검사의 대역 스키마로 제공하므로 실제 백엔드의
  동적 입력 실행 검증과 구분한다. WebSocket 연결은 이 로컬 대역에서 제공하지 않았다.
- 단일 영역 예제의 크롭/좌표/합성을 기본 ImageCrop·CropMask·PrimitiveInt·
  ImageCompositeMasked로 변경했다. 기존 크롭/합성 래퍼 두 개는 이전 저장 파일의
  호환용 deprecated 노드로만 유지한다. 다중 영역 스타일 식자는 별도 전용 처리다.
- Python 회귀 검사: **64 passed**. 위젯 선언/직렬화 위치, 타입·범위, 번역/검수/지시 설정,
  기본 노드 사용과 공유 좌표를 검사하는 16개 회귀 경우를 추가했다.
- 실제 DGX/GB10 추론, 사용자 장비의 확장 노드 조합, 실제 만화 생성 품질은 여전히 미검증이다.

## 2026-10-15 번역 JSON 응답 처리 수정

- 사용자 traceback은 Hayai 추론이 아니라 MangaTranslate의 `decode(content)`에서 발생했다.
  원시 응답이 없으므로 실제 JSON 잘림, 닫는 코드펜스 누락, 같은 줄 코드펜스 등의
  구체적인 서버 출력 형식은 이 로그만으로 확정하지 않았다.
- 서버 응답 전용 파서는 완전한 JSON 값 하나만 읽는다. 표준/동일 줄 코드펜스와
  JSON이 완전한 경우의 닫는 코드펜스 누락은 허용한다. 잘린 JSON의 괄호·따옴표를
  임의로 보충하거나 일부 영역만 회수하지 않는다. 문자열 안의 리터럴 백틱은 보존한다.
- 형식·영역 ID 계약 실패에 한해 원본 OCR/ID 전체를 재전송해 번역 단계만 한 번 재시도한다.
  재시도도 실패하면 메타데이터와 함께 중단한다. 비정상 finish_reason 및 reasoning만 있고
  content가 없는 응답은 재시도/부분 채택하지 않는다. 기존 수동 override 파서는 유지한다.
- Python 테스트 **91 passed**. 추가 27개 경우: 코드펜스 포맷, 누락 펜스와 실제 JSON
  잘림 구분, 추가 텍스트/다중 JSON 거부, 한글·개행·백틱 보존, 영역 ID 누락/중복,
  1회 재시도 상한, length/content_filter/error 및 답변 누락 거부.
- 실제 사용자 번역 서버의 해당 응답과 재실행 성공 여부는 이 로컬 검증에 포함하지 않는다.


## 기존 Koharu 인페인트 그래프와의 설정 대조

- 비교 기준: `ytoaa/koharu-remote` commit `ee6d9ddc82d9bfc4718383272f0e4797f805e2cd`,
  `comfyui/koharu_nodes/workflows/inpainting.api.json`의 prompt.
- 모델 본체/인코더/VAE, Euler, 8-step sigma, CFG 1, add_noise 및 기본 seed는 동일하다.
  기존도 Qwen에 마스크를 직접 조건으로 전달하지 않았다. 직접 마스크 입력이 없다는
  사실만으로 새 결과의 실패 원인이라고 판단할 수 없다.
- 05/06에서 달라졌던 원문 제거 지시를 기존의 모든 글자 제거 직접 지시로 되돌리고,
  `resolution` 기본값을 1024에서 기존의 0으로 복원했다. 기본 Qwen 노드에서 설정하며
  좌표/OCR JSON 지시를 생성하던 중간 노드는 이 예제들에서 제외한다.
- 두 API/GUI 예제를 JSON으로 파싱해 모든 연결·입출력 슬롯 대응, 중간 노드 제거,
  직접 prompt 및 resolution, 기존 모델/샘플러 값 보존을 확인했다.
- 실행 환경 연결 장애로 이번 변경의 Python 테스트·생성 스크립트·실제 프런트엔드 및
  GPU 재실행은 수행하지 못했다. 앞선 91 passed는 이전 번역 JSON 수정 시점의 결과다.
- 기존의 SAM 기반 글자 마스크/마스크 정제/국소 색 보정과 현재 사각형 마스크에는 아직
  차이가 있다. 이번 수정은 제거 지시와 해상도 설정 복원이며 전체 인페인트 동작 동등성이나
  실제 이미지 품질을 확인했다는 의미가 아니다. analyze_style의 8-pixel 조건은 스타일
  측정용 최소 변화량 검사이며 원문 제거 성공을 판정하는 조건이 아니다.


## 2026-10-16 검출 타일 경계 복구 v0.2.1

- 기준 `a85edaf`에서 576px 경계의 여러 행 세로 조각과 반쪽 본문을 재현했다.
  기존 7영역이 새 코드에서 6영역으로 복구되며, 미해결 조각은 OCR 전에 중단한다.
- 전체 검사 **144 passed**, 통합 모의 실행 성공 4경로·예상 중단 2경로.
- 조각 segmentation 픽셀 보존, 모든 fixture 글자 마스크 포함, 마스크 밖 픽셀 불변을 확인했다.
- 실제 사용자 이미지의 RF-DETR/Hayai/Qwen GPU 품질과 실제 ComfyUI executor는 미검증이다.
- 변경·실행 환경·재현 방법·정확한 보증 범위: [검증 보고서](docs/boundary-recovery-validation.md).


## 2026-10-16 복구 경로 보완 v0.2.2

- v0.2.1 사용자 예외의 정확한 bbox와 합성 보완 조각으로 기존 중단을 재현했다.
  양쪽 끝이 관측된 조각 연결, 여러 방향 문맥 확대, 전체 복구 후 최종 판정과 진단 로그를 추가했다.
- **157 passed**, 통합 모의 실행 성공 5경로·예상 중단 2경로.
- 실제 사용자 재검출 응답이 없으므로 이번 오류의 세부 원인과 GPU 해결 여부는 미확정이다.
- [코드 변경·재현 입력·검증 범위](docs/boundary-recovery-v0.2.2.md).


## 2026-10-16 원문 보존 통합 식자 v0.3.0

- 08의 제거·좌표 복원 뒤에 원문 크기 상한을 사용하는 MangaLetterPlan과 MangaLetterApply를 연결했다.
  기존 단일/페이지 식자 노드와 01~07 예제는 호환을 유지한다.
- 실제 동봉 폰트로 짧은 번역 크기 상한, 긴 번역 축소 우선, 비례 외곽선, 최소 크기 후 재배치,
  행 길이 균형·짧은 끝줄, 말풍선 경계, 검출 bubble segmentation 재사용, 이웃 글자 충돌 중단,
  가로/세로 방향, 독립 두 자리 숫자·라틴 회전·문장부호, 회전/기울기/수동 곡선,
  원문 한글 획의 분리와 외곽선 두께에 대한 크기 측정, 입력 검증을 검사한다.
- 전체 회귀 검사 **182 passed**. 생성 후 위젯 검사 **18 passed**, 전체 그래프 검사 **7 passed**.
  [기능 검증 CI](https://github.com/ytoaa/ComfyUI-Manga-Translator/actions/runs/38856867408)에서 모두 통과했다.
  로컬 executor 연결 장애로 GitHub Actions의 Python 3.12/PyTorch CPU 환경에서 실행했다.
- 배포 API 그래프를 실제 노드/PyTorch CPU로 실행하는 합성 입력 모의 실행은 성공 5경로,
  예상 중단 2경로다. 검출 6영역·OCR 8줄 대응을 유지하며 원문 크기 상한, 식자 알파 밖
  배경 픽셀의 완전 보존도 검사한다. 모델 응답은 대역이며 GPU 추론 결과가 아니다.
- 합성 식자 비교 6개를 실제 폰트로 렌더링해 크기 상한·축소·재배치·세로쓰기·말풍선·수동 변형을 시각 검토한다.
- 08 GUI/API 생성기를 실행한 뒤 위젯 계약 검사와 전체 그래프 회귀 검사를 다시 수행한다.
- 설치 ZIP을 풀어 새 노드 등록을 검사하고, 최종 ZIP의 파일별 SHA256와 ZIP 무결성을 검증한다.
- 실제 사용자 원본/GPU 결과, 자동 폰트 식별, 자동 곡선 복원, 완전한 OpenType 세로 조판,
  OCR 오인식·번역 문맥 오류·제거 잔상 해결은 이 CPU 검증에 포함하지 않는다.

재실행:
```bash
python -m pytest -q
python tools/simulate_integrated.py --destination validation/simulation
python tools/demo_hybrid_lettering.py --destination validation/hybrid
python tools/build_integrated_workflow.py
python -m pytest tests/test_workflow_widgets.py tests/test_integrated_simulation.py -q
python tools/package_style_lettering.py --destination validation/package
```
# v0.3.1 OCR / boundary policy verification — 2026-10-16

Base: `a063ffd1d99ea57d90427e23a0600aebbb0cf7c4`.

- Full CPU regression: **201 passed** (182 baseline + 19 new cases).
- Reported backpack-region effect false-positive geometry: excluding effects prevents recovery failure and mask leakage; enabling them retains strict failure.
- Reported r4/r5 line coordinates: one paragraph, surrounding paragraphs retained; distinct bubbles and existing multiline masks remain separate.
- Reported short loops and four-character omission: bounded alternate-budget retry; persistent suspicious OCR stops the complete graph before translation/Qwen/final saving.
- Long-line chunks preserve every input pixel, including small punctuation; blank margins do not create empty recognition chunks. Missing safe gaps and vertical inputs stay intact.
- Shipped 08 graph simulation: five successful paths and two expected failure paths. Successful fixtures keep six logical regions, eight source lines and nine recognition chunks, with exact outside-mask pixel preservation. The source/translation JSON retain per-region OCR diagnostics.
- Workflow widget/API contracts, Python compilation, installable ZIP imports, archive CRC and per-file SHA256 are checked locally. 08 regeneration preserves the committed bytes.

RF-DETR, Hayai, vLLM and Qwen responses in these simulations are explicit test doubles.
No actual GPU recognition accuracy, user-image quality improvement, live ComfyUI browser execution or Qwen residual-dot fix is claimed.
The input changes and heuristic rejection rules need real-image comparison using the new 08 workflow.
See [usage and limits](docs/ocr-boundary-v0.3.1.md).

# v0.3.2 uniform cleanup / width-first flow — 2026-10-16

Base: `491f1254222f4263c39c3c21562096178c816be1`. Full CPU regression: **212 passed**.
Eleven added cases cover disconnected white source pixels missing from segmentation, exact preservation outside
the effective cleanup mask, unrelated bright art, patterned/unsupported-region rejection, Qwen comparison mode,
single-newline reflow, blank paragraphs, strict/per-region preservation, frame bounds and punctuation-safe size estimation.
The shipped 08 graph removes a deliberately omitted 3×3 white fleck before lettering in an explicit fixture.
Font/pixel rendering reproduces 23px/two rows with preserve versus source-capped 27px/one row with reflow in the same frame.
Five successful and two expected-stop full graph simulations retain their prior detector/OCR/Qwen counts.
Workflow generation, widget/API contracts, compilation, ZIP import/integrity and source SHA256 are checked locally.
Real user-image RF-DETR/Hayai/Qwen GPU output and live ComfyUI frontend execution remain unverified.
See [settings and limits](docs/uniform-cleanup-flow-v0.3.2.md).

# v0.3.3 OCR direction / token recovery — 2026-10-16

Base: `8d61cfb2c6d86131250e633af24c14e94790308c`. Full CPU regression: **222 passed**.
Ten added cases cover tall horizontal paragraphs, avoiding per-letter vertical splitting of one horizontal row,
explicit vertical reading order, token-budget retry/disable/cap/persistent failure, combined token/repetition bounds,
and failure before translation/Qwen/final saving in the shipped 08 graph.
Local pixel analysis of three 278×446 crops from the attached 1060×1500 scan changes one unsplit input to
20/16/17 horizontal line crops. These are analysis rectangles, not the unknown actual failing detector ROI.
No model weights or GPU inference were used for this source-image segmentation check.
The existing five successful and two expected-stop complete graph simulations remain valid with mocked model responses.
Workflow widget/API serialization, regeneration, compilation, package import/integrity and source checksums are checked locally.
Actual Chinese OCR accuracy and resolution of the user's GPU run remain unverified.
See [cause, options and scope](docs/ocr-direction-budget-v0.3.3.md).

# v0.3.4 no-text page passthrough — 2026-10-17

Base: `c07ca562d9c906399cbd02fb583e5389154e2d7f`. Full CPU regression: **230 passed**.
Eight added cases exercise all shipped 08 output endpoints for no text, bubble-only and excluded-effect-only pages;
assert no Hayai/Qwen loader execution, OCR/Qwen inference or translation HTTP request; and compare saved PNG pixels
exactly with the input. OCR and translation review JSON files contain empty regions and `no_text_detected`.
Additional checks reject wrong-page manifests, unexpected OCR text, detector exceptions, missing regions and
missing detection lists in either full-page or detail responses. Existing empty OCR on actual text remains an error.
The simulation runner now maps scalar lazy checks like ComfyUI, while INPUT_IS_LIST checks keep list arguments.
Complete graph simulations cover six successful paths (including the new no-text page) and two expected stops.
Legacy examples serialize `allow_empty_page=false`; only refreshed 08 enables the passthrough and connects its manifest.
Workflow widget/API contracts, stable regeneration, compilation, package integrity/import and source checksums are checked locally.
Model responses are test doubles; actual user ComfyUI/GPU execution remains unverified.
See [behavior and update requirements](docs/no-text-pages-v0.3.4.md).

# v0.3.5 OCR layout recovery / readable fitting / text previews — 2026-10-17

Base: `4be9e25d2a8f9ed30764319a956dde390d228413`. Full CPU regression: **245 passed**.
Fifteen added cases cover dark/bright framed 580×203 OCR paragraphs, exact pixel reconstruction from recovery crops,
accepted-row diagnostics, persistent child failure without recursive retry, combined-output loop rejection,
vertical reading order, per-region work limit, disabling line split, no arbitrary slices, large connected glyph rejection,
and actual PNG/JSON failure diagnostics including inability to save them.
Actual bundled-font fitting tests exercise longer translations of a one-glyph source below the ratio floor,
while retaining the frame, unchanged alpha exterior, strict mode, explicit region min_scale and absolute min_font.
In a synthetic 120×150 frame, source cap 108px gives the previous floor 60px; refreshed-08 reflow/readable settings
render the full target at 43px within that same frame. This is not the user's actual r1 reconstruction.
The shipped graph adds two native PreviewAny endpoints directly after OCR/translation review saving.
Both execute in the existing complete graph tests; normal text and no-text paths remain covered.
Six successful and two expected-stop integrated simulations, stable GUI/API regeneration, workflow/widget serialization,
compilation and package checksums/import are checked locally. Legacy 07 keeps layout recovery disabled.
The supplied workflow is pasted Markdown with escaped JSON; its PreviewAny/source connections and OCR settings
were inspected as text. The new attachment is a canvas screenshot, not the failing OCR crop or r1 source/target JSON.
Actual 580×203 OCR root cause, r1 geometry/direction and user GPU/ComfyUI outcomes remain unverified.
See [settings, evidence and limitations](docs/ocr-fit-preview-v0.3.5.md).

# v0.3.6 selection audit / actual bubble containment — 2026-10-17

Base: `c7dd3149ba4dff43f8a8aea88c15c3f79fe23749`. Full CPU regression: **260 passed**.
Fifteen added cases cover jagged masks supplied directly or by detected RLE, source padding beyond the bubble,
ink-based neighbouring-bubble ownership, ambiguous versus duplicate masks, source crossing a known mask,
nonbubble titles/explicit bubble requirements, and impossible fits without clipping off glyphs.
Every positive alpha pixel is checked after outlines, shadows, rotation and bending, in addition to frame/collision checks.
An illustrative synthetic jagged bubble changes 3,174 rectangle-only outside pixels to zero with the full target retained;
this is not a reconstruction of the user's screenshot or a certification of the detector's mask accuracy.
Added tests distinguish disabled layout recovery from no alternative and verify the runtime flags in failure JSON.
Small/native pages with zero selected text get bounded compact retries, positive-text pages retain the native early exit,
and excluded effects retain raw label counts/review metadata. The shared native PrimitiveBoolean drives all three
include_sfx inputs. Existing full-graph text and no-text paths, six successful/two expected-stop simulations,
workflow regeneration, compilation and package import/checksums are verified locally.
The cover attachment is an 800×1125 source image, but its actual model detections were not supplied.
The reported teacher failure still needs its existing JSON and corresponding input/source PNGs.
No actual RF-DETR/Hayai/Qwen GPU execution or resolution of that 580×203 OCR failure is claimed.
See [configuration and remaining evidence](docs/selection-bubble-diagnostics-v0.3.6.md).

# v0.3.7 multicolumn OCR / compact boundary recovery — 2026-10-17

Base: `976d681240257c783f82dfd3c8f8316e01b2a466`. Full CPU regression: **269 passed**.
The actual 580×203 failure input and runtime JSON/log were supplied after v0.3.6.
The input contains two horizontal prose columns, a dotted gutter rule and a boxed section marker.
Direct pixel planning yields 9 left-column and 7 right-column crops; the marker merges two right-hand rows.
All 117,740 source pixels have coverage exactly one and coordinate reconstruction is byte-identical.
No supplied image or recognized private text is committed. Synthetic bright/dark textured fixtures check
independent column reading, unsliced section markers, exact pixels and bounded validated child outputs.
The reported cover fragment/window coordinates are reproduced with model doubles. Expanded misses can
reach a single 576×576 compact context, while duplicate windows, work limits and unresolved rejection remain.
The simulator registers the new input shape and continues to test that unresolved seams stop before model
loading, OCR, translation, cleanup and saving. Existing workflow inputs/connections are unchanged.
See [behavior, update and live verification limits](docs/column-compact-recovery-v0.3.7.md).

# v0.3.8 omission guard speckle false positive — 2026-10-17

Base: `7a49dc7d82797c7d802397ff70dcb68968deb3c5`. Full CPU regression: **273 passed**.
On the supplied 280×51 actual input, raw projection has 38 bands and incorrectly requires at least 10 characters.
Removing disconnected components below four pixels from the omission estimate alone yields 12 supported bands
and a weak lower bound of three characters; both supplied 7/8-character lengths no longer trigger omission.
Recognition input bytes are unchanged. This does not certify the spelling of either output; the saved seven-character
result is visibly incorrect and the first eight-character string was not supplied.
Four added regression cases cover bright/dark speckled paper, omission from real small components and the complete
adaptive-node path retaining a first result without an unnecessary alternate patch. Repetition and genuine omission
regressions remain active. Evidence counts are exposed in attempt diagnostics. Attached images are not committed.
See [behavior and remaining recognition limits](docs/omission-speckles-v0.3.8.md).

# v0.3.9 row-gap speckles / explicit manual integrated route — 2026-10-17

Base: `28171e94a16d42c0a3036544fe99b1db59cbd023`. Full CPU regression: **279 passed**.
Actual supplied 305×270 pixels now yield ten body rows and one footer crop. All 82,350 pixels have
coverage exactly one; reconstructed bytes match. Recovery ignores 776 tiny component pixels only in
analysis and retains original recognition pixels. Structural bright/dark fixtures verify the dotted gutter,
footer retention, unsliced body glyphs and bounded rejection when a recovered child still repeats.
Earlier 580×203 columns and 280×51 omission inputs remain regression checkpoints.
The actual footer also exposed an omission false positive for `32`. The omission component threshold now
scales to 20% of the largest foreground component, bounded to 4..16 pixels. A separate larger-speckle footer
fixture and the existing real-small-component omission alarm cover this change; no OCR text is substituted.
The user GPU log confirms that the compact cover attempt actually ran and also returned no selected text.
That cover remains an unresolved automatic detection case; no success is claimed or fabricated.
09 uses existing nodes with one human-entered region JSON, rectangular masks and the same integrated
OCR/translation/tiled-cleanup/lettering outputs. Its graph simulation uses synthetic region coordinates
instead of the example cover frames and verifies zero detector calls, both JSON previews, final save and
unchanged pixels outside the permitted mask. Actual cover model inference is not run here.
See [manual-mask contract and live limits](docs/row-noise-manual-v0.3.9.md).

# v0.3.10 lettering resampling margin — 2026-10-17

Base: `f663f79fd0d77a83835485415962612e00d39d86`. Full CPU regression: **285 passed**.
The provided 455-character reflowed r3 target in the reported 589×219 frame, bundled font/plain style,
left alignment/padding 2 reproduces the boundary failure at every size from 15 down to 10.
Old edge alpha maxima range 0.0134..0.0196. With minimum effective supersampling padding 4,
all six edge maxima are exactly zero and the complete text is retained. This uses real CPU font pixels,
not a model double, but the actual measured source style and complete plan were not supplied.
Six added regression cases cover both side alignments at two sizes, preservation of larger explicit padding,
and the reported r3 xywh frame with a synthetic dense translation fitting at its 15px cap.
Existing containment, collision, minimum font and impossible-fit checks remain active.
The cover screenshot confirms the user manual path reached final save. The guide's duplicate/implausible
translation content remains unresolved pending its saved OCR JSON; neither detection nor text is silently discarded.
See [changes and remaining source-content investigation](docs/lettering-raster-margin-v0.3.10.md).

# v0.3.11 page-column ownership before OCR — 2026-10-17

Base: `b1c50ba8373bdf343a49987f919fc16861c66644`. Full CPU regression: **299 passed**.
The supplied saved OCR document confirms overlapping cross-column source regions and implausible text
already present before translation. The earlier input-only recovery did not change logical lettering frames.
An opt-in page-column refinement now runs in MangaRegionCrops before recognition. It requires recurring
column anchors, multiple cross-column detections, pixel-supported gutters and horizontal body rows.
Manual, mixed-SFX, unassigned-fragment and ambiguous layouts retain the complete original layout.
Bounded paragraph ownership is shared by OCR, translation, cleanup and lettering. The appended output
provides validated row plans; collector diagnostics must match the corresponding manifest plan and ID.
The original three output slots and legacy default False are preserved. New 08 opts in; 09 stays manual.

Actual supplied 1060×1500 source pixels + 15 saved detector regions produce 24 logical regions and
90 planned initial recognition inputs, at most 8 per region. Column cuts are 0,108,422,746,1060 for this input only.
There are zero overlapping OCR-crop pixels and zero overlapping edit-frame pixels. Every generated
crop equals the corresponding original RGB; concatenating each row plan reconstructs its complete crop.
Both-polarity gutter checks and auxiliary-marker row merging retain light section numbers.
The source image and saved OCR text are not included in the repository.

Fourteen added synthetic regression cases cover unique column ownership, marker-safe planning,
original pixel reconstruction, bounded edit margins, proactive OCR before quality failure, manifest/plan
agreement, conservative bypasses, malformed-plan rejection and shipped graph connections. The existing
full graph tests still exercise final save, empty-page skips and failure stops with explicit model doubles.
This is CPU pixel/graph verification, not actual RF-DETR/Hayai/vLLM/Qwen inference. The new actual
recognition/translation quality and final GPU rendering remain to be checked on the user's machine.
See [behavior, compatibility and limits](docs/page-columns-v0.3.11.md).

# v0.3.12 folder projects and failure scenarios — 2026-10-17

Base: `e9d93e79772c65128ddcaebd32a5137bbec7c742`. Full CPU regression: **369 passed**.
Seventy added cases comprise 45 project/API/exception cases, 21 geometry-matrix cases, three zero/positive/
negative GrowMask checks and one mixed-folder full-graph integration. The axis matrix covers 648 combinations
of exact threshold and randomized lengths with tile sizes 384/576/1152 and overlap 0/64/384.

The mixed folder executes the shipped 08 with real custom nodes, CPU tensors, font pixels, masks, tile
planning/assembly, JSON validation and file saves. RF-DETR/Hayai/vLLM/Qwen and the server scheduling layer
are explicit doubles. Its 11 inputs yield completed 4, unchanged_blank 1, needs_review 1 and five intentional
failures: unresolved seam, repeated OCR, unchanged cleanup, impossible lettering and corrupt input.
The corrupt file is not submitted. Later valid pages save successfully. Ten prompts are submitted and
resuming submits zero more. Natural ordering, duplicate basenames in different folders and input/result
identity are preserved. This mixed run is now itself a test in the full suite.

Project tests cover response loss after acceptance, unknown/running jobs, bounded timeouts, OOM/disk/model
failures, missing or modified results, explicit retry, source changes, adding an earlier page while another is
active, removing an in-flight source, missing normalized inputs, JSON key reordering, corrupt manifests/state,
multi-frame/high-bit-depth/large/linked inputs, unreadable subfolders, EXIF/CMYK/gray/alpha normalization,
nonzero partial-success CLI exits and gap-preserving edition exports. Real urllib multipart/JSON/history/view
round trips run against a local HTTP server double. No global interruption or unrelated queue deletion occurs.

Two simulation gaps were corrected. scipy iterations=0 previously dilated to convergence; zero now preserves
the mask, and negative values erode. Saved JSON now appears directly in MangaSaveReview UI/API output,
including its relative file identity. Real failure-path tests verify this remains available before downstream
PreviewAny executes. The existing STRING result and native previews are retained.

During development one mixed run left a stale `submitting` checkpoint despite partial review files. Its
underlying cause was not isolated; a single-case trace and fresh full mixed traces did not reproduce it.
The controller now re-reads each persisted final state before allowing the next submission, and a fault-
injection regression verifies that an omitted final checkpoint pauses rather than continuing. The final full
suite, including the mixed-folder subprocess, passes. This is not a live-server durability guarantee.

A real CPU font probe confirms the remaining number-gutter issue: 540 translated-alpha pixels land inside
the preserved marker rectangle when a shared frame includes it. The probe records this as a known limitation,
not a pass for layout quality. Mixed heading styles, styled-cover automatic detection, semantic OCR/translation
accuracy, cross-page context and project GUI review remain outside the implemented guarantees.
The user-provided single-page save success is live evidence for that guide; this folder feature has not been
run against the user's ComfyUI/GB10 services here. No supplied source images or OCR text enter the repository.
See [commands, exception policy and precise limits](docs/project-processing-v0.3.12.md).
