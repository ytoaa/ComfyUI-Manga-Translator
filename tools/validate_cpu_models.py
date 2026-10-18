"""Explicit, offline CPU diagnostics with real pinned weights, never model doubles.

Run each model in a separate process. This does not enable CPU fallback in the
production ComfyUI nodes. Cases are JSON rows with id/image and optional patches.
Input images and raw answers stay in the caller's output directory.
"""
from argparse import ArgumentParser
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]


def modules():
    # Import adapters without starting ComfyUI or importing its node registry.
    package = types.ModuleType('manga_cpu_diagnostics')
    package.__path__ = [str(ROOT)]
    sys.modules[package.__name__] = package
    return lambda name: importlib.import_module(package.__name__ + '.' + name)


def run(args):
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    import torch
    from PIL import Image
    get = modules()
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    if not isinstance(cases, list) or not 1 <= len(cases) <= 128:
        raise ValueError('Expected 1..128 diagnostic cases')
    report = {'schema': 1, 'kind': args.kind, 'device': 'cpu', 'dtype': 'float32',
              'threads': args.threads, 'scope': 'real_model_inference_not_GPU_parity_or_general_accuracy',
              'versions': {}, 'cases': []}
    for name in ('torch', 'torchvision', 'transformers', 'rfdetr', 'tokenizers', 'supervision'):
        try: report['versions'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: pass
    started = time.monotonic()
    if args.kind == 'ocr':
        adapter = get('adapters.hayai')
        folder = adapter.validate(args.model_root / 'hayai')
        from tokenizers import Tokenizer
        backend = object.__new__(adapter.Backend)
        backend.model = adapter.load_model(folder, device='cpu')
        backend.tokenizer = Tokenizer.from_file(str(folder / 'tokenizer.json'))
        backend.device = 'cpu'
        options = get('adapters.options').OcrOptions
        quality = get('ocr_policy').text_problem
    else:
        adapter = get('adapters.model')
        folder = adapter.validate(args.model_root / 'detector')
        spec = importlib.util.spec_from_file_location('pinned_detector_cpu', folder / 'load_model.py')
        loader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loader)
        backend = object.__new__(adapter.Backend)
        backend.model = loader.load_model(folder / 'model.safetensors')
        if str(backend.model.model.device) != 'cpu':
            raise ValueError('Explicit CPU diagnostic requires a CPU-only runtime')
        backend.model.model.model.eval()
        backend.model_name, backend.revision = adapter.REPO, adapter.REV
    report.update(repository=adapter.REPO, revision=adapter.REV,
                  load_seconds=round(time.monotonic()-started, 3), bundle_sha256_verified=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['peak_rss_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    for case in cases:
        path = Path(case['image'])
        image = Image.open(path).convert('RGB')
        if image.width * image.height > 4 * 1024 * 1024:
            raise ValueError('Diagnostic image exceeds 4 Mi pixels')
        row = {'id': case['id'], 'size': list(image.size),
               'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        started = time.monotonic()
        if args.kind == 'ocr':
            budget = case.get('patches', 256)
            opts = options(max_new_tokens=case.get('max_new_tokens', 256),
                           repetition_penalty=case.get('repetition_penalty', 1.0))
            text, count = backend._generate(image, opts, budget)
            try:
                adapter.validate_result(text, count, opts.max_new_tokens)
                issue = quality(text, image)
            except adapter.HayaiOutputError as exc:
                issue = exc.code
            row.update(text=text, tokens=count, patches=budget,
                       model_size=list(adapter.preprocess_size(image.size, budget)),
                       options=opts.model_dump(exclude={'model'}), issue=issue)
        else:
            thresholds = case.get('thresholds', adapter.DEFAULTS)
            if (not isinstance(thresholds, dict) or set(thresholds) != set(adapter.DEFAULTS)
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1
                           for v in thresholds.values())):
                raise ValueError('Invalid diagnostic detector thresholds')
            row['thresholds'] = thresholds
            row['result'] = backend.detect(image, thresholds)
        row['seconds'] = round(time.monotonic()-started, 3)
        report['cases'].append(row)
        save()
        summary = {k: v for k, v in row.items() if k != 'result'}
        if 'result' in row:
            summary['detections'] = [{k: d[k] for k in ('label', 'score', 'bbox')}
                                     for d in row['result']['detections']]
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(json.dumps({'output': str(args.output), 'peak_rss_mib': report['peak_rss_mib']}), flush=True)


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--kind', required=True, choices=['detector', 'ocr'])
    parser.add_argument('--model-root', required=True, type=Path)
    parser.add_argument('--cases', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--threads', type=int, choices=range(1, 9), default=4)
    run(parser.parse_args())
