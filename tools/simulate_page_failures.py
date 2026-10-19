"""Reproduce image failure classes without copying private user inputs.

contracts: actual node code + explicitly scripted model responses.
detector/ocr: real pinned CPU weights, independent generated ground truth.
Exit 0=all stated criteria met, 1=observed gaps, 2=harness/runtime errors.
PASS for an intentional refusal is not a successful translated page.
"""
from argparse import ArgumentParser
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import types
import os

if __package__:
    from . import image_scenarios as S
else:
    import image_scenarios as S

ROOT = S.ROOT


def save(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def modules(destination):
    package = types.ModuleType('page_failure_simulation');package.__path__ = [str(ROOT)]
    sys.modules[package.__name__] = package
    paths = types.ModuleType('folder_paths');paths.models_dir = str(destination/'models')
    paths.get_output_directory = lambda: str(destination/'native-output')
    paths.get_input_directory = lambda: str(destination/'fixtures')
    paths.get_folder_paths = lambda _: []
    sys.modules['folder_paths'] = paths
    return lambda name: importlib.import_module(package.__name__+'.'+name)


def identity():
    paths = sorted([*ROOT.glob('*.py'), *ROOT.glob('adapters/*.py'), *ROOT.glob('lettering/*.py'),
                    ROOT/'tools/image_scenarios.py', Path(__file__)])
    result = {'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    try:
        result.update(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      working_tree_modified=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)))
    except (OSError, subprocess.CalledProcessError):result['source_commit'] = None
    return result


class Audit:
    def __init__(self, destination, mode):
        self.destination, self.mode = destination, mode
        self.report = {'schema': 1, 'mode': mode, 'device': 'cpu', **identity(), 'results': [], 'completed': False,
                       'scope': 'generated fixtures only; contracts use explicit doubles; real-model modes named separately',
                       'end_to_end_translation_qwen_verified': False}
        self.flush()

    def case(self, ident, group, criterion, fn, real_model=False):
        started = time.monotonic()
        row = {'id': ident, 'group': group, 'criterion': criterion, 'real_model': real_model}
        try:
            met, evidence = fn()
            row.update(status='PASS' if met else 'GAP', evidence=evidence)
        except Exception as exc:
            import traceback
            row.update(status='ERROR', error=str(exc), exception=type(exc).__name__, traceback=traceback.format_exc())
        row['seconds'] = round(time.monotonic()-started, 3)
        self.report['results'].append(row);self.flush()
        print(json.dumps({k: row[k] for k in ('id', 'group', 'status', 'seconds')}, ensure_ascii=False), flush=True)

    def flush(self):
        self.report['counts'] = dict(Counter(r['status'] for r in self.report['results']))
        self.report['peak_rss_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024, 1)
        save(self.destination/(self.mode+'-results.json'), self.report)

    def exit_code(self):
        statuses = [r['status'] for r in self.report['results']]
        return 2 if 'ERROR' in statuses else 1 if 'GAP' in statuses else 0


def contracts(audit, get):
    import numpy as np
    import torch
    from PIL import Image
    from scipy import ndimage
    D, R, N, M = [get(n) for n in ('detection_policy', 'region_policy', 'nodes', 'models')]
    H, G, I = [get(n) for n in ('lettering.hybrid', 'text_geometry', 'inpaint_tiles')]
    tensor = lambda im: torch.from_numpy(np.asarray(im, np.float32).copy()/255)[None]
    class Empty:
        calls = 0
        def detect(self, image, thresholds):
            self.calls += 1
            return {'protocol': 1, 'image_width': image.width, 'image_height': image.height, 'detections': []}
    for pixels in (940, 964, 979, 980, 1000):
        def boundary(pixels=pixels):
            complete = {'label': 'text', 'score': .9, 'bbox': [100, 100, 100+pixels, 180]}
            fragment = {'label': 'text', 'score': .9, 'bbox': [100, 100, 1100, 180],
                        'tile_provenance': {'window': [0, 0, 1100, 300], 'clipped_edges': ['right']}}
            backend = Empty()
            kept, report = D._recover_boundaries(Image.new('RGB', (1280, 400), 'white'), backend, {},
                                                 [complete, fragment], 'preserve_review')
            protected = report.get('boundary_review', {}).get('protected_boxes_pixels', [])
            contract = (not kept and bool(protected)) if pixels < 980 else bool(kept) and not protected
            return contract, {'complete_coverage': pixels/1000, 'policy_threshold': .98,
                              'recovery_calls': backend.calls, 'protected_boxes': protected,
                              'needs_review': bool(protected), 'contract_met': contract,
                              'scope': 'scripted geometry, not detector accuracy or complete translation',
                              'page_fully_translated': False}
        audit.case(f'boundary-{pixels}', 'boundary', '98% policy transition preserves unresolved source; bounded recovery', boundary)
    for gap in (0, 4, 12, 13):
        for padding, margin in ((0, 0), (4, 0), (4, 12)):
            def crop(gap=gap, padding=padding, margin=margin):
                page = torch.ones((1, 140, 480, 3))
                source = {'image_width': 480, 'image_height': 140,
                          'regions': [{'id': 'r1', 'bbox': [100*1000/480, 20*1000/140, 250*1000/480, 100*1000/140]}],
                          'needs_review': True, 'boundary_review': {'schema': 1, 'reason': 'unresolved_detection_boundary',
                              'protected_boxes_pixels': [[250+gap, 20, 290+gap, 100]]}}
                try:
                    _, manifest, _, _ = N.MangaRegionCrops().crop(page, json.dumps(source), padding, margin,
                                                               geometry_policy='preserve_review')
                    return True, {'gap': gap, 'padding': padding, 'margin': margin, 'manifest': json.loads(manifest)}
                except ValueError as exc:
                    if 'margin overlaps preserved' not in str(exc):raise
                    return False, {'gap': gap, 'padding': padding, 'margin': margin, 'error': str(exc),
                                   'source_guard_correctly_stopped_unsafe_crop': True,
                                   'workflow_continued_with_review': False}
            audit.case(f'margin-gap{gap}-p{padding}-e{margin}', 'crop-margin',
                       'preserve_review continues safely or preserves conflicting region before OCR; no fatal margin error', crop)
    for sidebar, texture, deskew in ((False, False, False), (False, True, False), (True, False, False),
                                      (True, True, False), (True, True, True)):
        def columns(sidebar=sidebar, texture=texture, deskew=deskew):
            page, data = S.column_page(sidebar, texture)
            support = np.logical_or.reduce(page.masks)
            _, manifest, _, _ = N.MangaRegionCrops().crop(tensor(page.image), json.dumps(data),
                refine_page_columns=True, auto_deskew=deskew, text_pixel_mask=torch.from_numpy(support[None].astype(np.float32)))
            doc = json.loads(manifest);boxes = [r['crop_bbox_pixels'] for r in doc['regions']]
            crossings = []
            for row, box in zip(doc['regions'], boxes):
                touched = sorted({truth['column'] for truth, mask in zip(page.rows, page.masks)
                                  if truth['column'] and (S.coverage(mask, [box]) or 0) > .05})
                if len(touched) > 1:crossings.append({'id': row['id'], 'columns': touched, 'crop': box})
            metric = S.boxes_score(page.rows, page.masks, boxes)
            path = audit.destination/'contracts-artifacts'/f'columns-{sidebar}-{texture}-{deskew}.png'
            path.parent.mkdir(exist_ok=True);page.image.save(path)
            return not crossings and not metric['missing_or_partial_ids'], {
                'sidebar': sidebar, 'texture': texture, 'deskew': deskew, 'cross_column_crops': crossings,
                'coverage': metric, 'manifest': doc, 'input_image': str(path), 'real_detector': False}
        audit.case(f'columns-sidebar{int(sidebar)}-texture{int(texture)}-deskew{int(deskew)}', 'columns',
                   'each OCR crop owns at most one generated body column and retains all selected reference ink', columns)
    for ident, response, expected_accept in (
            ('correct', 'THE STATION IS QUIET.', True), ('misspelling', 'THE STATION IS QUET.', False),
            ('foreign-sentence', '駅の時刻表を確認します。', False), ('unknown', '<UNK>', False),
            ('empty', '', False), ('repetition', 'ABCD'*40, False)):
        def quality(response=response, expected_accept=expected_accept):
            expected = 'THE STATION IS QUIET.'
            source, _ = S.text_layer(expected, size=26)
            class Scripted:
                calls = 0
                def ocr(self, image, options, max_patches):
                    self.calls += 1;return {'text': response}
            backend = Scripted()
            try:
                text, diagnostic, _ = M.MangaOCRAdaptive().read(tensor(source), backend,
                    line_split=False, quality_guard=True, retry_on_layout_failure=False)
                accepted, detail = True, {'actual': text, 'diagnostic': json.loads(diagnostic)}
            except ValueError as exc:accepted, detail = False, {'error': str(exc)}
            return accepted == expected_accept, {**detail, 'scripted_response': response,
                'expected_acceptance': expected_accept, 'accepted_by_contract': accepted,
                'model_double_calls': backend.calls, 'reference_score': S.text_score(expected, response),
                'scope': 'scripted acceptance blind spot; not an actual OCR prediction'}
        audit.case('ocr-policy-'+ident, 'ocr-guard', 'accept correct text; reject deliberately wrong/unreadable responses', quality)
    for reverse in (False, True):
        for direction in ('horizontal', 'vertical_rtl'):
            for length, target, should_fit in (('short', '다음 역에서 만나요', True),
                    ('medium', '우리는 다음 역에서 만나 함께 여행을 시작합니다.', True),
                    ('oversized', '우리는 오늘 기차를 타고 여행을 갑니다. '*30, False)):
                def lettering(reverse=reverse, direction=direction, target=target, should_fit=should_fit, length=length):
                    from PIL import ImageDraw, ImageFont
                    clean = np.ones((360, 480, 3), np.float32)
                    image = Image.fromarray((clean*255).astype('uint8'));draw = ImageDraw.Draw(image)
                    face = ImageFont.truetype(str(S.FONT), 30)
                    for xy in ((330, 110), (200, 210)):draw.text(xy, '가', font=face, fill='black')
                    original = np.asarray(image, np.float32)/255;support = (original.min(2)<.5).astype(np.float32)
                    rows = [{'id': 'a', 'bbox': [120, 90, 280, 180], 'source_text': '가', 'text': target},
                            {'id': 'b', 'bbox': [180, 125, 120, 110], 'source_text': '가', 'text': '번역'}]
                    if reverse:rows.reverse()
                    doc = {'schema': 1, 'coordinate_format': 'xywh', 'page_size': [480, 360], 'regions': rows}
                    try:
                        plan, _, _ = H.build_plan(original, clean, support, json.dumps(doc), direction=direction,
                            fit_policy='readable', line_breaks='reflow',
                            region_options_json='{"a":{"font_cap":40},"b":{"font_cap":40}}')
                        result, alpha, raw = H.render_plan(plan);report = json.loads(raw)
                    except ValueError as exc:
                        if 'no safe lettering fit' not in str(exc):raise
                        return not should_fit, {'intentional_impossible_case': not should_fit, 'error': str(exc),
                                               'diagnostic': getattr(exc, 'diagnostic', {})}
                    masks = []
                    for region in plan['regions']:
                        row = next(r for r in report['regions'] if r['id']==region['id'])
                        x, y, w, h = row['bbox'];size = row['render']['font_size']
                        style = H.scaled_style(region['style'], size/region['cap'], (w, h))
                        _, local, _ = H.core.render_text(region['text'], style, font_name=region['font'],
                            min_font=size, max_font=size, max_lines=0, **region['options'])
                        canvas = np.zeros(alpha.shape, bool);canvas[y:y+h, x:x+w] = local>0;masks.append(canvas)
                    overlap = bool((masks[0] & masks[1]).any())
                    exact = {r['id']: r['render']['text'] for r in report['regions']} == {r['id']: r['text'] for r in rows}
                    outside = bool(np.array_equal(result[alpha==0], clean[alpha==0]))
                    path = audit.destination/'contracts-artifacts'/f'letter-{reverse}-{direction}-{length}.png'
                    path.parent.mkdir(exist_ok=True);Image.fromarray((result*255).round().astype('uint8')).save(path)
                    return should_fit and exact and not overlap and outside, {'full_text_kept': exact,
                        'positive_alpha_collision': overlap, 'outside_alpha_unchanged': outside,
                        'report': report, 'image': str(path)}
                audit.case(f'letter-{int(reverse)}-{direction}-{length}', 'lettering',
                           'fit full feasible targets with disjoint glyph alpha; refuse oversized targets', lettering)
    for angle in (-17, 0, 13.5, 90):
        def rotation(angle=angle):
            source, mask = S.text_layer('LIBRARY NOTES\nA NEW JOURNEY\nKEEP THE GATE OPEN', size=26, angle=angle)
            plan, evidence = G.plan(source, ndimage.binary_dilation(mask, iterations=3), 'r1')
            if angle in (0, 90):met = not plan and not evidence['accepted']
            else:met = bool(plan) and abs(plan['source_angle']-angle)<=1 and len(plan['rows'])==3
            return met, {'angle': angle, 'plan': plan, 'evidence': evidence,
                         'scope': 'geometry decision only; unchanged 90-degree input is not recognition success'}
        audit.case('geometry-angle-'+str(angle), 'rotation', 'deskew supported slants; abstain on unchanged/90-degree input', rotation)
    for angle in (-17, 13.5, 21):
        def clipped(angle=angle):
            source, mask = S.text_layer('LIBRARY NOTES\nA NEW JOURNEY\nKEEP THE GATE OPEN', size=26, angle=angle)
            height = int(np.quantile(np.where(mask)[0], .88))
            plan, evidence = G.plan(source.crop((0, 0, source.width, height)),
                ndimage.binary_dilation(mask, iterations=3)[:height], 'clipped')
            return not plan and bool(evidence.get('needs_review')), {
                'angle': angle, 'cut_height': height, 'missing_reference_ink_fraction': float(mask[height:].sum()/mask.sum()),
                'evidence': evidence, 'reference_status': 'incomplete visible glyphs; no full-text CER is legitimate'}
        audit.case('geometry-clipped-'+str(angle), 'clipped-source',
                   'already clipped glyphs require review rather than certified OCR rows', clipped)
    for budget in (64, 1024*1024):
        for collision in (False, True):
            def checkpoint(budget=budget, collision=collision):
                from unittest.mock import patch
                K = get('stage_cache')
                image, support = S.text_layer('GATE', size=30)
                original = tensor(image);cleaned = torch.ones_like(original)
                graph = {'1': {'class_type': 'LoadImage', 'inputs': {}},
                         '2': {'class_type': 'MangaCleanupCheckpoint', 'inputs': {'original': ['1', 0], 'value': ['1', 0]}}}
                folder = audit.destination/f'cache-probe-{budget}-{collision}'
                with patch.object(K, 'MAX_BYTES', budget), patch.object(K, 'root', lambda: folder):
                    out = K.MangaCleanupCheckpoint().checkpoint(original, cleaned, 'refresh', prompt=graph,
                                                               unique_id='2', report_json='{"marker":"retained"}')
                    value, cache = out['result'];cache = json.loads(cache)
                    persisted = K.read(cache['stage_cache']['key'], 'image') is not None
                rows = [{'id': 'a', 'bbox': [0, 0, image.width, image.height], 'source_text': 'GATE', 'text': '출발'}]
                if collision:rows.append({**rows[0], 'id': 'b'})
                doc = {'schema': 1, 'coordinate_format': 'xywh', 'page_size': list(image.size), 'regions': rows}
                try:
                    plan, _, _ = H.build_plan(original[0].numpy(), value[0].numpy(), support.astype(np.float32), json.dumps(doc))
                    _, alpha, raw = H.render_plan(plan)
                    fit_ok = not collision and bool(alpha.any()) and json.loads(raw)['regions'][0]['render']['text']=='출발'
                    fit = {'rendered': True}
                except H.LetteringFitError as exc:
                    fit_ok = collision and bool(exc.diagnostic.get('collision_region_ids'))
                    fit = {'rendered': False, 'error': str(exc), 'diagnostic': exc.diagnostic}
                return bool(torch.equal(value, cleaned)) and cache.get('marker')=='retained' and persisted==(budget>64) and fit_ok, {
                    'injected_cache_budget_bytes': budget, 'persistence_written': persisted, 'value_forwarded_exactly': bool(torch.equal(value, cleaned)),
                    'cache_report': cache, 'lettering': fit,
                    'scope': 'small synthetic tensor with injected cache budget; not a 256MiB memory stress test'}
            audit.case(f'cache-{budget}-collision{int(collision)}', 'cache-lettering',
                       'cache persistence limit preserves value/report and does not change fit success or collision refusal', checkpoint)
    for textured in (False, True):
        def cleanup(textured=textured):
            source, ink = S.text_layer('NIGHT TRAIN', size=30)
            clean = np.ones((*ink.shape, 3), np.float32)
            if textured:
                yy, xx = np.indices(ink.shape);clean[:] = np.where(((xx//3+yy//3)%2)[..., None], .3, .8)
            original = clean.copy();original[ink] = 0
            grown = ndimage.binary_dilation(ink, iterations=8)
            plan = I.make_plan(original, ink, grown, uniform_fill=True)
            if plan['tiles']:
                try:I.assemble(plan, [], strict_cleanup=True)
                except ValueError as exc:return textured, {'requires_qwen': True, 'error': str(exc), 'report': plan['report'], 'fake_qwen_supplied': False}
                return False, {'error': 'Pending tile plan accepted zero generated tiles'}
            result, report = I.assemble(plan, [], strict_cleanup=True)
            correct = np.array_equal(result[~grown], original[~grown]) and np.max(np.abs(result[ink]-clean[ink]))<=1/255
            return not textured and correct, {'requires_qwen': False, 'real_uniform_cleanup_correct': bool(correct), 'report': json.loads(report)}
        audit.case('cleanup-'+('texture' if textured else 'flat'), 'cleanup',
                   'real flat cleanup works; textured pending tiles cannot be replaced by placeholders', cleanup)
    for visible in (False, True):
        def empty(visible=visible):
            image, mask = S.text_layer('NIGHT TRAIN', size=30)
            if not visible:image = Image.new('RGB', image.size, 'white')
            response = D.detail_detect(image, Empty(), {}, detail_mode='auto', boundary_policy='preserve_review')
            raw = R.MangaDetectionRegionsResolved().convert(response)[0]
            crops, manifest, _, plans = N.MangaRegionCrops().crop(tensor(image), raw, allow_empty_page=True)
            class Forbidden:
                def ocr(self, *args, **kw):raise AssertionError('Empty manifest reached OCR model')
            text, report, _ = M.MangaOCRAdaptive().read(crops[0], Forbidden(), manifest_json=manifest)
            doc = json.loads(N.MangaCollectOCR().collect([text], [manifest], [report])[0])
            return not visible and not doc['regions'], {'scripted_detector_miss': visible, 'manifest': doc,
                'real_ocr_calls': 0, 'visible_reference_text': 'NIGHT TRAIN' if visible else '',
                'scope': 'same normal empty-page exit can mean a true blank or a detector miss; independent truth distinguishes them'}
        audit.case('empty-'+('missed-text' if visible else 'blank'), 'empty-page',
                   'only a reference-blank page may count as successful no-text output', empty)


def real_ocr(audit, get, args, references):
    import numpy as np
    import torch
    from PIL import Image
    from tokenizers import Tokenizer
    A, M = get('adapters.hayai'), get('models')
    folder = A.validate(args.models/'hayai')
    calls = []
    class Measured(A.Backend):
        def _generate(self, image, options=None, max_patches=256):
            text, tokens = super()._generate(image, options, max_patches)
            calls.append({'input_size': list(image.size), 'input_rgb_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
                          'patches': max_patches, 'tokens': tokens, 'text': text})
            return text, tokens
    backend = object.__new__(Measured);backend.model = A.load_model(folder, 'cpu')
    backend.tokenizer = Tokenizer.from_file(str(folder/'tokenizer.json'))
    backend.model_name, backend.revision, backend.device = A.REPO, A.REV, 'cpu'
    backend.input_size = A.preprocess_size
    audit.report.update(model=A.REPO, revision=A.REV, bundle_sha256_verified=True)
    for row in references['ocr']:
        def recognize(row=row):
            path = args.destination/'fixtures'/row['image'];image = Image.open(path).convert('RGB')
            assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
            before = len(calls);tensor = torch.from_numpy(np.asarray(image, np.float32).copy()/255)[None]
            try:
                text, diagnostic, _ = M.MangaOCRAdaptive().read(tensor, backend, quality_guard=True,
                    line_split=True, text_direction='auto', retry_on_layout_failure=True)
                score = S.text_score(row['expected'], text)
                evidence = {'accepted_by_contract': True, 'actual': text, 'score': score, 'diagnostic': json.loads(diagnostic)}
                met = score['exact']
            except ValueError as exc:
                met = False;evidence = {'accepted_by_contract': False, 'error': str(exc), 'notes': getattr(exc, '__notes__', [])}
            return met, {**evidence, 'reference': row, 'model_calls': calls[before:],
                         'input_geometry': 'known generated crop; detector localization is not evaluated here'}
        audit.case('real-ocr-'+row['id'], 'real-ocr', 'full reference text matches NFKC + collapsed whitespace', recognize, True)


def real_detector(audit, get, args, references):
    import numpy as np
    import torch
    from PIL import Image, ImageDraw
    A, D, R, N, K = [get(n) for n in ('adapters.model', 'detection_policy', 'region_policy', 'nodes', 'mask_nodes')]
    folder = A.validate(args.models/'detector')
    spec = importlib.util.spec_from_file_location('scenario_pinned_detector', folder/'load_model.py')
    loader = importlib.util.module_from_spec(spec);sys.modules[spec.name] = loader;spec.loader.exec_module(loader)
    backend = object.__new__(A.Backend);backend.model = loader.load_model(folder/'model.safetensors')
    if str(backend.model.model.device)!='cpu':raise ValueError('This explicit diagnostic requires a CPU runtime')
    backend.model.model.model.eval();backend.model_name, backend.revision = A.REPO, A.REV
    audit.report.update(model=A.REPO, revision=A.REV, bundle_sha256_verified=True,
                        scope='real CPU detector + actual region/crop nodes on generated pages; no translation, OCR or Qwen')
    for row in references['pages']:
        def detect(row=row):
            path = args.destination/'fixtures'/row['image'];image = Image.open(path).convert('RGB')
            assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
            measured = {'calls': 0}
            class Measured:
                def detect(self, image, thresholds):
                    measured['calls'] += 1;return backend.detect(image, thresholds)
            found = D.detail_detect(image, Measured(), A.DEFAULTS, detail_mode='auto', detail_overlap=64,
                                    boundary_policy='preserve_review', include_sfx=args.include_sfx)
            prefix = args.destination/'detector-artifacts'/row['id'];prefix.parent.mkdir(exist_ok=True)
            save(prefix.with_suffix('.detections.json'), found)
            layout = R.MangaDetectionRegionsResolved().convert(found, include_sfx=args.include_sfx)[0]
            mask = K.MangaDetectionMask().make(found, include_sfx=args.include_sfx)[0]
            tensor = torch.from_numpy(np.asarray(image, np.float32).copy()/255)[None]
            try:
                _, manifest, _, _ = N.MangaRegionCrops().crop(tensor, layout, allow_empty_page=True,
                    refine_page_columns=True, auto_deskew=True, text_pixel_mask=mask, geometry_policy='preserve_review')
                doc = json.loads(manifest);boxes = [r['crop_bbox_pixels'] for r in doc['regions']]
                failure = None
            except ValueError as exc:
                doc = None;boxes = [];failure = str(exc)
            truth = np.load(args.destination/'fixtures'/(row['id']+'-truth.npz'))
            metric = S.boxes_score(row['regions'], [truth[r['id']] for r in row['regions']], boxes, args.include_sfx)
            preview = image.copy();draw = ImageDraw.Draw(preview)
            for box in boxes:draw.rectangle(box, outline='#006eff', width=3)
            preview.save(prefix.with_suffix('.crops.png'))
            save(prefix.with_suffix('.manifest.json'), doc)
            return not failure and S.localization_met(metric), {'reference': row, 'coverage': metric,
                'actual_detector_calls': measured['calls'], 'include_sfx': args.include_sfx, 'failure': failure,
                'needs_review': doc.get('needs_review', False) if doc else True,
                'manifest': doc, 'artifacts': str(prefix),
                'scope': 'coverage only; a wide false-positive crop can cover truth, so PASS is not detection precision or page quality'}
        audit.case('real-detector-'+row['id'], 'real-detector',
                   'retain reference text once, do not mix body columns, and do not create OCR crops on blank control', detect, True)


def summarize(destination):
    reports = []
    for mode in ('contracts', 'detector', 'ocr'):
        path = destination/(mode+'-results.json')
        if path.exists():reports.append(json.loads(path.read_text(encoding='utf-8')))
    lines = ['# Image scenario simulation', '',
             'Generated inputs only. PASS applies to the stated case criterion, including intentional refusals.',
             'GAP is an observed unmet criterion, never converted to PASS because it is already known.',
             'Real CPU recognition, scripted acceptance checks, geometry, and final page quality are distinct.',
             'Translation server / Qwen / ComfyUI executor / GPU parity are not verified.', '',
             '| Mode | PASS | GAP | ERROR |', '| --- | ---: | ---: | ---: |']
    for mode in ('contracts', 'detector', 'ocr'):
        report = next((r for r in reports if r['mode']==mode), None)
        if report is None:lines.append('| '+mode+' (NOT RUN) | — | — | — |');continue
        counts = report['counts'];label = mode if report.get('completed') else mode+' (INCOMPLETE)'
        lines.append('| '+label+' | '+' | '.join(str(counts.get(s, 0)) for s in ('PASS', 'GAP', 'ERROR'))+' |')
    for report in reports:
        lines += ['', '## '+report['mode'], '', '| Case | Status | Criterion |', '| --- | --- | --- |']
        lines += ['| '+r['id']+' | '+r['status']+' | '+r['criterion'].replace('|', '/')+' |' for r in report['results']]
    save(destination/'summary.json', {'schema': 1, 'reports': reports})
    (destination/'summary.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(destination/'summary.md')


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=['generate', 'contracts', 'detector', 'ocr', 'summary'])
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--models', type=Path)
    parser.add_argument('--threads', type=int, choices=range(1, 9), default=4)
    parser.add_argument('--include-sfx', action='store_true')
    args = parser.parse_args();args.destination = args.destination.resolve()
    if args.destination == ROOT or ROOT in args.destination.parents:
        parser.error('Keep generated evidence outside the Git checkout')
    if args.mode in ('detector', 'ocr') and args.models is None:parser.error('--models is required for real inference')
    args.destination.mkdir(parents=True, exist_ok=True)
    if args.mode=='summary':summarize(args.destination);return 0
    os.environ['CUDA_VISIBLE_DEVICES'] = '';os.environ['HF_HUB_OFFLINE'] = '1';os.environ['TRANSFORMERS_OFFLINE'] = '1'
    reference_path = args.destination/'fixtures/references.json'
    if args.mode in ('detector', 'ocr') and reference_path.exists():
        references = json.loads(reference_path.read_text(encoding='utf-8'))
        if references.get('generator_sha256')!=hashlib.sha256(Path(S.__file__).read_bytes()).hexdigest():
            raise ValueError('Fixture generator changed; run --mode generate before inference')
    else:references = S.generate(args.destination/'fixtures')
    if args.mode=='generate':print(args.destination/'fixtures/references.json');return 0
    import torch
    torch.set_num_threads(args.threads);torch.set_num_interop_threads(1)
    get = modules(args.destination);audit = Audit(args.destination, args.mode)
    audit.report.update(threads=args.threads, torch_version=torch.__version__, fixture_font_sha256=references['font_sha256'])
    for name in ('rfdetr', 'transformers', 'tokenizers', 'Pillow', 'numpy', 'scipy'):
        try:audit.report.setdefault('versions', {})[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:pass
    if args.mode=='contracts':contracts(audit, get)
    elif args.mode=='ocr':real_ocr(audit, get, args, references)
    else:real_detector(audit, get, args, references)
    audit.report['completed'] = True;audit.flush();return audit.exit_code()


if __name__=='__main__':
    try:code = main()
    except Exception:
        import traceback
        traceback.print_exc();code = 2
    raise SystemExit(code)
