import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tile_tests', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
T = sys.modules[spec.name+'.inpaint_tiles']


def fixture():
    y, x = np.mgrid[:640, :1600]
    clean = np.stack([.5+.1*np.sin(x/17), .55+.1*np.cos(y/21), np.full_like(x, .6, dtype=float)], axis=-1).astype(np.float32)
    raw = np.zeros((640, 1600), np.float32)
    for box in [(30, 20, 100, 55), (800, 100, 1500, 140), (1500, 590, 1600, 640)]:
        x0, y0, x1, y1 = box
        raw[y0:y1, x0:x1] = 1
    original = clean.copy(); original[raw > .5] = 0
    return original, clean, raw


def test_plan_cores_are_bounded_and_ownership_restores_page_exactly():
    original, clean, raw = fixture()
    plan = T.make_plan(original, raw, raw, uniform_fill=False)
    assert len(plan['tiles']) >= 3
    generated = []
    for tile in plan['tiles']:
        x0, y0, x1, y1 = tile['crop']
        assert x1-x0 <= 768 and y1-y0 <= 768
        candidate = np.ones((y1-y0, x1-x0, 3), np.float32)  # Destroy all context on purpose.
        candidate[tile['mask']] = clean[y0:y1, x0:x1][tile['mask']]
        generated.append(candidate)
    restored, report = T.assemble(plan, generated)
    assert np.array_equal(restored, clean)
    assert np.array_equal(restored[raw == 0], original[raw == 0])


def test_empty_pending_mask_uses_lazy_bypass_and_uniform_fill_needs_no_qwen():
    original = np.full((100, 200, 3), .7, np.float32)
    raw = np.zeros((100, 200), np.float32); raw[30:50, 60:90] = 1
    original[raw > .5] = 0
    plan = T.make_plan(original, raw, raw)
    assert plan['report']['uniform_filled_components'] == 1 and plan['tiles'] == []
    node = T.MangaInpaintAssemble()
    assert node.check_lazy_status([plan], [True]) == []
    assert node.check_lazy_status([plan], [True], (None,)) == []
    result, _ = node.finish([plan], [True], (None,))
    assert torch.allclose(result, torch.full_like(result, .7))


def test_unchanged_source_ink_stops_before_lettering():
    original, _, raw = fixture()
    plan = T.make_plan(original, raw, raw, uniform_fill=False)
    # Thin source strokes supply the high-pass samples checked by the gate.
    original2 = plan['original']
    for tile in plan['tiles']:
        x0, y0, x1, y1 = tile['crop']
        original2[y0:y1, x0:x1][tile['mask']] = .9
        local = original2[y0:y1, x0:x1]
        local[::4, ::4] = 0
    candidates = [original2[t['crop'][1]:t['crop'][3], t['crop'][0]:t['crop'][2]].copy() for t in plan['tiles']]
    with pytest.raises(ValueError, match='retained nearly all source ink'):
        T.assemble(plan, candidates)


@pytest.mark.parametrize('broken', ['missing', 'size', 'nonfinite'])
def test_broken_tile_batches_never_return_partial_pages(broken):
    original, clean, raw = fixture()
    plan = T.make_plan(original, raw, raw, uniform_fill=False)
    candidates = [clean[t['crop'][1]:t['crop'][3], t['crop'][0]:t['crop'][2]].copy() for t in plan['tiles']]
    if broken == 'missing': candidates.pop()
    elif broken == 'size': candidates[0] = candidates[0][:-1]
    else: candidates[0][0, 0, 0] = np.nan
    with pytest.raises(ValueError): T.assemble(plan, candidates)


def test_planner_enforces_pre_inference_tile_budget():
    original, _, raw = fixture()
    with pytest.raises(ValueError, match='max_tiles'):
        T.make_plan(original, raw, raw, tile_size=64, max_tiles=1, uniform_fill=False)


def test_lazy_assembler_demands_generated_tiles_only_when_needed():
    original, _, raw = fixture()
    plan = T.make_plan(original, raw, raw, uniform_fill=False)
    assert T.MangaInpaintAssemble().check_lazy_status([plan], [True]) == ['generated']
    assert T.MangaInpaintAssemble().check_lazy_status([plan], [True], (None,)) == ['generated']


def uniform_residue_fixture(patterned=False):
    original=np.full((100,220,3),.47,np.float32)
    raw=np.zeros((100,220),np.float32)
    for x in (30,55,80,105):
        original[35:55,x:x+8]=1
        raw[35:55,x:x+8]=1
    # Real source pixels omitted by the segmentation, beyond its grown mask.
    original[45:48,145:148]=1
    original[51:53,165:167]=.8
    if patterned:
        original[::3]=.25
    document=__import__('json').dumps({'image_width':220,'image_height':100,'regions':[
        {'id':'r1','kind':'text','bbox':[25/220*1000,30/100*1000,175/220*1000,60/100*1000]}]})
    return original,raw,document


def test_confirmed_uniform_region_removes_disconnected_white_residue_before_lettering():
    original,raw,document=uniform_residue_fixture()
    old=T.make_plan(original,raw,raw)
    assert np.all(old['base'][45:48,145:148] == 1)
    plan=T.make_plan(original,raw,raw,regions_json=document,recover_uniform_ink=True)
    output,report=T.assemble(plan,[])
    assert np.all(output[45:48,145:148] == np.float32(.47))
    assert np.all(output[51:53,165:167] == np.float32(.47))
    assert plan['report']['uniform_region_recovery'][0]['recovered_ink_pixels'] == 13
    assert plan['cleanup_mask'].sum() > raw.sum()
    assert np.array_equal(output[~plan['cleanup_mask']],original[~plan['cleanup_mask']])


def test_uniform_recovery_never_erases_identical_bright_art_outside_text_region():
    original,raw,document=uniform_residue_fixture()
    original[80:90,180:190]=1
    plan=T.make_plan(original,raw,raw,regions_json=document,recover_uniform_ink=True)
    output,_=T.assemble(plan,[])
    assert np.array_equal(output[80:90,180:190],original[80:90,180:190])
    assert not plan['cleanup_mask'][80:90,180:190].any()


def test_patterned_background_is_rejected_by_uniform_recovery():
    original,raw,document=uniform_residue_fixture(patterned=True)
    plan=T.make_plan(original,raw,raw,regions_json=document,recover_uniform_ink=True)
    assert not plan['report']['uniform_region_recovery'][0]['accepted']
    assert np.array_equal(plan['cleanup_mask'],raw>.5)
    assert np.all(plan['base'][45:48,145:148][1:] == 1)


def test_uniform_recovery_requires_matching_page_and_substantial_existing_ink():
    original,raw,document=uniform_residue_fixture()
    data=__import__('json').loads(document);data['image_width']=221
    with pytest.raises(ValueError,match='different page size'):
        T.make_plan(original,raw,raw,regions_json=__import__('json').dumps(data),recover_uniform_ink=True)
    plan=T.make_plan(original,raw*0,raw,regions_json=document,recover_uniform_ink=True)
    assert not plan['report']['uniform_region_recovery'][0]['accepted']


def test_uniform_fill_off_keeps_qwen_path_and_original_masks():
    original,raw,document=uniform_residue_fixture()
    plan=T.make_plan(original,raw,raw,uniform_fill=False,regions_json=document,recover_uniform_ink=True)
    assert plan['tiles'] and plan['report']['uniform_region_recovery'] == []
    assert np.array_equal(plan['cleanup_mask'],raw>.5)
