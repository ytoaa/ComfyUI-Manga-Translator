"""Readable recovery needs positive evidence; explicit constraints stay hard."""
import numpy as np
import pytest
from tests.test_hybrid_lettering import fixture, run, hybrid


@pytest.mark.parametrize('direction',['horizontal','vertical_rtl'])
def test_tiny_source_readable_enlargement_is_reported(direction):
    plan,_,alpha,report,_,build=run(fixture('가나',source='SOURCE',font_size=7),fit_policy='readable',page_direction=direction)
    row=report['regions'][0]
    assert row['render']['font_size']>=10 and alpha.any()
    assert row['readability_adjustments']['source_enlarged']
    assert row['scale']==round(row['render']['font_size']/row['source_profile']['font_cap'],4)
    assert report['needs_review'] and build['needs_review']


@pytest.mark.parametrize('options',[{'mode':'strict'},{'fit_policy':'source_ratio'},{'region_options_json':'{"r1":{"font_cap":6}}'}])
def test_tiny_source_hard_constraints_are_preserved(options):
    with pytest.raises(ValueError,match='below readability'):
        hybrid.build_plan(*fixture('가',font_size=7),**{'fit_policy':'readable',**options})


def faint():
    original,clean,mask,doc=fixture('가나',source='SOURCE',font_size=32)
    clean[:]=.65
    original=clean-mask[...,None]*.04
    return original,clean,mask,doc


def test_faint_supported_pigment_renders_with_review():
    plan,_,alpha,report,_,_=run(faint(),fit_policy='readable')
    assert report['regions'][0]['readability_adjustments']['low_contrast_source']
    assert report['needs_review'] and alpha.any()
    assert np.allclose(plan['regions'][0]['style']['foreground'],.61,atol=.002)


@pytest.mark.parametrize('fault',['rounding','global_shift','nonuniform'])
def test_weak_or_unstable_background_is_not_certified(fault):
    original,clean,mask,_=faint()
    if fault=='rounding':original=clean-mask[...,None]/255
    if fault=='global_shift':original-=.02
    if fault=='nonuniform':
        gradient=np.linspace(0,.2,clean.shape[1])[None,:,None]
        original-=gradient;clean-=gradient
    with pytest.raises(ValueError,match='Too few text pixels'):
        hybrid.source_style(original,clean,mask,True)
