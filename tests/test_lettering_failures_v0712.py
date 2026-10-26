"""Real raster regressions for page bubble budgets, missing glyphs and model markers."""
from copy import deepcopy
import json

import numpy as np
import pytest

from tests.test_bubble_containment import T,detector
from tests.test_fit_preservation import three_regions
from tests.test_translation_response import N,VALID,reply,run as translation_run

B=T.hybrid.bubble_constraints


def many_bubbles():
    masks=[]
    for i in range(70):
        mask=np.zeros((240,400),bool)
        x=(i%35)*11;y=(i//35)*8
        mask[y:y+4,x:x+4]=True;masks.append(mask)
    actual=np.zeros((240,400),bool);actual[60:190,70:330]=True
    masks.append(actual)
    return masks


@pytest.mark.parametrize('mode',['source','bubble'])
def test_over_64_page_bubbles_do_not_stop_one_independent_text_owner(mode):
    masks=many_bubbles();result=detector(*masks)
    values=T.fixture('번역',width=400,height=240,box=[95,70,210,110])
    # Reproduce the old global count failure on the very same observations.
    with pytest.raises(ValueError,match='Too many detected bubble masks'):
        B.candidates(None,result,(240,400,3))
    _,out,alpha,report,_,_=T.run(values,detection_result=result,respect_bubbles=True,mode=mode)
    assert report['regions'][0]['render']['text']=='번역'
    assert alpha.any() and not alpha[~masks[-1]].any()
    assert np.array_equal(out[~masks[-1]],values[1][~masks[-1]])


def test_unrelated_masks_are_metadata_validated_but_not_dense_decoded(monkeypatch):
    from hybrid_test_plugin import mask_nodes
    entries=[]
    for i in range(70):
        entries.append({'label':'bubble','mask':{'x':i*5,'y':0,'width':4,'height':4,'runs':[0,16]}})
    entries.append({'label':'bubble','mask':{'x':100,'y':70,'width':200,'height':100,'runs':[0,20000]}})
    calls=[];original=mask_nodes._decode_mask
    def observe(raw,*args):calls.append(raw);return original(raw,*args)
    monkeypatch.setattr(mask_nodes,'_decode_mask',observe)
    index=B.RegionCandidates(None,{'detections':entries},(240,400,3))
    assert len(index.for_region([110,80,150,80]))==1 and len(calls)==1
    entries[0]['mask']['runs']=[15]
    with pytest.raises(ValueError,match='RLE length mismatch'):
        B.RegionCandidates(None,{'detections':entries},(240,400,3))


def test_duplicate_masks_retain_only_the_common_interior_and_no_union():
    a=np.ones((80,100),bool);b=a.copy();a[0,0]=False;b[0,1]=False
    items=B.RegionCandidates(None,detector(a,b,a),(80,100,3)).for_region([10,10,50,40])
    assert len(items)==1 and np.array_equal(items[0]['mask'],a&b)


def crowded_detection(shape=(240,400)):
    # Every distinct candidate covers 50% of the same source ink, yet pairs
    # differ enough that the 95% common-interior dedup rule cannot combine them.
    rng=np.random.default_rng(7312);masks=[]
    for _ in range(65):
        mask=np.zeros(shape,bool);mask[100:120,150:250]=True
        mask[30:70,80:320]=rng.random((40,240))>.5
        masks.append(mask)
    return detector(*masks)


def test_local_overflow_is_review_not_an_unconstrained_title():
    result=crowded_detection();values=T.fixture('번역',width=400,height=240,font_size=18,box=[80,30,240,170])
    _,out,alpha,report,_,_=T.run(values,respect_bubbles=True,detection_result=result,bubble_failure_policy='preserve_review')
    assert not alpha.any() and report['needs_review']
    assert report['lettering_review'][0]['diagnostic']['code']=='bubble_candidate_limit'
    a,b,c,d=report['lettering_review'][0]['bbox_pixels']
    assert np.array_equal(out[b:d,a:c],values[0][b:d,a:c])
    for options in ({'bubble_failure_policy':'stop'}, {'bubble_failure_policy':'preserve_review','region_options_json':'{"r1":{"require_bubble":true}}'}):
        with pytest.raises(ValueError,match='Too many detected bubble masks'):
            T.run(values,respect_bubbles=True,detection_result=result,**options)


def test_detector_and_pixel_budgets_still_raise_in_review_mode(monkeypatch):
    valid={'label':'bubble','mask':{'x':0,'y':0,'width':4,'height':4,'runs':[0,16]}}
    with pytest.raises(ValueError,match='512-candidate'):
        B.RegionCandidates(None,{'detections':[valid]*513},(10,10,3))
    index=B.RegionCandidates(None,{'detections':[valid]},(10,10,3))
    monkeypatch.setattr(T.core,'MAX_SOURCE_PIXELS',15)
    with pytest.raises(ValueError,match='64 Mi-pixel'):index.for_region([0,0,4,4])


def test_missing_arabic_glyph_preserves_parent_and_neighbours_but_renders_independent_region():
    original,clean,support,raw=three_regions();doc=json.loads(raw)
    doc['regions'][0]['text']='한글 ل'
    doc['regions'][0]['parent_id']='caption';doc['regions'][0]['source_edit_bbox']=[15,15,270,165]
    plan,_,build=T.hybrid.build_plan(original,clean,support,json.dumps(doc),fit_failure_policy='preserve_review')
    out,alpha,report=T.hybrid.render_plan(plan);report=json.loads(report)
    assert [r['id'] for r in report['regions']]==['independent']
    failed=next(r for r in report['lettering_review'] if r['id']=='bad')
    assert failed['reason']=='unsupported_translation_glyphs'
    assert failed['diagnostic']['missing_characters']==['ل']
    assert failed['diagnostic']['missing_codepoints']==['U+0644']
    assert np.array_equal(out[15:180,15:285],original[15:180,15:285])
    assert not alpha[15:180,15:285].any()
    assert json.loads(build)['needs_review']
    assert doc['regions'][0]['text']=='한글 ل'  # No dropped glyph or substitute text.


@pytest.mark.parametrize('options',[{'fit_failure_policy':'stop'}, {'fit_failure_policy':'preserve_review','mode':'strict'}])
def test_missing_glyph_strict_paths_still_fail_with_region_id(options):
    with pytest.raises(ValueError,match='r1: Font lacks requested characters: ل'):
        T.run(T.fixture('한글 ل'),**options)


def test_invalid_font_name_is_not_hidden_as_a_quality_failure():
    with pytest.raises(ValueError,match='Font not found'):
        T.run(T.fixture('한글'),fit_failure_policy='preserve_review',default_font='missing-font.ttf')


@pytest.mark.parametrize('marker',['^n','{n}',r'\n',r'\r\n'])
def test_model_line_break_placeholders_retry_without_publishing_them(monkeypatch,marker):
    bad=deepcopy(VALID);bad['translations'][0]['target']='그건...'+marker+'그렇긴 하지'
    good=deepcopy(VALID);good['translations'][0]['target']='그건...\n그렇긴 하지'
    calls,invoke=translation_run(monkeypatch,[reply(N.encode(bad)),reply(N.encode(good))])
    out=json.loads(invoke());row=next(r for r in out['regions'] if r['id']=='b')
    assert row['target']=='그건...\n그렇긴 하지' and len(calls)==2
    assert '^n' in calls[1]['messages'][-1]['content']


def test_repeated_marker_response_is_rejected_atomically(monkeypatch,tmp_path):
    monkeypatch.setattr(N.translation_protocol,'failure_root',lambda:tmp_path)
    bad=deepcopy(VALID);bad['translations'][0]['target']='그건...^n그렇긴 하지'
    calls,invoke=translation_run(monkeypatch,[reply(N.encode(bad)),reply(N.encode(bad))])
    with pytest.raises(ValueError,match='translation_line_break_marker'):invoke()
    assert len(calls)==2
    assert json.loads(next(tmp_path.glob('translation_*.json')).read_text())['code']=='invalid_translation'


@pytest.mark.parametrize('source,target',[('xⁿ を計算','x^n을 계산'),
    ('Use ^n literally','^n 그대로'),(r'Use \n literally',r'\n 그대로'),
    ('folder path',r'C:\new\notes'),('原文','첫째\n둘째')])
def test_real_newlines_math_paths_and_source_literals_are_preserved(source,target):
    assert N.text_contract.translation_text(source,target)==(target,0)


def test_manual_marker_text_remains_authored_and_no_api_is_called(monkeypatch):
    monkeypatch.setattr(N,'api_json',lambda *a,**k:pytest.fail('Manual override called API'))
    source={'regions':[{'id':'a','bbox':[0,0,100,100],'source':'原文'}]}
    override={'translations':[{'id':'a','target':'문자 ^n 그대로'}]}
    out=N.MangaTranslate().translate(N.encode(source),'','','','',4096,300,N.encode(override))[0]
    assert json.loads(out)['regions'][0]['target']=='문자 ^n 그대로'
