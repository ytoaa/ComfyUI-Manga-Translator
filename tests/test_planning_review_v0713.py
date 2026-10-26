"""Plan-time quality failures restore source; invalid tuning and strict stay hard."""
import json
import numpy as np
import pytest
from fontTools import subset
from fontTools.ttLib import TTFont
from tests.test_hybrid_lettering import fixture,hybrid,core,run
from tests.test_fit_preservation import three_regions
from tests.test_lettering_failures_v0712 import many_bubbles
from tests.test_bubble_containment import detector


def test_real_six_pixel_estimate_preserves_source_without_lowering_the_minimum():
    values=fixture('완전한 번역문',font_size=8)
    plan,out,alpha,report,_,build=run(values,fit_failure_policy='preserve_review')
    row=report['lettering_review'][0]
    assert row['reason']=='source_below_readability_minimum'
    assert row['diagnostic']['source_cap']==6 and row['diagnostic']['minimum_font']==10
    assert not plan['regions'] and not alpha.any() and report['needs_review'] and build['needs_review']
    a,b,c,d=row['bbox_pixels'];assert np.array_equal(out[b:d,a:c],values[0][b:d,a:c])
    assert report.get('page_status')!='no_text_detected'
    assert report['skip_reason']=='lettering_regions_preserved'


@pytest.mark.parametrize('options',[{'fit_failure_policy':'stop'},
    {'fit_failure_policy':'preserve_review','mode':'strict'},
    {'fit_failure_policy':'preserve_review','region_options_json':'{"r1":{"mode":"strict"}}'}])
def test_six_pixel_strict_and_stop_remain_errors(options):
    with pytest.raises(ValueError,match='r1: source size 6px is below readability minimum 10px'):
        run(fixture('번역',font_size=8),**options)


def test_low_cap_restores_parent_and_touching_regions_but_keeps_independent_text():
    original,clean,mask,raw=three_regions();data=json.loads(raw)
    data['regions'][0]['text']='번역'
    data['regions'][0].update(parent_id='parent',source_edit_bbox=[15,15,270,165])
    plan,out,alpha,report,_,_=run((original,clean,mask,json.dumps(data)),fit_failure_policy='preserve_review',
                                 region_options_json='{"bad":{"font_cap":6}}')
    assert [r['id'] for r in report['regions']]==['independent']
    assert {r['id'] for r in report['lettering_review']}=={'bad','touching'}
    assert np.array_equal(out[15:180,15:285],original[15:180,15:285])
    assert not alpha[15:180,15:285].any()
    assert any(r['diagnostic']['cap_origin']=='override' for r in report['lettering_review'] if r['id']=='bad')


def test_closure_uses_the_whole_restore_frame_even_when_child_sources_do_not_overlap():
    original,clean,mask,raw=three_regions();data=json.loads(raw)
    data['regions'][0]['bbox']=[20,20,90,150];data['regions'][0]['text']='가'
    data['regions'][1].update(bbox=[170,20,110,150],parent_id='other_parent',source_edit_bbox=[100,15,185,165])
    _,out,alpha,report,_,_=run((original,clean,mask,json.dumps(data)),fit_failure_policy='preserve_review',
                              region_options_json='{"bad":{"font_cap":6}}')
    assert {r['id'] for r in report['lettering_review']}=={'bad','touching'}
    assert [r['id'] for r in report['regions']]==['independent']
    assert np.array_equal(out[15:180,100:285],original[15:180,100:285])
    assert not alpha[15:180,100:285].any()


def test_strict_neighbour_cannot_be_silently_preserved_by_plan_recovery():
    with pytest.raises(ValueError,match='strict lettering overlaps'):
        run(three_regions(),fit_failure_policy='preserve_review',
            region_options_json='{"bad":{"font_cap":6},"touching":{"mode":"strict"}}')


def test_explicit_per_region_cap_can_authorize_enlargement_without_lowering_minimum():
    plan,_,alpha,report,_,_=run(fixture('가',font_size=7),fit_failure_policy='preserve_review',
                               region_options_json='{"r1":{"font_cap":10}}')
    assert alpha.any() and report['regions'][0]['render']['font_size']==10
    assert not report['lettering_review'] and plan['regions'][0]['floor']==10


@pytest.mark.parametrize('patch',[{'mode':'invalid'},{'direction':'invalid'},{'fit_policy':'invalid'},
    {'line_breaks':'invalid'},{'min_font':3},{'min_font':True},{'font_cap':float('nan')},
    {'padding':-1},{'alignment':'invalid'},{'tracking':50},{'min_scale':0},
    {'require_bubble':'yes'},{'supersample':0}])
def test_invalid_controls_are_not_hidden_by_small_source_preservation(patch):
    values=list(fixture('가',font_size=7));data=json.loads(values[3])
    if 'supersample' in patch:data['regions'][0]['layout']=patch;options='{}'
    else:options=json.dumps({'r1':patch})
    values[3]=json.dumps(data)
    with pytest.raises(ValueError):run(values,fit_failure_policy='preserve_review',region_options_json=options)


def test_rectified_measurement_failure_uses_the_same_source_restore_path(monkeypatch):
    values=list(fixture('번역'));data=json.loads(values[3]);data['source_orientation']={'r1':{'source_angle':8}}
    values[3]=json.dumps(data);original=hybrid.profile;calls=[]
    def measurement(*a,**kw):
        calls.append(True)
        if len(calls)==2:raise ValueError('Too few source ink pixels to estimate typography')
        return original(*a,**kw)
    monkeypatch.setattr(hybrid,'profile',measurement)
    _,out,alpha,report,_,_=run(values,fit_failure_policy='preserve_review')
    assert not alpha.any() and report['lettering_review'][0]['diagnostic']['code']=='insufficient_rectified_style_pixels'
    a,b,c,d=report['lettering_review'][0]['bbox_pixels'];assert np.array_equal(out[b:d,a:c],values[0][b:d,a:c])


def test_target_covered_latin_font_does_not_require_a_korean_probe(tmp_path,monkeypatch):
    path=tmp_path/'Latin.ttf';font=TTFont(core.font_path('NanumGothic-Bold.ttf','HELLO'))
    sub=subset.Subsetter();sub.populate(text='HELLOMSOURCE ');sub.subset(font);font.save(path);font.close()
    available=core.fonts();available['Latin.ttf']=str(path);monkeypatch.setattr(core,'fonts',lambda:available)
    assert ord('가') not in core._font_coverage(str(path),path.stat().st_mtime_ns,path.stat().st_size)
    _,_,alpha,report,_,_=run(fixture('HELLO'),default_font='Latin.ttf',fit_failure_policy='preserve_review')
    assert alpha.any() and report['regions'][0]['render']['font']=='Latin.ttf'


def test_bubble_expansion_also_uses_regional_index_when_containment_switch_is_off():
    masks=many_bubbles();_,_,alpha,report,_,_=run(fixture('번역',width=400,height=240,box=[95,70,210,110]),
        detection_result=detector(*masks),mode='bubble',respect_bubbles=False)
    assert alpha.any() and not alpha[~masks[-1]].any() and report['regions']


@pytest.mark.parametrize('policy',['stop','preserve_review'])
def test_valid_but_eroded_empty_glyph_is_fit_failure_not_a_configuration_error(policy):
    values=list(fixture('I'));data=json.loads(values[3]);data['regions'][0]['style']={'weight_px':-8}
    values[3]=json.dumps(data)
    if policy=='stop':
        with pytest.raises(hybrid.LetteringFitError):run(values,fit_failure_policy=policy,region_options_json='{"r1":{"font_cap":10}}')
    else:
        _,out,alpha,report,_,_=run(values,fit_failure_policy=policy,region_options_json='{"r1":{"font_cap":10}}')
        assert not alpha.any() and report['lettering_review'][0]['reason']=='unfit_lettering_preserved'
