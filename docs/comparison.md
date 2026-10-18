# 번역 프로젝트 비교

조사일: **2026-10-18**. 우리 프로젝트는 v0.6.4·정리 커밋 `b211cd0`을 기준으로 합니다. [목차](README.md) · [현재 구조](architecture.md) · [남은 한계](known-issues.md)

## 평가 범위

공식 문서와 아래 고정 커밋의 주요 데이터·실행·식자 코드를 조사했습니다. 다른 앱을 설치해 같은 페이지를 실행한 품질/속도 벤치마크는 아닙니다. 최신 배포판과 기본 브랜치의 기능도 같다고 가정하지 않습니다.

| 프로젝트 | 조사한 기본 브랜치 커밋 | 조회된 최신 릴리스 |
| --- | --- | --- |
| [Koharu](https://github.com/koharu-rs/koharu) | main · [85d6de3](https://github.com/koharu-rs/koharu/commit/85d6de339ee7d486fe381249205126d944d40bb7), 10월 16일 | [0.83.5](https://github.com/koharu-rs/koharu/releases/tag/0.83.5), 9월 22일 |
| [BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) | dev · [fa3e137](https://github.com/dmMaze/BallonsTranslator/commit/fa3e1374b4ca7c040a1a04effb96c95aac2a5e5c), 10월 18일 | [v1.5.20](https://github.com/dmMaze/BallonsTranslator/releases/tag/v1.5.20), 10월 18일 |
| [comic-translate](https://github.com/ogkalu2/comic-translate) | main · [8977b91](https://github.com/ogkalu2/comic-translate/commit/8977b91a4f7a40c3917c5a268e9e7d78e1d818da), 9월 10일 | [v2.8.9](https://github.com/ogkalu2/comic-translate/releases/tag/v2.8.9), 9월 11일 |
| [manga-image-translator](https://github.com/zyddnys/manga-image-translator) | main · [d6de6ab](https://github.com/zyddnys/manga-image-translator/commit/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2), 10월 11일 | [beta-0.3](https://github.com/zyddnys/manga-image-translator/releases/tag/beta-0.3), 2022년 4월 23일. 비교는 현재 main 기준 |

아래 경쟁 프로젝트 기능은 이 기본 브랜치와 조사 당시 공식 문서의 범위입니다. 릴리스 날짜·별 수·테스트 개수는 결과 품질 순위로 사용하지 않습니다.

## 우리 프로젝트의 위치

현재 강점은 **ComfyUI 안에서 과정이 보이는 실행**, 원본 보호와 공유 편집 계획, 페이지별 시도 기록, 원문 제거와 번역 글자 렌더링의 분리입니다. 일반적인 편집 앱과 다른 선택이며 유지할 가치가 있습니다.

부족한 것은 자동 처리 뒤 사람이 내용을 고쳐 완성하는 흐름과 배치 데이터의 표현력입니다. 현재 JSON에도 원문·번역·행 좌표·진단은 있지만, 제목/본문 계층과 사람이 수정한 상태를 독립적으로 보존하고 필요한 단계만 다시 실행하는 공통 문서 모델은 아직 제한적입니다. ComfyUI의 실행 캐시와 수동 JSON override가 전용 검수/단계 재실행 체계를 대신하지는 못합니다.

| 비교 축 | 우리 프로젝트 v0.6.4 | 다른 프로젝트에서 확인한 차이 |
| --- | --- | --- |
| 작업 환경 | 통합 08 한 개, 한 장/폴더 모두 일반 캔버스 prompt로 처리 | Koharu·BallonsTranslator·comic-translate는 전용 편집 앱 중심. manga-image-translator는 CLI·서버·배치 활용 폭이 큼 |
| 검출/OCR | 고정 RF-DETR/Hayai와 제한된 기하·패치·토큰 재시도 | Koharu는 OCR 모델 선택, comic-translate는 언어별 기본 OCR과 추가 선택. 엔진 수가 정확도를 보장하지는 않음 |
| 수정/재실행 | 미리보기·JSON 저장/override·실패/검수 페이지 재시도 | Koharu는 선택 레이어/페이지·단계 실행과 수동 수정 보존. BallonsTranslator는 원문/번역·마스크·서식의 직접 편집 |
| 조판 | 실제 폰트·방향 통일·원문 스타일 측정·회전·영역 제약 | Koharu는 의미 텍스트와 frame/typography 분리. BallonsTranslator는 rich text·서식·변형 편집. manga-image-translator는 글줄 다각형·회전 좌표 활용 |
| 번역 문맥 | 페이지 안 영역을 한 요청에서 공유 | BallonsTranslator는 번역 이력·용어집·요약/프로젝트 메모리. manga-image-translator는 일부 번역기에서 이전 페이지 문맥·용어집 |
| 폴더/복구 | attempt 기록·해시·큐/이력 대조, 브라우저가 다음 페이지 제출 | Koharu는 단계 완료 결과를 저장. comic-translate는 읽으면서 배치 처리, OCR/번역 캐시와 긴 웹툰 처리 구현 |
| 진단 | 단계별 PreviewAny/이미지·원시 응답·보존/검수 이유 | 편집 앱은 결과를 보면서 원문·번역·마스크·레이어를 고치는 접근성이 좋음 |
| 검증 | 계약/기하/폰트/픽셀 회귀와 일부 실제 CPU 추론 | 공통 입력·정답·환경을 맞춘 상호 비교는 아직 수행하지 않음 |

## 설계에서 배울 점

### Koharu: 분석·내용·표현 분리

[Scene/storage 문서](https://koharu.rs/development/scene)는 검출 분석, 원문/번역 내용, 시각 배치를 나눕니다. 고정 커밋의 [text.rs](https://github.com/koharu-rs/koharu/blob/85d6de339ee7d486fe381249205126d944d40bb7/crates/koharu-scene/src/components/text.rs)에도 `TextContent`, `SourceText`, `Translation`, `TextRole`이 분리되어 있습니다. 역할 필드의 존재가 제목/본문의 자동 분류 정확도를 증명하지는 않습니다.

[처리 안내](https://koharu.rs/guides/processing)는 완료한 단계의 결과를 유지하고 선택 영역/페이지/단계를 실행하며 사람이 수정한 텍스트를 보존하는 동작을 설명합니다. [렌더링 구현](https://github.com/koharu-rs/koharu/blob/85d6de339ee7d486fe381249205126d944d40bb7/crates/koharu-renderer/src/renderer.rs)은 geometry frame과 배치 변환을 다룹니다. [식자 안내](https://koharu.rs/guides/typesetting)는 frame fitting·폰트 fallback·세로 CJK shaping을 명시합니다.

우리에게 필요한 적용은 Rust나 전체 scene 엔진의 이식이 아닙니다. 안정된 영역 ID 아래 검출 근거, 확정/수정한 원문·번역, 배치와 스타일을 구별하고, 어느 부분이 바뀌었는지에 따라 후속 작업만 무효화하는 계약입니다. 글자 방향만 바꿨다면 원문 OCR과 번역을 그대로 재사용할 수 있어야 합니다.

### BallonsTranslator: 검수와 책 전체의 일관성

[공식 안내](https://github.com/dmMaze/BallonsTranslator/blob/fa3e1374b4ca7c040a1a04effb96c95aac2a5e5c/README.md)는 마스크/복원 편집, rich text·서식 preset·변형, 번역 이력과 용어집, 시각 문맥·요약·메모리를 제공합니다. [TextBlock](https://github.com/dmMaze/BallonsTranslator/blob/fa3e1374b4ca7c040a1a04effb96c95aac2a5e5c/ballontranslator/utils/textblock.py)은 행·각도·원문·번역·rich text·font format을 저장합니다.

[LLM 설계 문서](https://github.com/dmMaze/BallonsTranslator/blob/fa3e1374b4ca7c040a1a04effb96c95aac2a5e5c/doc/modules/llm_translator.md)는 요청 snapshot, 응답 계약, 문맥 예산, 저장과 전송 책임을 구별합니다. 재시도에는 고정 입력을 사용하고, 부분 선택은 전체 페이지 번역 완료나 문맥 갱신으로 간주하지 않습니다.

우리에게는 먼저 읽기 전용 용어집과 사람이 확정한 인물명/말투를 연결하는 것이 유용합니다. 자동 생성 메모리는 그 뒤입니다. 잘못 인식한 원문이나 검수 전 번역이 책 전체의 사실로 전파되지 않도록 출처·검수 상태·예산을 함께 저장해야 합니다.

### manga-image-translator: 행 기하와 중간 결과의 재사용

[TextBlock](https://github.com/zyddnys/manga-image-translator/blob/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2/manga_translator/utils/textblock.py)은 글줄 다각형, 회전 전후 사각형, 방향을 다룹니다. [렌더러](https://github.com/zyddnys/manga-image-translator/blob/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2/manga_translator/rendering/__init__.py)는 회전 전 크기로 배치하고 perspective transform으로 결과를 옮기는 경로를 갖고 있습니다. 우리 회전 조판의 후속 설계에서 직접 참고할 부분입니다.

[공식 설정](https://github.com/zyddnys/manga-image-translator/blob/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2/README.md)에는 원문/번역 save/load, 수동 식자용 출력, 배치, 방향 강제, 번역기별 문맥·용어집이 있습니다. 모든 번역기가 같은 문맥 기능을 지원하는 것은 아닙니다. 우리도 동일한 OCR 결과로 번역/식자 실험을 반복할 수 있는 명시적 경계를 마련해야 합니다.

### comic-translate: 언어별 구성과 수동 교정, 긴 페이지

[공식 안내](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/README.md)는 일본어 manga-ocr, 한국어 Pororo, 기타 언어 PPOCRv5의 기본 구분과 선택 OCR, 수동 모드, 페이지 텍스트/이미지 문맥, 여러 입력 형식을 설명합니다. 다양한 언어/페이지에 같은 OCR 경로만 반복하는 접근과 비교할 지점입니다.

[캐시 구현](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/pipeline/cache_manager.py)은 OCR/번역 결과를 별도로 저장하며 모델·언어·문맥을 키에 포함합니다. 다만 이미지 표본 해시와 좌표 허용 오차로 블록을 매칭하므로, 이를 우리 원본 보호 계약의 신원 검사에 그대로 도입하지는 않습니다. 단계 재사용이라는 목적을 배우되 전체 입력/크롭/설정 digest와 안정된 ID를 유지해야 합니다.

[웹툰 batch 흐름](https://github.com/ogkalu2/comic-translate/blob/8977b91a4f7a40c3917c5a268e9e7d78e1d818da/pipeline/webtoon_batch/flow.py)은 긴 물리 페이지와 가상 처리 페이지를 구별합니다. 이는 여러 이미지가 있는 폴더를 순서대로 실행하는 문제와 별도입니다. 우리 상세 검출 타일도 곧 웹툰 문맥/읽기 순서 처리의 완성을 의미하지 않습니다.

## 현재 문제와 구조적 해법

| 관측한 문제 | 필요한 변경 | 개선을 확인할 기준 |
| --- | --- | --- |
| 제목·본문·보조 문구가 하나로 합쳐짐 | 영역 아래 paragraph/line/style run과 역할·읽기 순서 표현 | 제목/본문을 따로 수정·조판하고 ID 대응을 유지 |
| 기울어진 글자가 작은 수평 박스에서 축소됨 | 회전한 로컬 frame에서 fit 후 페이지로 변환, 실제 glyph 외곽 미리보기 | 각도별 가용 공간 활용과 말풍선/이웃 영역 준수 |
| needs_review가 반복되고 사람이 고친 결과를 반영하기 어려움 | 워크플로우 노드 안 교정 입력·저장·확정, 단계별 artifact 재사용 | 번역 수정 시 검출/OCR 재실행 없이 제거·식자로 연결 |
| Hayai가 같은 입력에서 반복/오독 | 공통 OCR 결과 계약과 선택 가능한 두 번째 엔진, 불일치 근거 저장 | 정답 대비 오류 감소, 비용과 수동 검수량 함께 측정 |
| 페이지마다 인물명·어조가 달라짐 | 프로젝트 용어집·확정 번역 문맥과 bounded history | 고유명사 일관성, 실패/검수 페이지가 문맥을 오염하지 않음 |
| 실패 수 감소가 품질 향상으로 읽힘 | 실행 상태와 인식/번역/레이아웃 검수 결과를 분리 | 원본 보존 비율·누락·오독·침범·교정 시간을 별도 집계 |

검출 경계 오류를 원본 보존과 needs_review로 바꾸는 것은 손상·배치 중단을 줄이는 개선입니다. 미검출 글자가 번역되었다는 증거는 아닙니다. OCR이 정상 종료하고 JSON 형식이 맞아도 원문과 번역은 틀릴 수 있습니다.

## 다음 작업 순서

1. **데이터 계약 정리:** 기존 ID·노드 호환을 유지하며 검출 근거/원문·번역/배치·수정 출처를 분리합니다. 모든 재시도 분기에서 임의 필드를 추가하지 않고 schema와 좌표 변환을 공통 경계에서 검증합니다.
2. **검수와 단계 재실행:** 통합 08의 노드 안에서 고치고 저장·확정할 수 있게 합니다. 처리 설정 전체가 바뀔 때 새 프로젝트를 요구하는 현재 보호 장치를, 단계별 의존성과 artifact 신원 검사로 점진적으로 개선합니다. 저장된 attempt는 보존합니다.
3. **조판:** 앞서 미룬 제목/본문 분리·회전 frame·실제 외곽 미리보기·아래 공간 활용을 같은 계약 위에서 고칩니다.
4. **책 단위 문맥:** 명시적 용어집과 확정한 번역을 먼저 추가합니다. 자동 요약/메모리는 별도 검증 후 결정합니다.
5. **OCR 대안과 평가:** 동일 크롭·정답으로 Hayai와 후보 엔진을 비교한 뒤 선택/분기 정책을 결정합니다. 모델을 계속 추가하거나 일치한 출력만으로 정답 판정하지 않습니다.

ComfyUI 안에서 실시간 상태를 확인하는 목표는 유지합니다. 별도 사이드바·독립 편집 앱·숨은 백그라운드 추론 작업자를 도입하는 제안이 아닙니다. 이번 비교에서는 실행 코드나 워크플로우를 변경하지 않습니다.

## 공통 품질 평가 제안

일반 말풍선, 세로/가로 혼합, 기울어진 카드, 작은 주석/효과음, 다단 설명, 무문자/긴 페이지를 포함한 고정 자료를 먼저 정합니다. 검출만 비교할 때는 동일 원본, OCR만 비교할 때는 동일 크롭, 번역만 비교할 때는 사람이 확정한 동일 원문을 사용합니다. 최종 결과는 앱별 기본 설정과 조건을 맞춘 설정을 구별합니다.

- **검출:** 글줄/영역 누락과 과검출, 효과음/본문 혼동. 창마다 중복된 raw observation 수를 글자 영역 수로 세지 않습니다.
- **OCR:** 사람이 확인한 정답 대비 문자 오류와 누락, 미인식/보존 비율. confidence를 제공하지 않는 모델의 휴리스틱 통과를 confidence로 표시하지 않습니다.
- **번역:** 의미·고유명사·어조·영역 대응을 사람이 검수합니다. JSON 유효성은 별도입니다.
- **제거/식자:** 잔존 원문, 그림 손상, 글자 크기, 줄바꿈, 제목/본문 계층, 영역 침범을 확인합니다.
- **운영:** 페이지 시간·최대 메모리/VRAM·실패/재개·사람이 교정한 시간을 같은 조건에서 기록합니다.

기존 [627개 회귀 및 실제 CPU 관측](validation/README.md)은 유지보수 근거입니다. 627장의 실제 번역 성공이나 경쟁 앱보다 높은 정확도를 뜻하지 않습니다. 사용자 18페이지의 과거 버전 상태 집계도 현재 v0.6.4의 정확도 수치로 재사용하지 않습니다.
