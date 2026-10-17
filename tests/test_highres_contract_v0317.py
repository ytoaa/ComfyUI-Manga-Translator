"""High-resolution runtime contracts introduced after real folder-book failures."""
import importlib.util
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'highres_contract_extension', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)

limits = sys.modules[spec.name+'.limits']
core = sys.modules[spec.name+'.lettering.core']
tiles = sys.modules[spec.name+'.inpaint_tiles']


def test_page_region_raster_and_typography_budgets_are_separate():
    assert limits.MAX_SOURCE_PIXELS == 64*1024*1024
    assert limits.MAX_REGION_PIXELS == 16*1024*1024
    assert limits.MAX_RASTER_PIXELS == 32*1024*1024
    assert limits.MAX_TYPOGRAPHY_PIXELS == 32*1024*1024
    assert core.MAX_SOURCE_PIXELS == tiles.MAX_SOURCE_PIXELS == limits.MAX_SOURCE_PIXELS
    assert core.MAX_REGION_PIXELS == limits.MAX_REGION_PIXELS
    assert core.MAX_RASTER_PIXELS == limits.MAX_RASTER_PIXELS


def test_real_logged_1262x4364_text_region_is_not_rejected_by_old_4mp_limit():
    shape = (4364,1262,3)
    assert 1262*4364 > 4*1024*1024
    assert core.bbox([0,0,1262,4364],shape) == (0,0,1262,4364)


def test_rgb_page_validation_uses_page_budget_not_region_or_raster_budget(monkeypatch):
    monkeypatch.setattr(core,'MAX_SOURCE_PIXELS',100)
    monkeypatch.setattr(core,'MAX_REGION_PIXELS',40)
    monkeypatch.setattr(core,'MAX_RASTER_PIXELS',60)
    page=np.zeros((9,10,3),np.float32)  # 90px: above both smaller work budgets.
    assert core.rgb(page).shape == page.shape
    try:
        core.bbox([0,0,8,6],page.shape)  # 48px > mocked region budget.
    except ValueError as exc:
        assert '16 Mi pixels' in str(exc)
    else:
        raise AssertionError('region budget was not enforced separately')


def test_empty_masks_bypass_component_labeling_and_qwen(monkeypatch):
    page=np.full((80,120,3),.5,np.float32)
    empty=np.zeros((80,120),np.float32)
    def forbidden(*args,**kwargs):
        raise AssertionError('empty page must not run connected-component labeling')
    monkeypatch.setattr(tiles.ndimage,'label',forbidden)
    plan=tiles.make_plan(page,empty,empty)
    assert plan['tiles']==[]
    assert plan['report']['cleanup_skipped'] is True
    assert plan['report']['skip_reason']=='empty_masks'
    result,raw=tiles.assemble(plan,[])
    assert np.array_equal(result,page)
    assert 'empty_masks' in raw


def test_cleanup_page_ceiling_follows_shared_source_policy(monkeypatch):
    page=np.zeros((9,10,3),np.float32)
    mask=np.zeros((9,10),np.float32)
    monkeypatch.setattr(tiles,'MAX_SOURCE_PIXELS',89)
    try:
        tiles.make_plan(page,mask,mask)
    except ValueError as exc:
        assert '64 Mi-pixel source-page ceiling' in str(exc)
    else:
        raise AssertionError('cleanup planner ignored source-page ceiling')
