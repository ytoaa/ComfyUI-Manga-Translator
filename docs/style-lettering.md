# 원본 스타일을 참조한 식자

제공 워크플로우는 [통합 08](../lettering/example_workflows/08-integrated-tiled-cleanup-lettering.json) 하나다. 이전 단계별·수동·질감 실험 예제는 배포하지 않는다. 설치·한 장/폴더 실행은 [README](../README.md), 방향·폰트·줄바꿈·말풍선·영역별 JSON은 [식자 설정](hybrid-lettering.md)을 따른다.

통합 흐름은 검출/OCR/번역 이후 타일별 원문 제거를 수행하고, `MangaLetterPrepare → MangaLetterPlan → MangaLetterApply`로 번역문을 그린다. Qwen은 원문 제거와 배경 복원에 사용한다. 한글은 실제 폰트로 렌더링하고 새 글자 알파로 합성한다.

원문 잉크색·외곽선·밝기 질감을 측정하고, 가로/세로쓰기·회전·기울기·그림자를 조절할 수 있다. 원본 폰트 자동 식별·손글씨의 완전한 형태 복제는 지원하지 않는다. 새 폰트는 `ComfyUI/models/fonts/`에 두고 재시작한다. 동봉 나눔고딕 Regular/Bold는 한글·영문용이다.

기존 저수준 스타일 분석·렌더링·수동 영역 노드는 저장 그래프 호환을 위해 유지한다. 실험용 질감 노드도 삭제하지 않지만 별도 예제로 안내하지 않는다. CPU 합성 입력은 `lettering/examples/`, 재생성 도구는 `tools/build_lettering_fixture.py`다. 이 이미지는 실제 모델 추론 결과가 아니다.

자원 상한은 [고해상도 계약](high-resolution-runtime-v0.3.17.md)을 따르고, 실제 검증 범위는 [VALIDATION](../VALIDATION.md)에 기록한다.
