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
