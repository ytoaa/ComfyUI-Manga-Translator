"""Source identity, unrelated ink and local preservation contracts; no private fixtures."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('source_ownership_tests',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from source_ownership_tests import region_policy as R, source_ownership as S, page_edit as P
from source_ownership_tests.adapters.model import rle


def mask(pixels,x=10,y=10):
    return {'x':x,'y':y,'width':pixels.shape[1],'height':pixels.shape[0],'runs':rle(pixels)}


def item(label='text',bounds=None,pixels=None):
    row={'label':label,'bbox':bounds or [10,10,74,74],'score':.9}
    if pixels is not None:row['mask']=mask(pixels)
    return row


def test_almost_contained_ink_in_the_same_frame_has_one_owner_with_all_detector_ids():
    a=np.zeros((64,64),bool);a[10:50,10:40]=True;b=a.copy();b[10:50,40:45]=True
    assert S.mask_overlap(mask(a),mask(b))['iou']<.9
    raw={'protocol':1,'image_width':100,'image_height':100,'detections':[item(pixels=a),item('onomatopoeia',pixels=b)]}
    rows=json.loads(R.MangaDetectionRegionsResolved().convert(raw,include_sfx=True)[0])['regions']
    assert len(rows)==1
    assert rows[0]['source_ownership']['detector_ids']==['d1','d2']
    assert rows[0]['source_ownership']['labels']==['onomatopoeia','text']
    assert rows[0]['source_ownership']['cross_label_alias']


@pytest.mark.parametrize('case',['disjoint','small_caption_on_large_effect','shifted_frame','missing_mask','empty_mask'])
def test_distinct_caption_and_effect_layers_are_not_merged(case):
    a=np.zeros((64,64),bool);a[10:50,10:40]=True;b=a.copy();left=item(pixels=a);right=item('onomatopoeia',pixels=b)
    if case=='disjoint':b[:]=False;b[10:50,42:60]=True;right['mask']=mask(b)
    elif case=='small_caption_on_large_effect':b[:]=True;right['mask']=mask(b)
    elif case=='shifted_frame':right['bbox']=[11,10,75,74]
    elif case=='missing_mask':right.pop('mask')
    else:right['mask']=mask(np.zeros_like(a))
    assert len(R.merge_detector_regions([left,right],.75))==2


def test_repeated_word_in_different_places_keeps_distinct_owners():
    a=np.ones((64,64),bool);left=item(pixels=a);right=item('onomatopoeia',[110,10,174,74]);right['mask']=mask(a,110,10)
    left['source']=right['source']='はい'
    assert len(R.merge_detector_regions([left,right],.75))==2


def test_nearby_shared_ink_is_reviewed_without_automatically_merging_separate_frames():
    pixels=np.ones((64,64),bool)
    a=item(pixels=pixels);b=item('onomatopoeia',[11,10,75,74]);b['mask']=mask(pixels,11,10)
    raw={'protocol':1,'image_width':100,'image_height':100,'detections':[a,b]}
    doc=json.loads(R.MangaDetectionRegionsResolved().convert(raw,include_sfx=True)[0])
    assert len(doc['regions'])==2 and doc['needs_review']
    for row in doc['regions']:row.update(source='同じ',target='시험')
    edits=P.build(doc,100,100)['page_edit_plan']['regions']
    assert all(r['action']=='preserve'and r['reason']=='ambiguous_cross_label_source'for r in edits)


def test_rows_in_different_panels_do_not_merge_but_nested_page_panel_is_allowed():
    rows=[item(bounds=[20,20,220,40]),item(bounds=[20,45,220,65])]
    panels=[item('panel',[0,0,240,43]),item('panel',[0,43,240,100])]
    assert len(R.group_adjacent_lines(rows,[],panels))==2
    assert len(R.group_adjacent_lines(rows,[],[item('panel',[0,0,250,120]),item('panel',[10,10,230,90])]))==1


def test_ambiguous_overlapping_panels_do_not_authorize_paragraph_join():
    rows=[item(bounds=[20,20,220,40]),item(bounds=[20,45,220,65])]
    panels=[item('panel',[0,0,230,100]),item('panel',[10,0,250,100])]
    assert len(R.group_adjacent_lines(rows,[],panels))==2


def review_document(source='A',bubble=False):
    return {'image_width':400,'image_height':200,'regions':[
        {'id':'effect','kind':'sfx','source':source,'target':'번역','bbox':[50,50,200,300],
         'source_ownership':{'schema':1,'bubble_verified':bubble}},
        {'id':'body','source':'本文','target':'본문','bbox':[600,600,900,800]}]}


def test_isolated_short_source_is_reviewed_without_erasing_independent_body():
    data=P.build(review_document(),400,200)
    assert [r['action']for r in data['page_edit_plan']['regions']]==['preserve','replace']
    assert data['page_edit_plan']['regions'][0]['reason']=='ambiguous_isolated_source'
    source=np.ones((200,400),np.float32);_,cleanup=P.masks(data,source,source)
    assert not cleanup[:80,:110].any() and cleanup[130:150,260:350].all()


@pytest.mark.parametrize('condition',['verified_bubble','explicit_replace','legacy','manual_document'])
def test_real_one_character_source_has_explicit_supported_paths(condition):
    data=review_document('あ',condition=='verified_bubble');kw={}
    if condition=='explicit_replace':kw['actions']={'effect':'replace'}
    elif condition=='legacy':kw['source_review_policy']='legacy'
    elif condition=='manual_document':data['regions'][0].pop('source_ownership')
    assert P.build(data,400,200,**kw)['page_edit_plan']['regions'][0]['action']=='replace'


def test_large_unverified_display_source_is_reviewed_without_claiming_it_is_not_text():
    doc=review_document('大きな題名');doc['regions'][0]['bbox']=[10,10,150,900]
    d=P.build(doc,400,200)
    assert d['page_edit_plan']['regions'][0]['reason']=='unverified_display_text'
    assert d['needs_review']


def test_verified_multiline_horizontal_body_is_not_reviewed_as_a_large_title():
    doc=review_document('本文の説明です');doc['regions'][0]['bbox']=[10,10,990,300]
    doc['regions'][0]['line_bboxes_pixels']=[[4,2,396,20],[4,25,396,43]]
    assert P.build(doc,400,200)['page_edit_plan']['regions'][0]['action']=='replace'
    doc['regions'][0].pop('line_bboxes_pixels')
    doc['regions'][0]['ocr_diagnostics']={'line_count':2}
    assert P.build(doc,400,200)['page_edit_plan']['regions'][0]['action']=='replace'


def test_review_policy_and_ownership_cannot_change_after_planning():
    doc=P.build(review_document(),400,200)
    for field in ('policy','ownership'):
        changed=copy.deepcopy(doc)
        if field=='policy':changed['source_review_policy']='legacy'
        else:changed['regions'][0]['source_ownership']['bubble_verified']=True
        with pytest.raises(ValueError,match='stale'):P.validate(changed,400,200)


def test_local_protection_closes_touching_sources_but_preserves_independent_candidates():
    raw={'protocol':1,'image_width':500,'image_height':200,
         'boundary_review':{'schema':1,'protected_boxes_pixels':[[0,0,30,30]]},
         'detections':[item(bounds=[20,20,60,60]),item(bounds=[55,40,100,70]),item(bounds=[300,100,400,140])]}
    output=json.loads(R.MangaDetectionRegionsResolved().convert(raw)[0])
    assert len(output['regions'])==1 and len(output['region_preservation'])==2
    assert output['needs_review']
    with pytest.raises(ValueError,match='overlaps preserved'):R.MangaDetectionRegionsResolved().convert(raw,protected_overlap_policy='stop')


def test_repeated_detected_bubbles_keep_only_the_common_verified_interior():
    from source_ownership_tests.lettering import bubble_constraints as B
    pixels=np.ones((60,60),bool);detections=[];expected=pixels.copy()
    for i in range(70):
        variant=pixels.copy();variant[0,i%60]=False;expected&=variant
        detections.append(item('bubble',[10,10,70,70],variant))
    found=B.candidates(None,{'detections':detections},(100,100,3))
    assert len(found)==1 and np.array_equal(found[0]['mask'],expected)
    assert found[0]['source']=='detector_intersection'


def test_many_distinct_bubbles_still_respect_the_original_budget():
    from source_ownership_tests.lettering import bubble_constraints as B
    detections=[]
    for i in range(65):
        pixels=np.ones((4,4),bool);detections.append({'label':'bubble','bbox':[i*5,0,i*5+4,4],
            'mask':mask(pixels,i*5,0)})
    with pytest.raises(ValueError,match='Too many detected bubble masks'):
        B.candidates(None,{'detections':detections},(10,400,3))
