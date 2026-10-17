"""Pre-OCR multi-column ownership; generated pixels and model doubles only."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('page_columns_tests', ROOT/'__init__.py',
                                            submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
from page_columns_tests import layout_refinement as P, nodes as N, models as M


def page_fixture():
    image = Image.new('RGB', (700, 600), '#faf6ee')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Regular.ttf'), 14)
    boxes = []
    for column, x in enumerate((80, 280, 480)):
        for paragraph, top in enumerate((40, 220, 400)):
            for row in range(6):
                draw.text((x+4, top+row*20), f'Text {column} row {row}', font=font, fill='black')
            if column == 0:
                boxes.append([x, top, x+140, top+125])
        if column != 0:
            boxes.append([x, 40, x+140, 525])
    # Detector regions containing two columns duplicate already selected text.
    boxes += [[80, 40, 420, 300], [280, 220, 620, 525]]
    # Light section number across two rows: gutter validation must see it,
    # and row planning must preserve it as one input instead of cutting it.
    draw.rectangle((258, 40, 277, 78), fill='#777777')
    draw.text((261, 52), '5', font=font, fill='white')
    regions = [{'id': f'r{i+1}', 'kind': 'text',
                'bbox': [v*1000/[700, 600, 700, 600][k] for k, v in enumerate(box)]}
               for i, box in enumerate(boxes)]
    return image, {'origin': 'rfdetr', 'image_width': 700, 'image_height': 600, 'regions': regions}


def tensor(image):
    import torch
    return torch.from_numpy(np.asarray(image, np.float32)/255)[None]


def intersection(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0]))*max(0, min(a[3], b[3])-max(a[1], b[1]))


def test_cross_column_duplicates_become_unique_logical_regions_before_ocr():
    image, data = page_fixture()
    refined, geometry = P.refine_columns(image, data)
    assert refined['layout_refinement']['strategy'] == 'verified_page_columns'
    assert len(refined['layout_refinement']['column_cuts_pixels']) == 4
    assert {ident for row in refined['regions'] for ident in row['layout_sources']} == {r['id'] for r in data['regions']}
    boxes = [p['bounds_pixels'] for p in geometry.values()]
    assert all(intersection(a, b) == 0 for i, a in enumerate(boxes) for b in boxes[i+1:])
    assert all(1 <= len(p['row_bands_pixels']) <= 8 for p in geometry.values())
    assert all(p['bounds_pixels'][2]-p['bounds_pixels'][0] < 250 for p in geometry.values())
    # White-on-gray marker is wholly on the middle-column side of the cut.
    cut = refined['layout_refinement']['column_cuts_pixels'][1]
    assert cut <= 258
    middle = [p for ident, p in geometry.items() if ident.startswith('c2')]
    assert any(a <= 52 and 68 <= b for p in middle for _, a, _, b in p['row_bands_pixels'])
    # A cross-column detection near the top cannot widen later paragraphs.
    assert all(p['bounds_pixels'][0] >= 280 for p in middle if p['bounds_pixels'][1] >= 400)
    assert all(p['bounds_pixels'][2] <= 220 for ident, p in geometry.items()
               if ident.startswith('c1') and p['bounds_pixels'][1] >= 400)


def test_refined_crop_plans_partition_original_pixels_and_bound_edit_margins():
    image, data = page_fixture()
    crops, raw, mask, plans = N.MangaRegionCrops().crop(tensor(image), json.dumps(data),
                                                     refine_page_columns=True)
    manifest = json.loads(raw)
    edits = [r['edit_bbox_pixels'] for r in manifest['regions']]
    assert all(intersection(a, b) == 0 for i, a in enumerate(edits) for b in edits[i+1:])
    assert len(crops) == len(plans) == len(manifest['regions'])
    for region, crop, raw_plan in zip(manifest['regions'], crops, plans):
        rgb = M.pil_image(crop)
        assert np.array_equal(np.asarray(rgb), np.asarray(image.crop(region['crop_bbox_pixels'])))
        plan = json.loads(raw_plan)
        leaves = P.planned_inputs(rgb, plan)
        assert np.array_equal(np.concatenate([np.asarray(leaf) for leaf in leaves]), np.asarray(rgb))
        assert plan['region_id'] == region['id']
        assert region['ocr_region_plan'] == plan
    assert mask.any()


def test_verified_rows_are_used_before_quality_failure_and_ids_reach_collector():
    image, data = page_fixture()
    crops, manifest, _, plans = N.MangaRegionCrops().crop(tensor(image), json.dumps(data), refine_page_columns=True)
    values, reports = [], []
    class Model:
        calls = []
        def ocr(self, image, options, max_patches):
            self.calls.append(image.size)
            return {'text': f'본문 {len(self.calls)} 내용'}
    model = Model()
    for crop, plan in zip(crops, plans):
        text, report, _ = M.MangaOCRAdaptive().read(crop, model,
            region_plan_json=plan, quality_guard=False, retry_on_layout_failure=False)
        values.append(text)
        reports.append(report)
        assert json.loads(report)['initial_line_count'] == len(json.loads(plan)['rows'])
        assert all('layout_recovery' not in chunk for chunk in json.loads(report)['chunks'])
    result = json.loads(N.MangaCollectOCR().collect(values, [manifest], reports)[0])
    assert len(model.calls) > len(crops)
    assert len(model.calls) == sum(len(json.loads(plan)['rows']) for plan in plans)
    assert all(r['id'] == r['ocr_diagnostics']['region_plan']['region_id'] for r in result['regions'])
    assert all(size[0] < 250 and size[1] < 100 for size in model.calls)
    with pytest.raises(ValueError, match='plan differs'):
        N.MangaCollectOCR().collect(values, [manifest], reports[::-1])
    with pytest.raises(ValueError, match='connect ocr_region_plans'):
        N.MangaCollectOCR().collect(values, [manifest])


@pytest.mark.parametrize('change', ['manual', 'no_crossings', 'ambiguous_gutters', 'mixed_sfx', 'unassigned_fragment'])
def test_unverified_or_manual_layout_retains_original_regions(change):
    image, data = page_fixture()
    if change == 'manual':
        data['origin'] = 'manual'
    elif change == 'no_crossings':
        data['regions'] = data['regions'][:-2]
    elif change == 'mixed_sfx':
        data['regions'][0]['kind'] = 'onomatopoeia'
    elif change == 'unassigned_fragment':
        data['regions'].append({'id':'small_label','kind':'text',
                                'bbox':[320*1000/700,555*1000/600,350*1000/700,580*1000/600]})
    else:
        # Dense foreground throughout both alleged gutters supplies no safe cut.
        pixels = np.asarray(image).copy()
        rng = np.random.default_rng(72)
        for a, b in ((220, 280), (420, 480)):
            pixels[:, a:b] = rng.integers(0, 256, (600, b-a, 3), dtype=np.uint8)
        image = Image.fromarray(pixels)
    result, plans = P.refine_columns(image, data)
    assert result is data and plans == {}


@pytest.mark.parametrize('alter', ['size', 'gap', 'overlap', 'truncated', 'vertical'])
def test_invalid_explicit_row_plans_stop_before_model_calls(alter):
    image = Image.new('RGB', (100, 80))
    plan = {'strategy': 'verified_page_rows', 'region_id': 'c1p1',
            'source_size': [100, 80], 'rows': [[0, 0, 100, 40], [0, 40, 100, 80]]}
    if alter == 'size': plan['source_size'] = [101, 80]
    if alter == 'gap': plan['rows'][1][1] = 41
    if alter == 'overlap': plan['rows'][1][1] = 39
    if alter == 'truncated': plan['rows'][-1][3] = 79
    class Model:
        def ocr(self, *a, **kw): pytest.fail('Invalid plan reached OCR')
    with pytest.raises(ValueError, match='plan|horizontal'):
        M.MangaOCRAdaptive().read(tensor(image), Model(), region_plan_json=json.dumps(plan),
                                 text_direction='vertical_rtl' if alter == 'vertical' else 'auto')


def test_shipped_workflows_share_refined_manifest_for_ocr_and_cleanup():
    for name, expected in (('08-integrated-tiled-cleanup-lettering', True),
                           ('09-manual-regions-integrated-cleanup-lettering', False)):
        graph = json.loads((ROOT/'lettering/example_workflows'/f'{name}.api.json').read_text())
        ident, crops = next((i, n) for i, n in graph.items() if n['class_type'] == 'MangaRegionCrops')
        assert crops['inputs']['refine_page_columns'] is expected
        ocr = next(n for n in graph.values() if n['class_type'] == 'MangaOCRAdaptive')
        cleanup = next(n for n in graph.values() if n['class_type'] == 'MangaInpaintPlan')
        collect = next(n for n in graph.values() if n['class_type'] == 'MangaCollectOCR')
        assert ocr['inputs']['region_plan_json'] == [ident, 3]
        assert cleanup['inputs']['regions_json'] == collect['inputs']['manifest_json'] == [ident, 1]
