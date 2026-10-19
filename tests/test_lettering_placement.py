"""Distinct paragraphs must share permitted space without stealing source frames."""
from copy import deepcopy
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest
from tests.test_hybrid_lettering import core, hybrid, run


def joined_paragraphs(reverse=False, target='가나다라마바사아자차카타파하'):
    clean=np.ones((360,480,3),np.float32)
    image=Image.fromarray((clean*255).astype('uint8'));draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(core.font_path('NanumGothic-Bold.ttf','가'),30)
    draw.text((330,110),'가',font=font,fill='black')
    draw.text((200,210),'가',font=font,fill='black')
    original=np.asarray(image,np.float32)/255
    support=(original.min(2)<.5).astype(np.float32)
    regions=[{'id':'r2','bbox':[120,90,280,180],'source_text':'가','text':target},
             {'id':'r3','bbox':[180,125,120,110],'source_text':'가','text':'번역'}]
    if reverse:regions.reverse()
    document=json.dumps({'schema':1,'coordinate_format':'xywh','page_size':[480,360],'regions':regions})
    return original,clean,support,document


def options():
    return {'fit_policy':'readable','line_breaks':'reflow',
            'region_options_json':'{"r2":{"font_cap":40},"r3":{"font_cap":40}}'}


@pytest.mark.parametrize('reverse',[False,True])
def test_overlapping_frames_keep_both_complete_translations_without_tiny_collision(reverse):
    values=joined_paragraphs(reverse)
    plan,result,alpha,report,_,_=run(values,**options())
    assert {r['id'] for r in report['regions']}=={'r2','r3'}
    assert all(r['render']['font_size']>=22 for r in report['regions'])
    expected={r['id']:r['text'] for r in json.loads(values[3])['regions']}
    assert {r['id']:r['render']['text'] for r in report['regions']}==expected
    assert any(r['placement']['repositioned'] for r in report['regions'])
    assert np.array_equal(result[alpha==0],values[1][alpha==0])
    individual=[]
    for region in plan['regions']:
        # Keep all source reservations while measuring each actual output alpha.
        # Re-render the selected final bounds with the reported exact font size.
        row=next(r for r in report['regions'] if r['id']==region['id'])
        x,y,w,h=row['bbox'];size=row['render']['font_size']
        style=hybrid.scaled_style(region['style'],size/region['cap'],(w,h))
        _,local,_=core.render_text(region['text'],style,font_name=region['font'],
            min_font=size,max_font=size,max_lines=0,**region['options'])
        page=np.zeros(alpha.shape,bool);page[y:y+h,x:x+w]=local>0
        individual.append(page)
    assert not (individual[0]&individual[1]).any()


def test_joined_bubble_keeps_every_positive_alpha_inside_its_real_mask():
    values=joined_paragraphs();bubble=np.zeros((360,480),np.float32)
    bubble[50:300,95:430]=1
    _,result,alpha,report,_,_=run(values,**options(),respect_bubbles=True,bubble_mask=bubble)
    assert not alpha[bubble==0].any()
    assert all(r['bubble_containment']['status']=='verified' for r in report['regions'])
    assert np.array_equal(result[bubble==0],values[1][bubble==0])


def test_new_placement_still_honours_protected_original_pixels():
    values=joined_paragraphs();plan,_,_=hybrid.build_plan(*values,**options())
    plan['protected_boxes_pixels']=[[250,90,254,270]]
    result,alpha,raw=hybrid.render_plan(plan)
    assert not alpha[90:270,250:254].any()
    assert np.array_equal(result[90:270,250:254],values[1][90:270,250:254])
    assert len(json.loads(raw)['regions'])==2


def test_identical_source_anchors_are_not_spread_into_invented_locations():
    values=joined_paragraphs();plan,_,_=hybrid.build_plan(*values,**options())
    other=deepcopy(plan['regions'][0]);other['id']='duplicate'
    plan['regions']=[plan['regions'][0],other]
    with pytest.raises(hybrid.LetteringFitError,match='collision') as caught:
        hybrid.render_plan(plan)
    assert caught.value.diagnostic['coincident_source_anchors']
    assert caught.value.diagnostic['collision_region_ids']==['r2']


def test_readability_floor_and_strict_layout_are_not_relaxed_by_repositioning():
    with pytest.raises(ValueError,match='no safe lettering fit'):
        run(joined_paragraphs(target='너무 긴 번역문 '*80),**options())
    values=joined_paragraphs();plan,_,_=hybrid.build_plan(*values,**options(),mode='strict')
    with pytest.raises(ValueError,match='no safe lettering fit'):
        hybrid.render_plan(plan)


def test_coarse_free_rectangles_never_certify_a_one_pixel_obstacle():
    from tests.test_hybrid_lettering import hybrid as H
    allowed=np.ones((513,517),bool);allowed[:,258]=False;allowed[257,:]=False
    rectangles=H.placement.free_rectangles(allowed,[100,200,517,513],[200,250,250,300])
    assert 0<len(rectangles)<=5
    for x,y,w,h in rectangles:
        assert allowed[y-200:y-200+h,x-100:x-100+w].all()


def test_source_reservations_are_complementary_on_an_overlap():
    plan,_,_=hybrid.build_plan(*joined_paragraphs(),**options())
    a,b=plan['regions'];bounds=[120,90,280,180]
    own_a,_=hybrid.placement.reserve_sources(a,plan['regions'],bounds)
    own_b,_=hybrid.placement.reserve_sources(b,plan['regions'],bounds)
    # Only compare the physical intersection of the two source frames.
    assert not (own_a[35:145,60:180]&own_b[35:145,60:180]).any()


def test_reported_high_resolution_frame_uses_page_coordinates_without_scaling():
    a={'id':'r2','source':[3600,300,500,800]}
    b={'id':'r3','source':[3461,608,457,705]}
    owned,neighbours=hybrid.placement.reserve_sources(b,[a,b],b['source'])
    assert neighbours==['r2'] and owned.shape==(705,457)
    rectangles=hybrid.placement.free_rectangles(owned,b['source'],b['source'])
    assert rectangles
    for x,y,w,h in rectangles:
        assert 3461<=x<x+w<=3918 and 608<=y<y+h<=1313
        assert owned[y-608:y-608+h,x-3461:x-3461+w].all()


def test_rotated_neighbour_reserves_its_quad_instead_of_empty_box_corners():
    a={'id':'r1','source':[0,0,200,200]}
    b={'id':'r2','source':[80,80,120,120],
       'frame_quad':[[140,80],[200,140],[140,200],[80,140]]}
    owned,_=hybrid.placement.reserve_sources(a,[a,b],a['source'])
    assert owned[85,190]  # Outside the actual rotated neighbour, inside its AABB.
    assert not owned[140,160]


@pytest.mark.parametrize('storage_fails',[False,True])
def test_failed_node_retains_original_fit_error_and_bounded_neighbour_diagnostics(tmp_path,monkeypatch,storage_fails):
    import sys,types
    import importlib
    nodes=importlib.import_module(hybrid.__package__+'.hybrid_nodes')
    values=joined_paragraphs();plan,_,_=hybrid.build_plan(*values,**options())
    other=deepcopy(plan['regions'][0]);other['id']='duplicate'
    plan['regions']=[plan['regions'][0],other]
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(
        models_dir=str(tmp_path/'models'),get_output_directory=lambda:str(tmp_path)))
    if storage_fails:
        from pathlib import Path
        monkeypatch.setattr(Path,'write_text',lambda *a,**kw:(_ for _ in ()).throw(OSError('injected disk failure')))
    with pytest.raises(hybrid.LetteringFitError,match='collision') as caught:
        nodes.MangaLetterApply().render(plan)
    assert caught.value.diagnostic['collision_region_ids']==['r2']
    if storage_fails:
        assert 'diagnostics=unavailable' in str(caught.value)
    else:
        path=next(tmp_path.glob('manga_translator/lettering_failures/*.json'))
        saved=json.loads(path.read_text())
        assert saved['failure']['collision_region_ids']==['r2']
        assert {r['id'] for r in saved['regions']}=={'r2','duplicate'}
        assert str(path) in str(caught.value) and path.stat().st_size<2*1024*1024
