# ComfyUI-Manga-Translator

ComfyUI에서 원문 검출 → OCR → 번역 → 이미지 모델 편집 → 최종 저장을 연결하는 초기 커스텀 노드 패키지. 첫 예제는 RF-DETR, Hayai OCR v2, 기존 번역 LLM 서버, Qwen Image 2.1 Turbo를 사용한다. Koharu 실행파일과 Rust 렌더러는 필요하지 않다.

**현재 상태: 초기 버전. ComfyUI 프런트엔드 1.53.10에서 예제 8개의 가져오기·설정 복원·저장 후 재불러오기·API 직렬화를 모델 백엔드 대역으로 검사했다. 실제 GPU OCR/검출, 번역 서버, 이미지 편집 결과는 미검증이다.** 검증 범위는 [VALIDATION.md](VALIDATION.md)에 기록한다. 선행 프로젝트와 엔진 비교는 [조사 문서](docs/reference-research.md)에 있다.

## 원본 참조 스타일 식자 추가

원본 잉크색·외곽선·미세 질감을 측정하고 실제 한글 폰트로 번역문을 그리는 **스타일 식자 노드 11개와 예제 6개**를 추가했다. 가로/세로쓰기, 글자 크기 맞춤, 최대 행/열 수, 회전·기울기·그림자를 조절한다. 최종 합성은 원문 마스크가 아니라 새 번역문 알파를 사용한다. **원본 폰트 자동 복제 모델은 아니며** 실제 만화 품질과 GPU 실행은 미검증이다.

기존 01/02 그래프는 그대로 유지한다. 추가 전체 흐름은 `lettering/example_workflows/05-rfdetr-ocr-cleanup-lettering.json`과 `06-manual-ocr-cleanup-lettering.json`이다. 기존 검출/OCR/번역 JSON을 그대로 연결하되 Qwen에는 원문 제거만 맡기고, 번역문 생성은 별도 식자 단계가 담당한다. 모델 없이 확인할 합성 테스트 입력·워크플로도 포함했다. 설치·사용·제약은 [스타일 식자 안내](docs/style-lettering.md)를 참고한다.

2026-10-15 설정 로드 오류 수정: 연결 전용 문자열을 일반 위젯으로 생성해 번역 URL·모델·언어·토큰 수가 밀리던 선언을 수정했다. 업데이트 후 ComfyUI를 재시작하고 제공된 워크플로를 다시 가져온다. 기본 노드가 있는 기능은 기본 노드를 사용하며, 01/03/04 식자 예제의 크롭과 최종 합성은 ImageCrop·CropMask·ImageCompositeMasked로 구성한다.

## 설치

1. 이 저장소 폴더를 `ComfyUI/custom_nodes/ComfyUI-Manga-Translator`에 둔다. 저장소 루트의 `__init__.py`가 바로 보이는 구조다.
2. 기존 ComfyUI Python 환경을 사용한다. RF-DETR/Hayai를 이전에 실행한 환경이라면 모델 어댑터 의존성이 이미 있을 수 있다. [requirements.txt](requirements.txt)는 어댑터 요구사항이다. 설치 전에 기존 torch/CUDA/Transformers 버전과 충돌 여부를 확인하고, 현재 동작 중인 환경을 임의로 업그레이드하지 않는다. 이 패키지는 런타임에 설치·다운로드를 수행하지 않는다.
3. ComfyUI를 재시작하고 브라우저를 새로고침한다.
4. `workflows/01-rfdetr-hayai-qwen21.json`을 ComfyUI로 가져온다. `.api.json`은 API 제출용이며 캔버스 가져오기는 일반 `.json`을 쓴다.
5. `원본 이미지`에서 입력 이미지를 업로드하고, 로더에서 실제 설치된 모델을 선택한다.

Git으로 설치할 경우 ComfyUI의 `custom_nodes` 폴더에서:

```bash
git clone https://github.com/ytoaa/ComfyUI-Manga-Translator.git
```

필요한 Qwen 예제 노드: `TextEncodeQwenImage21`, `QwenImage21Cache`, `ManualSigmas` 및 표준 로더/샘플러/VAE 노드. 이전에 사용한 Qwen 2.1 워크플로우와 같은 노드다. 누락되면 지원되는 ComfyUI/관련 노드가 필요하다. 다른 모델 이름을 넣어 이 노드와 호환시키는 방식은 지원하지 않는다.

## 모델 번들

아래 폴더에 기존 완전한 번들을 연결하거나 배치한다. 가중치 파일을 따로 다운로드하거나 옮기지는 않는다.

```text
ComfyUI/models/manga_translator/detection/<bundle>/
ComfyUI/models/manga_translator/ocr/<bundle>/
```

검출 번들은 `model.safetensors`, `load_model.py`, `inference_config.json`이 필요하다. Hayai는 `model.safetensors`, `config.json`, `configuration_hayai.py`, `modeling_hayai.py`, `tokenizer.json`, `vision-config.json`이 필요하다. 로딩 시 핀된 SHA 또는 호환 번들 매니페스트를 검증한다.

기존 `models/koharu/detection`, `models/koharu/ocr` 및 등록된 `koharu_detection`, `koharu_ocr` 경로는 **읽기 전용 호환 조회**를 지원한다. 기존 `koharu_nodes`를 import하거나 그 저장소에 실행을 위임하지 않는다. 검사 실패를 피하기 위해 가중치나 모델 코드를 임의로 이름만 바꿔 넣지 않는다.

## 두 워크플로우

### 01: 자동 검출 + OCR + 번역 + 편집

`LoadImage → RF-DETR → 박스 중복 제거 → 영역 자르기 → Hayai OCR → 원문 JSON → 번역 LLM → 번역 JSON → 이미지 편집 지시 → Qwen 2.1 Turbo → 편집 영역 합성 → SaveImage`

Qwen-VL 서버는 필요하지 않다. RF-DETR의 글자 박스를 OCR용으로 사용한다. 효과음은 `include_sfx`로 선택하며 기본은 꺼짐이다. 정렬은 단순 좌표 순서여서 복잡한 컷의 의미적 읽기 순서를 보장하지 않는다.

### 02: 수동 영역 + OCR + 번역 + 편집

`workflows/02-manual-regions-hayai-qwen21.json`은 RF-DETR 없이 실행한다. **기본 좌표는 대화에 첨부된 선생님 소개 이미지에 맞춘 예시**다. 다른 페이지에는 `OCR 자르기 · 편집 영역`의 `layout_json`을 수정한다. `examples/sample-layout.json`을 참고한다. 좌표는 `[왼쪽,위,오른쪽,아래]`, 각각 이미지의 0–1000 범위로 정규화한다. 목록 순서대로 OCR과 번역이 연결된다.

OCR 입력은 크롭별 리스트로 전달한다. Hayai의 반복·토큰 한도 오류는 중단으로 표시하고, 반복 오류만 제한적으로 한 번 재시도한다. 한 영역이 너무 길면 영역을 더 나누거나 OCR 설정을 조정한다. 부분 OCR 결과를 정상 번역으로 조용히 처리하지 않는다.

## 번역 설정과 수동 검수

- `번역 · 기존 LLM 서버`의 `base_url`을 **ComfyUI가 실행되는 서버에서 접근 가능한** 기존 OpenAI-compatible `/v1` 주소로 설정한다. 기본 `http://127.0.0.1:8000/v1`은 같은 호스트의 서버용이다.
- `model`은 정확한 서버 모델 ID다. `/models`에 모델이 하나만 있으면 빈칸으로 자동 선택할 수 있다.
- 인증이 필요하면 ComfyUI 프로세스 환경변수 `MANGA_LLM_API_KEY`를 사용한다. 실제 키는 워크플로우 JSON이나 저장소에 넣지 않는다.
- 기본 번역 언어는 Korean이다. 원문 전체 영역을 한 요청으로 보내 문맥을 공유하며, 모든 ID가 돌아왔는지 검사한다.
- 번역 응답은 완전한 JSON 하나를 요구한다. Markdown 코드블록의 닫는 표시만 없고 JSON이 완전한 경우에는 읽을 수 있다. JSON 문법·영역 ID 검증 실패 시 원본 OCR/ID를 다시 보내 번역만 한 번 재시도하며, 두 번 실패하면 중단한다. `finish_reason=length` 등 비정상 종료나 답변 내용 누락은 부분 결과로 처리하지 않는다. 로그에는 종료 사유·출력 토큰 수·문자 수를 기록하며 원문/번역문 전체는 기록하지 않는다.
- 기존 번역문을 직접 넣으려면 `translated_override_json`에 다음 형식으로 입력한다. 이 값이 있으면 번역 서버를 호출하지 않는다. ID는 해당 실행의 원문 JSON과 모두 일치해야 한다.

```json
{"translations":[{"id":"r1","target":"확정한 번역문"}]}
```

일반 Run은 모든 단계를 이어서 실행한다. 자동으로 사람의 승인을 기다리는 단계는 없다. OCR/번역을 먼저 검수하려면 해당 단계만 출력에 연결해 실행하거나 마지막 편집 출력 연결을 잠시 끊고 JSON을 확인한 뒤, 수동 override에 확정 번역문을 넣는다.

## 편집 범위와 결과

`ocr_padding`은 OCR 크롭 여유, `edit_margin`은 **이미지 편집 결과를 적용할 사각형 영역의 여유**다. 원래 글자 윤곽 마스크는 사용하지 않는다. 편집 결과를 원본 크기로 맞추고 영역 바깥은 원본 픽셀을 유지한다. 영역 안의 그림·배경 보존은 모델 품질과 영역 선택에 달려 있다. 번역문이 사각형 밖으로 넘어가면 잘릴 수 있으므로 여유와 프롬프트를 조정한다.

Qwen은 원본의 글자색·제목/본문 구분·배치를 참고해 편집하도록 지시받는다. 별도 클린업 모델이나 테두리 추정 코드는 거치지 않는다. 현재 예제는 기존 Turbo의 8-step sigma, Euler, CFG 1 설정을 그대로 따른다.

참조 이미지 `resolution` 기본은 1024이며 비율을 유지해 약 1024² 픽셀 규모로 맞춘다. 0으로 바꾸면 원본 크기를 32픽셀 배수로 맞춘다. 작은 원본에서 긴 한국어 문장을 편집하는 경우 해상도 설정을 비교하고, 큰 페이지는 VRAM과 소요 시간도 함께 확인한다.

- 최종 PNG: `ComfyUI/output/manga_translator/final_*.png`
- 원문 JSON: `ComfyUI/output/manga_translator/ocr_*.json`
- 번역 JSON: `ComfyUI/output/manga_translator/translation_*.json`
- 크롭과 Qwen의 원시 출력은 PreviewImage에서 비교한다.

한국어 오타·누락, 영역 대응 오류, 원문 잔상, 그림 변형, 경계의 색 차이를 직접 검수해야 한다. 자동 생성 결과 OCR 재검증이나 실패 영역 자동 재생성은 아직 구현하지 않았다.

## 모델 교체

OCR는 `STRING`을 반환하는 다른 노드로 바꿀 수 있으며 영역 수·순서를 보존해야 한다. 비전은 새 모델의 결과를 같은 영역 JSON으로 변환하면 된다. 번역은 `/v1/chat/completions` 호환 서버를 교체한다. 최종 편집 모델은 `edit_prompt`와 원본 IMAGE를 입력받도록 인코더·로더·샘플러 부분을 교체한다.

Qwen-VL은 추후 영역 분석·문맥 판단용 선택 사항이다. Qwen Edit이 구조화 좌표를 반환한다거나, 현재 RF-DETR보다 낫다고 가정하지 않는다. [비교 근거](docs/reference-research.md)를 참고한다.

## 출처와 라이선스

새 연결 코드와 전체 출처는 [LICENSE](LICENSE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [provenance.json](provenance.json)에 기록한다. 포함된 RF-DETR/Hayai 어댑터는 기존 공개 프로젝트에서 가져와 고지를 보존한다. 모델 가중치는 포함하지 않으며 각 배포자의 별도 조건이 적용된다.
