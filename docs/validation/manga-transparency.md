# 복잡한 일본 만화·반투명 말풍선 추가 검사

운영 코드 기준은 `a4087cb`(v0.7.7)입니다. 이번 변경은 개발용 생성기·실행기·검사와 관측 기록입니다. 운영 기본값을 변경하지 않았습니다. 사용자 원본, 생성 이미지, 글자/말풍선 마스크, 모델 응답과 가중치는 Git에 포함하지 않습니다.

## 입력과 범위

새로 생성한 글자 없는 만화 배경 2개(비 오는 역, 야간 서고)에 독립적으로 일본어 문자를 그렸습니다. 각 배경의 16조건으로 **768×1152 페이지 32개**, 별도로 손그림 대사·효과음까지 처음부터 섞인 만화 **1페이지**를 생성했습니다. 기존 사용자 이미지를 다시 실행한 결과가 아닙니다.

32페이지 조건은 무문자, 흰 말풍선 알파 255/192/128/64/0, 검은 말풍선 알파 128/255, 테두리 없는 대사, 기울어진 외곽선 효과음, 세로 두 단·후리가나, 겹친 말풍선, 컷 경계 문자, 옅은 문자, JPEG38+blur0.55, 페이지 밖으로 잘린 문자입니다. 알파 0에도 테두리는 남으며, 글자가 주변 그림과 섞입니다. 완전히 투명한 이미지 파일을 뜻하지 않습니다.

문자열·RAQM 세로 조형·일본어 폰트와 자산 SHA256을 확인합니다. 정답 배경에도 동일한 반투명 말풍선·테두리·꼬리·그림이 있습니다. 제거 정답을 흰색 덮어쓰기로 만들지 않습니다. 손그림 페이지의 6문자군은 사람이 이미지를 보고 전사했으며, 정확한 원래 배경/글자 픽셀 정답은 없습니다.

실제 CPU RF-DETR **65회**, Hayai **148회 생성**을 실행했습니다. RF는 고정 릴리스와 기본 임계값, detail=auto, boundary=preserve_review, **include_sfx=True**입니다. 검출 후 실제 영역·마스크·크롭·adaptive OCR·수집·수정 계획·균일 배경 제거 노드를 사용합니다. 번역은 호출하지 않고 식자에 고정 한글 시험문장을 넣습니다. 실제 ComfyUI executor/GPU 및 Qwen 실행은 검증하지 않았습니다.

실행 환경은 Python3.12, torch2.6.0+cpu, torchvision0.21.0+cpu, rfdetr1.7.0, transformers5.1.0, supervision0.28.0, opencv4.13.0입니다. 검출/인식 가중치와 릴리스 코드는 어댑터의 고정 SHA256으로 검증했습니다.

수정된 JPEG 정답 검사까지 포함한 전체 CPU 회귀는 **782개 통과**했습니다. 테스트 통과가 위 실제 모델의 미충족 조건을 해결했다는 뜻은 아닙니다.

## 관측 결과

| 검사 | 결과 | 해석 |
|---|---:|---|
| 32페이지 실제 검출·크롭 | 24 기준 충족 / 8 미충족 | 글자 픽셀 98% 유지 등 국소화 기준. 전체 검출 정밀도나 페이지 성공률이 아님 |
| 알려진 OCR 크롭 40조건, 기본값 | 정확 14 / 내용 정확 19 | 줄바꿈·공백 차이를 내용 지표에서만 제외 |
| 같은 크롭, 작은 패치 설정 | 정확 27 / 내용 정확 34 | 40조건은 서로 다른 PNG 34개. 표본 내 비교이며 일반 정확도가 아님 |
| 손그림 페이지의 6개 정답 크롭 | 기본 정확 5 / 작은 패치 정확 4 | 작은 패치도 실제 퇴행 발생 |
| 제어 제거·독립 식자 96조건 | 90 충족 / 6 미충족 | 4조건은 작은 후리가나 거부, 2조건은 JPEG 잔류 1픽셀 |
| 알려진 말풍선 마스크 식자 22페이지 | 20 렌더 / 2 거부 | 정확한 배경·원문 위치를 공급한 독립 식자 |
| 실제 RF 말풍선 마스크 식자 22페이지 | 20 렌더 / 2 거부 | 렌더된 22영역 중 검증된 enclosing bubble은 12영역. 나머지는 원문 frame fallback |
| 별도 겹친 말풍선·손상 마스크 4조건 | 4 충족 | 정상 소유권 확인, 문자를 가로지르는 마스크에서는 원문 보존. 보존은 식자 완료가 아님 |

작은 패치 비교는 `base_patches=256, small_text_patches=512, small_text_px=8, line_split=True`입니다. 운영 adaptive 기본값과 비교한 실험 옵션이며 기본값으로 승격하지 않았습니다.

알려진 기하 제거 32페이지 중 22는 Qwen 출력 대기, 8은 실제 균일 제거 assembly 완료, 2는 무문자입니다. assembly 8개 중 6개가 정답 허용오차를 충족했고, JPEG 2개는 글자 위치의 잔류는 없으나 별도 압축한 정답 배경과 비교할 때 각 1픽셀이 0.035 허용오차를 초과했습니다. 새 그림 손상은 관측되지 않았습니다. 이는 Qwen 복원 품질을 입증하지 않습니다.

실제 검출 결과부터 이어 실행한 **16페이지**는 11개 Qwen 대기, 5개 후속 단계 종료입니다. 종료 5개 중 2개만 정답 무문자이며, 텍스트가 있는 페이지의 전체 완료 기준을 충족한 것은 **0개**입니다. 잘못 읽은 원문, 빠진 효과음, 줄바꿈 차이 등을 별도로 기록했습니다. 안전성 PASS 8개를 페이지 성공 8개로 해석하면 안 됩니다.

## 남은 문제

- 완전 투명 말풍선의 대사, 그림과 섞인 작은 대사/효과음, 일부 컷 경계 문자가 누락됐습니다. 같은 효과음도 배경에 따라 검출 여부가 달랐습니다.
- 글자는 검출됐어도 반투명 말풍선의 segmentation/소유권을 확인하지 못하는 조건이 있습니다. 렌더 결과가 우연히 말풍선 안에 남은 것과 검증된 경계는 구분합니다.
- 작은 후리가나는 추정 source cap 9px이 최소 10px보다 작아 페이지 식자 계획에서 거부됐습니다. 자동으로 작은 글자를 버리거나 가독성 제한을 낮추지 않았습니다.
- 손그림 페이지에서 알려진 크롭의 `ドン`은 OCR이 맞혔지만 **실제 검출은 놓쳤습니다**. OCR 크롭 성능과 검출 경로의 성능이 다릅니다.
- 같은 페이지의 `待って！`, `シーン`은 중복 영역이 남았고, `ここで会おう。` 안의 `こ`도 따로 잡혔습니다. 모자 장식은 `®`, 작은 `シーン`은 `ン` 등으로 수집됐습니다. 현재 v0.7.7의 동일 bbox+동일 mask 병합이 이 근접/부분 중복을 모두 해결하지는 않습니다.
- 손그림 `ザアア`는 기본값에서 맞고 작은 패치에서는 `ザァァ`로 틀렸습니다. 작은 패치 설정의 전역 적용을 정당화하지 않습니다.
- 손그림 페이지는 10개 편집 영역을 수집한 뒤 실제 Qwen 4타일 대기로 끝났습니다. 깨끗한 정답 배경이 없으므로 픽셀 복원 품질을 채점하지 않았고, 최종 복원/식자 성공으로 세지 않았습니다.

## 채점 기준 수정의 출처

초기 생성기는 JPEG 글자 마스크를 17px max filter로 부풀렸습니다. codec 영향 영역을 글자로 취급해 JPEG 두 페이지를 검출 실패로 잘못 셌습니다. 최종 생성기는 **blur0.55를 적용한 글자 알파**와 별도 `codec_artifact_support`를 저장합니다.

원래 보고서와 생성기, 두 마스크, references를 보존했습니다. 새 references의 32개 입력/clean PNG와 40개 OCR PNG 해시가 모두 원본 실행과 같음을 확인한 뒤, **동일한 실제 검출 결과를 재채점**했습니다. 새 RF 추론으로 꾸미지 않았습니다. 원래 검출 집계 22/10은 최종 24/8로 교정됐습니다. 제어 제거·식자 96조건은 수정된 마스크로 다시 실제 실행했습니다. 이 과정에서 숨겨졌던 JPEG 잔류 1픽셀 두 건도 드러났습니다.

## 재현

외부 자산 폴더에는 `rain.png`, `temple.png`, `NotoSerifJP.ttf`, `assets.json`이 필요합니다. inventory 각 항목 `rain`, `temple`, `font`의 `sha256`을 입력 바이트와 맞춥니다. 일본어 폰트는 Google Fonts의 Noto Serif JP이며 다운로드한 실제 파일과 OFL은 비공개 검증 묶음에 포함합니다. 폰트 자산을 Git에 복사하지 않습니다.

```bash
python tools/stress_manga_pages.py generate --destination /tmp/manga-check --assets /path/to/private-assets
python tools/stress_manga_pages.py contracts --destination /tmp/manga-check
python tools/stress_manga_pages.py bubble-lettering --destination /tmp/manga-check
python tools/stress_manga_pages.py detector --destination /tmp/manga-check --models /path/to/pinned-models
python tools/stress_manga_pages.py ocr-default --destination /tmp/manga-check --models /path/to/pinned-models
python tools/stress_manga_pages.py ocr-reduced --destination /tmp/manga-check --models /path/to/pinned-models
python tools/stress_manga_pages.py chain-default --destination /tmp/manga-check --models /path/to/pinned-models
```

모델 폴더는 `detector/`, `hayai/` 하위 구조입니다. chain-default는 완료된 실제 detector 보고서의 source/fixture SHA를 요구하며, blank/opaque/alpha128/alpha064/dark128/borderless/vertical-ruby/outlined-sfx 각 배경 8조건(16페이지)을 실행합니다. 모델/픽셀 검증의 GAP은 exit1, 실행기 오류는 exit2입니다. 같은 모드 보고서를 덮어쓰지 않으므로 새 destination에서 시작합니다. 손그림 수동 전사 및 frozen 결과 재채점은 비공개 묶음의 실행 기록과 보조 스크립트를 참조합니다.
