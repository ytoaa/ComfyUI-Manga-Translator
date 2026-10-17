# ComfyUI-Manga-Translator

ComfyUI 캔버스에서 글자 검출 → OCR → 번역 → 원문 제거 → 한글 식자 → 저장까지 실행한다. **제공 워크플로우는 [통합 08 하나](lettering/example_workflows/08-integrated-tiled-cleanup-lettering.json)**다. 첫 입력 노드에서 이미지 한 장과 폴더 프로젝트를 선택한다. 별도 사이드바나 페이지마다 다른 워크플로우는 필요하지 않다.

v0.4.0은 **폴더의 각 페이지도 현재 캔버스의 일반 Run 안에서 끝까지 실행**한다. 첫 입력 노드에서 페이지·현재 노드·진행 상태를 실시간으로 보고, 기본 이미지/JSON 미리보기와 중지를 사용한다. 완료 후 브라우저가 같은 캔버스의 다음 Run을 제출하며, 서버의 별도 프로젝트 추론 작업자나 숨은 자식 실행은 사용하지 않는다. [실행 구조·중지·재개](docs/canvas-execution-v0.4.0.md).

**업데이트 후 새 통합 08 JSON을 가져와야 한다.** 폴더의 결과·OCR·번역 저장 경로 세 개가 첫 노드에 연결됐다. 기존 프로젝트 기록과 재시작 복구는 유지한다.
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
