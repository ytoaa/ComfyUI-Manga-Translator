# 초기 선행 프로젝트 조사 · 보존 기록

2026-10 개발 중 작성한 소스 조사 기록이다. 외부 프로젝트의 현재 상태를 다시 조사한 결과가 아니며, 아래 초기 설계안은 현재 동작 명세가 아니다. 현재 구조는 [아키텍처](../architecture.md), 지원 범위는 [알려진 한계](../known-issues.md)를 따른다.

# 유사 프로젝트 조사

조사일: 2026-10-14. README뿐 아니라 주요 구현 파일과 저장소 라이선스를 직접 확인했다. 아래 프로젝트를 이 환경에 설치하거나 같은 이미지로 품질·속도를 비교한 것은 아니다.

## 가장 가까운 선행 구조

**[hgmzhn/manga-translator-ui](https://github.com/hgmzhn/manga-translator-ui)**의 AI renderer가 이번 목표와 가장 가깝다. OCR·번역 뒤 원본 페이지와 원문/번역문 목록을 이미지 생성 API로 보내, 완성된 페이지를 받는다. OpenAI와 Gemini 렌더러를 제공하며 AI renderer 사용 시 별도 인페인팅을 건너뛰는 경로가 있다. 원문을 위치 대응의 힌트로 쓰고, 번역문 누락과 페이지 변경을 막도록 지시한다. ComfyUI 노드 프로젝트는 아니다. GPL-3.0 코드다.

직접 확인한 출처: [AI renderer 설명](https://github.com/hgmzhn/manga-translator-ui/blob/main/doc/wiki/en/desktop/prompts/ai-renderer-prompt.md), [구현](https://github.com/hgmzhn/manga-translator-ui/blob/main/manga_translator/rendering/model_api_renderer.py), [라이선스](https://github.com/hgmzhn/manga-translator-ui/blob/main/LICENSE.txt).

이번 프로젝트에서는 이 **설계 방식**을 참고한다. 해당 구현이나 기본 프롬프트는 복사하지 않는다. ComfyUI에서 원본과 확정 번역문을 이미지 편집 노드에 연결한다. 정사각형 패딩이나 원본 글자 스타일 추정은 새 공통 파이프라인에 강제하지 않는다.

## 비교한 다른 프로젝트

| 프로젝트 | 확인한 특징 | 참고할 지점 | 저장소 코드 라이선스 |
|---|---|---|---|
| [ogkalu2/comic-translate](https://github.com/ogkalu2/comic-translate) | 다양한 만화·언어의 검출/OCR/인페인트/LLM 번역/렌더링을 구분한 앱 | 엔진 교체 경계, 단계별 책임과 편집 흐름 | [Apache-2.0](https://github.com/ogkalu2/comic-translate/blob/main/LICENSE) |
| [dmMaze/BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) | 자동 번역과 수동 마스크·텍스트 편집, 원문 서식 추정, 문맥/용어집 지원 | OCR·번역 수정, 용어 일관성, 검수 UX | [GPL-3.0](https://github.com/dmMaze/BallonsTranslator/blob/dev/LICENSE) |
| [zyddnys/manga-image-translator](https://github.com/zyddnys/manga-image-translator) | 검출/OCR/번역/복원/조판이 분리된 CLI·서버 파이프라인 | 단계별 결과 저장, 엔진 선택 및 실행 경계 | [GPL-3.0](https://github.com/zyddnys/manga-image-translator/blob/main/LICENSE) |
| [meangrinch/MangaTranslator](https://github.com/meangrinch/MangaTranslator) | 말풍선 밖 글자도 처리; 확산 모델로 복원하고 폰트로 조판 | 말풍선과 배경 글자의 처리 구분, 영역별 품질 설정 | [Apache-2.0](https://github.com/meangrinch/MangaTranslator/blob/main/LICENSE) |
| [1038lab/ComfyUI-QwenVL](https://github.com/1038lab/ComfyUI-QwenVL) | ComfyUI 안에서 비전 언어 모델을 실행; Transformers/GGUF 경로와 예제 워크플로우 | 추후 선택형 의미·레이아웃 분석 노드 연결 | [GPL-3.0](https://github.com/1038lab/ComfyUI-QwenVL/blob/main/LICENSE) |
| [kijai/ComfyUI-Florence2](https://github.com/kijai/ComfyUI-Florence2) | ComfyUI에서 캡션/검출/세그멘테이션/문서 질의응답 등 비전 작업 | Qwen 이외 비전 모델을 연결하는 대안 | [MIT](https://github.com/kijai/ComfyUI-Florence2/blob/main/LICENSE) |
| [stavsap/comfyui-ollama](https://github.com/stavsap/comfyui-ollama) | 서버 연결·LLM 옵션·생성/채팅을 구분하고 비전·구조화 결과 예제 제공 | 모델 서버와 워크플로우의 분리, 범용 텍스트 연결 | [Apache-2.0](https://github.com/stavsap/comfyui-ollama/blob/main/LICENSE) |

이들 라이선스는 저장소 코드에 대한 확인이다. 모델 가중치·데이터·개별 포함 구성요소의 조건까지 동일하다는 뜻은 아니다. 이번 패키지에는 위 비교 대상의 소스나 모델을 포함하지 않는다. 코드 도입 시 대상 파일의 고지와 조건을 따로 확인해야 한다.

## ComfyUI 전용 추가 조사

GitHub 저장소 검색을 README까지 확장해 ComfyUI 노드와 ComfyUI 연동 편집기를 추가로 확인했다. 아래 사례는 설치·실행 검증 없이 소스와 문서를 확인한 결과다.

| 프로젝트 | 실제로 확인한 기능 | 이번 목표와의 차이 |
|---|---|---|
| [banqingyuan/ComfyUI-text-replace](https://github.com/banqingyuan/ComfyUI-text-replace) | 등록된 네 노드: OCR Location, Image Erase, Chat Overlay, Extract JSON. OCR은 Baidu API를 사용하고 Overlay는 Pillow 폰트로 글자를 그린다. | ComfyUI 안에서 글자 위치·제거·덮어쓰기를 연결하는 가장 가까운 부분 사례. 이미지 편집 모델이 번역문 조판까지 맡는 완성형은 확인하지 못했다. 저장소 트리에 README와 LICENSE 파일이 없어 코드는 도입하지 않는다. |
| [chflame163/ComfyUI_LayerStyle_Advance](https://github.com/chflame163/ComfyUI_LayerStyle_Advance) | Florence2 기반 객체 박스, 마스크 관련 노드, GeminiImageEdit 노드와 편집 예제 JSON. | 비전 분석과 이미지 편집을 ComfyUI에서 연결하는 구성요소 참고. 만화 OCR·번역·검수 전체 자동 파이프라인으로 확인한 것은 아니다. |
| [new-sankaku/manga-editor-desu](https://github.com/new-sankaku/manga-editor-desu) | 웹 만화 편집기, 텍스트·말풍선·레이어 편집, ComfyUI 생성/인페인트/사용자 워크플로우 연결. | ComfyUI와 연동하는 시각적 편집기 참고. ComfyUI 자체의 만화 번역 노드 팩과는 다르다. |
| [Kataage/ComfyUI-Manga-Autopilot](https://github.com/Kataage/ComfyUI-Manga-Autopilot) | 아이디어에서 만화 구성·패널 생성·글자·내보내기를 이어가는 ComfyUI 확장. | 기존 만화의 언어 번역보다는 새 만화 제작 목적이다. 프로젝트/단계 상태·편집 UI 설계를 참고할 수 있다. |

첫 사례는 [노드 등록](https://github.com/banqingyuan/ComfyUI-text-replace/blob/main/__init__.py), [OCR 노드](https://github.com/banqingyuan/ComfyUI-text-replace/blob/main/nodes/ocr_loc_node.py), [글자 덮어쓰기](https://github.com/banqingyuan/ComfyUI-text-replace/blob/main/nodes/chat_overlay_node.py)를 직접 확인했다. 따라서 ComfyUI 관련 사례가 없다는 뜻은 아니다. 이번 조사에서 **현재 요구한 OCR 보존 + 확정 번역문 + 교체 가능한 이미지 편집 모델의 최종 합성**을 즉시 대체할, 실행 검증된 완성형 노드 팩은 확인하지 못했다.

위 네 프로젝트의 코드·폰트·모델은 새 저장소에 복사하지 않았다.

## 현재 비전과 Qwen-VL 비교

현재 RF-DETR은 만화의 `text`, `onomatopoeia`, `bubble`, `panel` 네 종류를 검출하고 박스와 인스턴스 마스크를 반환한다. OCR이나 의미적 읽기 순서는 반환하지 않는다. 배포자의 검증에서는 1,001페이지 Manga109 검증 세트에서 박스 mAP50–95 0.7969, 글자 클래스 박스 AP 0.8779, 마스크 mAP50–95 0.5713이다. 제목·크레딧·효과음·복잡한 콜라주에 대한 한계도 명시돼 있다. [RF-DETR 모델 카드](https://huggingface.co/mayocream/koharu-layout-rfdetr-seg-2xl-1152)

Qwen3-VL은 공간 grounding, 문서 구조 분석, 다국어 OCR 등 더 넓은 비전·언어 작업을 제공한다. 생성형 좌표/설명을 실제 픽셀 마스크로 바꾸는 단계는 별도로 필요하다. 위 RF-DETR과 **같은 만화 검증 세트·입력 해상도·장비로 비교한 근거는 이번 조사에서 확인하지 못했다**. 따라서 Qwen-VL이 더 정확하거나 빠르다고 단정하지 않는다. [Qwen3-VL 공식 설명](https://github.com/QwenLM/Qwen3-VL)

Qwen Image Edit/2.1은 이미지와 편집 지시를 받아 결과 이미지를 만드는 모델이다. 공식 API에서 OCR용 구조화 박스·마스크를 반환하는 역할은 확인되지 않는다. 원본과 확정 번역문으로 바로 편집하는 경로에는 별도 Qwen-VL이 필수는 아니다. OCR 영역 자동화에는 기존 RF-DETR을 쓰거나 다른 비전 노드를 연결할 수 있다. [현재 Turbo의 공식 편집 지원](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo)

## 새 저장소 설계 결정

- 이름은 **ComfyUI-Manga-Translator**. 모델 이름을 프로젝트 이름에 고정하지 않는다.
- 원문 검출, OCR, 번역, 편집 지시, 최종 이미지 저장을 구분한다.
- OCR·번역 결과는 영역 ID와 좌표를 포함한 JSON으로 남긴다. 부분 응답·ID 누락을 오류로 처리한다.
- 이미지 편집 모델에는 원본과 확정 번역문을 함께 준다. 공통 코드는 특정 모델의 폰트 추정이나 렌더러에 의존하지 않는다.
- 첫 예제의 편집 모델은 현재 설치된 Qwen 2.1 Turbo다. 다른 모델은 인코더·로더·샘플러 서브그래프를 해당 모델에 맞춰 교체한다. 파일 이름만 바꾸는 방식은 아니다.
- 현재 RF-DETR/Hayai 로컬 어댑터를 독립 패키지로 가져오고 출처를 기록한다. Koharu 앱, Rust scene/renderer, HTTP 브리지는 사용하지 않는다.
- 자동 영역 버전과 수동 영역 버전을 제공한다. Qwen-VL의 새 설치는 이번 첫 버전의 필수 조건으로 만들지 않는다.
- 자동 정렬은 단순 좌표 정렬이다. 의미적인 만화 컷 읽기 순서 예측이나 생성 이미지의 한국어 OCR 재검증은 아직 구현하지 않았다.
- GPU 품질·속도 검증은 워크플로우 가져오기 후 실제 서버에서 수행해야 한다. 로컬 구조/계약 검증을 생성 품질 증거로 취급하지 않는다.
