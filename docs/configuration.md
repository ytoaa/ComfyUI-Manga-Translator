# 모델과 처리 설정

[목차](README.md) · [사용법](usage.md)

아래 기본값은 노드 함수의 모든 기본값이 아니라 **배포된 통합 08** 기준입니다. 이전에 저장한 캔버스의 값은 다를 수 있습니다.

## 모델과 의존성

- RF-DETR 검출 번들과 Hayai OCR 번들이 필요합니다. 운영 노드는 CUDA를 사용합니다. CPU 진단은 별도 개발 도구입니다.
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

로더는 핀된 파일 해시 또는 호환 `model-files.json`을 검사합니다. 파일 하나만 옮기거나 코드·설정 이름만 바꿔 넣지 않습니다. 기존 `models/koharu/detection`, `models/koharu/ocr`와 등록된 `koharu_detection`, `koharu_ocr`는 읽기 전용 호환 조회를 지원합니다. 가중치는 저장소/ZIP에 포함하지 않으며 런타임 자동 다운로드도 없습니다.

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
| target_language | Korean |
| api_key_env | MANGA_LLM_API_KEY — 키는 ComfyUI 프로세스의 환경변수로 전달 |
| max_tokens / timeout | 4096 / 300초 |
| response_format | json_schema |

`json_schema`는 페이지의 ID·개수·필드를 요청에 지정합니다. 서버가 지원하지 않으면 `json_object` 또는 `prompt_only`를 명시적으로 선택합니다. 자동으로 제약을 해제하지 않습니다. 응답 후 클라이언트의 JSON/ID/문자열 검사도 수행하며 JSON/영역 계약 실패만 한 번 재생성합니다. HTTP 실패·빈 답변·비정상 종료의 부분 결과는 채택하지 않습니다.

번역문은 일반 텍스트입니다. 번역기가 새로 만든 `<br>` 계열은 실제 개행으로 정규화하고, 미해결 `<UNK>` 계열은 거부합니다. 임의 HTML 전체를 지우지는 않습니다.

`translated_override_json`에 다음을 넣으면 번역 API를 호출하지 않습니다. ID와 개수는 해당 페이지 원문과 일치해야 합니다.

```json
{"translations":[{"id":"r1","target":"확정한 번역문"}]}
```

일반 Run은 사람의 승인을 기다리지 않고 마지막까지 진행합니다. 먼저 검수하려면 해당 단계만 출력하도록 그래프를 구성한 뒤, 확인한 번역을 override로 전달합니다.

## 제거·식자와 영역별 설정

원문 제거의 기본값은 512px 소유 코어, 128px 문맥, 최대 64타일입니다. `uniform_fill=true`, `recover_uniform_ink=true`로 확인된 단색 영역을 보완하며 남은 타일만 Qwen에 보냅니다. `strict_cleanup=true`는 잔존 원문 의심 시 중단합니다. `blend_width=8`은 제거 마스크 여유의 경계를 완화하며 원문 획의 제거 강도는 유지합니다.

식자는 `MangaLetterPlan`의 `line_breaks=reflow`, `fit_policy=readable`, `min_font=10`, `min_scale=0.55`, `respect_bubbles=true`가 기본입니다. reflow는 단일 개행을 풀어 폭을 활용하며 빈 줄 문단은 유지합니다. 말풍선은 실제 검출 마스크가 있을 때 제약으로 사용합니다. 공간 부족·보존 영역 침범·이웃 번역 충돌은 오류로 남깁니다.

영역별 `region_options_json` 예:

```json
{"r1":{"line_breaks":"preserve","font_cap":28},"r2":{"rotation":8,"bend":12}}
```

`rotation`, `shear`, `bend`는 수동으로 조절할 수 있습니다. 기하가 확인된 가로 글줄은 OCR과 같은 원문 회전각이 식자에 전달됩니다. 자동 곡선 복원이나 원본 폰트 식별은 지원하지 않습니다. `페이지 편집 계획`의 `region_actions_json={"r1":"preserve"}`는 해당 영역을 제거·새 식자 대상에서 제외합니다.

검수 화면의 주황 프레임은 페이지 기준 수평 작업 범위입니다. 회전 글줄의 기울어진 외곽선이 아닙니다. 제목·본문 계층 복원과 회전 조판·검수 표시 개선은 [후속 작업](known-issues.md)입니다.
