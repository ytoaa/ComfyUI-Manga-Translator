"""Unfit source groups are restored with real font rendering; no clipped text."""
from copy import deepcopy
import json
import numpy as np
import pytest
from tests.test_hybrid_lettering import fixture,hybrid


def three_regions():
    original,clean,mask,_=fixture('가',width=500,height=220,source='SOURCE',box=[20,20,120,150])
    rows=[{'id':'bad','bbox':[20,20,120,150],'source_text':'SOURCE','text':'가'*2000},
          {'id':'touching','bbox':[130,20,150,150],'source_text':'SOURCE','text':'본문'},
          {'id':'independent','bbox':[320,20,160,150],'source_text':'SOURCE','text':'확인'}]
    # Put real source ink in every frame, including the independent region.
    for a,b,c,d in [(35,55,110,90),(150,55,250,90),(340,55,450,90)]:
        original[b:d,a:c]=0;mask[b:d,a:c]=1
    return original,clean,mask,json.dumps({'schema':1,'coordinate_format':'xywh','page_size':[500,220],'regions':rows})


def test_unfit_connected_group_restores_original_and_keeps_independent_translation():
    values=three_regions();plan,_,_=hybrid.build_plan(*values,min_font=10,fit_policy='readable',
        fit_failure_policy='preserve_review',region_options_json='{"bad":{"font_cap":10},"touching":{"font_cap":10}}')
    snapshot=plan['cleaned'].copy();original_ids=[r['id']for r in plan['regions']]
    output,alpha,raw=hybrid.render_plan(plan);report=json.loads(raw)
    assert [r['id']for r in report['regions']]==['independent']
    assert {r['id']for r in report['lettering_review']}=={'bad','touching'}
    assert report['needs_review']
    for a,b,c,d in report['protected_boxes_pixels']:
        assert not alpha[b:d,a:c].any() and np.array_equal(output[b:d,a:c],values[0][b:d,a:c])
    assert np.array_equal(plan['cleaned'],snapshot) and [r['id']for r in plan['regions']]==original_ids


@pytest.mark.parametrize('policy',['stop','preserve_review'])
def test_explicit_strict_fit_still_raises(policy):
    values=fixture('가'*2000,width=200,height=100)
    plan,_,_=hybrid.build_plan(*values,mode='strict',fit_failure_policy=policy)
    with pytest.raises(hybrid.LetteringFitError):hybrid.render_plan(plan)


def test_bad_recovery_policy_or_missing_original_does_not_publish_a_page():
    values=fixture();plan,_,_=hybrid.build_plan(*values,fit_failure_policy='preserve_review')
    plan.pop('original')
    with pytest.raises(ValueError):hybrid.render_plan(plan)
    plan['fit_failure_policy']='ignore'
    with pytest.raises(ValueError):hybrid.render_plan(plan)


def test_rejected_layout_does_not_composite_any_partial_layers(monkeypatch):
    values=three_regions();calls=[]
    plan,_,_=hybrid.build_plan(*values,region_options_json='{"bad":{"font_cap":10}}')
    original=hybrid.core.composite
    def observe(*args,**kwargs):
        calls.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(hybrid.core,'composite',observe)
    with pytest.raises(hybrid.LetteringFitError):hybrid.render_plan(plan)
    assert not calls


def test_insufficient_style_source_is_preserved_instead_of_raising_in_review_mode():
    original,clean,mask,document=fixture();mask[:]=0
    plan,_,_=hybrid.build_plan(original,clean,mask,document,fit_failure_policy='preserve_review')
    result,alpha,raw=hybrid.render_plan(plan);report=json.loads(raw)
    assert not report['regions'] and not alpha.any()
    assert report['lettering_review'][0]['reason']=='insufficient_source_style_pixels'
    for a,b,c,d in report['protected_boxes_pixels']:assert np.array_equal(result[b:d,a:c],original[b:d,a:c])


def test_parent_restore_frame_is_used_for_a_failed_paragraph():
    values=list(three_regions());data=json.loads(values[3])
    data['regions'][0]['parent_id']='page_caption'
    data['regions'][0]['source_edit_bbox']=[15,15,270,165]
    values[3]=json.dumps(data)
    plan,_,_=hybrid.build_plan(*values,fit_failure_policy='preserve_review',region_options_json='{"bad":{"font_cap":10}}')
    output,alpha,raw=hybrid.render_plan(plan);report=json.loads(raw)
    assert [15,15,285,180]in report['protected_boxes_pixels']
    assert np.array_equal(output[15:180,15:285],values[0][15:180,15:285])
    assert not alpha[15:180,15:285].any()
