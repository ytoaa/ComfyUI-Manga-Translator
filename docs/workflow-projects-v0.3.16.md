# 폴더 프로젝트 control-plane v0.3.16

> 이 문서는 당시 버전의 기록이다. 현재 캔버스 실행과 실시간 상태 사용법은 [v0.4.0](canvas-execution-v0.4.0.md)을 따른다.

v0.3.16은 08 통합 워크플로우의 폴더 실행에서 확인된 세 가지 구조 문제를 함께 수정한다.

1. 부모 `MangaWorkflowInput` 제어 prompt가 성공하기 전에 페이지 child prompt를 제출하지 않는다.
2. 프로젝트 identity에서 브라우저 업로드 임시 경로와 `시작·재개 / 상태 확인 / 일시정지 / 실패 재시도` 같은 제어 위젯을 제외한다.
3. 전체 페이지 16 MiPixel 제한을 모델 작업 한계로 취급하지 않고, 원본 보존용 안전 상한과 실제 타일/영역 모델 예산을 분리한다.

## 실행 순서

폴더 Run은 다음 순서를 따른다.

```text
브라우저 Run
  -> 부모 ComfyUI prompt
  -> MangaWorkflowInput이 프로젝트 worker 시작
  -> 부모 prompt 성공 이력 확인
  -> 폴더/저장 그래프 준비
  -> page 1을 단일 이미지 child prompt로 제출
  -> child 완료/수집
  -> page 2 ...
```

부모 prompt가 아직 `queue_running`/`queue_pending`에 있으면 worker는 기다린다. 부모 이력이 `success + completed=true`가 된 뒤에만 첫 페이지를 제출한다. 부모가 오류/중지되거나 큐와 이력에서 모두 사라지면 child를 0개 제출한 채 프로젝트를 `paused`로 둔다.

## child prompt 경계

저장된 master 08은 폴더 프로젝트 모드일 수 있지만 페이지 실행용 child graph는 제출 직전에 다음처럼 바꾼다.

```text
input_mode   = 이미지 한 장
image        = manga_translator/<project-id>/<normalized-page>.png
input_folder = ""
action       = 상태 확인
```

`extra_pnginfo.manga_project_page` marker가 해당 작업을 프로젝트 페이지로 식별한다. 따라서 child validation은 이미 정규화해 업로드한 한 장만 확인하며 원래 업로드 폴더를 다시 요구하거나 프로젝트를 재귀적으로 시작하지 않는다.

## 프로젝트 identity

재개 가능 여부를 판단하는 workflow fingerprint에는 검출/OCR/번역/Qwen/식자 등 실제 처리 설정만 포함한다. 다음 값은 처리 의미가 아니라 제어/위치 정보이므로 fingerprint에서 제외한다.

- `input_mode`
- `image`
- `input_folder`
- `project_name`
- `action`
- 결과 파일 prefix

원본 업로드 경로 역시 프로젝트 config identity에서 제외하고 현재 경로는 `project.json.source_folder`에 정보성으로 기록한다. 같은 책을 브라우저에서 다시 업로드하여 `manga_uploads/<새 UUID>/...`가 되더라도 상대 경로와 파일 hash가 같으면 기존 완료 페이지를 재사용할 수 있다. 파일이 실제로 바뀌면 기존 페이지 hash와 달라져 새 attempt를 만든다.

실제 모델/식자 설정이 달라진 workflow fingerprint는 계속 새 `project_name`을 요구한다.

## 원본 해상도 정책

기존 16,777,216 픽셀 제한은 작은 글씨를 보존해야 하는 현재 08 구조와 맞지 않았다. v0.3.16은 기본 원본 안전 상한을 67,108,864 픽셀(64 MiPixel)로 올린다.

이 값은 RF-DETR/Hayai/Qwen의 직접 모델 입력 크기를 뜻하지 않는다. 모델별 실제 계산은 기존처럼 detail detection, OCR region crop/patch budget, Qwen cleanup tile로 제한한다. 원본 페이지는 좌표와 작은 글씨 정보를 유지하기 위해 불필요하게 16 MiPixel로 축소하지 않는다.

64 MiPixel을 넘는 입력, 256 MiB를 넘는 단일 파일, 다중 프레임, high-bit-depth 입력, symlink 입력은 계속 명시적으로 거부한다.

## 기존 실패 프로젝트 마이그레이션

v0.3.15 이하 `project.json`의 config가 다음 조건을 만족하면 새 identity 형식으로 안전하게 마이그레이션한다.

- 같은 ComfyUI server 종류
- 같은 recursive/normalisation 정책
- 저장된 workflow가 현재 저장 master graph와 의미상 동일
- 기존 pixel limit이 새 limit보다 크지 않음

특히 이전 16 MiPixel 상한 때문에 `invalid_input / Input exceeds configured pixel budget`으로 실패한 페이지는 limit 증가 마이그레이션 시 한 번 자동 재평가한다. 새 64 MiPixel 상한도 넘으면 다시 실패로 고정되고 이후 일반 `시작·재개`에서 무한 재시도하지 않는다.

## export

완료 또는 검증된 빈 페이지가 하나도 없으면 빈 `exports/<edition>`을 만들지 않고 `summary.json`의 `export`를 `null`로 기록한다.

## 검증 시나리오

`tests/test_project_control_v0316.py`에는 다음 회귀가 포함된다.

- 16 MiPixel legacy limit과 64 MiPixel source safety limit 분리
- control widget 변경이 workflow identity를 바꾸지 않음
- 실제 처리 설정 변경은 계속 차단
- 같은 책을 새 브라우저 upload UUID로 다시 올려도 완료 페이지 재사용
- legacy pixel-budget 실패 project 마이그레이션 및 1회 정책 재평가
- child graph가 single-image validation 경계로 변환됨
- 부모 gate가 열리기 전 child 제출 0건
- 부모 실패/중지 시 child 제출 0건
- 모든 페이지 invalid인 경우 빈 export 미생성

이 테스트는 control-plane과 파일/큐 계약을 검증한다. RF-DETR/Hayai/번역/Qwen의 실제 DGX 품질은 별도 실측 범위다.
