# v0.3.17 — 고해상도 폴더 페이지 실행 계약

실제 폴더 프로젝트에서 16 MiPixel보다 큰 페이지가 프로젝트 입력 단계는 통과한 뒤 `MangaInpaintPlan`/식자 계층의 과거 16 MiPixel·4 MiPixel 제한에 다시 걸리는 문제를 수정한다. 이 변경은 단순히 모든 제한을 64 MiPixel로 올리는 것이 아니라 작업 종류별 자원 한계를 분리한다.

## 확인된 실제 실패

첫 실제 페이지는 RF-DETR, Hayai OCR, 번역까지 진행한 뒤 `lettering.core.rgb()`의 과거 16 MiPixel 페이지 제한에서 중단됐다. OCR에는 `1262x4364`(약 5.5 MiPixel) 영역도 실제로 들어왔으므로 과거 4 MiPixel 식자 영역 제한도 다음 실패가 될 수 있었다.

텍스트가 검출되지 않은 다른 페이지도 OCR/번역을 정상 생략한 뒤 cleanup planner가 전체 페이지를 검사하면서 동일한 16 MiPixel 제한에 걸렸다. 따라서 원인은 개별 모델이 아니라 폴더 프로젝트와 내부 cleanup/lettering 코드의 페이지 크기 계약 불일치였다.

## 공유 자원 계약

`limits.py`가 다음 계약을 한 곳에서 정의한다.

- 원본 페이지 안전 상한: 64 MiPixel
- 개별 OCR/식자 영역: 16 MiPixel
- supersample 임시 글자 래스터: 32 MiPixel
- 한 페이지의 식자 후보 영역 총합: 32 MiPixel
- 입력 파일 바이트 상한: 256 MiB

Qwen cleanup은 계속 최대 512px core + 128px context의 bounded tile만 처리한다. 고해상도 원본 허용이 Qwen에 64 MiPixel 이미지를 통째로 전달한다는 뜻은 아니다.

## no-text 페이지

source mask와 cleanup mask가 모두 비어 있으면 cleanup planner는 connected-component labeling과 Qwen 경로를 시작하지 않는다. 원본 페이지와 빈 마스크를 그대로 보존하는 skip plan을 반환한다. 이후 assembler도 생성 타일을 요구하지 않고 원본 픽셀을 그대로 반환한다.

## 고해상도 식자

개별 region은 16 MiPixel까지 허용한다. 기본 supersample 값이 2이더라도 임시 래스터가 32 MiPixel을 넘으면 1까지 자동으로 낮춘다. region 자체가 supersample=1에서도 32 MiPixel을 넘는 경우에만 명시적으로 중단한다. 실제 사용된 supersample과 요청값은 렌더 보고서에 함께 기록한다.

## 기존 실패 프로젝트 재개

새 attempt에는 `resource_contract_version`을 기록한다. 이 필드가 없는 이전 attempt가 정확히 과거 16/4 MiPixel 크기 제한 메시지로 실패했다면 `시작·재개`에서 해당 페이지를 새 attempt로 한 번 다시 처리할 수 있다. 현재 계약에서 발생한 일반 실패를 무한 자동 재시도하지 않는다.

## 여전히 의도적으로 유지되는 한계

- RF-DETR 경계 복구 호출/region 수 제한
- cleanup `max_tiles` 제한(기본 64, 노드 최대 256)
- OCR patch/token 예산
- 64 MiPixel 원본 페이지 안전 상한
- 16 MiPixel 개별 식자 영역 상한
- 32 MiPixel 임시 래스터/총 식자 후보 예산

이들은 서로 다른 단계의 bounded-work 안전장치이며 원본 페이지 상한과 혼용하지 않는다.

## 검증 범위

`tests/test_highres_contract_v0317.py`는 공유 상한 일치, 실제 관측된 `1262x4364` 영역, no-text cleanup 조기 우회, stale 16 MiPixel 실패의 제한적 재시도, 현재 계약 실패의 비자동 재시도를 고정한다. 실제 DGX 모델 품질과 VRAM/RAM 피크는 별도의 실기 검증 대상이다.
