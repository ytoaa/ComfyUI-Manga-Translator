"""Execute the shipped integrated graph on CPU with explicit model test doubles.

Actual custom nodes, tensors, masks, OCR splitting, translation JSON validation,
tile planning/assembly, font rendering and file saving run. RF-DETR/Hayai/vLLM/
Qwen inference is replaced by fixture oracles; this is NOT a GPU quality result.
"""
from argparse import ArgumentParser
from collections import Counter
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
import torch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('integrated_simulation', ROOT/'__init__.py',
                                             submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
M = sys.modules[spec.name+'.models']
N = sys.modules[spec.name+'.nodes']
P = sys.modules[spec.name+'.detection_policy']
T = sys.modules[spec.name+'.inpaint_tiles']
from integrated_simulation.adapters.model import rle


def tensor(picture):
    return torch.from_numpy(np.asarray(picture, np.float32).copy()/255)[None]


def pil(value):
    return Image.fromarray((value[0].detach().cpu().numpy()*255).round().clip(0, 255).astype(np.uint8))


def fingerprint(picture):
    return picture.size, hashlib.sha256(picture.tobytes()).hexdigest()


def fixture(patterned_header=True):
    clean = Image.new('RGB', (1600, 640), '#e8e8e8')
    draw = ImageDraw.Draw(clean)
    if patterned_header:
        for x in range(0, 1600, 80):
            draw.polygon([(x, 0), (x+80, 0), (x+40, 120)], fill='#cccccc')
    draw.rectangle((420, 130, 1560, 605), fill='#777777')
    draw.rectangle((30, 115, 260, 570), fill='white', outline='black', width=3)
    draw.line([(60, 250), (140, 270), (220, 250), (220, 410), (140, 430), (60, 410), (60, 250)], fill='black', width=3)
    draw.line([(140, 270), (140, 430)], fill='black', width=3)
    records = [
        {'source': 'TEACHER', 'target': '선생님', 'bbox': [890, 20, 1050, 100], 'size': 26, 'color': 'black'},
        {'source': 'TEST', 'target': 'TEST', 'bbox': [70, 140, 230, 190], 'size': 32, 'color': 'black'},
        {'source': 'PAGE NOTES', 'target': '밤의 기록', 'bbox': [460, 190, 1160, 235], 'size': 26, 'color': 'white'},
        {'source': 'Check the original and translation before image editing.\nKeep names and paragraph order.',
         'target': '원문과 번역문을 확인한 뒤 이미지 편집 모델에 전달합니다.\n고유명사와 문단 순서도 확인합니다。'.replace('。', '.'),
         'bbox': [460, 275, 1510, 350], 'size': 24, 'color': 'white', 'miss_full': True},
        {'source': 'Correct the text layout.\nSplit the body into lines.',
         'target': '문장의 배치를 수정하고 있습니다.\n본문은 나누어 드립니다.',
         'bbox': [460, 390, 1490, 475], 'size': 28, 'color': 'white'},
        {'source': 'A long sentence.', 'target': '긴 문장입니다.',
         'bbox': [460, 515, 1300, 560], 'size': 28, 'color': 'white'},
    ]
    original = clean.copy()
    allmask = np.zeros((640, 1600), bool)
    for record in records:
        ink = Image.new('L', clean.size)
        d = ImageDraw.Draw(ink)
        font = ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Bold.ttf'), record['size'])
        x0, y0, _, _ = record['bbox']
        d.multiline_text((x0+4, y0+2), record['source'], font=font, fill=255, spacing=10, anchor='la')
        alpha = np.asarray(ink) > 0
        # The fixture's known detector boxes must contain every source glyph.
        yy, xx = np.nonzero(alpha)
        if xx.max() >= record['bbox'][2] or yy.max() >= record['bbox'][3]:
            raise ValueError('Fixture text exceeds its intended region')
        original.paste(record['color'], mask=ink)
        record['mask'] = alpha
        allmask |= alpha
    return original, clean, allmask, records


class DetectorOracle:
    def __init__(self, records, original, seam_case=False, failed_recovery=False, require_recovery=False, empty_recovery=False):
        self.records, self.calls, self.windows = records, 0, []
        self.original, self.seam_case, self.failed_recovery = original, seam_case, failed_recovery
        self.require_recovery, self.empty_recovery = require_recovery or failed_recovery, empty_recovery
        self.crops = {fingerprint(original): (0, 0, 1600, 640)}
        for tile in (1152, 576):
            for y0, y1 in P._sliding_windows(640, tile, 64):
                for x0, x1 in P._sliding_windows(1600, tile, 64):
                    box = [x0, x1, y0, y1]
                    if box not in self.windows: self.windows.append(box)
                    self.register_crop((x0,y0,x1,y1))
    def register_crop(self, window):
        self.crops[fingerprint(self.original.crop(window))] = tuple(window)
    def detect(self, image, thresholds):
        x0,y0,x1,y1 = self.crops[fingerprint(image)]
        full, initial = self.calls == 0, self.calls < 9
        self.calls += 1
        assert image.size == (x1-x0, y1-y0)
        found = []
        records = [] if (self.failed_recovery or self.empty_recovery) and not initial else self.records
        for index, record in enumerate(records):
            if record.get('miss_full') and initial and (full or image.width > 576 or (self.require_recovery and x0!=0)): continue
            if self.seam_case and initial and (x0,y0,x1)==(0,0,576) and index >= 2: continue
            a, b, c, d = record['bbox']
            a, b, c, d = max(a, x0), max(b, y0), min(c, x1), min(d, y1)
            if a >= c or b >= d: continue
            local = record['mask'][b:d, a:c]
            if not local.any(): continue
            found.append({'label': 'text', 'score': .95,
                          'bbox': [a-x0, b-y0, c-x0, d-y0],
                          'mask': {'x': a-x0, 'y': b-y0, 'width': c-a, 'height': d-b,
                                   'runs': rle(local)}})
        if self.seam_case and initial and (x0,y0,x1)==(0,0,576):
            # Reproduce a cross-row vertical strip whose right edge is exactly
            # 576px, rather than always returning oracle-quality paragraphs.
            ink = np.logical_or.reduce([r['mask'] for r in self.records[2:]])[185:548,462:576]
            found.append({'label':'text','score':.99,'bbox':[462,185,576,548],
                          'mask':{'x':462,'y':185,'width':114,'height':363,'runs':rle(ink)}})
        response = {'protocol': 1, 'image_width': image.width, 'image_height': image.height,
                    'model': 'SIMULATION-detector-oracle', 'revision': 'fixture', 'detections': found}
        for fragment in P._window_detections(response,(x0,y0,x1,y1),1600,640,'detail'):
            if fragment['tile_provenance']['clipped_edges']:
                for attempt in range(3): self.register_crop(P._recovery_window(fragment,1600,640,attempt))
        return response


class OCROracle:
    def __init__(self, original, records):
        self.expected, self.calls = {}, 0
        for record in records:
            x0, y0, x1, y1 = record['bbox']
            crop = original.crop((max(0, x0-4), max(0, y0-4), min(1600, x1+4), min(640, y1+4)))
            lines = M._ocr_line_images(crop)
            texts = record['source'].split('\n')
            if len(lines) != len(texts):
                raise ValueError(f'Fixture splitter returned {len(lines)} lines for {len(texts)} source lines')
            # Register the shipped input planner's exact chunks. Character
            # positions come from the fixture font, not an OCR prediction.
            from integrated_simulation.ocr_policy import plan_line
            font = ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Bold.ttf'),record['size'])
            for line, text in zip(lines, texts):
                parts = plan_line(line)
                if len(parts) == 1:
                    self.expected[fingerprint(line)] = text
                    continue
                midpoints = [8+(font.getlength(text[:i])+font.getlength(text[:i+1]))/2 for i in range(len(text))]
                for part,box in parts:
                    value = ''.join(char for char,x in zip(text,midpoints) if box[0] <= x < box[2]).strip()
                    if not value:
                        raise ValueError('OCR fixture planned an empty recognition chunk')
                    self.expected[fingerprint(part)] = value
    def ocr(self, image, options, max_patches):
        self.calls += 1
        if fingerprint(image) not in self.expected:
            raise ValueError('OCR was given an unexpected crop: coordinate/region simulation mismatch')
        return {'text': self.expected[fingerprint(image)], 'model': 'SIMULATION-ocr-oracle', 'revision': 'fixture'}


class GraphRunner:
    def __init__(self, destination, uniform_fill=True, failed_qwen=False, patterned_header=True,
                 seam_case=False, failed_recovery=False, require_recovery=False, empty_recovery=False):
        self.original, self.clean, self.raw, self.records = fixture(patterned_header)
        self.graph = json.loads((ROOT/'lettering/example_workflows/08-integrated-tiled-cleanup-lettering.api.json').read_text(encoding='utf-8'))
        self.cache, self.calls, self.destination = {}, Counter(), Path(destination)
        self.destination.mkdir(parents=True, exist_ok=True)
        self.detector = DetectorOracle(self.records,self.original,seam_case,failed_recovery,require_recovery,empty_recovery)
        self.ocr = OCROracle(self.original, self.records)
        self.failed_qwen = failed_qwen
        self.qwen_calls = 0
        self.saved = []
        for node in self.graph.values():
            if node['class_type'] == 'MangaInpaintPlan': node['inputs']['uniform_fill'] = uniform_fill
    def run(self, ident):
        if ident in self.cache: return self.cache[ident]
        node = self.graph[ident]; kind = node['class_type']
        cls = plugin.NODE_CLASS_MAPPINGS.get(kind)
        obj = cls() if cls else None
        schema = cls.INPUT_TYPES() if cls and kind not in ('MangaDetectorLoader', 'MangaOCRLoader') else {}
        fields = {**schema.get('required', {}), **schema.get('optional', {})}
        values, lazy = {}, {}
        def resolve(value):
            return self.run(value[0])[value[1]] if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) else [value]
        for key, value in node['inputs'].items():
            if len(fields.get(key, ())) > 1 and fields[key][1].get('lazy'):
                lazy[key] = value
                values[key] = (None,)  # Match ComfyUI execution.get_input_data.
            else: values[key] = resolve(value)
        if lazy:
            wanted = obj.check_lazy_status(**values)
            for key in wanted: values[key] = resolve(lazy[key])
        input_is_list = bool(getattr(cls, 'INPUT_IS_LIST', False))
        outputs = []
        count = 1 if input_is_list else max((len(v) for v in values.values()), default=1)
        if any(not v for v in values.values()): raise ValueError(f'Empty list evaluated on active node {kind}')
        for i in range(count):
            args = values if input_is_list else {k: v[min(i, len(v)-1)] for k, v in values.items()}
            self.calls[kind] += 1
            if cls and kind not in ('MangaDetectorLoader', 'MangaOCRLoader'):
                result = getattr(obj, cls.FUNCTION)(**args)
            else: result = self.native(kind, args)
            if isinstance(result, dict): result = result.get('result', ())
            while len(outputs) < len(result): outputs.append([])
            list_outputs = getattr(cls, 'OUTPUT_IS_LIST', ()) if cls else ()
            for slot, item in enumerate(result):
                if slot < len(list_outputs) and list_outputs[slot]: outputs[slot].extend(item)
                else: outputs[slot].append(item)
        self.cache[ident] = outputs
        return outputs
    def native(self, kind, a):
        if kind == 'LoadImage': return tensor(self.original), torch.zeros((1, 640, 1600))
        if kind == 'MangaDetectorLoader': return (self.detector,)
        if kind == 'MangaOCRLoader': return (self.ocr,)
        if kind in ('UNETLoader', 'CLIPLoader', 'VAELoader', 'KSamplerSelect'): return (object(),)
        if kind == 'QwenImage21Cache': return (a['model'],)
        if kind == 'ManualSigmas': return (a['sigmas'],)
        if kind == 'GrowMask':
            binary = a['mask'][0].numpy() > .5
            expanded = ndimage.binary_dilation(binary, iterations=a['expand'])
            return (torch.from_numpy(expanded.astype(np.float32))[None],)
        if kind == 'MaskToImage': return (a['mask'][..., None].repeat(1, 1, 1, 3),)
        if kind == 'ImageCrop': return (a['image'][:, a['y']:a['y']+a['height'], a['x']:a['x']+a['width'], :].clone(),)
        if kind == 'TextEncodeQwenImage21':
            value = a['images.image_1']
            assert max(value.shape[1:3]) <= 768
            return value, value, value
        if kind == 'SamplerCustom': return a['latent_image'], a['latent_image']
        if kind == 'VAEDecode':
            plan_id = next(k for k, n in self.graph.items() if n['class_type'] == 'MangaInpaintPlan')
            plan = self.cache[plan_id][6][0]
            tile = plan['tiles'][self.qwen_calls]
            self.qwen_calls += 1
            x0, y0, x1, y1 = tile['crop']
            if self.failed_qwen: return (tensor(self.original.crop((x0, y0, x1, y1))),)
            clean = self.clean.crop((x0, y0, x1, y1))
            size = (max(32, clean.width//32*32), max(32, clean.height//32*32))
            return (tensor(clean.resize(size, Image.Resampling.LANCZOS)),)
        if kind == 'ImageScale': return (tensor(pil(a['image']).resize((a['width'], a['height']), Image.Resampling.LANCZOS)),)
        if kind == 'ImageCompositeMasked':
            assert a['x'] == a['y'] == 0 and not a['resize_source']
            alpha = a['mask'][..., None]
            return (a['source']*alpha + a['destination']*(1-alpha),)
        if kind == 'PreviewImage': return ()
        if kind == 'SaveImage':
            path = self.destination/'final.png'
            pil(a['images']).save(path)
            self.saved.append(path)
            return ()
        raise ValueError('Unsupported native simulation node: '+kind)
    @contextmanager
    def services(self):
        previous, folder = N.api_json, sys.modules.get('folder_paths')
        targets = {r['source']: r['target'] for r in self.records}
        def fake_api(base, path, key, timeout, payload=None):
            if path == '/models': return {'data': [{'id': 'SIMULATION-translation-oracle'}]}
            data = json.loads(payload['messages'][1]['content'])
            answer = {'translations': [{'id': row['id'], 'target': targets[row['source']]} for row in data['regions']]}
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer, ensure_ascii=False)}}]}
        N.api_json = fake_api
        sys.modules['folder_paths'] = types.SimpleNamespace(get_output_directory=lambda: str(self.destination),
                                                          models_dir=str(self.destination/'models'))
        try: yield
        finally:
            N.api_json = previous
            if folder is None: sys.modules.pop('folder_paths', None)
            else: sys.modules['folder_paths'] = folder
    def execute(self):
        with self.services():
            # Run the same output endpoints shipped in the GUI/API graph.
            for ident, node in self.graph.items():
                cls = plugin.NODE_CLASS_MAPPINGS.get(node['class_type'])
                if node['class_type'] in ('SaveImage', 'PreviewImage') or getattr(cls, 'OUTPUT_NODE', False):
                    self.run(ident)
        plan_id = next(k for k, n in self.graph.items() if n['class_type'] == 'MangaInpaintPlan')
        finish_id = next(k for k, n in self.graph.items() if n['class_type'] == 'MangaInpaintAssemble')
        regions_id = next(k for k, n in self.graph.items() if n['class_type'] == 'MangaDetectionRegions')
        plan = self.cache[plan_id][6][0]
        cleaned = self.cache[finish_id][0][0]
        selected = json.loads(self.cache[regions_id][0][0])
        assert len(selected['regions']) == len(self.records), 'Lost or duplicated logical regions'
        assert np.all(plan['source_mask'][self.raw]), 'Detected source ink was lost from cleanup mask'
        outside = ~plan['cleanup_mask']
        assert np.array_equal(cleaned[0].numpy()[outside], np.asarray(self.original, np.float32)[outside]/255)
        assert self.saved, 'No final image reached the shipped save node'
        self.original.save(self.destination/'source.png')
        self.clean.save(self.destination/'oracle-background.png')
        pil(cleaned).save(self.destination/'cleaned.png')
        Image.fromarray((plan['cleanup_mask']*255).astype(np.uint8)).save(self.destination/'cleanup-mask.png')
        lettering_id=next(k for k,n in self.graph.items() if n['class_type']=='MangaLetterApply')
        lettering=json.loads(self.cache[lettering_id][2][0])
        (self.destination/'lettering-report.json').write_text(json.dumps(lettering,ensure_ascii=False,indent=2),encoding='utf-8')
        assert all(r['render']['font_size']<=r['source_profile']['font_cap'] for r in lettering['regions'])
        final=self.cache[lettering_id][0][0][0].numpy()
        alpha=self.cache[lettering_id][1][0][0].numpy()
        assert np.array_equal(final[alpha==0],cleaned[0].numpy()[alpha==0])
        report = {'lettering':lettering,'simulation_only': True, 'model_inference': 'fixture test doubles; NOT RF-DETR/Hayai/vLLM/Qwen GPU results',
                  'execution': 'shipped API graph, real custom nodes, PyTorch CPU and native-equivalent image operations',
                  'selected_regions': len(selected['regions']), 'detector_calls': self.detector.calls,
                  'boundary_recovery': selected['region_resolution']['boundary_recovery'],
                  'ocr_line_calls': self.ocr.calls, 'qwen_tile_calls': self.qwen_calls,
                  'calls': dict(self.calls), 'cleanup': json.loads(self.cache[finish_id][1][0]),
                  'outside_mask_unchanged': True, 'all_fixture_ink_masked': True, 'final_saved': True,
                  'full_page_qwen_was_called': False}
        (self.destination/'simulation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report


def simulate(destination):
    destination = Path(destination)
    reports = {}
    for name, fill, pattern in [('uniform-and-qwen', True, True), ('all-bounded-qwen', False, True),
                                ('uniform-bypass', True, False)]:
        reports[name] = GraphRunner(destination/name, uniform_fill=fill, patterned_header=pattern).execute()
    reports['seam-recovery'] = GraphRunner(destination/'seam-recovery', seam_case=True,require_recovery=True).execute()
    reports['fragment-stitching'] = GraphRunner(destination/'fragment-stitching',seam_case=True,empty_recovery=True).execute()
    failed_detection = GraphRunner(destination/'unresolved-seam-stopped', seam_case=True, failed_recovery=True)
    try:
        failed_detection.execute()
    except ValueError as exc:
        assert 'unresolved clipped text' in str(exc)
        assert not failed_detection.saved and failed_detection.ocr.calls == 0
        assert failed_detection.qwen_calls == 0
        reports['unresolved-seam-stopped'] = {'expected_stop': True, 'message': str(exc),
                                            'final_saved': False, 'ocr_line_calls': 0, 'qwen_tile_calls': 0}
    else:
        raise AssertionError('Unresolved seam reached OCR')
    failed = GraphRunner(destination/'unchanged-qwen-stopped', uniform_fill=False, failed_qwen=True)
    try:
        failed.execute()
    except ValueError as exc:
        assert 'retained nearly all source ink' in str(exc)
        assert not failed.saved, 'Failed cleanup reached final image save'
        reports['unchanged-qwen-stopped'] = {'expected_stop': True, 'message': str(exc), 'final_saved': False}
    else:
        raise AssertionError('Unchanged source was silently lettered')
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'summary.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: {key: v.get(key) for key in ('selected_regions', 'qwen_tile_calls', 'final_saved', 'expected_stop')}
                      for k, v in reports.items()}, ensure_ascii=False))
    return reports


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    simulate(parser.parse_args().destination)
