"""Full glyph alpha must stay inside the verified bubble, including concavities."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image,ImageDraw
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bubble_fit_fixture',ROOT/'tests/test_hybrid_lettering.py')
T=importlib.util.module_from_spec(spec);sys.modules[spec.name]=T;spec.loader.exec_module(T)


def detector(*masks):
    items=[]
    for mask in masks:
        flat=mask.astype(np.uint8).ravel();edges=np.flatnonzero(np.diff(flat))+1
        runs=np.diff(np.r_[0,edges,len(flat)]).tolist()
        if flat[0]:runs.insert(0,0)
        items.append({'label':'bubble','score':.9,'bbox':[0,0,mask.shape[1],mask.shape[0]],
                      'mask':{'x':0,'y':0,'width':mask.shape[1],'height':mask.shape[0],'runs':runs}})
    return {'protocol':1,'image_width':masks[0].shape[1],'image_height':masks[0].shape[0],'detections':items}


def jagged():
    mask=Image.new('L',(400,320));draw=ImageDraw.Draw(mask)
    draw.polygon([(200,20),(220,70),(285,40),(270,110),(340,105),(300,160),
                  (340,215),(270,210),(285,280),(220,250),(200,305),(180,250),
                  (115,280),(130,210),(60,215),(100,160),(60,105),(130,110),(115,40),(180,70)],fill=255)
    return np.asarray(mask)>0


@pytest.mark.parametrize('via_detector',[False,True])
def test_jagged_bubble_constrains_every_alpha_pixel_instead_of_its_box(via_detector):
    mask=jagged()
    values=T.fixture('이 말풍선 안에서 모든 번역문이 테두리를 넘지 않도록 배치해야 합니다',
                     width=400,height=320,source='SOURCE',font_size=40,box=[65,30,270,260])
    options={'detection_result':detector(mask)} if via_detector else {'bubble_mask':mask.astype(np.float32)}
    _,_,old_alpha,_,_,_=T.run(values,fit_policy='readable',line_breaks='reflow')
    assert (old_alpha[~mask]>0).any(), 'Fixture must reproduce rectangle-only escape'
    _,result,alpha,report,_,_=T.run(values,fit_policy='readable',line_breaks='reflow',respect_bubbles=True,**options)
    assert alpha.sum()>10 and not (alpha[~mask]>0).any()
    assert np.array_equal(result[~mask],values[1][~mask])
    row=report['regions'][0]
    assert row['bubble_containment']['status']=='verified'
    assert row['render']['text']==json.loads(values[3])['regions'][0]['text']


def test_padded_source_frame_can_extend_beyond_bubble_without_losing_ink_ownership():
    yy,xx=np.mgrid[:240,:400]
    mask=((xx-200)/115)**2+((yy-120)/90)**2<1
    values=T.fixture('말풍선 내부 번역문',width=400,height=240,font_size=32,box=[45,10,310,220])
    _,_,alpha,report,_,_=T.run(values,respect_bubbles=True,bubble_mask=mask.astype(np.float32),fit_policy='readable')
    assert report['regions'][0]['bubble_containment']['source_ink_coverage']>=.95
    assert not alpha[~mask].any()


def test_ink_ownership_does_not_select_a_neighbour_from_padded_box_centre():
    yy,xx=np.mgrid[:240,:800]
    left=((xx-400)/135)**2+((yy-120)/95)**2<1
    right=((xx-680)/85)**2+((yy-120)/95)**2<1
    values=T.fixture('원래 말풍선 안에서 번역합니다',width=800,height=240,font_size=28,box=[280,20,500,200])
    _,_,alpha,report,_,_=T.run(values,respect_bubbles=True,bubble_mask=(left|right).astype(np.float32),fit_policy='readable')
    assert report['regions'][0]['bubble_containment']['status']=='verified'
    assert not alpha[right].any() and not alpha[~left].any()


def test_ambiguous_overlapping_detections_stop_instead_of_picking_an_arbitrary_bubble():
    yy,xx=np.mgrid[:240,:400]
    a=((xx-155)/150)**2+((yy-120)/100)**2<1
    b=((xx-245)/150)**2+((yy-120)/100)**2<1
    with pytest.raises(ValueError,match='Ambiguous'):
        T.run(T.fixture('번역',width=400,height=240,source='TEST',font_size=26),
              respect_bubbles=True,detection_result=detector(a,b))


def test_duplicate_detections_of_the_same_bubble_are_not_ambiguous():
    yy,xx=np.mgrid[:240,:400]
    mask=((xx-200)/170)**2+((yy-120)/105)**2<1
    _,_,alpha,report,_,_=T.run(T.fixture('번역',width=400,height=240),
        respect_bubbles=True,detection_result=detector(mask,mask))
    assert report['regions'][0]['bubble_containment']['status']=='verified' and not alpha[~mask].any()


def test_source_ink_crossing_a_known_bubble_is_not_silently_treated_as_a_title():
    mask=np.zeros((240,400),np.float32);mask[:,:215]=1
    with pytest.raises(ValueError,match='crosses'):
        T.run(T.fixture('번역',width=400,height=240,source='SOURCE',font_size=44),
              respect_bubbles=True,bubble_mask=mask)


def test_nonbubble_title_remains_supported_and_strict_requirement_can_stop_it():
    values=T.fixture('표지 제목')
    _,_,alpha,report,_,_=T.run(values,respect_bubbles=True)
    assert alpha.sum()>0 and report['regions'][0]['bubble_containment']['status']=='unavailable'
    with pytest.raises(ValueError,match='no verified enclosing bubble'):
        T.run(values,respect_bubbles=True,region_options_json='{"r1":{"require_bubble":true}}')


def test_impossible_fit_does_not_clip_off_letters_at_the_mask_edge():
    mask=np.zeros((120,320),np.float32);mask[25:95,70:250]=1
    values=T.fixture('너무 긴 번역문입니다 '*20)
    with pytest.raises(ValueError,match='no safe lettering fit'):
        T.run(values,respect_bubbles=True,bubble_mask=mask,fit_policy='readable')
