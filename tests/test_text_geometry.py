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


@pytest.mark.parametrize('bright',[False,True])
def test_whole_glyph_baselines_work_for_both_ink_polarities(bright):
    source,_,support,_=fixture()
    if bright:source=Image.fromarray(255-np.asarray(source))
    plan,evidence=G.plan(source,support,'r1')
    assert len(plan['rows'])==3
    assert evidence['row_validation']['method']=='component_baselines'
    assert not evidence['row_validation']['clipped_source_rows']


def test_fragmented_detector_support_cannot_split_a_whole_glyph_in_half():
    source=Image.new('RGB',(360,180),'white');support=Image.new('L',source.size,0)
    font=ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Bold.ttf'),30)
    for y in (10,65,120):
        ImageDraw.Draw(source).text((20,y),'HHHHHHHH',font=font,fill='black')
        ImageDraw.Draw(support).text((20,y),'HHHHHHHH',font=font,fill=255)
    support=np.asarray(support).copy()>0
    for y in (29,84,139):support[y:y+4]=False
    old_bands=ndimage.label(support.sum(axis=1)>3)[1]
    assert old_bands==6
    rows,evidence=G._verified_rows(source,support,np.ones(support.shape,bool))
    assert len(rows)==3 and not evidence['needs_review']
    ink=np.asarray(source)[:,:,0]<128
    for row in rows[:-1]:assert not ink[row[3]-1:row[3]+1].any()


@pytest.mark.parametrize('cut',[50,60,70])
def test_glyphs_already_cut_by_source_crop_are_not_certified(cut):
    source,_,support,_=fixture()
    h=source.height-cut;source=source.crop((0,0,source.width,h));support=support[:h]
    plan,evidence=G.plan(source,support,'r1')
    assert not plan and evidence['needs_review']
    assert evidence['reason']=='source_crop_cuts_glyphs'
    assert evidence['row_validation']['clipped_source_rows']


def test_unverified_crop_bypasses_ocr_and_preserves_pixels_before_cleanup(monkeypatch):
    from geometry_tests import page_edit
    source,_,support,_=fixture();h=source.height-60
    source=source.crop((0,0,source.width,h));support=support[:h]
    page=tensor(np.asarray(source,np.float32)/255)
    manifest=json.dumps({'regions':[{'id':'r1','bbox':[0,0,1000,1000]}]})
    crops,doc,_,plans=N.MangaRegionCrops().crop(page,manifest,0,0,auto_deskew=True,
        text_pixel_mask=torch.from_numpy(support[None].astype(np.float32)))
    data=json.loads(doc)
    assert data['regions']==[] and data['needs_review']
    assert data['no_text_reason']=='unverified_ocr_geometry'
    assert torch.equal(crops[0],page) and plans==['{}']
    assert M.MangaOCRAdaptive().check_lazy_status(crops[0],manifest_json=doc)==[]
    text,report,_=M.MangaOCRAdaptive().read(crops[0],manifest_json=doc)
    collected=N.MangaCollectOCR().collect([text],[doc],[report])[0]
    monkeypatch.setattr(N,'api_json',lambda *a,**k:pytest.fail('Unverified crop reached translation'))
    translated=N.MangaTranslate().translate(collected,'','','','',4096,300)[0]
    mask=torch.from_numpy(support[None].astype(np.float32))
    edit,raw,cleanup,_,_=page_edit.MangaPageEditPlan().plan(page,translated,mask,torch.ones_like(mask))['result']
    assert not raw.any() and not cleanup.any()
    data=json.loads(edit)
    assert data['boundary_review']['reason']=='unverified_ocr_geometry'
    original=page[0].numpy()
    cleanup_plan=T.make_plan(original,raw[0].numpy(),cleanup[0].numpy(),regions_json=edit)
    assert not cleanup_plan['tiles']
    output,_=T.assemble(cleanup_plan,[])
    assert np.array_equal(output,original)
    with pytest.raises(ValueError,match='unverified OCR geometry'):
        N.MangaRegionCrops().crop(page,manifest,0,0,auto_deskew=True,text_pixel_mask=mask,geometry_policy='strict')


def test_geometry_review_closes_neighbour_ownership_before_any_crop(monkeypatch):
    # Region order must not let an earlier neighbour escape preservation.
    page=torch.ones((1,80,240,3));mask=torch.ones((1,80,240))
    data={'regions':[{'id':'safe','bbox':[0,0,300,1000]},
                     {'id':'bad','bbox':[290,0,600,1000]},
                     {'id':'separate','bbox':[800,0,1000,1000]}]}
    monkeypatch.setattr(G,'plan',lambda image,support,ident: ({},{'needs_review':True,'reason':'source_crop_cuts_glyphs'}) if ident=='bad' else ({},{}))
    crops,doc,_,_=N.MangaRegionCrops().crop(page,json.dumps(data),0,0,auto_deskew=True,text_pixel_mask=mask)
    data=json.loads(doc)
    assert [r['id'] for r in data['regions']]==['separate'] and len(crops)==1
    assert data['ocr_geometry_review']['preserved_region_ids']==['safe','bad']


def test_geometry_policy_default_keeps_existing_project_identity():
    from geometry_tests.tools.run_project import workflow_fingerprint
    graph=json.loads((ROOT/'lettering/example_workflows/08-integrated-tiled-cleanup-lettering.api.json').read_text())
    old=deepcopy(graph)
    crop=next(n for n in graph.values() if n['class_type']=='MangaRegionCrops')
    crop['inputs']['geometry_policy']='preserve_review'
    assert workflow_fingerprint(graph)==workflow_fingerprint(old)
    crop['inputs']['geometry_policy']='strict'
    assert workflow_fingerprint(graph)!=workflow_fingerprint(old)


@pytest.mark.parametrize('angle,cut',[(-17.,110),(13.5,60),(21.,60)])
def test_clipped_glyphs_are_recovered_from_real_page_context(angle,cut):
    from geometry_tests import source_recovery as R
    source,ink,support,_=fixture(angle);h=source.height-cut
    limited=support.copy();limited[h:]=False
    box=[0,0,source.width,h]
    _,analysis=G.plan(source.crop(box),limited[:h],'r1')
    assert analysis['needs_review']
    result,audit=R.recover(source,box,limited,'r1',analysis)
    assert result and audit['status']=='recovered' and audit['added_ink_pixels']>0
    plan=result['plan'];context=source.crop(result['crop_bbox_pixels'])
    inputs=G.planned_inputs(context,plan)
    assert len(inputs)==3 and plan['row_mode']=='context_glyph_bounds'
    local=R._context_ink(context,plan)
    a,b,c,d=result['crop_bbox_pixels']
    # Actual original glyphs beyond the detector crop must be reached, rather
    # than merely accepting the same truncated OCR input.
    assert local[h-b:].any()
    assert (local & ink[b:d,a:c]).sum()>.7*local.sum()


def test_context_recovery_will_not_take_another_regions_edit_owner():
    from geometry_tests import source_recovery as R
    source,_,support,_=fixture();h=source.height-60;box=[0,0,source.width,h]
    _,analysis=G.plan(source.crop(box),support[:h],'r1')
    result,audit=R.recover(source,box,support,'r1',analysis,obstacles=[[0,h,source.width,source.height]])
    assert result is None and audit['reason']=='neighbour_ownership_conflict'


def test_context_continuation_does_not_drop_glyphs_outside_detector_support():
    from geometry_tests import source_recovery as R
    source,ink,support,_=fixture();h=source.height-60;box=[0,0,source.width,h]
    # The detector cannot supply pixels outside its own clipped window.
    limited=support.copy();limited[h:]=False
    _,analysis=G.plan(source.crop(box),limited[:h],'r1')
    result,audit=R.recover(source,box,limited,'r1',analysis)
    assert result and len(result['plan']['rows'])==3
    context=source.crop(result['crop_bbox_pixels']);mask=R._context_ink(context,result['plan'])
    # Compare with the full-support result, not a handpicked font-size limit.
    full,_=R.recover(source,box,support,'r1',analysis)
    expected=R._context_ink(source.crop(full['crop_bbox_pixels']),full['plan'])
    assert np.array_equal(mask,expected)


def test_recovered_source_pixels_reach_cleanup_and_changed_inputs_are_rejected():
    from geometry_tests import source_recovery as R, page_edit as E
    source,_,support,_=fixture();h=source.height-60
    mask=support.copy();mask[h:]=False
    page=tensor(np.asarray(source,np.float32)/255)
    w,full_h=source.size
    manifest=json.dumps({'regions':[{'id':'r1','bbox':[0,0,1000,h/full_h*1000]}]})
    crops,doc,_,plans=N.MangaRegionCrops().crop(page,manifest,0,12,auto_deskew=True,
                                             text_pixel_mask=torch.from_numpy(mask[None].astype(np.float32)))
    data=json.loads(doc);row=data['regions'][0]
    assert 'no_text_reason' not in data and json.loads(plans[0])['row_mode']=='context_glyph_bounds'
    assert data['ocr_geometry_recovery']['regions'][0]['status']=='recovered'
    assert len(G.planned_inputs(source.crop(row['crop_bbox_pixels']),json.loads(plans[0])))==3
    row.update(source='MY PROFILE\nNAME CLASS LABEL\nANOTHER SAMPLE LINE',target='프로필\n이름과 직업\n설명 문장')
    raw=torch.from_numpy(mask[None].astype(np.float32))
    edited,raw,cleanup,_,_=E.MangaPageEditPlan().plan(page,json.dumps(data),raw,raw)['result']
    assert raw[0,h:].any() and cleanup[0,h:].any()
    assert raw.sum()<raw.numel()*.2  # Never grant the context rectangle as erase pixels.
    changed=page.clone();changed[:,100,100]=0
    with pytest.raises(ValueError,match='stale or unverified'):
        E.MangaPageEditPlan().plan(changed,json.dumps(data),raw,cleanup)
    modified=deepcopy(json.loads(plans[0]));modified['rows'][0][0]+=1
    with pytest.raises(ValueError,match='stale or unverified'):
        G.planned_inputs(source.crop(row['crop_bbox_pixels']),modified)
    # Manual source preservation still wins after successful reconstruction.
    kept,kept_mask,_,_,_=E.MangaPageEditPlan().plan(page,json.dumps(data),raw,cleanup,'{"r1":"preserve"}')['result']
    assert not kept_mask.any() and json.loads(kept)['page_edit_plan']['regions'][0]['action']=='preserve'


def test_page_edit_review_inherits_ocr_review_without_relabelling_the_reason():
    from geometry_tests import page_edit as E
    data={'regions':[],'needs_review':True,'review_reason':'unverified_ocr_geometry'}
    result=E.build(data,60,40)
    assert result['page_edit_plan']['needs_review'] is True
    assert result['review_reason']=='unverified_ocr_geometry'


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
