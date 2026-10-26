"""Panel/bubble boundaries precede duplicate merging; all mask ink survives."""
from copy import deepcopy
import json
import numpy as np
import pytest
from tests.test_source_ownership import R,S,P,mask
from source_ownership_tests import region_boundaries as B
from source_ownership_tests.mask_nodes import _decode_mask


def item(box,pixels=None,label='text',score=.9):
    row={'label':label,'bbox':box,'score':score}
    if pixels is not None:row['mask']=mask(pixels,box[0],box[1])
    return row


def ink_union(rows,width,height):
    page=np.zeros((height,width),bool)
    for row in rows:
        local,(x,y,w,h)=_decode_mask(row['mask'],width,height)
        page[y:y+h,x:x+w]|=local>.5
    return page


def test_reported_r9_extent_splits_at_a_verified_panel_gap_before_ocr():
    # Exact reported r9 frame, synthetic ink and controlled panel geometry.
    # No private page pixels, OCR strings or inferred actual panel masks.
    pixels=np.zeros((1105,111),bool);pixels[40:350,15:80]=True;pixels[790:1070,10:90]=True
    long=item([252,917,363,2022],pixels)
    panels=[item([100,750,2000,1430],label='panel'),item([100,1510,2000,2200],label='panel')]
    barriers=B.separators(panels);parts,audit=B.partition([long],barriers,2150,3035)
    assert len(parts)==2 and audit[0]['parts']==2
    assert np.array_equal(ink_union(parts,2150,3035),ink_union([long],2150,3035))
    assert not B.compatible(parts[0],parts[1],barriers)
    selected=R.merge_detector_regions(parts,.75,barriers=barriers,width=2150,height=3035)
    assert len(selected)==2
    doc=json.loads(R.MangaDetectionRegionsResolved().convert({'protocol':1,'image_width':2150,
        'image_height':3035,'detections':[long,*panels]})[0])
    assert len(doc['regions'])==2
    for row in doc['regions']:
        row.update(source='Synthetic source',target='시험 번역')
        assert S.review_reason(row,2150,3035) is None
    planned=P.build(doc,2150,3035)
    assert all(r['action']=='replace' for r in planned['page_edit_plan']['regions'])
    assert doc['region_resolution']['input_regions']==1
    assert doc['region_resolution']['boundary_partition']['split_observations']==1


@pytest.mark.parametrize('axis',[0,1])
def test_children_do_not_rejoin_through_partial_duplicate_observations(axis):
    pixels=np.zeros((200,40),bool);pixels[10:70,5:35]=1;pixels[130:190,5:35]=1
    boxes=[[10,0,50,200],[0,0,100,80],[0,120,100,210]]
    if axis==0:
        pixels=pixels.T;boxes=[[q[1],q[0],q[3],q[2]]for q in boxes]
    whole=item(boxes[0],pixels)
    owners=[item(boxes[1],label='panel'),item(boxes[2],label='panel')]
    bounds=B.separators(owners)
    parts,_=B.partition([whole],bounds,250,250)
    duplicate=deepcopy(parts[0]);duplicate['score']=.99
    merged=R.merge_detector_regions([*parts,duplicate],.75,barriers=bounds,width=250,height=250)
    assert len(merged)==2 and np.array_equal(ink_union(merged,250,250),ink_union([whole],250,250))


def test_horizontal_fragment_rule_does_not_join_adjacent_vertical_columns():
    left=item([100,100,180,600]);right=item([170,100,250,600])
    assert len(R.merge_detector_regions([left,right],.75))==2


@pytest.mark.parametrize('case',['ink_in_gap','no_mask','clipped_owner','no_frames','overlapping_frames'])
def test_no_source_partition_without_complete_blank_gap_evidence(case):
    pixels=np.zeros((200,40),bool);pixels[10:70,5:35]=1;pixels[130:190,5:35]=1
    row=item([10,0,50,200],pixels)
    owners=[item([0,0,100,80],label='panel'),item([0,120,100,210],label='panel')]
    if case=='ink_in_gap':pixels[70:131,15]=True;row=item([10,0,50,200],pixels)
    elif case=='no_mask':row.pop('mask')
    elif case=='clipped_owner':owners[0]['tile_provenance']={'clipped_edges':['bottom']}
    elif case=='no_frames':owners=[]
    else:owners[0]['bbox'][3]=150
    parts,audit=B.partition([row],B.separators(owners),250,250)
    assert len(parts)==1 and not audit and parts[0]==row


def test_nested_page_frame_and_duplicate_panels_do_not_create_spurious_cuts():
    owners=[item([0,0,400,600],label='panel'),item([0,0,400,180],label='panel'),
            item([0,210,400,390],label='panel'),item([0,420,400,600],label='panel')]
    owners.append(item([1,211,399,389],label='panel'))
    barriers=B.separators(owners)
    # Non-adjacent top/bottom frames bracket this panel but cannot split its
    # two overlapping observations merely at the middle of that big interval.
    a=item([20,230,300,315]);b=item([20,280,300,370])
    assert B.compatible(a,b,barriers)
    assert not any(q[1]<250<q[2] and q[2]-q[1]<100 for q in barriers)


def test_bubble_gaps_work_without_panel_detections():
    pixels=np.zeros((200,40),bool);pixels[10:70,5:35]=1;pixels[130:190,5:35]=1
    owners=[item([0,0,100,80],label='bubble'),item([0,120,100,210],label='bubble')]
    parts,_=B.partition([item([10,0,50,200],pixels)],B.separators(owners),250,250)
    assert len(parts)==2


def test_duplicate_merge_retains_all_positive_ink_instead_of_only_winner_mask():
    a=np.zeros((40,80),bool);a[10:30,5:40]=True;b=a.copy();b[10:30,40:75]=True
    rows=[item([10,10,90,50],a),item([10,10,90,50],b,score=.8)]
    merged=R.merge_detector_regions(rows,.75,width=120,height=80)
    assert len(merged)==1
    assert np.array_equal(ink_union(merged,120,80),ink_union(rows,120,80))


def test_partition_budgets_and_invalid_rle_still_stop(monkeypatch):
    pixels=np.zeros((200,40),bool);pixels[10:70,5:35]=1;pixels[130:190,5:35]=1
    row=item([10,0,50,200],pixels)
    owners=[item([0,0,100,80],label='panel'),item([0,120,100,210],label='panel')]
    barriers=B.separators(owners);row['mask']['runs']=[1]
    with pytest.raises(ValueError,match='RLE'):B.partition([row],barriers,250,250)
    row=item([10,0,50,200],pixels);monkeypatch.setattr(B,'MAX_REGION_PIXELS',1)
    with pytest.raises(ValueError,match='16 Mi'):B.partition([row],barriers,250,250)
