# ComfyUI-Manga-Translator

v0.6.3은 **글자 성분을 가르지 않는 회전 행 구성**과 **OCR 입력 잘림의 원본 보존·검수**를 추가한다. 투영 봉우리만으로 글줄을 나누지 않고 글자 높이·기준선·검출 지지 범위를 확인한다. `④ OCR 전 단·회전 보정`의 `geometry_policy` 기본값은 `preserve_review`다. 원본 크롭에서 이미 잘린 영역은 OCR·번역·제거 전에 제외하고 `unverified_ocr_geometry`로 기록한다. 읽을 수 없는 원문을 고쳤다는 뜻은 아니며 해당 영역은 번역되지 않고 남는다. [실제 CPU 비교·사용법](docs/ocr-geometry-v0.6.3.md).

v0.6.2는 **고정 가중치의 실제 CPU 검증**에서 확인한 미인식 표시 검사 우회를 보완한다. `<UNK>`·`[UNK]`와 대소문자 변형도 모든 OCR 복구 조각에서 검사하고, 번역이 원문의 개행 대신 새 `{n}` 표시를 만들면 한 번 재생성한다. 검출 6조건·OCR 19케이스 비교에서 잘린 입력·잘못된 행 경계와 정상 입력의 잔여 오독을 함께 확인했다. 임계값·패치 예산을 무조건 낮추거나 높이지 않는다. [실제 응답·재현·한계](docs/cpu-validation-v0.6.2.md).

v0.6.1은 번역기가 추가한 `<br>` 계열 표시를 실제 줄바꿈으로 정규화하고, OCR의 `<UNK_SPAN>` 미인식 표시가 번역·식자로 넘어가는 것을 차단한다. 변환 전 번역문과 변환 개수는 `translation_diagnostics`로 기존 `미리보기 아무거나`에서 확인한다. 08 그래프·위젯은 바뀌지 않아 v0.6.0 프로젝트 이름을 유지할 수 있다. [적용·검증·남은 한계](docs/plain-text-v0.6.1.md).

ComfyUI 캔버스에서 글자 검출 → OCR → 번역 → 원문 제거 → 한글 식자 → 저장까지 실행한다. **제공 워크플로우는 [통합 08 하나](lettering/example_workflows/08-integrated-tiled-cleanup-lettering.json)**다. 첫 입력 노드에서 이미지 한 장과 폴더 프로젝트를 선택한다. 별도 사이드바나 페이지마다 다른 워크플로우는 필요하지 않다.

v0.6.0은 **검출 마스크로 지지되는 기울어진 가로 글줄의 OCR 회전 보정**과 같은 각도의 식자 측정을 추가한다. 새 08의 `MangaRegionCrops.auto_deskew=true`는 각도와 여러 행이 확인될 때만 OCR용 복사본을 보정한다. `MangaInpaintAssemble.blend_width=8`은 원문 획의 제거 강도를 유지하며 마스크 여유 부분의 경계를 완화한다. 새 08을 가져오고, 폴더 프로젝트는 처리 설정이 바뀌므로 새 `project_name`을 사용한다. [보정 조건·좌표·남은 한계](docs/oriented-ocr-v0.6.0.md).

v0.5.2는 통합 08 하단에 **단계별 디버그 행**을 추가한다. 검출·OCR·제거 계획·제거 결과·식자 계획·식자 결과의 `미리보기 아무거나` 6개와 선택/제외 박스·원문 스타일 마스크·새 글자 알파의 이미지 검수를 제공한다. 새 08을 가져오면 연결되어 있으며 기존 프로젝트 이름을 유지할 수 있다. 디버그 가지는 처리 설정이나 품질 판정을 바꾸지 않는다. [출력 포트·사용법·실제 사례 분석](docs/debug-inspection-v0.5.2.md).

v0.5.1은 번역 요청에 **JSON 스키마 출력 제약**을 추가한다. 번역 노드의 `response_format` 기본값은 `json_schema`다. JSON 문법뿐 아니라 페이지별 ID·개수·필드를 지정하며 응답 후 ID/내용 검사도 유지한다. 실패한 응답 두 개와 종료 사유는 `output/manga_translator/translation_failures`에 저장한다. 기존 v0.5.0 프로젝트는 기본 설정으로 이름 변경 없이 `실패 재시도`할 수 있다. [서버 호환 모드·진단·검증 범위](docs/translation-protocol-v0.5.1.md).

v0.5.0은 **번역문 방향을 가로/세로로 통일**하고, 번역 후 **페이지 편집 계획**에서 교체·원본 보존을 결정한다. 제거와 식자가 같은 저장 명세를 사용하며 보존 영역을 제거 전에 마스크에서 제외한다. 새 08을 가져와 입력 옆 `번역문 방향` 노드의 `lettering_direction`을 선택한다(기본 `가로 통일`). v0.4.x에서 이 그래프로 옮기는 기존 프로젝트는 설정이 달라지므로 새 `project_name`으로 실행하며 이전 결과는 보존된다. [설정·편집 명세·검증 범위](docs/page-edit-plan-v0.5.0.md).

v0.4.4는 원본의 세로 점 9개를 Hayai가 15개·12개로 늘려 읽어 `short_repetition`으로 중단한 사례를 보완한다. 품질 검사 사용 시 형태·정렬·간격이 확인되는 3~24개의 점 나열만 원본에서 개수를 세고, 번역과 새 식자를 생략해 해당 영역의 원본 픽셀을 복원한다. 일반 문자 반복 검사와 애매한 입력의 기존 OCR 경로는 유지한다. [점 나열 처리와 검증 범위](docs/dot-punctuation-v0.4.4.md).

v0.4.3은 첨부 진단 이미지에서 확인한 **그림 선 오검출·효과음의 text 오분류로 인한 경계 실패**를 처리한다. 통합 08의 `boundary_policy=preserve_review`는 복구 불가 영역과 접촉 문단을 원본 보존하고, 확인된 다른 영역을 처리한 결과를 **needs_review**로 기록한다. 제거 마스크 확대·단색 보완·식자에서도 보존 영역을 보호하며, 폴더 수집 시 최종 픽셀을 원본과 비교한다. `strict`는 기존의 페이지 중단 정책이다. [보존 범위·사용법·검증 한계](docs/boundary-review-v0.4.3.md).

v0.4.2는 실제 폴더 처리에서 남은 **경계 복구 5건·폰트 누락 2건·말풍선 중첩 1건의 처리 경로**를 보완한다. 큰 페이지는 native 크기의 이동된 정사각 문맥을 먼저 재검출하고, 일본어 혼합 문장은 동봉 대체 폰트로 실제 렌더링하며, 중첩 말풍선은 모든 후보가 공통으로 허용하는 내부 공간에서만 식자한다. 기존 프로젝트와 08을 유지하고 `실패 재시도`로 적용한다. [수정 범위와 검증 한계](docs/page-failures-v0.4.2.md).

v0.4.1은 이전 작업의 큐·이력이 사라졌을 때 `실패 재시도`가 막히는 복구 경로를 보완한다. 현재 캔버스 prompt가 같은 ComfyUI 큐에서 실제 실행 중이고 이전 작업이 없음을 재확인한 경우, 프로세스 재시작 시각에 의존하지 않고 이전 시도를 미확정 결과로 보존한 뒤 새 시도를 허용한다. 복구가 막혀도 이번에 선택한 동작과 확인 근거를 정확히 보고한다. 이미 v0.4.0의 새 08을 사용 중이면 JSON을 다시 가져올 필요는 없다.

v0.4.0은 **폴더의 각 페이지도 현재 캔버스의 일반 Run 안에서 끝까지 실행**한다. 첫 입력 노드에서 페이지·현재 노드·진행 상태를 실시간으로 보고, 기본 이미지/JSON 미리보기와 중지를 사용한다. 완료 후 브라우저가 같은 캔버스의 다음 Run을 제출하며, 서버의 별도 프로젝트 추론 작업자나 숨은 자식 실행은 사용하지 않는다. [실행 구조·중지·재개](docs/canvas-execution-v0.4.0.md).

**v0.4.0 이전 워크플로우는 새 통합 08 JSON을 가져와야 한다.** 폴더의 결과·OCR·번역 저장 경로 세 개가 첫 노드에 연결됐다. 기존 프로젝트 기록과 재시작 복구는 유지한다.
## 설치

1. 이 저장소를 `ComfyUI/custom_nodes/ComfyUI-Manga-Translator`에 설치하거나 기존 저장소에서 `git pull`한다.
2. 기존 ComfyUI Python 환경을 사용한다. [requirements.txt](requirements.txt)는 모델 어댑터 요구사항이며, 현재 동작하는 torch/CUDA/Transformers를 임의로 교체하지 않는다. 런타임 자동 설치·모델 다운로드는 없다.
3. ComfyUI를 재시작하고 브라우저를 새로고침한다.
4. [08-integrated-tiled-cleanup-lettering.json](lettering/example_workflows/08-integrated-tiled-cleanup-lettering.json)을 캔버스로 가져온다. 캔버스에서는 `.api.json`이 아닌 일반 `.json`을 연다.
5. 검출/Hayai 번들, 설치된 Qwen 모델, 번역 서버를 설정한다. 기존에 저장한 번역 URL·모델·폰트 설정은 다시 확인한다.

처음 설치할 때는 `ComfyUI/custom_nodes`에서 실행한다.

```bash
git clone https://github.com/ytoaa/ComfyUI-Manga-Translator.git
```

Qwen 경로에는 `TextEncodeQwenImage21`, `QwenImage21Cache`, `ManualSigmas`와 표준 로더·샘플러·VAE 노드가 필요하다. 이전 Qwen 2.1 Turbo에서 사용한 노드를 재사용한다. Koharu 실행파일·Rust 렌더러·Qwen-VL 서버는 필요하지 않다.

## 같은 워크플로우에서 입력 선택

| 작업 | 첫 입력 노드 설정 | 실행 |
|---|---|---|
| 한 장 | `input_mode=이미지 한 장`, 이미지 선택/업로드 | 기본 Run |
| PC의 이미지 폴더 | 노드 안의 `PC 폴더 업로드`, `project_name` 확인 | 업로드 완료 후 `action=시작·재개`, Run |
| 서버의 이미지 폴더 | `input_mode=폴더 프로젝트`, `input_folder`에 ComfyUI/input 아래 상대 경로 | `project_name`과 `action=시작·재개`, Run |
| 진행 확인·일시정지·실패 재시도 | 같은 프로젝트에서 해당 `action` 선택 | 기본 Run |

PC 폴더는 하위 경로를 보존해 기본 ComfyUI 업로드로 전송한다. 모든 파일이 업로드된 뒤 입력 모드와 폴더가 반영된다. 폴더 프로젝트는 숫자 순서로 한 페이지씩 같은 그래프를 ComfyUI 큐에서 실행한다. 첫 Run에서 첫 페이지가 실제 실행된다. 첫 노드의 실시간 상태와 연결된 미리보기에서 확인한다. 자동으로 다음 페이지를 실행하려면 브라우저를 열어 둔다.

완료 페이지는 재개 시 재실행하지 않는다. 노드의 `연속 처리 중지 · 현재 페이지 이후` 버튼은 현재 페이지 후 멈추고, 기본 ComfyUI 중지는 현재 실행을 중단한다. 재개는 프로젝트에 저장한 처리 설정을 사용한다. 모델·번역·식자 설정을 바꿔 새로 처리하려면 새 `project_name`을 사용한다. 같은 책을 새 업로드 경로에 올려도 상대 경로와 파일 해시가 같으면 완료 결과를 재사용한다.

[현재 폴더 실행·예외 처리](docs/canvas-execution-v0.4.0.md), [PC 폴더 업로드](docs/folder-upload-v0.3.15.md)를 참고한다. 이전 버전의 폴더 실행 문서는 변경 이력이다.

## 검수와 결과

- 원본 크롭·OCR 행/조각·실효 제거 마스크·식자 전 배경·식자 공간은 연결된 이미지 미리보기에서 확인한다.
- OCR JSON·번역 JSON·프로젝트 진행 보고서는 기본 **미리보기 아무거나**에 연결되어 있다.
- 한 장의 최종 PNG는 `ComfyUI/output/manga_translator/integrated_tiles_*.png`, OCR/번역 JSON은 같은 폴더의 `ocr_*.json` / `translation_*.json`에 저장한다.
- 폴더 기록과 페이지별 시도 결과는 `ComfyUI/output/manga_translator/workflow_projects/<project_name>/`에 저장한다. 진행 보고서의 결과·export 위치를 확인한다.
- 경계 복구 실패 문맥 PNG와 상세 JSON은 `ComfyUI/output/manga_translator/detection_failures/`에 남는다.
- OCR 실패 입력 PNG와 진단 JSON은 `ComfyUI/output/manga_translator/ocr_failures/`에 남는다.

효과음·표지 큰 글자 포함 스위치는 검출·영역·마스크에 공통으로 적용하며 기본은 제외다. 선택 검출이 0개면 OCR·번역·Qwen·식자를 생략하고 원본을 저장한다. 폴더 프로젝트는 균일한 빈 페이지와 검출이 없지만 검수가 필요한 페이지를 구분한다. 검출 0개가 실제 글자 없음의 보증은 아니다.

반복 OCR·복구되지 않은 경계·안전하게 맞지 않는 식자는 명시적 오류로 남긴다. 폴더에서는 페이지 품질 실패를 분리하고, 메모리·디스크·구성·큐 접수 여부 불명은 추가 제출을 멈춘다. 실패 내용을 지운 채 정상 결과로 넘기지 않는다.

원문 제거는 최대 512px 코어+128px 문맥 타일과 실효 마스크를 사용한다. 크롭·복원·합성·저장은 기본 노드를 사용하고, 한글은 원문 스타일을 참조해 폰트로 그린다. 단색 잔상 보완·줄바꿈·말풍선·충돌 검사의 상세 설명은 [통합 처리](docs/integrated-workflow.md)와 [식자 설정](docs/hybrid-lettering.md)에 있다.

원본은 64 MiPixel, 개별 식자 영역은 16 MiPixel, 임시 글자 래스터와 한 페이지 후보 영역 총합은 각각 32 MiPixel까지다. 원본 크기와 모델 타일/패치 예산은 별개다. [고해상도 실행 계약](docs/high-resolution-runtime-v0.3.17.md).

## 모델 번들

아래 폴더에 기존 완전한 번들을 연결하거나 배치한다. 가중치 파일을 따로 다운로드하거나 옮기지는 않는다.

```text
ComfyUI/models/manga_translator/detection/<bundle>/
ComfyUI/models/manga_translator/ocr/<bundle>/
```

검출 번들은 `model.safetensors`, `load_model.py`, `inference_config.json`이 필요하다. Hayai는 `model.safetensors`, `config.json`, `configuration_hayai.py`, `modeling_hayai.py`, `tokenizer.json`, `vision-config.json`이 필요하다. 로딩 시 핀된 SHA 또는 호환 번들 매니페스트를 검증한다.

기존 `models/koharu/detection`, `models/koharu/ocr` 및 등록된 `koharu_detection`, `koharu_ocr` 경로는 **읽기 전용 호환 조회**를 지원한다. 기존 `koharu_nodes`를 import하거나 그 저장소에 실행을 위임하지 않는다. 검사 실패를 피하기 위해 가중치나 모델 코드를 임의로 이름만 바꿔 넣지 않는다.

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

## 검증과 남은 범위

[VALIDATION.md](VALIDATION.md)에 CPU 회귀·그래프 모의 실행·패키지 검증과 과거 검증 기록을 구분해 기록한다. 모델 대역으로 성공한 시뮬레이션은 실제 DGX RF-DETR/Hayai/번역/Qwen 품질 검증이 아니다.

일부 표지 자동 검출, 번호 칸·제목/본문 구분, OCR 의미 오류와 페이지 간 용어 공유는 개선 대상이다. 폰트 자동 식별이나 원본 글자체의 완전한 복제도 제공하지 않는다. 워크플로우를 하나로 정리한 변경이 이 품질 문제들을 해결했다는 뜻은 아니다.

## 출처와 라이선스

새 연결 코드와 전체 출처는 [LICENSE](LICENSE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [provenance.json](provenance.json)에 기록한다. 포함된 RF-DETR/Hayai 어댑터는 기존 공개 프로젝트에서 가져와 고지를 보존한다. 모델 가중치는 포함하지 않으며 각 배포자의 별도 조건이 적용된다.
