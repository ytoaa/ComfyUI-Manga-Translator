"""Synthetic font geometry and halo blending, independent of model accuracy."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
import pytest
import torch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('geometry_tests',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from geometry_tests import text_geometry as G, nodes as N, models as M, inpaint_tiles as T
from geometry_tests.lettering import hybrid
from geometry_tests.lettering.nodes import tensor, MangaLetterPrepare


def fixture(angle=13.5):
    canvas=Image.new('RGB',(480,160),(220,205,215))
    glyph=Image.new('L',canvas.size,0)
    font=ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Bold.ttf'),23)
    for y,text in [(12,'MY PROFILE'),(55,'NAME CLASS LABEL'),(98,'ANOTHER SAMPLE LINE')]:
        ImageDraw.Draw(canvas).text((22,y),text,font=font,fill=(70,25,65))
        ImageDraw.Draw(glyph).text((22,y),text,font=font,fill=255)
    original=canvas.rotate(angle,Image.Resampling.BICUBIC,expand=True,fillcolor=(220,205,215))
    ink=np.asarray(glyph.rotate(angle,Image.Resampling.NEAREST,expand=True))>0
    support=ndimage.binary_dilation(ink,iterations=3)
    clean=np.full((*ink.shape,3),np.array([220,205,215])/255,np.float32)
    return original,ink,support,clean


@pytest.mark.parametrize('angle',[-17.,-8.,13.5,21.])
def test_mask_supported_geometry_recovers_rotation_and_row_partition(angle):
    source,_,support,_=fixture(angle)
    plan,evidence=G.plan(source,support,'r1')
    assert evidence['accepted']
    assert abs(plan['source_angle']-angle)<=1
    inputs=G.planned_inputs(source,plan)
    assert len(inputs)==3
    assert sum(im.height for im in inputs)==plan['rectified_size'][1]
    assert plan['rows'][0][1]==0 and plan['rows'][-1][3]==plan['rectified_size'][1]


@pytest.mark.parametrize('kind',['horizontal','blank','vertical','missing_support'])
def test_ambiguous_or_unneeded_deskew_keeps_the_existing_path(kind):
    source,_,support,_=fixture(0)
    if kind=='blank':source=Image.new('RGB',source.size,'white')
    if kind=='vertical':source=source.transpose(Image.Transpose.ROTATE_90);support=support.T
    if kind=='missing_support':support=np.zeros(support.shape,bool)
    plan,evidence=G.plan(source,support,'r1')
    assert not plan and not evidence['accepted']


@pytest.mark.parametrize('change',['size','angle','row_gap','frame'])
def test_changed_geometry_is_rejected_before_recognition(change):
    source,_,support,_=fixture()
    plan,_=G.plan(source,support,'r1')
    plan=deepcopy(plan)
    if change=='size':plan['source_size'][0]+=1
    if change=='angle':plan['correction_degrees']=float('nan')
    if change=='row_gap':plan['rows'][1][1]+=1
    if change=='frame':plan['coordinate_frame']='page_pixels'
    with pytest.raises(ValueError):G.planned_inputs(source,plan)


def test_crop_to_ocr_to_lettering_shares_the_rectified_frame():
    original,ink,support,clean=fixture()
    h,w=support.shape
    page=tensor(np.asarray(original,np.float32)/255)
    manifest=json.dumps({'image_width':w,'image_height':h,'regions':[{'id':'r1','bbox':[0,0,1000,1000]}]})
    crops,manifest,_,plans=N.MangaRegionCrops().crop(page,manifest,0,0,auto_deskew=True,
                                                   text_pixel_mask=torch.from_numpy(support[None].astype(np.float32)))
    plan=json.loads(plans[0]);assert plan['strategy']==G.STRATEGY
    expected=G.planned_inputs(original,plan)
    texts=['MY PROFILE','NAME CLASS LABEL','ANOTHER SAMPLE LINE']
    class OCR:
        count=0
        def ocr(self,image,*args,**kwargs):
            assert image.size==expected[self.count].size
            result={'text':texts[self.count]};self.count+=1;return result
    model=OCR()
    text,report,_=M.MangaOCRAdaptive().read(crops[0],model,region_plan_json=plans[0],
                                         quality_guard=True,retry_on_layout_failure=True,split_long_lines=True)
    assert text=='\n'.join(texts) and model.count==3
    report=json.loads(report)
    assert report['chunks'][0]['region_coordinate_frame']=='rectified_crop_pixels'
    collected=json.loads(N.MangaCollectOCR().collect([text],[manifest],[json.dumps(report)])[0])
    collected['regions'][0]['target']='프로필\n이름과 직업\n설명 문장'
    prepared,style_mask=MangaLetterPrepare().prepare(page,json.dumps(collected),0,
                         text_pixel_mask=torch.from_numpy(ink[None].astype(np.float32)))
    assert 'r1' in json.loads(prepared)['source_orientation']
    result,_,summary=hybrid.build_plan(np.asarray(original,np.float32)/255,clean,style_mask[0].numpy(),prepared,
                                     page_direction='horizontal',line_breaks='reflow',fit_policy='readable')
    row=result['regions'][0]
    assert row['options']['rotation']==pytest.approx(plan['source_angle'])
    assert 15<=row['cap']<=35
    _,alpha,render=hybrid.render_plan(result)
    assert alpha.any() and json.loads(render)['regions'][0]['render']['font_size']<=row['cap']


def test_halo_feather_reduces_boundary_jump_without_restoring_source_ink():
    original=np.full((120,320,3),.5,np.float32)
    raw=np.zeros((120,320),bool);raw[50:65,40:280]=1
    original[raw]=0
    cleanup=ndimage.binary_dilation(raw,iterations=10)
    plan=T.make_plan(original,raw,cleanup,uniform_fill=False)
    generated=[]
    for tile in plan['tiles']:
        a,b,c,d=tile['crop'];candidate=original[b:d,a:c].copy();candidate[tile['mask']]=.85
        generated.append(candidate)
    hard,_=T.assemble(plan,generated,blend_width=0)
    soft,report=T.assemble(plan,generated,blend_width=8)
    assert np.array_equal(soft[~cleanup],original[~cleanup])
    assert np.array_equal(soft[raw],hard[raw])
    border=cleanup & ~ndimage.binary_erosion(cleanup)
    assert np.abs(soft[border]-.5).mean()<np.abs(hard[border]-.5).mean()/4
    assert json.loads(report)['edge_blend']['source_pixels_unattenuated']


def test_internal_tile_ownership_boundary_does_not_become_a_fade():
    original=np.full((100,1100,3),.5,np.float32)
    raw=np.zeros((100,1100),bool);raw[45:50,20:1080]=1
    original[raw]=0
    cleanup=ndimage.binary_dilation(raw,iterations=12)
    plan=T.make_plan(original,raw,cleanup,uniform_fill=False)
    generated=[np.full((*tile['mask'].shape,3),.8,np.float32) for tile in plan['tiles']]
    soft,_=T.assemble(plan,generated,blend_width=8)
    # This halo row is more than 8px from the real mask perimeter. Every
    # ownership core must retain the same candidate color across split columns.
    assert np.allclose(soft[40,40:1060],.8)


def test_uniform_fill_keeps_lazy_model_bypass_with_halo_blending():
    original=np.full((90,200,3),.6,np.float32)
    raw=np.zeros((90,200),bool);raw[35:55,60:140]=1;original[raw]=0
    cleanup=ndimage.binary_dilation(raw,iterations=8)
    plan=T.make_plan(original,raw,cleanup)
    assert not plan['tiles']
    node=T.MangaInpaintAssemble()
    assert node.check_lazy_status([plan],[True],(None,),[8])==[]
    output,report=node.finish([plan],[True],(None,),[8])
    assert np.allclose(output[0].numpy(),.6)
    assert json.loads(report)['edge_blend']['blended_halo_pixels']>0


def test_extreme_aspect_rotation_is_rejected_before_allocating_a_raster():
    class Source:
        size=(20000,180)
        def convert(self,*args):pytest.fail('Oversized rotated raster was allocated')
    assert G.rotation_pixels(Source.size,14)>8*1024*1024
    with pytest.raises(ValueError,match='8 Mi pixels'):G.rotate_rgb(Source(),14)
