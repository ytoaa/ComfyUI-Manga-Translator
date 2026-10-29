# v0.7.22 코드·사용 시나리오 검증

2026-10-30 (한국시간). 실제 ComfyUI 실행 및 GPU 검증은 요청 범위에서 제외했다.
유한한 시험으로 모든 입력·환경의 가능성을 증명했다는 뜻은 아니다.

| 범위 | 실행 근거 | 남은 한계 |
| --- | --- | --- |
| 설치·패키징 | 소스 해시, 추출 패키지 import, 워크플로우, 노드 스키마 회귀 | 실제 ComfyUI 설치·업데이트 조합 |
| 모델 취득·로딩 | 해시, 다운로드 실패·중단, 파일 세대 변경 회귀 | 실제 가중치 추론, 장치별 조합 |
| 입력·문서·수동 편집 | 크기·좌표·예산·revision·보호 범위 회귀 | 임의 실사 페이지의 의미 정답 |
| 검출·OCR·번역 | 소유권·중복·줄바꿈·보존 계약, 응답 오류 주입 | 실제 모델 오독·누락·번역 품질 |
| HTTP | 실제 loopback 서버, UTF-8, 401/429/503, 잘린 전송, timeout, redirect | 외부 운영 서버, TLS·프록시 조합 |
| 제거·식자 | 생성 픽셀 기준, 비정상 출력 주입, 작은 글자·저대비·색상 합성 | 의미적으로 자연스러운 생성 배경 |
| 저장·캐시 | 실제 파일, symlink, 부분 쓰기, 프로세스 경쟁 | 악의적 동시 경로 교체, 네트워크 파일시스템 |
| 중단·재개 | 별도 POSIX 프로세스의 잠금·강제 종료·atomic replace | 전원 단절 내구성, Windows 실행 |
| UI·상태 | 배포 JavaScript의 DOM/network 대역 실행, 검수 결과 저장·재사용 | 실제 브라우저 CSS·여러 탭·ComfyUI E2E |
| 문서·배포 | 버전·범위·소스 목록·링크 검증 | 게시 여부는 최종 기록 확인 |

## 수정 사항

**SYS-LETTER-15/16.** 원문 크기가 최소 글자 크기보다 작은 경우 readable에서만
최소 크기로 확대한다. strict 및 명시적 font_cap/max_font는 유지한다.
확대 후에도 말풍선·이웃·보호 영역·실제 glyph alpha 제한을 통과해야 한다.
스타일 배율은 원래 측정값에 대해 계산한다. 저대비 복구는 32개 이상 픽셀,
국소 지지, 안정된 단색 배경, 일관된 명암 방향을 요구한다. 전체 화면 변색·
양자화 잡음·불균일 배경은 거부한다. 두 조정 모두 검수와 구체적 UI 사유를 남긴다.

**SYS-CLEANUP-17.** 타일 전체 변경률만으로 놓치던 일부 원문 잔존을 검사한다.
8픽셀 이상 성분 중 거의 바뀌지 않은 성분과 원문 밖 경계의 큰 색 차이를
검사한다. strict에서는 중단하며 해제 시 needs_review와 사유를 남긴다.
잘못된 출력의 거부는 올바른 배경 생성이나 번역 성공을 뜻하지 않는다.

**SYS-STATUS-18.** 제거 검수 상태를 checkpoint UI·캐시에 보존하고 최종 출력의
조상 노드에서만 수집한다. cleanup-report.json을 해시와 함께 저장하며 재개
후에도 검수를 유지한다. 다른 출력의 보고서는 무시한다. 기존 완료 기록은
소급 재분류하지 않으며 새 실행/재수집에 적용된다.

**SYS-HTTP-19.** 유효한 JSON이라도 Content-Length보다 짧거나 chunk가 불완전한
전송은 공통 서비스 오류로 처리한다. Authorization은 첫 요청에만 보내고
redirect에는 전달하지 않는다. 인증이 필요한 redirect 서버는 최종 API 주소를
직접 설정해야 한다. 실제 로컬 소켓과 가짜 키로 시험한다.

**SYS-EXPORT-20.** 번역 실패 진단의 경로 탈출·부분 JSON을 방지한다.
8 MiB 상한, 임시 파일 fsync/replace, 실패 시 정리를 적용한다.
원래 번역 오류를 진단 저장 오류로 덮어쓰지 않는다.

**SYS-ALPHA-21.** 외곽선 폭 0에도 흰색 층이 glyph와 중복 합성되었다.
축소 후 alpha를 먼저 자르면 Lanczos overshoot에서도 색이 변했다.
외곽선 비활성 시 coverage를 제거하고 원래 alpha로 unpremultiply한 뒤 clip한다.
회색/파란색 × 1·2·4배 샘플링 × 0·11도 회전의 12조건에서
foreground × alpha + background × (1-alpha)를 독립 정답으로 비교한다.
이 문제는 이전의 기하·문자열 검사만으로 발견되지 않았다.

## 검사기 자체의 보강

- 단계 전환 감사의 캐시 갱신 주입을 예전 read_bytes에서 현재 bounded
  Path.open/read로 옮겼다. 주입 실행 및 이미지/보고서 세대 일치 단언은 유지한다.
- 업로드·연속 실행 시험의 0ms timeout이 늦은 정상 응답과 경쟁하던 불안정을
  없앴다. 가상 deadline을 명시적으로 진행하며 정상 지연·실제 timeout·타이머
  해제 단언을 유지한다.
- 이전에 결함 존속을 기대하던 제거 검사를 수정했다. 별도 시험에서 production
  guard를 일부러 우회하면 같은 비정상 픽셀을 여전히 GAP으로 판정해야 한다.
  성공 수치를 위해 독립 픽셀 정답을 완화하지 않았다.

## 재현 명령

테스트 의존성이 별도 폴더라면 PYTHONPATH에 추가한다.

```sh
OMP_NUM_THREADS=4 python -m pytest tests -v --rootdir=tests --confcutdir=tests --tb=short
python tools/stress_image_processing.py --mode contracts --destination /tmp/manga-v0722-images
python tools/audit_boundaries.py --destination /tmp/manga-v0722-boundaries
python tools/audit_boundaries.py --transitions --destination /tmp/manga-v0722-transitions
node tools/check_node_ui.cjs
node tools/check_canvas_frontend.cjs
node tools/check_canvas_faults.cjs
node tools/check_folder_upload.cjs
python tools/check_repository.py
```

프로세스 종료 검사는 atomic 파일 가시성을 검사하며 전원 단절 시험이 아니다.
HTTP는 실제 로컬 서버지만 번역 결과는 고정 응답이다. 생성 이미지 시나리오는
실제 폰트/기하/합성을 실행하지만 모델 정확도 시험은 아니다.

## 최종 실행 기록

현재 실행에서 생성 이미지 계약 77/77, 독립 경계 43/43, 단계 전환 29/29가 통과했다.
작은 글자·저대비 렌더 결과를 직접 확인했다. 저대비는 원래 옅은 색을 유지하므로
검수 대상이며 자동 고대비 변환으로 보정하지 않는다.

색상·HTTP 신규 검사 39개를 v0.7.21 코드에 적용하면 24 FAIL / 15 PASS였다.
현재 코드의 전체 회귀는 **1273 PASS / 0 FAIL**, 262.09초였다.
71개 검사가 v0.7.21의 1202개에 추가되었다. POSIX fork를 사용하는 프로세스
시험에서 Python 3.12의 multithreaded-fork DeprecationWarning 5개가 발생했다.
해당 시험은 통과했지만 다른 OS나 향후 Python의 프로세스 방식까지 증명하지 않는다.

배포 JavaScript의 노드 검수 UI·canvas 계약·연속 실행 15조건·업로드 9조건이
통과했다. 최종 패키징·워크플로우 재검사 5개도 통과했다(2.98초). Python compileall,
생성 워크플로우와 등록 파일의 일치, 소스 209개·문서 링크 125개·adapter
provenance 검증을 통과했다.
[실행 요약과 검증 소스 해시](v0722-evidence.json)를 함께 보관한다.

실제 Chromium 레이아웃 실행은 실행 파일 부재로 중단되었고, 설치 시도도
다운로드 ZIP의 central directory signature 오류로 실패했다. DOM 대역 통과를
실제 브라우저 통과로 계산하지 않는다. 실제 ComfyUI/GPU는 요청대로 실행하지 않았다.
