# 검증 범위

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
python tools/build_lettering_examples.py
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
