# 원본 참조 기반 한국어 스타일 식자 0.1.0

기존 `MangaTranslate`의 확정 번역문과 원본 글자 이미지를 재사용한다.
Koharu 실행파일·Rust 식자 엔진·별도 Koharu Remote 저장소는 필요하지 않다.

## 이번에 구현한 범위

1. 원본 글자/지운 배경/원문 마스크를 동일 좌표로 추출한다.
2. 그 차이에서 잉크색, 대비되는 외곽선색·두께, 잉크의 미세 밝기 질감을 측정한다.
3. **실제 한글 폰트**로 확정된 번역문을 렌더링한다. 자동 크기 맞춤, 최대 행/열 수, 가로/세로쓰기, 자간, 행간, 회전, 전단 기울기, 외곽선, 그림자를 조절한다.
4. **번역문에서 새로 만든 알파**로 원문 제거 배경에 합성한다. 원문 글자 마스크와 교차하지 않는다. 새 글자의 획·외곽선·그림자가 원문 위치와 달라도 해당 배치 영역 안에서 유지된다.
5. 여러 영역은 기존 `source`/`target` 번역 JSON에서 ID와 원본 좌표를 유지해 처리한다. 겹치는 영역은 JSON 순서대로 합성하지만 참조 스타일은 항상 합성 전의 원본/지운 배경에서 읽는다.

**측정 기반 스타일 근사다. 원본 폰트의 자동 식별·새 한글 폰트 학습·손글씨/붓글씨의 완전한 형태 복제는 구현하지 않았다.** 한글 폰트를 직접 선택하고 획/배치/질감을 조절한다. 폰트의 미지원 글자가 사각형으로 출력되거나 긴 번역문이 잘리지 않도록 명시적 오류를 반환한다. 폰트 렌더링이므로 일반 문장 내용은 생성 모델에 맡기지 않는다. 자동 OCR 재검증은 이 버전에 포함하지 않는다.

## 설치와 예제 입력

2026-10-15 수정: 연결 전용 JSON/문자열 입력에 `forceInput`을 명시하고 모든 예제의
`widgets_values` 순서를 노드 선언과 맞췄다. 기존 파일에서는 번역 노드의 `Korean`이
model로 들어가고 토큰 수·timeout이 밀릴 수 있었다. 저장된 잘못된 캔버스를 그대로
계속 쓰지 말고, 저장소 업데이트 → ComfyUI 재시작 → 브라우저 새로고침 후 제공된
일반 `.json`을 다시 가져온다. 개인 번역 URL·모델·이미지 선택은 다시 확인한다.

기본 노드 우선 원칙: 01/03/04의 영역 크롭은 기본 `ImageCrop` 두 개와 `CropMask`,
좌표 공유는 기본 `PrimitiveInt`, 최종 합성은 기본 `ImageCompositeMasked`를 사용한다.
좌표 Int 노드는 `fixed`로 유지한다. 이전 `MangaLetterRegion`/`MangaLetterComposite`는
기존 저장 파일 호환용 deprecated 노드이며 새 예제에서는 사용하지 않는다.
스타일 분석·한글 렌더링·영역 JSON 연결·다중 영역 식자만 전용 노드에서 수행한다.

기존 설치된 이 저장소를 업데이트하고 ComfyUI를 재시작한다. 추가 CPU 라이브러리는 `scipy`, `fonttools`이며 기존 ComfyUI 환경에 있으면 설치할 필요가 없다. torch/CUDA/Transformers를 교체하는 명령은 실행하지 않는다. 직접 확인하려면 ComfyUI의 Python으로 `import scipy, fontTools`를 실행한다.

동봉 나눔고딕 Regular/Bold는 한글·영문용이다. 다른 한글 폰트는 `ComfyUI/models/fonts/` 아래에 두고 재시작하면 선택 목록에 나온다. 동봉 폰트를 원본 일본어 폰트로 가정하지 않는다. 스타일 참조는 원본 이미지 픽셀에서 읽는다.

저장소에서:

```bash
python3 tools/install_lettering_demo.py --comfy-root /실제/ComfyUI
```

이 명령은 합성 테스트 이미지 3개만 `ComfyUI/input/manga-lettering-demo/`에 복사한다. 다른 내용의 기존 파일은 보존하고 중단한다. 모델, 설정, 적용 프로필, 실행 스크립트는 변경하지 않는다. `lettering/example_workflows/`의 일반 `.json`을 캔버스에 가져온다. `.api.json`은 API 제출용이다.

| 파일 | 용도 |
|---|---|
| `01-single-region.json` | 모델 없이 원본 글자 분석→스타일 조절→한국어 식자→합성 |
| `02-page-regions.json` | 모델 없이 페이지의 여러 영역을 JSON으로 식자 |
| `03-vllm-translation.json` | 한 영역의 원문 STRING을 기존 vLLM에서 번역한 뒤 식자 |
| `04-qwen-pigment-experimental.json` | 선택형 Qwen 미세 잉크 질감 후보 실험 |
| `05-rfdetr-ocr-cleanup-lettering.json` | **기존 자동 검출/OCR/번역 전체 흐름 + 원문 제거 + 스타일 식자** |
| `06-manual-ocr-cleanup-lettering.json` | 기존 수동 영역/OCR/번역 흐름 + 원문 제거 + 스타일 식자 |

01/02의 입력과 출력 예제는 코드가 만든 합성 테스트 이미지다. 실제 만화나 Qwen이 처리한 결과가 아니다. 05/06은 기존 워크플로를 분기해 만든 통합 예제로, 설치된 실제 모델을 선택하고 원본 이미지를 올려야 한다. 06의 기본 수동 좌표는 기존 소개 이미지용 예시이므로 다른 페이지에서는 변경해야 한다.

## 기존 그래프와 연결하는 지점

기존 OCR/번역까지는 유지한다. `MangaEditPrompt`를 새 `MangaCleanupPrompt`로 바꾸면 Qwen은 **원문 제거와 배경 복원만** 한다. 번역문을 쓰는 요청은 보내지 않는다.

`MangaTranslate` 또는 번역 검수 저장의 JSON을 `MangaLetterPrepare`에 연결한다. 이 노드는 기존 0–1000 정규화 xyxy 좌표를 원본 페이지의 xywh로 변환한다. 기존 `edit_bbox_pixels`가 있으면 그 편집 범위를 사용하며, ID·페이지 크기·문자열을 검사한다.

`MangaLetterPage`에 원본, 원문 제거 결과, 변환된 JSON, 스타일 참조 마스크를 연결하고 그 결과를 `SaveImage`로 보낸다. 기본 참조 마스크는 편집 사각형이다. Qwen이 배경까지 많이 바꿨으면 스타일 측정이 영향을 받을 수 있으므로 정확한 원문 획 마스크를 `MangaLetterPrepare.text_pixel_mask`에 추가하거나 단일 영역 그래프에서 색/외곽선을 직접 조절한다.

Qwen의 배경 복원 오류는 이 식자 단계가 고쳐 주지 않는다. 글자 제거와 스타일 식자의 결과를 따로 확인한다.

## 영역별 스타일/레이아웃

`MangaLetterPrepare.region_options_json` 예시:

```json
{
  "r1": {
    "font": "NanumGothic-Regular.ttf",
    "layout": {"max_font": 64, "min_font": 12, "max_lines": 2, "padding": 8}
  },
  "r2": {
    "font": "NanumGothic-Bold.ttf",
    "layout": {"rotation": 8, "shear": 0.16, "max_lines": 1},
    "style": {
      "foreground": "#b51f28", "outline_color": "#ffffff", "outline_width": 3,
      "texture_strength": 1, "shadow_x": 3, "shadow_y": 4, "shadow_blur": 0
    }
  }
}
```

없는 영역 ID, 잘못된 좌표, 폰트 글리프 누락, 최소 글자 크기에서도 공간 부족은 오류다. 자동 축약·번역 변경·글자 삭제를 하지 않는다. `max_lines=0`은 자동 행/열 수이며 1로 설정하면 한 줄/열 안에서 크기를 맞춘다. 세로쓰기는 글자 단위 조판이며 일본어 전용 구두점 회전·루비/후리가나·곡선 경로는 지원하지 않는다.

## 선택형 Qwen 질감 보강의 정확한 범위

04는 기존 Qwen Image 2.1 Turbo INT8, Qwen3-VL 인코더, VAE, 8-step sigma, Euler, CFG 1을 재사용한다. 별도 가중치 다운로드는 없다. 참조 1은 원본 글자 크롭, 참조 2는 정확한 한글 렌더링이다. 이미지 모델이 만든 글자를 직접 붙이지 않고 **기본 글자 내부의 제한된 미세 밝기 변화만** 가져온다. 기본 획 모양·색·외곽선·알파는 유지한다.

따라서 원본 글자의 손글씨 형태를 새로 복제하는 TextCtrl/AnyText 모델 구현이 아니다. Qwen이 만드는 새로운 글자 모양·배경·색을 그대로 채택하지 않는다. `strength=0`은 기본 렌더링 그대로이고 `max_shift`로 밝기 변화량을 제한한다. 영역 크기 Int의 width/height가 크롭과 후보의 ImageScale에 공유된다.

**GPU/실제 ComfyUI 실행과 실물 만화 스타일 품질은 미검증이다.** CPU 폰트/픽셀 처리와 그래프 연결 검사 범위는 `VALIDATION.md`를 참고한다.

## 자원 제한

- 한 번에 페이지 하나, 16 Mi pixels 이하
- 영역 하나 4 Mi pixels 이하, 영역 최대 64개, 합산 영역 16 Mi pixels 이하
- 번역문 영역당 2048 Unicode 문자 이하
- supersample 후 캔버스 16 Mi pixels 이하
- 폰트 경로는 동봉 폰트와 `ComfyUI/models/fonts` 목록에서만 선택
- 워크플로/JSON에 API 키를 저장하지 않음; 기존 일괄 번역은 `MANGA_LLM_API_KEY` 유지
