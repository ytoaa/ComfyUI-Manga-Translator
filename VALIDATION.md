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
