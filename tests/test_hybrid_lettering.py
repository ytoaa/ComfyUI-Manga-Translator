"""Hybrid fitting invariants with actual bundled font pixels, no model mocks."""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hybrid_test_plugin',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from hybrid_test_plugin.lettering import core, hybrid, vertical


def fixture(target='한국어 번역',width=320,height=120,source='SOURCE',font_size=32,box=None,stroke=0):
    clean=np.full((height,width,3),.65,np.float32)
    picture=Image.fromarray((clean*255).round().astype('uint8'))
    font=ImageFont.truetype(core.font_path('NanumGothic-Bold.ttf',source),font_size)
    draw=ImageDraw.Draw(picture)
    draw.text((width//2,height//2),source,font=font,fill='black',anchor='mm',stroke_width=stroke,stroke_fill='white')
    original=np.asarray(picture,np.float32)/255
    mask=(np.max(np.abs(original-clean),axis=2)>.03).astype(np.float32)
    item={'id':'r1','bbox':box or [10,10,width-20,height-20],'text':target,'source_text':source}
    doc=json.dumps({'schema':1,'coordinate_format':'xywh','page_size':[width,height],'regions':[item]})
    return original,clean,mask,doc


def run(values,**kw):
    plan,preview,report=hybrid.build_plan(*values,**kw)
    result,alpha,render=hybrid.render_plan(plan)
    return plan,result,alpha,json.loads(render),preview,json.loads(report)


def test_short_target_never_grows_above_measured_source_and_background_is_exact():
    values=fixture('가')
    plan,result,alpha,report,_,_=run(values)
    row=report['regions'][0]
    assert row['render']['font_size']<=plan['regions'][0]['cap']
    assert row['scale']<=1
    assert np.array_equal(result[alpha==0],values[1][alpha==0])
    assert alpha.max()>.99


def test_longer_translation_shrinks_before_adding_rows():
    values=fixture('원본보다 아주 긴 한국어 문장입니다',width=400,font_size=42)
    plan,_,_,report,_,_=run(values,min_font=8,min_scale=.3)
    row=report['regions'][0]
    assert row['render']['font_size']<plan['regions'][0]['cap']
    assert row['render']['line_count']==1
    assert row['fit_phase']=='source-lines'


def test_outline_shadow_and_weight_scale_with_font_size():
    values=fixture('원본보다 아주 긴 한국어 문장입니다',width=400,font_size=42,stroke=3)
    plan,_,_,report,_,_=run(values,min_font=8,min_scale=.3)
    row=report['regions'][0]
    assert row['outline_width']==pytest.approx(plan['regions'][0]['style']['outline_width']*row['render']['font_size']/plan['regions'][0]['cap'])
    style=hybrid.scaled_style(plan['regions'][0]['style'],.5,(200,100))
    assert style['outline_width']==plan['regions'][0]['style']['outline_width']/2


def test_reflow_after_source_line_count_fails_at_readability_floor():
    values=fixture('이 문장은 여러 줄로 재배치해야 읽을 수 있는 번역문입니다',width=210,height=180,font_size=32)
    _,_,_,report,_,_=run(values,min_scale=.65)
    assert report['regions'][0]['fit_phase']=='reflow'
    assert report['regions'][0]['render']['line_count']>1


def test_strict_does_not_silently_cut_or_reflow():
    values=fixture('아주 긴 번역문을 반복합니다 '*12,width=210,font_size=32)
    with pytest.raises(ValueError,match='no safe lettering fit'):
        run(values,mode='strict',min_scale=.8)


def test_bubble_expands_only_inside_supplied_component():
    values=fixture('원본보다 긴 번역문을 말풍선 안에 다시 배치합니다',width=400,height=240,font_size=26,box=[140,85,120,70],source='TEST')
    yy,xx=np.mgrid[:240,:400]
    inside=(((xx-200)/170)**2+((yy-120)/100)**2<1).astype(np.float32)
    _,_,alpha,report,_,_=run(values,mode='bubble',min_scale=.8,bubble_mask=inside)
    assert report['regions'][0]['fit_phase']=='bubble'
    assert not np.any((alpha>.01)&(inside==0))


def test_missing_or_unrelated_bubble_mask_retains_source_frame():
    values=fixture('번역')
    plan,_,report=hybrid.build_plan(*values,mode='bubble',bubble_mask=np.zeros((120,320),np.float32))
    assert len(plan['regions'][0]['phases'])==2
    assert 'source frame retained' in json.loads(report)['regions'][0]['warning']


def test_neighbouring_letters_cannot_overlap():
    original,clean,mask,document=fixture('동일한 위치의 번역문')
    data=json.loads(document);data['regions'].append({**data['regions'][0],'id':'r2'})
    with pytest.raises(ValueError,match='collision'):
        run((original,clean,mask,json.dumps(data)),min_scale=.9)


@pytest.mark.parametrize('direction',['vertical_rtl','vertical_ltr'])
def test_typographic_vertical_preserves_unicode_and_groups_latin_digits(direction):
    values=fixture('가나다 12 TEST!',width=200,height=320,font_size=32)
    _,_,alpha,report,_,_=run(values,direction=direction,min_scale=.3)
    row=report['regions'][0]['render']
    assert row['text']=='가나다 12 TEST!' and row['direction']==direction
    assert row['vertical_policy']=='typographic'
    assert alpha.sum()>30
    assert vertical.tokens('가12TEST')==['가','12TEST']
    font=ImageFont.truetype(core.font_path('NanumGothic-Bold.ttf','TEST'),40)
    assert vertical.advance('12',font,50)==50
    assert vertical.advance('TEST',font,50)>=font.getlength('TEST')


def test_explicit_newlines_are_kept():
    _,_,_,report,_,_=run(fixture('첫 줄\n둘째 줄'),min_scale=.3)
    assert report['regions'][0]['render']['line_count']>=2


def test_rotation_shear_and_manual_curve_keep_alpha_inside_frame():
    options=json.dumps({'r1':{'rotation':12,'shear':.1,'bend':8}})
    _,_,alpha,report,_,_=run(fixture('효과음',width=400,height=180,font_size=48),region_options_json=options,min_scale=.3)
    assert report['regions'][0]['render']['rotation']==12
    assert report['regions'][0]['bend']==8
    assert not alpha[0].any() and not alpha[-1].any()


@pytest.mark.parametrize('override',[{'no_such_id':{}},{'r1':{'direction':'diagonal'}},{'r1':{'unknown':2}},{'r1':{'font_cap':float('nan')}},{'r1':{'bend':999}}])
def test_invalid_region_controls_are_rejected(override):
    with pytest.raises(ValueError):
        hybrid.build_plan(*fixture(),region_options_json=json.dumps(override))


def test_font_coverage_is_checked_before_rendering():
    with pytest.raises(ValueError,match='Font lacks'):
        hybrid.build_plan(*fixture('가😀'))


def test_new_nodes_are_registered_and_shipped_graph_uses_them():
    assert 'MangaLetterPlan' in plugin.NODE_CLASS_MAPPINGS
    assert 'MangaLetterApply' in plugin.NODE_CLASS_MAPPINGS
    path=ROOT/'lettering/example_workflows/08-integrated-tiled-cleanup-lettering.api.json'
    graph=json.loads(path.read_text())
    kinds=[r['class_type'] for r in graph.values()]
    assert kinds.count('MangaLetterPlan')==kinds.count('MangaLetterApply')==1
    assert 'ImageCrop' in kinds and 'ImageCompositeMasked' in kinds
    assert plugin.NODE_CLASS_MAPPINGS['MangaLetterPlan'].INPUT_TYPES()['required']['regions_json'][1]['forceInput']


def test_korean_source_disconnected_strokes_keep_plausible_size():
    original,clean,mask,doc=fixture('번역문',source='선생님',font_size=32)
    plan,_,_=hybrid.build_plan(original,clean,mask,doc)
    assert 24<=plan['regions'][0]['cap']<=42


def test_vertical_source_direction_uses_ink_instead_of_crop_aspect_ratio():
    original,clean,mask,doc=fixture('번역문',width=180,height=300,source='가',font_size=30)
    picture=Image.fromarray((clean*255).round().astype('uint8'));draw=ImageDraw.Draw(picture)
    font=ImageFont.truetype(core.font_path('NanumGothic-Bold.ttf','가나다라'),30)
    for i,char in enumerate('가나다라'):
        draw.text((75,25+50*i),char,font=font,fill='black')
    original=np.asarray(picture,np.float32)/255
    mask=(np.max(np.abs(original-clean),axis=2)>.03).astype(np.float32)
    plan,_,_=hybrid.build_plan(original,clean,mask,doc)
    assert plan['regions'][0]['options']['direction']=='vertical_rtl'


def test_actual_detector_bubble_mask_is_reused_without_manual_mask():
    values=fixture('원본보다 긴 번역문을 말풍선 안에 다시 배치합니다',width=400,height=240,font_size=26,box=[140,85,120,70],source='TEST')
    yy,xx=np.mgrid[:240,:400]
    binary=(((xx-200)/170)**2+((yy-120)/100)**2<1).ravel().astype(np.uint8)
    edges=np.flatnonzero(np.diff(binary))+1
    runs=np.diff(np.r_[0,edges,len(binary)]).tolist()
    if binary[0]: runs.insert(0,0)
    result={'protocol':1,'image_width':400,'image_height':240,'detections':[
        {'label':'bubble','mask':{'x':0,'y':0,'width':400,'height':240,'runs':runs}}]}
    _,_,alpha,report,_,_=run(values,mode='bubble',min_scale=.8,detection_result=result)
    assert report['regions'][0]['fit_phase']=='bubble'
    assert not np.any((alpha>.01)&(~binary.reshape(240,400).astype(bool)))


def test_missing_vertical_punctuation_does_not_drop_requested_characters():
    values=fixture('가(나) 12 TEST!',width=200,height=320,font_size=32)
    _,_,alpha,report,_,_=run(values,direction='vertical_rtl',min_scale=.3)
    assert report['regions'][0]['render']['text']=='가(나) 12 TEST!'
    assert alpha.sum()>50
