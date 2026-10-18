# 현재 구조와 유지보수 경계

기준: v0.7.0 통합 08. [설정](configuration.md) · [개발](development.md) · [한계](known-issues.md)

## 코드의 책임

| 위치 | 책임 |
| --- | --- |
| adapters/ | 고정 모델 메타데이터·번들 검증·RF-DETR/Hayai 호출 |
| detection_policy.py, region_policy.py, mask_nodes.py | 상세 검출·경계 복구·영역 정리·실제 segmentation 마스크 |
| document.py | legacy 영역 필드를 유지하는 schema 2 snapshot, 문단 블록, revision에 묶인 인간 수정 |
| stage_cache.py, recognition_cache.py | 전체 픽셀/모델/설정별 단계 저장·검증과 native lazy 평가 |
| translation_context.py, ocr_engines.py | 확정 문맥·용어집, 고정 OCR 선택·원자 다운로드 |
| lettering/frame.py | 로컬 회전 사각형 조판과 페이지 변환 |
| nodes.py, models.py | ComfyUI 노드 경계, 크롭·OCR·수집·번역 |
| layout_refinement.py, text_geometry.py, source_recovery.py | 다단 정리·회전/행 계획·잘린 원문의 문맥 복구 |
| text_contract.py, ocr_policy.py, translation_protocol.py | 텍스트 계약·품질 휴리스틱·번역 응답 형식과 진단 |
| page_edit.py, boundary_review.py | 교체/보존 결정과 보호 범위의 공통 계약 |
| inpaint_tiles.py | 실효 마스크·소유 타일·좌표 복원·잔존 원문 검사 |
| lettering/ | 폰트·방향·줄바꿈·스타일 측정·회전 식자·충돌/말풍선 제약 |
| workflow_project.py, workflow_native.py, web/ | 캔버스 입력·폴더 업로드·진행/중지·페이지 연속 실행 |
| tools/run_project.py | 프로젝트 기록·입력/결과 검증의 공유 구현. 위치는 tools지만 운영 노드도 import하므로 실행 ZIP에 필요 |
| tests/, 나머지 tools/ | 회귀·시뮬레이션·그래프 생성·패키징·명시적 CPU 진단 |

기존 노드 ID·import 경로는 유지하고 새 checkpoint·검수·문맥 노드를 뒤에 추가합니다. 기존 그래프 호환을 위한 저수준/수동 노드는 유지하지만 추가 배포 워크플로우를 제공하지 않습니다.

## 페이지 데이터와 좌표

검출·OCR·번역은 영역 ID를 유지하는 JSON으로 연결합니다. `bbox`는 페이지 기준 0–1000 정규화 xyxy, `crop_bbox_pixels`/`edit_bbox_pixels`/`line_bboxes_pixels`는 원본 페이지의 픽셀 xyxy입니다. OCR의 회전 행은 `rectified_crop_pixels` 좌표계로 명시합니다. 식자 내부 문서는 픽셀 xywh를 사용합니다. 좌표계를 이름 없이 혼용하지 않습니다.

원본 크롭이 잘린 경우 source_recovery는 제한된 문맥에서 원래 기준선에 이어지는 글자를 찾습니다. OCR용 각 행과 제거용 픽셀은 같은 기하에서 만들어집니다. 복구 성공은 인식 정답 판정이 아닙니다. 실패하면 기본 보존·검수 정책으로 돌아갑니다.

문서의 `analysis`에는 명시된 좌표, `content`에는 원문/번역/블록, `presentation`에는 폰트/배치/스타일, `authored`에는 수정 출처를 둡니다. flat 영역 필드는 기존 노드 호환용 표현이며 snapshot은 공통 경계에서 다시 생성합니다. target 검수에서 원문/블록 기하를 변경할 수 없습니다. 원문 변경은 번역과 편집 계획을 무효화합니다.

단계 캐시는 전체 픽셀과 모델/설정의 canonical digest, 실제 원문 revision/문맥을 키에 사용합니다. 지운 배경은 실효 제거 계획과 Qwen 설정에 의존하며 번역 문자열 자체에 의존하지 않습니다. 손상 파일은 payload SHA256 검사에서 거부합니다. 체크포인트는 ComfyUI의 lazy 입력 평가로 재계산을 생략하고 별도 실행 작업자를 만들지 않습니다.

## 제거·식자의 공통 편집 결정

번역 후 `page_edit_plan`이 영역별 replace/preserve를 결정합니다. 제거·식자·폴더 수집은 같은 계획을 사용합니다. 원문/번역/좌표/digest가 달라지면 오래된 계획을 거부합니다. 보호 영역과 접촉한 편집 영역은 보존으로 닫습니다. 원본 보존 픽셀은 최종 수집에서도 확인합니다.

제거 모델은 번역문을 쓰지 않습니다. 타일별 원문 제거 결과를 원래 좌표로 조립하고 한글 폰트 알파를 별도로 합성합니다. 새 글자 알파를 원문 segmentation과 교차해 잘라내지 않습니다. 제거 마스크 밖 원본 픽셀은 보존합니다. 원문 잔존 검사와 단색 보완은 픽셀 휴리스틱입니다.

## 폴더 실행과 복구

각 페이지는 현재 캔버스 prompt에서 실행됩니다. 실행 이력·큐·저장된 attempt를 대조한 뒤 브라우저가 같은 그래프의 다음 일반 prompt를 제출합니다. 서버의 별도 GPU 추론 작업자나 숨은 자식 prompt에 위임하지 않습니다. 오래된 실행 결과가 불명확하면 멈추며, 명시적 재시도에서 원래 기록을 남기고 재대조합니다.

project fingerprint는 처리 설정의 신원입니다. 입력/출력 경로·동작 선택과 순수 디버그 가지는 처리 모델/번역/식자 설정과 구분합니다. 변경 허용 범위를 넓혀 과거 결과를 임의로 재사용하지 않습니다.

## 자원 계약

원본은 64 Mi 픽셀/입력 파일 256 MiB, 개별 식자 영역은 16 Mi 픽셀, 임시 글자 래스터와 페이지 후보 영역 합은 각각 32 Mi 픽셀, 활성 식자 영역은 64개까지입니다. 회전 OCR 분석은 원본 4 Mi·회전 래스터 8 Mi 픽셀의 별도 한도가 있습니다. 원본 페이지를 허용하는 것과 모델 입력·타일·패치 예산은 별개입니다. 상수의 기준은 limits.py이며 각 단계의 더 작은 분석 예산도 확인해야 합니다.
