# Adversarial ownership audit (v0.7.18)

This is a bounded CPU contract audit, not exhaustive verification of arbitrary
images or live detector/OCR/translation/inpainting model accuracy.

## Newly reproduced defect

The verified bubble interior was dilated by two pixels before creating an OCR
reference. This admitted adjacent foreign ink and closed excluded small holes.
An independent 60 x 40 image with a 10 x 3 neighboring stroke at x=30 exposed
20 foreign pixels in the reference. The corrected reference contains zero.
The original image and every pixel inside the certified interior remain exact.

The fix removes that dilation. Pixels outside a certified interior, including
uncertified antialias fringes, are neutralized in the OCR copy. No page pixels
are changed by this operation. This does not repair an incorrect detector mask;
that remains a real-model validation requirement.

## New regression matrix

- 24 edge cases: horizontal/vertical boundaries, gaps 0/1/2/3, backgrounds
  black/gray/white. Assert exact original, exact allowed mask, unchanged own
  pixels, and neutralized outside pixels.
- 15 hole cases: excluded holes 1/2/3/4/7 pixels wide on three backgrounds.
- 100 deterministic random geometries, each exercised with forward, reverse,
  and duplicate bubble observations. Assert every source pixel is assigned
  exactly once and input objects are unchanged. These are 300 executions, not
  300 independent random samples.
- Four clipped-interior cases: top/bottom/left/right remain uncertified.

Before the fix, the initial edge/random matrix returned 24 failed and 100
passed. Some edge cases fail the exact-mask invariant even when the farther
neighbor is not reached; do not report all 24 as observed foreign-ink leakage.
After the fix the matrix is included in the full regression run.

## Wider coverage

Run the full suite, including malformed RLE and source budgets, Unicode and
translation contracts, empty pages, tile seams, font fallback, fitting and
collision handling, protected pixels, review propagation, interruption/restart,
cache identities, UI and package invariants. Separately run audit_boundaries
(baseline and transitions) and stress_image_processing contracts (generated
images, corrupt inputs, bounded injected model outputs).

Commands (with project dependencies installed):

```sh
python -m pytest tests -q --confcutdir=tests --rootdir=tests --tb=short
python tools/audit_boundaries.py --destination /tmp/manga-boundaries
python tools/audit_boundaries.py --transitions --destination /tmp/manga-transitions
python tools/stress_image_processing.py --mode contracts --destination /tmp/manga-stress
```

Expected preservation or explicit rejection is a safe-handling result, never
counted as a completed translation. Real full-resolution user pages, real model
hallucinations, detector misses, GPU memory pressure and remote-service failures
cannot be exhaustively certified here. Reproduction export is required to replay
the exact reported page and masks.

## Results and unresolved limits

- Baseline boundary audit: 43 PASS, zero failures/errors.
- Transition audit: 29 PASS after correcting invalid fixture parent boxes. The
  first run had 28 PASS and one invalid-geometry failure; the production
  containment rejection was correct and was not weakened.
- Generated image/input/tile stress: 69 PASS and **8 GAP**, no hidden conversion
  of GAP to PASS. Six lettering cases abstain (tiny 9px source below 10px
  readability floor, or insufficient low-contrast ink). Two injected inpaint
  outputs (partial residual source and wrong color) pass the current heuristic
  but differ from the independently known clean reference.

Those eight gaps are not fixed by this release. They require separate policy
and semantic quality work. Raising a pixel-change threshold cannot establish
correct background restoration, and lowering readability/ink requirements
would conceal uncertainty. This release therefore does not certify complete
translation or correct background on arbitrary images.
