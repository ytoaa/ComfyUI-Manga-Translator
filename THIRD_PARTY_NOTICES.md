# 출처 및 포함 코드 고지

## 포함한 코드

`adapters/model.py`, `model_files.py`, `model_bundle.py`, `hayai.py`, `hayai_files.py`, `options.py`는 [ytoaa/koharu-remote](https://github.com/ytoaa/koharu-remote)의 `dgx/vision/`에서 가져왔다. 기준 커밋은 `ee6d9ddc82d9bfc4718383272f0e4797f805e2cd`이다. 이 여섯 파일의 내용은 변경하지 않았다. SHA256과 원본 경로는 `provenance.json`에 기록한다.

기존 프로젝트가 기반으로 삼은 공식 [Koharu](https://github.com/koharu-rs/koharu)의 버전은 0.83.5, 커밋은 `52bb4f55e2266f72c1523562a583c827ec191ceb`이다. 그 프로젝트의 MIT/Apache-2.0 라이선스 원문과 저작권 고지를 `LICENSE-THIRD-PARTY-MIT`, `LICENSE-THIRD-PARTY-APACHE`에 보존한다. 기존 모델별 전처리·핀된 로더·검증 코드를 독립 패키지에서 활용하기 위한 출처 고지이며 공식 Koharu의 배포나 보증을 뜻하지 않는다.

원본의 Hi-SAM 코드, Rust scene/renderer, Koharu Windows 앱, 기존 중계 서버는 이 패키지에 포함하지 않는다. 자체 작성한 `models.py`가 위 모델 어댑터를 호출하고 `nodes.py`가 모델과 독립적인 워크플로우 데이터를 연결한다.

## 포함하지 않은 모델 가중치

- RF-DETR: [mayocream/koharu-layout-rfdetr-seg-2xl-1152](https://huggingface.co/mayocream/koharu-layout-rfdetr-seg-2xl-1152), revision `aed55fdb8ca953c6bec33cf6ed6dd52a9b72bfa2`. 모델 카드의 custom/other 조건 및 Manga109 관련 조건을 확인해야 한다.
- Hayai OCR v2: [JustANormalTinkerer/hayai-ocr-v2](https://huggingface.co/JustANormalTinkerer/hayai-ocr-v2), revision `4a4ce477c9a8841f208b94e1d9ed5c0938965e05`. SigLIP2 vision config도 기존 핀과 검증을 사용한다. 모델 저장소의 별도 조건이 적용된다.
- 첫 편집 예제의 Qwen Image 2.1 Turbo: [Qwen/Qwen-Image-2.1-Turbo](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo). Qwen Research License 모델이다. 기존 로컬 ComfyUI의 모델을 사용하며 가중치를 재배포하지 않는다.
- 번역 LLM은 사용자가 설정한 기존 서버의 모델이며 이 저장소에 포함하지 않는다.

ComfyUI의 표준 및 Qwen 노드를 워크플로우에서 참조하지만 ComfyUI 소스를 포함하지 않는다. Python 의존성도 각 배포자의 조건에 따른다.

## 설계 참고만 한 프로젝트

[조사 문서](docs/reference-research.md)에 나열한 `manga-translator-ui`, `comic-translate`, `BallonsTranslator`, `manga-image-translator`, `MangaTranslator`, `ComfyUI-QwenVL`, `ComfyUI-Florence2`, `comfyui-ollama`의 코드·기본 프롬프트·모델·폰트는 가져오지 않았다. 특히 AI renderer의 **구조**를 참고했으며 GPL 코드나 프롬프트를 새 패키지에 복사하지 않았다.

추가 조사한 `ComfyUI-text-replace`, `ComfyUI_LayerStyle_Advance`, `manga-editor-desu`, `ComfyUI-Manga-Autopilot`도 참고 사례이며 그 코드나 포함 폰트를 도입하지 않았다.
