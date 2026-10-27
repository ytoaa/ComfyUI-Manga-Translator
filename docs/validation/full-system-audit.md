# Whole-system audit — IN PROGRESS

Scope: all runtime modules and actual user workflows, not just previous image
bugs. Baseline: v0.7.18. A passing existing suite is not a completed code review.

| Area | Code / evidence to inspect | Current audit status |
| --- | --- | --- |
| Installation/update | adapters, model files, packaging, requirements | Pending fresh audit |
| Model downloads/loading | hashes, locks, failures, partial files, device options | Pending fresh audit |
| Input/project inventory | tools/run_project.py, workflow_project.py | Initial source read; adversarial cases pending |
| Detection and ownership | detection_policy, region_policy, source_partition, mask_nodes | Prior bounded audit; full option combinations pending |
| OCR | models, ocr_engines, ocr_policy, source_recovery | Pending fresh audit |
| Translation | translation_protocol, translation_context, text_contract, nodes | Pending fresh audit |
| Document/manual editing | document, edit_review, boundary_review | Pending fresh audit |
| Cleanup | inpaint_tiles, mask nodes | Two known injected-output quality gaps open |
| Lettering | lettering package | Six known tiny/low-contrast cases open |
| Cache and reuse | stage_cache, recognition_cache | Review-report persistence defect reproduced and locally patched; tests underway |
| Cancellation/restart/concurrency | workflow_native, workflow_project, run_project, web | Existing tests selected; broader fault injection pending |
| UI/output/status | web, debug_nodes, reproduction | Pending fresh audit |
| Budgets/security/filesystem | limits, all external boundaries | Pending fresh audit |
| Documentation/workflow compatibility | docs, generator, examples | Stale architecture/known-issues version summaries found; update pending |
| Live environment | real models, ComfyUI browser, GPU, service failures | Not available in this execution environment |

## Finding SYS-CACHE-01

A report above 2 MB was silently omitted while its image was persisted. A later
reuse returned the image without its review evidence. The new negative test
failed on the baseline. Reject persistence of the pair when the report is
invalid/oversized, invalidate any old manifest for that key, and keep inference
results available to the current caller. Also serialize the outer manifest as
UTF-8 without ASCII escaping: valid multibyte reports otherwise inflate beyond
the manifest read limit.

Local regression cases: oversized report, array instead of object, malformed
JSON, normal review roundtrip, large valid Unicode report, invalid refresh over
an existing cache. These do not prove power-loss durability or network filesystem
atomicity. Full release regression is executed after the new fault tests; live-environment coverage remains unverified.

## Additional findings and evidence

SYS-TRANSPORT-02: standalone translation assumed provider fields were objects
and arrays; null/scalar responses produced AttributeError/TypeError. Validate
root response, model inventory, choices and message shape. Eleven injected
response cases reject with ValueError. No real HTTP service is called.

SYS-SAVE-03: review saves could leave partial JSON on disk failure. Remove only
the file created by this attempt on failure; never remove an existing sequence
file. Validate resolved output directory remains under the configured root.
Fault tests cover partial writes and symlink escape. This is not a race-free
filesystem sandbox against a process concurrently swapping directories.

Additional negative checks: fsync and replace failure preserve the previous
project output; hash mismatch, timeout and cancellation remove temporary model
downloads. All registered node input names match function signatures and all
explicit defaults fit advertised choices/ranges, with a controlled empty-model
ComfyUI folder_paths substitute.

The adjacent code-inventory.json covers Python syntax/callable inventory only.
It must not be read as a claim of line-by-line manual review. Full existing tests
cover installation packaging, document edits, masks/OCR/translation, cleanup,
lettering, project queue, restart and UI contracts. Areas marked pending in the
initial table still require deeper manual/real-environment review: rerunning a
suite does not close them. The eight image quality gaps remain open.

SYS-CACHE-04: a checksummed OCR cache can still contain invalid nested payloads
(schema drift or corrupted previews). Validate text/report/preview structure and
base64/image decoding with a cumulative pixel bound. Recompute rather than
report reuse when invalid. Five new negative payload tests passed.

Execution checkpoint: 1138 regression tests passed before SYS-CACHE-04; baseline
boundary audit 43 PASS, transition audit 29 PASS; both frontend contract tools
PASS. Final rerun includes SYS-CACHE-04.

SYS-PROJECT-05: the page runner recognized "HTTP error 429" but the actual
translation nodes emit "HTTP 429", "HTTP 401/403/503", or service timeout text.
Six injected two-page runs reproduced unintended submission of the second page.
Match HTTP authentication/rate-limit/server failures and the exact translation
transport errors, pause the project, and retain the failed attempt. Ordinary
page-quality errors still follow the configured continuation policy.

End-to-end controlled project simulation: completed 4, needs_review 4, failed 2,
unchanged_blank 1; no extra submissions on resume. These are expected mixed
outcomes under injected models, not 11 successfully translated real pages.
