# v0.3.18 통합 워크플로우 하나로 정리

제공 예제를 통합 08 하나로 정리한다. `lettering/example_workflows/08-integrated-tiled-cleanup-lettering.json`은 ComfyUI 캔버스용이고 같은 이름의 `.api.json`은 동일 그래프의 API 제출 형식이다. 기존 경로·노드 ID·모델 설정·연결·기본값은 유지한다.

한 장, 서버 폴더, PC 폴더 업로드는 첫 `MangaWorkflowInput` 노드에서 선택한다. 프로젝트 진행 보고서와 OCR/번역 저장 JSON의 기본 `PreviewAny` 연결도 유지한다. 페이지마다 다른 예제를 선택하는 흐름은 제공하지 않는다.

## 정리한 범위

- 예전 단계별·수동·실험 예제 10개의 GUI/API 쌍을 배포에서 제거한다. 예전 root `workflows/`도 비운다.
- 통합 생성기는 제거한 예제를 템플릿으로 읽지 않는다. `tools/workflow_graph.py`의 그래프 도구와 `tools/integrated_model_nodes.json`의 모델 노드 선언으로 같은 08을 만든다. 모델 노드 선언 파일은 실행 가능한 워크플로우가 아니다.
- 예전 예제를 다시 만드는 생성기는 제거한다. 합성 식자 이미지를 만드는 도구는 `tools/build_lettering_fixture.py`로 분리한다.
- CPU 시뮬레이션·연결/위젯·패키지 검사는 제공하는 단일 그래프를 대상으로 한다. 삭제된 예제를 읽던 테스트는 현재 그래프의 타일 크롭/복원/합성·최종 식자 연결 검사로 바꾼다.
- 테스트에 남아 있던 이전 부모 큐 대기 함수 호출을 현재 `wait_for_parent_success` 계약으로 맞춘다. 런타임 큐 정책은 바꾸지 않는다.
- 이전 버전 진단 문서는 과거 기록으로 유지한다. 최신 사용법은 README와 통합 처리 문서를 따른다.

## 업데이트

기존 Git 설치는 `git pull` 후 ComfyUI를 재시작하고 브라우저를 새로고침한다. 새 작업은 08 일반 JSON을 가져온다. 개인이 저장한 예전 그래프와 그 노드는 삭제하지 않는다. 다른 폴더에 예전 배포 ZIP을 덮어 설치하면 남은 옛 JSON이 보일 수 있으므로 새 배포 폴더를 사용하거나 예전 예제 파일을 직접 정리한다.

진행 중인 폴더 프로젝트는 저장한 08 설정과 기록으로 재개한다. 이번 정리는 제공 그래프의 처리 설정을 바꾸지 않아 기존 프로젝트의 처리 identity를 변경하지 않는다. 실제 처리 설정을 바꾸면 새 프로젝트 이름을 사용한다.

## 재현

```bash
python tools/build_integrated_workflow.py
python -m pytest tests -q --confcutdir=tests
python tools/simulate_integrated.py --destination /tmp/manga-integrated-check
python tools/package_style_lettering.py --destination /tmp/manga-package-check
sha256sum --check SHA256SUMS
```

생성 회귀 검사는 예전 예제와 완성된 08이 없는 임시 폴더에서 모델 선언만으로 생성하고, 배포 GUI/API와 바이트 단위로 비교한다. ZIP에 통합 GUI/API 쌍만 포함되는지도 검사한다. 실제 GPU 모델 추론은 이 검증의 범위가 아니다.
