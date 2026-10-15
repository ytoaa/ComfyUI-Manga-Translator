# 검증 범위

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
