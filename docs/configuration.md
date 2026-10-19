# 모델과 처리 설정

[목차](README.md) · [사용법](usage.md)

아래 기본값은 노드 함수의 모든 기본값이 아니라 **배포된 통합 08** 기준입니다. 이전에 저장한 캔버스의 값은 다를 수 있습니다.

## 모델과 의존성

- RF-DETR 검출 번들과 선택한 OCR 번들이 필요합니다. 검출은 기존 CUDA 경로를 유지하며 새 OCR 선택 노드는 auto/cuda/cpu를 지원합니다.
- 번역은 ComfyUI 서버에서 접근 가능한 OpenAI-compatible LLM 서버를 연결합니다.
- 원문 제거는 설치된 Qwen 모델과 `TextEncodeQwenImage21`, `QwenImage21Cache`, `ManualSigmas`, 로더·샘플러·VAE 노드를 사용합니다. 다른 제거 모델은 해당 서브그래프에 맞게 교체해야 하며 파일 이름만 바꾸면 호환되지 않습니다.
- [requirements.txt](../requirements.txt)는 런타임 의존성입니다. Koharu 앱·Rust 렌더러·중계 서비스는 필요하지 않습니다.

필요한 의존성이 없다면 **ComfyUI가 실제 사용하는 Python**으로 `python -m pip install -r requirements.txt`를 실행합니다. 운영 환경을 갱신하기 전에 기존 torch/CUDA와 모델 어댑터의 호환성을 확인합니다.

완전한 모델 번들의 위치:

```text
ComfyUI/models/manga_translator/detection/<bundle>/
ComfyUI/models/manga_translator/ocr/<bundle>/
```

| 번들 | 필요한 파일 |
| --- | --- |
| 검출 | model.safetensors, load_model.py, inference_config.json |
| Hayai | model.safetensors, config.json, configuration_hayai.py, modeling_hayai.py, tokenizer.json, vision-config.json |

로더는 핀된 파일 해시 또는 호환 `model-files.json`을 검사합니다. 파일 하나만 옮기거나 코드·설정 이름만 바꿔 넣지 않습니다. 기존 `models/koharu/detection`, `models/koharu/ocr`와 등록된 `koharu_detection`, `koharu_ocr`는 읽기 전용 호환 조회를 지원합니다. 가중치는 저장소/ZIP에 포함하지 않습니다. 새 OCR 선택 노드에서는 누락된 고정 번들만 자동으로 내려받습니다. 기존 수동 로더는 유지합니다.

## OCR 엔진과 다운로드

`OCR 엔진 · 모델 자동 준비`의 `engine`에서 선택합니다.

| 옵션 | 용도와 제한 |
| --- | --- |
| Hayai v2 · 기본 | 기존 고정 Hayai 경로. 기하·반복·미인식 검사는 계속 적용 |
| Manga OCR · Japanese | 일본어 만화 인식 대안. 224×224 모델 입력, 한국어/중국어용 엔진으로 취급하지 않음 |
| download_missing=true | 누락 번들을 임시 폴더에 받고 모든 파일 SHA256 확인 후 원자적으로 설치 |
| device=auto | CUDA가 있으면 CUDA, 없으면 CPU. CPU는 느릴 수 있음 |

모델 경로는 `models/manga_translator/ocr/hayai-ocr-v2` 또는 `manga-ocr-base`입니다. Hayai의 기존 고정 번들은 먼저 조회합니다. 불완전하거나 수정된 폴더는 덮어쓰지 않으며 보존/이름 변경 후 다시 실행합니다. 네트워크/DNS/체크섬 실패는 해당 모델 노드에서 확인할 수 있습니다. 다운로드 진행 파일·용량은 노드 안에 표시됩니다. 글자 없는 페이지는 OCR 로더까지 생략합니다.

Manga OCR은 `kha-white/manga-ocr-base`의 고정 revision `aa6573bd10b0d446cbf622e29c3e084914df9741`을 사용합니다. bin 체크포인트의 안전한 weights_only 로딩을 위해 torch 2.6 이상이 필요합니다. Python 패키지나 torch/CUDA를 노드에서 자동 설치/교체하지 않습니다. 두 엔진의 출력 일치나 휴리스틱 통과가 정답을 보증하지 않습니다.

## 번역문 방향

입력 옆 **번역문 방향** 노드의 `lettering_direction`을 선택합니다. 폴더 전체에 같은 선택이 적용됩니다.

| 선택 | 동작 |
| --- | --- |
| 가로 통일 · 기본 | 모든 번역문을 가로로 배치 |
| 세로 통일 · 오른쪽 열부터 | 모든 번역문을 세로로, 오른쪽 열부터 배치 |
| 세로 통일 · 왼쪽 열부터 | 모든 번역문을 세로로, 왼쪽 열부터 배치 |
| 원문 따라 자동 | 영역별 원문 픽셀에서 추정한 방향 사용 |

자동은 원문의 방향을 완벽하게 복제하는 기능이 아닙니다. OCR의 `text_direction`과 번역문 식자 방향은 별개이며 방향 통일 노드는 OCR 입력을 바꾸지 않습니다. 가로·세로 통일은 영역별 반대 방향 설정보다 우선합니다.

## 검출과 OCR

| 위치 / 옵션 | 08 기본값 | 의미 |
| --- | --- | --- |
| 효과음·표지 큰 글자 포함 | false | 검출·영역·마스크에 공통 적용. 제외 관측 수는 타일 중복을 포함합니다. |
| MangaDetectorDetail.detail_mode | auto | 큰 페이지에서 native/detail 창을 제한된 예산으로 사용 |
| boundary_policy | preserve_review | 경계 복구 불가 영역을 보존·검수. strict는 중단 |
| MangaRegionCrops.ocr_padding / edit_margin | 4 / 12px | OCR 크롭과 편집 여백을 별도로 관리 |
| refine_page_columns / auto_deskew | true / true | 확인된 다단 본문 정리와 회전 글줄 계획 |
| geometry_policy | preserve_review | 잘린 글줄의 원본 문맥 복구 실패 시 보존·검수. strict는 중단 |
| MangaOCRAdaptive.max_new_tokens | 256 | 한 OCR 생성의 최대 토큰 수 |
| base_patches / small_text_patches | 256 / 512 | 일반 / 작은 글자 입력 예산 |
| small_text_px | 48 | 작은 입력의 패치 배정 기준 |
| line_split / split_long_lines | true / true | 행과 긴 줄 분할 |
| tight_crop | false | 과도한 타이트 크롭을 기본으로 하지 않음 |
| quality_guard | true | 반복·미인식·누락 의심 등 휴리스틱 검사 |
| text_direction | auto | OCR 입력의 행/열 추정 |

반복·토큰·품질·레이아웃 재시도는 제한된 횟수만 수행합니다. 패치/토큰 수를 늘린다고 인식 정확도가 보장되지 않습니다. `issue=null`도 정답 판정이 아닙니다. 원본 문맥에서 같은 글줄을 완성하지 못하면 추측한 문장으로 진행하지 않습니다.

## 번역 서버와 수동 번역

`번역 · 기존 LLM 서버` 노드에서 설정합니다.

| 옵션 | 기본값 / 의미 |
| --- | --- |
| base_url | http://127.0.0.1:8000/v1 — 같은 호스트의 서버일 때만 유효 |
| model | 정확한 서버 ID. 비워두면 /models에 모델이 하나일 때만 자동 선택 |
| target_language | `책 용어집` 노드에서 Korean 설정, 번역 노드로 연결 |
| api_key_env | MANGA_LLM_API_KEY — 키는 ComfyUI 프로세스의 환경변수로 전달 |
| max_tokens / timeout | 4096 / 300초 |
| response_format | json_schema |
| length_recovery | split — 출력 한도 도달 시 ID 묶음 분할. stop은 즉시 중단 |
| request_budget | 16 — 최초 생성·형식 재시도·길이 복구를 합친 최대 요청 수. 1–32 |

`json_schema`는 페이지의 ID·개수·필드를 요청에 지정합니다. 서버가 지원하지 않으면 `json_object` 또는 `prompt_only`를 명시적으로 선택합니다. 자동으로 제약을 해제하지 않습니다. 응답 후 클라이언트의 JSON/ID/문자열 검사도 수행하며 JSON/영역 계약 실패만 한 번 재생성합니다. HTTP 실패·빈 답변·비정상 종료의 부분 결과는 채택하지 않습니다.

`finish_reason=length`이면 잘린 응답은 파싱·이어쓰기·부분 저장에 사용하지 않습니다. 기본 split은 영역 ID 묶음을 반으로 나누고 전체 페이지 원문·용어집·검수 문맥을 유지해 다시 요청합니다. 단일 영역은 한 번만 재생성하며 max_tokens는 자동으로 늘리지 않습니다. 모든 묶음의 ID와 번역이 검증돼야 페이지 결과를 반환합니다. 단위별 target은 2,048자 한도입니다. 요청 예산 소진·서버 오류·미해결 응답은 진단과 함께 중단합니다.

번역문은 일반 텍스트입니다. 번역기가 새로 만든 `<br>` 계열은 실제 개행으로 정규화하고, 미해결 `<UNK>` 계열은 거부합니다. 임의 HTML 전체를 지우지는 않습니다.

`translated_override_json`에 다음을 넣으면 번역 API를 호출하지 않습니다. ID와 개수는 해당 페이지 원문과 일치해야 합니다.

```json
{"translations":[{"id":"r1","target":"확정한 번역문"}]}
```

일반 Run은 마지막까지 진행합니다. 결과를 보고 `원문 검수`/`번역 검수` 노드의 입력란에서 고친 뒤 다시 Run합니다. 수정은 `edits_json.pages`에 내용 revision별로, 소유권은 `identities`에 프로젝트·페이지별로 저장합니다. 입력 노드의 상태 출력이 두 검수 노드의 `page_context_json`에 연결되어야 합니다. 새 통합 08에 연결되어 있으며, 기존 캔버스는 새 JSON을 가져오거나 이 두 연결을 추가하세요. 입력·원문·기하가 달라지면 이전 교정을 자동 적용하지 않고 안내하며, 진단 정보만 바뀌면 교정을 유지합니다. 이전 형식의 교정 JSON은 보존하지만 소유권을 확인할 수 없어 자동 적용하지 않습니다. 내용을 확인해 새 입력란에서 다시 저장하세요. 제목/본문은 블록별로 수정하며 각 번역 블록에 2,048자 한도를 적용합니다. 원문 수정은 오래된 번역과 편집 계획을 무효화합니다.

폴더에서 한 페이지 교정은 그 페이지의 새 시도만 선택합니다. 폰트·방향 등 공통 처리 설정 변경은 각 페이지의 저장된 처리 revision과 대조하므로, 일부 처리 후 중지·재개해도 남은 이전 설정의 페이지를 선택합니다. 이전 시도와 결과는 보존합니다. 다른 탭에서 같은 프로젝트를 시작하면 기존 실행의 소유권과 완료 티켓을 유지하고 두 번째 요청을 중단합니다.

`이 페이지 번역 확정`은 사람이 확인한 번역에만 사용합니다. 확정 후 다시 Run해 저장한 결과만 다음 페이지 문맥의 후보가 됩니다. 용어집은 `[ {"source":"원문 이름","target":"확정 이름","note":"호칭"} ]` 형식입니다. 현재 원문에 등장한 항목과 검증된 이전 페이지 중 사람이 확정한 번역만 예산 내에서 전송합니다. 자동 메모리/요약은 만들지 않습니다.

## 제거·식자와 영역별 설정

원문 제거의 기본값은 512px 소유 코어, 128px 문맥, 최대 64타일입니다. `uniform_fill=true`, `recover_uniform_ink=true`로 확인된 단색 영역을 보완하며 남은 타일만 Qwen에 보냅니다. `strict_cleanup=true`는 잔존 원문 의심 시 중단합니다. `blend_width=8`은 제거 마스크 여유의 경계를 완화하며 원문 획의 제거 강도는 유지합니다.

식자는 `MangaLetterPlan`의 `line_breaks=reflow`, `fit_policy=readable`, `min_font=10`, `min_scale=0.55`, `respect_bubbles=true`가 기본입니다. reflow는 단일 개행을 풀어 폭을 활용하며 빈 줄 문단은 유지합니다. 말풍선은 실제 검출 마스크가 있을 때 제약으로 사용합니다. 공간 부족·보존 영역 침범·이웃 번역 충돌은 오류로 남깁니다.

`bubble_failure_policy=preserve_review`는 말풍선 소유권/공통 내부 공간의 근거가 불확실한 영역과 겹친 이웃을 원본 복원·보호하고 나머지 식자를 진행합니다. `stop` 또는 영역별 `require_bubble=true`는 중단합니다. 마스크를 임의로 합치거나 기존 95% 원문 획 지지 기준을 낮추지 않습니다. 잘못된 입력·분석 예산 초과·일반 공간 부족은 계속 오류입니다. 최종 `lettering_review`가 있으면 폴더는 needs_review이며 보존 영역이 번역 완료된 것은 아닙니다.

새 옵션은 최신 통합 08을 가져오면 보입니다. 구형 캔버스의 누락 옵션은 기본값을 사용하며, 기존 URL·모델·폰트 설정은 확인 후 옮깁니다.

영역별 `region_options_json` 예:

```json
{"r1":{"line_breaks":"preserve","font_cap":28},"r2":{"rotation":8,"bend":12}}
```

`rotation`, `shear`, `bend`는 수동으로 조절할 수 있습니다. 기하가 확인된 가로 글줄은 OCR과 같은 원문 회전각이 식자에 전달됩니다. 자동 곡선 복원이나 원본 폰트 식별은 지원하지 않습니다. `페이지 편집 계획`의 `region_actions_json={"r1":"preserve"}`는 해당 영역을 제거·새 식자 대상에서 제외합니다.

새 08의 `oriented_fit=true`는 회전된 로컬 사각형에서 식자한 뒤 페이지로 옮깁니다. 파란 다각형은 식자 프레임, 주황 박스는 원본 페이지 작업 범위입니다. 실제 새 글자 알파는 식자 결과 이미지에서 확인합니다. 말풍선·보존 픽셀·이웃 충돌 검사는 변환 후에도 적용됩니다. 제목/본문은 검증된 행 높이 차이가 있을 때만 자동 분리합니다. 폰트 자동 식별이나 일반 문서 역할 분류기는 아닙니다.

## 단계 결과 재사용

검출·번역·지운 배경 checkpoint와 OCR 노드의 크롭별 캐시는 원본 전체 픽셀과 해당 단계의 모델/설정/문맥으로 식별합니다. `reuse`는 검증된 저장 결과를 쓰고, `refresh`는 해당 단계를 다시 계산해 저장하며, `off`는 저장하지 않습니다. 저장 위치는 `output/manga_translator/stage_cache`입니다. 손상/미완성 캐시는 재사용하지 않습니다. 개별 항목 256 MiB를 넘으면 저장을 생략합니다.

폰트/번역문 방향 변경은 앞 단계 결과를 유지합니다. 원문 수정은 번역부터 다시 계산합니다. 번역 수정은 실제 제거 계획이 같으면 지운 배경을 유지하고 식자를 다시 계산합니다. 캐시는 의미 정확도 판정이 아닙니다. OCR 엔진/처리 코드를 바꾸면 이전 OCR 결과를 같은 것으로 취급하지 않습니다.

외부 번역 서버가 같은 `model` ID로 가중치를 바꾸면 클라이언트가 자동으로 알아낼 수 없습니다. 번역 노드의 `model_revision`을 바꾸거나 번역 checkpoint를 `refresh`로 실행하세요. 로컬 검출/Qwen 파일은 내용 SHA256으로 캐시 신원을 구분하며 파일 stat이 같으면 프로세스 안에서 계산한 해시를 재사용합니다.

OCR 재인식은 `MangaOCRAdaptive.cache_policy=refresh`로 실행합니다. 별도의 집계 문서 캐시를 겹치지 않아 새 OCR 결과가 오래된 페이지 JSON에 가려지지 않습니다. OCR 엔진/입력/분할/생성 설정과 원본 크롭 픽셀을 함께 식별합니다.
