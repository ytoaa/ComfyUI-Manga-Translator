# Workflow v2: 작은 글씨 검출·OCR·마스크 분리

이 문서는 `07-rfdetr-detail-adaptive-ocr-cleanup-lettering` 예제의 설계 이유를 기록한다. 목표는 Koharu를 그대로 복제하는 것이 아니라, 기존에 잘 동작했던 경계와 다른 만화 번역 프로젝트의 장점을 비교한 뒤 ComfyUI에 맞는 더 단순하고 검수 가능한 구조를 만드는 것이다.

## 비교한 구현

### Koharu remote 경로

기존 Koharu 경로는 RF-DETR 뒤에서 segmentation mask 정제와 겹침 보존을 수행하고, OCR 전에 여러 줄을 분리해 Hayai를 행/열 단위로 실행했다. 이 구조는 OCR 입력을 작게 나누는 데 효과적이었지만, 그대로 옮기면 ComfyUI에 별도 전처리/마스크 노드가 과도하게 늘어난다.

### manga-image-translator

`zyddnys/manga-image-translator`는 작은 원본에서 검출 누락을 줄이기 위해 detection size와 upscaling을 조절할 수 있고, textline merge와 mask refinement를 별도 단계로 둔다. 또한 원문 잔상을 줄이기 위해 inpainting mask를 확장하는 옵션을 제공한다.

참고: https://github.com/zyddnys/manga-image-translator

### comic-translate

`ogkalu2/comic-translate`는 검출된 텍스트 블록을 개별 crop으로 OCR하며, OCR crop에 소량의 bbox 확장을 적용한다. 즉 페이지 전체를 그대로 OCR하기보다 텍스트 블록 단위로 모델 입력을 집중시킨다.

참고: https://github.com/ogkalu2/comic-translate

## 선택한 구조

### 1. 검출은 전역 업스케일보다 `full page + detail tiles`

현재 RF-DETR 어댑터는 어떤 입력을 받아도 모델 내부에서 `1152x1152`로 다시 맞춘다. 따라서 1600px 페이지를 먼저 2배 확대해도 모델 입력 단계에서 다시 1152px로 줄어들어 작은 글씨가 실질적으로 커지지 않는다.

`MangaDetectorDetail`은 먼저 전체 페이지를 한 번 검출한 뒤, 큰 축만 겹친 타일로 나눠 같은 RF-DETR에 다시 넣는다. 타일 하나가 1152 모델 입력을 더 많이 차지하므로 작은 글씨가 실제 추론 입력에서 커진다. `auto`는 작은 페이지에서는 추가 실행을 생략하고, 긴 축이 커질수록 2x/3x detail pass를 사용한다. 겹친 타일은 중심이 속한 core tile 하나만 결과를 소유해 중복을 제한한다.

### 2. OCR은 `line split -> tight crop -> adaptive patches`

Hayai도 단순 외부 확대보다 patch budget이 실제 입력 해상도를 결정한다. 따라서 `MangaOCRAdaptive`는 다음 순서로 처리한다.

1. 검출 영역을 가로 행 또는 세로 열로 분리한다.
2. 각 행/열의 빈 여백을 보수적으로 줄여 글자가 차지하는 비율을 높인다.
3. 일반 글씨에는 기본 512 patches를 사용한다.
4. 짧은 축이 작은 글씨에는 1024 patches를 자동 사용한다.
5. 줄별 OCR 결과를 읽기 순서대로 다시 합친다.

기본값은 `max_new_tokens=256`, `base_patches=512`, `small_text_patches=1024`, `small_text_px=48`이다. 사용자는 속도/VRAM과 품질에 따라 바꿀 수 있다.

### 3. OCR 영역과 실제 글자 픽셀 마스크를 분리

이전 통합 그래프는 `MangaRegionCrops.edit_region_mask`라는 사각형 영역이 OCR, Qwen cleanup 적용 범위, 식자 스타일 참조 범위를 사실상 함께 결정했다. detector가 한 문단을 놓치면 Qwen이 실제로 지운 글자도 최종 합성에서 원본으로 되돌아오는 문제가 있었다.

v2에서는 RF-DETR의 segmentation RLE를 `MangaDetectionMask`가 표준 ComfyUI `MASK`로만 변환한다. 이후 동작은 가능한 한 기본 노드를 사용한다.

- 원문 픽셀 마스크 확인: `MaskToImage -> PreviewImage`
- cleanup 여유: 기본 `GrowMask`
- Qwen 결과 적용: 기본 `ImageCompositeMasked`
- 식자 스타일 참조: raw text pixel mask를 `MangaLetterPrepare.text_pixel_mask`에 연결

`MangaDetectionMask`가 커스텀인 이유는 RF-DETR 전용 local RLE를 ComfyUI `MASK`로 디코딩해야 하기 때문이다. 마스크 확대·시각화·합성은 기본 노드로 처리한다.

## v2 기본 그래프

```text
LoadImage
  ├─> MangaDetectorDetail ─> MangaDetectionRegions ─> MangaRegionCrops
  │                              │                         │
  │                              │                         └─> MangaOCRAdaptive
  │                              │                                  └─> Translate
  │                              │
  │                              └─ OCR region contract
  │
  └─> Qwen Image cleanup ───────────────────────────────┐
                                                       │
MangaDetectorDetail ─> MangaDetectionMask ─> GrowMask ─┴─> ImageCompositeMasked
                      │                                      │
                      ├─> MaskToImage -> Preview             └─> cleaned page
                      └─> MangaLetterPrepare.text_pixel_mask

translated JSON + original + text pixel mask
  └─> MangaLetterPrepare -> MangaLetterPage -> SaveImage
```

## 현재 한계

`MangaDetectionMask`는 RF-DETR이 실제로 검출한 segmentation만 사용할 수 있다. RF-DETR full/detail pass 모두 놓친 글자는 mask에도 존재하지 않는다. 그 경우 별도 text-segmentation 보조 모델을 추가할 수 있지만, v2에서는 먼저 동일 RF-DETR의 detail pass가 실제 페이지에서 누락을 얼마나 줄이는지 검증한다. 필요할 때만 보조 모델을 추가해 불필요한 모델/노드 복잡도를 피한다.

또한 Qwen raw cleanup은 여전히 페이지 전체를 생성한다. 최종 cleaned page에는 RF-DETR text pixel mask를 확장한 영역만 반영하므로 그림 변형 범위를 제한한다. mask 누락 여부는 제공된 `실제 글자 픽셀 마스크 · 검수` Preview에서 먼저 확인한다.
