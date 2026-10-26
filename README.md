# ComfyUI-Manga-Translator

ComfyUI 캔버스에서 만화·이미지의 **글자 검출 → OCR → 번역 → 원문 제거 → 한글 식자 → 저장**을 연결하는 커스텀 노드입니다. 이미지 한 장과 폴더 프로젝트를 **통합 08 워크플로우 하나**로 처리합니다.

현재 처리 버전은 **v0.7.12**입니다. 원문이 불확실하거나 안전한 식자가 불가능한 영역은 원본 보존·검수 또는 명시적 실패로 남깁니다. 실행 성공과 번역 정확도는 별개입니다.

## 시작하기

1. `ComfyUI/custom_nodes`에서 저장소를 설치합니다. 기존 설치는 해당 저장소에서 `git pull`합니다.

   ```bash
   git clone https://github.com/ytoaa/ComfyUI-Manga-Translator.git
   ```

2. 기존 ComfyUI Python 환경에 [의존성](requirements.txt)이 있는지 확인합니다. 동작 중인 torch/CUDA를 CPU 검증용 패키지로 교체하지 않습니다.
3. ComfyUI 재시작 후 브라우저를 새로고침합니다.
4. [통합 08 JSON](lettering/example_workflows/08-integrated-tiled-cleanup-lettering.json)을 캔버스로 가져옵니다. `.api.json`은 자동화용입니다.
5. 입력 이미지·검출 번들·OCR 엔진·번역 서버·기존 Qwen 제거 모델을 설정하고 Run합니다.

검출은 RF-DETR, OCR은 Hayai v2 또는 일본어 Manga OCR, 번역은 사용자가 지정한 OpenAI-compatible 서버를 사용합니다. 원문 제거는 기존 ComfyUI Qwen 노드로 수행하며, 번역 글자는 실제 폰트로 렌더링합니다. 모델 가중치는 포함하지 않습니다. OCR 모델은 선택한 고정 버전을 처음 사용할 때 내려받을 수 있습니다. 검출·Qwen 모델과 Python 패키지를 자동 설치하지 않습니다. [필수 모델·노드와 경로](docs/configuration.md)를 먼저 확인하세요.

## 자주 찾는 기능

| 작업 | 위치 |
| --- | --- |
| 한 장 / 서버 폴더 / PC 폴더 업로드 | 첫 입력 노드 · [사용법](docs/usage.md) |
| 가로·세로 통일 | 입력 옆 `번역문 방향` 노드, 기본 **가로 통일** |
| 실패 또는 검수 결과 재처리 | 첫 입력 노드 `action=실패·검수 재시도` |
| OCR·번역·제거·식자 중간 결과 | 연결된 `미리보기 아무거나`와 하단 디버그 행 |
| 오류·원본 보존 사유 확인 | [문제 해결](docs/troubleshooting.md) |
| 원문·번역 직접 수정 / 확정 | `원문 검수`, `번역 검수` 노드 안 입력란 |
| 영역별 보존·교체 / 제거 마스크 브러시 | 상단 `삭제 전 원문 검수` 노드 · [사용법](docs/usage.md#영역-검수와-제거-마스크-브러시) |
| OCR 엔진 / 누락 모델 다운로드 | `OCR 엔진 · 모델 자동 준비` 노드 |
| 용어집·말투·확정한 앞 페이지 | `책 용어집 · 말투 · 확정된 앞 페이지` 노드 |
| 단계 결과 재사용 | 검출·번역·지운 배경 재사용 노드와 OCR 노드의 `cache_policy` |
| 영역별 식자 조정 | [설정](docs/configuration.md) |

폴더도 각 페이지가 현재 캔버스의 일반 실행으로 처리됩니다. 다음 페이지 자동 실행에는 브라우저가 열려 있어야 합니다. 이전 시도는 보존하며, 같은 처리 설정과 페이지 교정으로 완료된 페이지는 일반 재개로 반복 처리하지 않습니다. 0.7.1의 페이지별 교정에는 새 통합 08의 검수 식별 연결이 필요합니다. 이전 교정은 삭제하지 않고 충돌을 안내하므로 확인 후 다시 저장하세요.

## 결과와 한계

한 장의 PNG와 OCR/번역 JSON은 `ComfyUI/output/manga_translator/`, 폴더 기록은 그 아래 `workflow_projects/<project_name>/`에 저장됩니다.

v0.7.3은 검출 분석·텍스트·표현·수정 출처를 나누고, 단계 결과를 저장해 다시 사용합니다. 확인된 글줄 높이 차이는 제목/본문 블록으로 나누며 회전한 로컬 프레임에서 식자합니다. 모든 페이지의 계층을 자동 복원하는 기능은 아닙니다. 작은 글자·손글씨 오독, 표지/효과음 미검출과 번역 오류도 남을 수 있습니다. [현재 한계와 보류 작업](docs/known-issues.md)을 참고하세요. 말풍선 소유권이 불확실한 영역은 기본으로 원본을 복원해 검수에 남기며, 번역 출력 한도는 제한된 ID 분할 요청으로 복구합니다. 설정과 최종 식자 보고서는 [설정](docs/configuration.md)·[문제 해결](docs/troubleshooting.md)에서 확인합니다.

## 문서와 개발

- [문서 목차](docs/README.md): 사용·설정·문제 해결
- [구조](docs/architecture.md) · [개발과 패키징](docs/development.md)
- [검증 범위](VALIDATION.md) · [변경 이력](CHANGELOG.md)

사용 안내는 현재 동작을 설명합니다. 과거 버전의 재현 기록·초기 조사와 폐기된 실행 방식은 문서 목차에서 별도 이력으로 연결합니다. Git 이력에서 정리 전 자료도 확인할 수 있습니다.

[라이선스](LICENSE) · [포함 코드·폰트 고지](THIRD_PARTY_NOTICES.md) · [출처 메타데이터](provenance.json). 모델별 배포 조건은 각 모델 저장소를 확인해야 합니다.

선택형 CPU 대체 모델(CTD / PP-OCRv6 / LaMa·Anime LaMa)의 설치·연결과 실제 비교 범위는 [대체 모델 검사](docs/validation/alternative-models.md)를 확인하세요. 기존 검출/OCR 기본값은 유지합니다.
