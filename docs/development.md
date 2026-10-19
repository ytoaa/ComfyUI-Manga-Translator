# 개발과 배포 정리

[목차](README.md) · [구조](architecture.md) · [검증](validation/README.md)

아래 개발 명령은 Git 체크아웃 또는 개발 source ZIP에서 실행합니다. 기본 실행 ZIP에는 테스트·개발 도구가 없습니다.

## 저장소와 설치 ZIP

- 저장소에는 운영 코드·폰트·통합 08, 현재 문서, 테스트·개발 도구와 과거 증거 기록을 둡니다.
- 기본 **실행 ZIP**은 운영 코드·폰트·08·현재 문서를 포함합니다. 테스트·개발 도구·과거 기록·생성 예제 결과는 제외합니다. 공유 런타임인 tools/run_project.py는 포함합니다.
- `--include-development` **source ZIP**은 체크섬에 등록된 개발 자료도 포함합니다. 일반 설치에 추가로 설치할 파일이 아닙니다.
- 생성 PNG·실행 JSON·모델·개인 입력·출력은 Git에 넣지 않습니다. 과거 생성 결과와 폐기된 설명은 Git 이력으로 찾습니다.

## CPU 회귀

운영 ComfyUI와 분리한 개발 환경에서 실행합니다. 실제 모델 가중치 없이 계약·기하·폰트·캔버스 회귀를 수행할 수 있습니다.

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install pytest numpy Pillow scipy fonttools psutil 'pydantic>=2,<3'
python -m pytest tests -q --confcutdir=tests --tb=short
node tools/check_canvas_frontend.cjs
node tools/check_node_ui.cjs
```

추가 브라우저 CSS 검사는 개발 환경에 Playwright와 Chromium을 준비하고 `node tools/check_node_layout.cjs`로 실행합니다. `MANGA_LAYOUT_CHROMIUM`으로 실행 파일을 지정할 수 있습니다. 5종 노드 × 3너비 × 2확장 등록 순서의 30개 슬롯을 검사하며, 노드 API는 대역이므로 운영 ComfyUI 전체 시각 검사와 구분합니다. 브라우저가 시작하지 못하면 PASS로 기록하지 않습니다.

별도 환경에서만 CPU torch를 설치합니다. 모델 대역으로 실행한 회귀를 실제 GPU/모델 품질 결과라고 부르지 않습니다.

## 워크플로우와 시각 자료 재생성

```bash
python tools/build_integrated_workflow.py
python tools/simulate_integrated.py --destination validation/simulation
python tools/demo_hybrid_lettering.py --destination validation/hybrid
python tools/build_lettering_fixture.py --destination validation/lettering
```

08 GUI/API가 함께 생성됩니다. 새 워크플로우 변형을 수동으로 늘리지 않습니다. 생성된 이미지·보고서는 validation/ 아래에서 검토하며 커밋하지 않습니다. 빌더의 모델 노드 원형 tools/integrated_model_nodes.json은 재생성 입력이므로 보존합니다.

## 저장소 검사와 패키징

```bash
python tools/check_repository.py
python tools/package_style_lettering.py --destination dist
python tools/package_style_lettering.py --destination dist --include-development
```

저장소 검사는 등록 파일 체크섬·현재 로컬 문서 링크·출처 해시·통합 워크플로우 수를 확인합니다. 패키저는 소스를 바꾸지 않고 ZIP 안에 해당 프로필의 SHA256SUMS를 생성합니다. 파일 버전은 workflow_native.py의 VERSION에서 읽습니다.

의도한 변경 뒤 체크섬을 갱신할 때만 다음을 실행합니다. 먼저 추가/삭제를 Git에 등록해야 파일 목록이 반영됩니다.

```bash
git add --all
python tools/check_repository.py --write-checksums
git add SHA256SUMS
python tools/check_repository.py
```

검사·테스트가 끝난 뒤 같은 코드의 문서/체크섬만 정리할 수 있습니다. 코드가 바뀌면 관련 검증을 다시 수행합니다. 패키지 검사는 추출된 실행 ZIP에서 전체 노드 import와 GUI/API 예제가 하나인지 확인합니다.

## 실제 모델 진단

가중치가 필요한 명시적 오프라인 CPU 도구는 tools/validate_cpu_models.py입니다. [CPU 모델 관측](validation/cpu-models.md)의 고정 번들과 조건을 따릅니다. 기본 패키지의 운영 CUDA 정책을 CPU로 바꾸지 않습니다.

[페이지 실패 상황 시뮬레이션](validation/image-scenarios.md)은 `tools/simulate_page_failures.py`로 실행합니다. 경계·크롭·OCR 수용·회전·잘린 획·캐시·제거·식자·빈 페이지 55조건과, 정답을 알고 생성한 6종 페이지/15종 글자 입력의 실제 CPU 모델 평가를 분리합니다. 생성물은 체크아웃 밖에 두며 미충족은 GAP·종료 코드 1로 남깁니다. 운영 코드의 자동 수정이나 실제 사용자 페이지 성공 판정 도구가 아닙니다.

과거 검증은 docs/history에 보존합니다. 일반 사용법과 개발 명령은 버전별 기록에 추가하지 않고 이 문서와 현재 안내를 수정합니다. 새 관측은 검증 목차와 관련 증거 문서에 추가하며 실제 추론·합성·대역을 구분합니다.

추가 경계 감사는 `python tools/audit_boundaries.py --destination validation/boundary-audit`로 실행합니다. 기본 43개 계약·폰트·장애 주입 검사와, `--actual-ocr --models /path/to/models --row-inputs /path/to/rows`를 더한 63개 검사를 구분합니다. 사용자 행 입력과 모델은 공개 저장소에 포함하지 않습니다. FAIL/ERROR는 종료 코드 1, 인식 관측은 OBSERVED이며 정확도 통과로 합산하지 않습니다. [검증 목차](validation/README.md)에 조건과 이전 실패를 기록합니다.

`--transitions`는 기존 검사 대신 새 전이·경계 29개만 실행합니다. 이 모드에서 `--actual-ocr --models /path/to/models`를 더하면 비문자 합성 입력 8건을 실제 CPU 모델로 관찰해 총 37개가 됩니다. 행 이미지 파일은 필요하지 않습니다. 두 OS 프로세스의 모델 설치 경쟁은 합성 응답으로 실행하며 외부 다운로드를 하지 않습니다. 발견된 실패를 숨기거나 운영 코드를 자동 변경하지 않습니다.
