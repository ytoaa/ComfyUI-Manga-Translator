# Whole-system audit — IN PROGRESS

Scope: all runtime modules and actual user workflows, not just previous image
bugs. Baseline: v0.7.18. A passing existing suite is not a completed code review.

| Area | Code / evidence inspected | Current audit status |
| --- | --- | --- |
| Installation/update | packaging manifest, extracted runtime import, requirements, adapter provenance | Local package tests; real ComfyUI dependency installation/update matrix still open |
| Model downloads/loading | pinned adapter bundles, OCR downloads, hashes and partial-file cleanup | Hash/timeout/cancellation fault tests; live GPU/device/model combinations open |
| Input/project inventory | tools/run_project.py, workflow_project.py | Normalization, inventory, recovery and path contracts reviewed/tested; remote/multi-platform filesystems open |
| Detection and ownership | detection_policy, region_policy, source_partition, mask_nodes | Prior bounded image audit; full option combinations and real-page replay open |
| OCR | models, ocr_engines, ocr_policy, source_recovery | Cache payload and acquisition recovery checked; semantic accuracy and all engine combinations open |
| Translation | translation_protocol, text_contract, nodes, lettering/translate | Malformed responses and real emitted service error messages tested; live server/model/template behavior open |
| Document/manual editing | document, edit_review, boundary_review | Revision/ownership, block/source invalidation, brush limits/protection reviewed; malformed frontend containers fixed and tested; real browser editing E2E open |
| Cleanup | inpaint_tiles, mask nodes | Two known injected-output quality gaps open |
| Lettering | lettering package | Six known tiny/low-contrast cases open |
| Cache and reuse | stage_cache, recognition_cache | Report persistence and nested OCR payload findings fixed; concurrent processes/power-loss durability open |
| Cancellation/restart/concurrency | workflow_native, workflow_project, run_project, web | Queue/restart tests and new reordered/stalled event checks; real multiple tabs/processes open |
| UI/output/status | all three web modules, save/review paths | Canvas and upload handlers executed with fault-injected network/DOM; actual ComfyUI browser layout/E2E open |
| Budgets/security/filesystem | limits, document/brush budgets, save/project/native file paths | Selected external boundaries inspected; symlink and disk faults tested; not a race-free sandbox/security audit |
| Documentation/workflow compatibility | docs, generator, examples | Current version/limitations clarified; generated workflow and package contracts tested |
| Live environment | real models, ComfyUI browser, GPU, service failures | Not available in this execution environment |

This table records bounded evidence, not a promise that every file/combination was
manually audited. No background task continues after a response is finished.

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
lettering, project queue, restart and UI contracts. The open items in the
coverage table still require deeper manual/real-environment review: rerunning a
suite does not close them. The eight image quality gaps remain open.

SYS-CACHE-04: a checksummed OCR cache can still contain invalid nested payloads
(schema drift or corrupted previews). Validate text/report/preview structure and
base64/image decoding with a cumulative pixel bound. Recompute rather than
report reuse when invalid. Five new negative payload tests passed.

v0.7.19 final checkpoint: 1149 regression tests passed (131.56 s), including
SYS-CACHE-04 and SYS-PROJECT-05. Baseline boundary audit: 43 PASS; transition
audit: 29 PASS; both original frontend contract tools PASS. Published main and
13 changed files were verified byte-for-byte against commit f555b54.

SYS-PROJECT-05: the page runner recognized "HTTP error 429" but the actual
translation nodes emit "HTTP 429", "HTTP 401/403/503", or service timeout text.
Six injected two-page runs reproduced unintended submission of the second page.
Match HTTP authentication/rate-limit/server failures and the exact translation
transport errors, pause the project, and retain the failed attempt. Ordinary
page-quality errors still follow the configured continuation policy.

End-to-end controlled project simulation: completed 4, needs_review 4, failed 2,
unchanged_blank 1; no extra submissions on resume. These are expected mixed
outcomes under injected models, not 11 successfully translated real pages.


## v0.7.20: continuation, uploads and output paths

SYS-CANVAS-06: completion/pause requests had no deadline, even after response
headers arrived. A duplicate executed event could replace a stopped job with a
fresh unstopped job; an already settled ticket could reactivate stale UI state.
Late replies also overwrote another selected project's status. A string-valued
`continue` field was accepted as truthy. Seven of the first eleven independently
injected scenarios failed before the fix. Requests now bound headers and body to
15 seconds, validate response shape, preserve duplicate/settled ownership, and
recheck current run ownership before updating UI or continuing. The expanded
15-case harness also covers a newer run, disconnect during a reply, a replayed
ticket after reconnect, and queue rejection with restoration of temporary metadata.
The reconnect/replayed-ticket ordering independently reproduced an extra queue
submission; disconnected prompt IDs are now retained in the bounded settled set.

SYS-UPLOAD-07: repeated callbacks opened multiple folder pickers; a stalled fetch
or response body left upload busy indefinitely. Late completion overwrote user
settings edited during upload, and an unexpected server destination was accepted.
Five of nine scenarios failed on the baseline. Guard the entire picker/transfer,
bound each file to 120 seconds, validate the returned destination, and apply the
new input folder only when all files succeed and captured settings still match.
Tests also cover cancel/reselect, nested folders, unsupported files, and second-
file disk failure. Already uploaded partial files are left on the server; no
unknown files are deleted and no ambiguous upload is automatically retried.

SYS-PATH-08: checking a project folder against its resolved parent allowed a
symlink in either intermediate output directory to redirect outside configured
ComfyUI output. Both ancestor cases reproduced. Check the resolved project root
against the configured output root too. A configured output root that itself is
a symlink remains supported (third test). This guards stable paths, not concurrent
hostile symlink replacement between validation and write.

Reproduction (from repository root):

```sh
node tools/check_canvas_faults.cjs
node tools/check_folder_upload.cjs
python -m pytest tests/test_canvas_frontend.py tests/test_workflow_projects.py -q --rootdir=tests --confcutdir=tests
```

These frontend harnesses execute the shipped JavaScript using controlled events,
DOM/picker/network substitutes and accelerated HTTP timers. They do not prove
browser compatibility, actual server cancellation, upload throughput or GPU
inference. Timeouts stop local continuation; an HTTP abort does not prove the
server stopped processing an already received request.


SYS-REVIEW-09: a JSON array at the root or in `pages` accepted named revision
properties in JavaScript, but JSON serialization discarded them. The panel
reported edits saved even though they were absent from `edits_json`. The new
regression reproduced that misleading success before the fix. Both text review
and cleanup brush review now validate root, page/identity maps, selected revision
and region patch containers before modifying or approving edits. Ten malformed
container cases retain the original widget JSON and show an error; ordinary
paragraph editing, approval and brush scenarios remain in the same harness.

```sh
node tools/check_node_ui.cjs
```

Release checkpoint (2026-10-28): full regression 1154 PASS in 135.46 seconds.
After the last reconnect-order fix, the frontend/project-path/packaging selection
also passed 35 tests. The JavaScript harnesses include 15 continuation, nine
upload and ten malformed-review-container scenarios in addition to the existing
UI checks; these are nested checks, not 34 extra pytest tests. Source inventory:
195 registered files, 122 local documentation links, one GUI/API workflow and
adapter provenance verified. No actual model accuracy or live deployment is
inferred from these counts. The audit remains IN PROGRESS with the open scope
listed above.
