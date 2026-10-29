"""Known-background oracle for injected inpaint outputs, without a model."""
import json
import numpy as np
from scipy import ndimage
from PIL import Image, ImageDraw, ImageFont
import pytest
from tools.simulate_ownership_scenarios import module
T=module('inpaint_tiles')


def inputs():
    clean=np.repeat(np.linspace(.65,.85,240,dtype=np.float32)[None,:,None],120,axis=0)
    clean=np.repeat(clean,3,axis=2)
    mask=Image.new('L',(240,120));draw=ImageDraw.Draw(mask)
    from tests.test_lettering import core
    font=ImageFont.truetype(core.font_path('NanumGothic-Bold.ttf','AB CD'),30)
    draw.text((35,35),'AB CD',font=font,fill=255)
    ink=np.asarray(mask)>100
    original=clean.copy();original[ink]=.1
    owned=ndimage.binary_dilation(ink,iterations=8)
    plan={'version':1,'original':original,'base':original.copy(),'source_mask':ink,
          'cleanup_mask':owned,'tiles':[{'crop':[0,0,240,120],'mask':owned}], 'report':{}}
    return plan,clean,ink


@pytest.mark.parametrize('fault',['partial','color'])
@pytest.mark.parametrize('strict',[True,False])
def test_bad_generated_output_is_stopped_or_marked_for_review(fault,strict):
    plan,candidate,ink=inputs()
    if fault=='partial':candidate[ink & (np.indices(ink.shape)[1]<65)]=.1
    else:candidate[plan['cleanup_mask']]=[.1,.1,.9]
    if strict:
        with pytest.raises(ValueError,match='lettering was stopped'):T.assemble(plan,[candidate])
    else:
        _,raw=T.assemble(plan,[candidate],False)
        report=json.loads(raw)
        assert report['needs_review'] and report['quality_warnings']


@pytest.mark.parametrize('variation',['clean','outside','small_drift'])
def test_valid_owned_background_stays_accepted(variation):
    plan,candidate,_=inputs()
    if variation=='outside':candidate[~plan['cleanup_mask']]=0
    if variation=='small_drift':candidate-=.01
    output,raw=T.assemble(plan,[candidate])
    assert not json.loads(raw)['needs_review']
    assert np.array_equal(output[~plan['cleanup_mask']],plan['original'][~plan['cleanup_mask']])
