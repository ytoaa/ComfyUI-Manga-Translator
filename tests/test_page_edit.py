"""Edit permission reaches cleanup, lettering and durable page verification."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest
import torch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('page_edit_tests',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from page_edit_tests import page_edit as E, inpaint_tiles as T
from page_edit_tests.lettering import hybrid
from page_edit_tests.lettering.nodes import MangaLetterPrepare


def fixture():
    original=np.full((160,360,3),.7,np.float32)
    source=np.zeros((160,360),np.float32)
    source[35:55,35:90]=1;source[95:115,210:300]=1
    original[source>.5]=0
    data={'image_width':360,'image_height':160,'regions':[
        {'id':'r1','bbox':[50,100,300,400],'edit_bbox_pixels':[18,16,108,64],'source':'先生','target':'선생님'},
        {'id':'r2','bbox':[550,500,900,850],'edit_bbox_pixels':[198,80,324,136],'source':'本文','target':'본문'}]}
    return original,source,data


def test_preserved_region_is_not_uniform_filled_and_shared_by_lettering():
    original,source,data=fixture()
    document=E.build(data,360,160,{'r1':'preserve'},source)
    raw,pending=E.masks(document,source,source)
    assert not raw[:70].any() and raw[95:115,210:300].all()
    plan=T.make_plan(original,raw,pending,regions_json=json.dumps(document),recover_uniform_ink=True)
    cleaned,_=T.assemble(plan,[])
    assert np.array_equal(cleaned[:70],original[:70])
    assert np.allclose(cleaned[95:115,210:300],.7)
    prepared,support=MangaLetterPrepare().prepare(torch.from_numpy(original)[None],json.dumps(document))
    values=json.loads(prepared)
    assert [r['id'] for r in values['regions']]==['r2']
    assert values['source_preservation'][0]['id']=='r1'
    lettering,_,_=hybrid.build_plan(original,cleaned,support[0].numpy(),prepared,fit_policy='readable')
    result,alpha,_=hybrid.render_plan(lettering)
    assert np.array_equal(result[:70],original[:70]) and not alpha[:70].any()


def test_unassigned_ink_is_preserved_and_requires_review():
    original,source,data=fixture()
    source[2:8,340:345]=1;original[2:8,340:345]=0
    document=E.build(data,360,160,source_mask=source)
    assert document['needs_review']
    assert document['page_edit_plan']['unassigned_boxes_pixels']==[[340,2,345,8]]
    raw,pending=E.masks(document,source,source)
    assert not raw[2:8,340:345].any()
    plan=T.make_plan(original,raw,pending,regions_json=json.dumps(document))
    output,_=T.assemble(plan,[])
    assert np.array_equal(output[2:8,340:345],original[2:8,340:345])


def test_overlap_closure_preserves_whole_connected_regions():
    _,source,data=fixture()
    data['regions'][1]['edit_bbox_pixels']=[100,60,324,136]
    doc=E.build(data,360,160,{'r1':'preserve'},source)
    assert [r['action'] for r in doc['page_edit_plan']['regions']]==['preserve','preserve']
    assert doc['page_edit_plan']['regions'][1]['reason']=='protected_region_overlap'
    assert doc['needs_review'] and not E.masks(doc,source,source)[0].any()
    E.validate(doc,360,160)


@pytest.mark.parametrize('change',['target','source','bbox','ids','size','plan_geometry','plan_float','protection'])
def test_stale_or_inconsistent_plan_is_rejected_before_cleanup(change):
    original,source,data=fixture()
    doc=E.build(data,360,160,{'r1':'preserve'},source)
    if change in ('target','source'):doc['regions'][0][change]='수정'
    elif change=='bbox':doc['regions'][0]['bbox'][0]+=1
    elif change=='ids':doc['regions'].reverse()
    elif change=='size':doc['image_width']=720
    elif change=='plan_geometry':doc['page_edit_plan']['regions'][0]['bbox_pixels'][0]+=1
    elif change=='plan_float':doc['page_edit_plan']['regions'][0]['bbox_pixels'][0]=18.0
    else:doc['page_edit_plan']['protected_boxes_pixels']=[]
    with pytest.raises(ValueError):
        T.make_plan(original,source,source,regions_json=json.dumps(doc))


@pytest.mark.parametrize('actions',[{'missing':'preserve'},{'r1':'skip'},{'r1':None},[]])
def test_invalid_manual_actions_never_change_pixels(actions):
    original,source,data=fixture();snapshot=original.copy()
    with pytest.raises(ValueError):E.build(data,360,160,actions,source)
    assert np.array_equal(original,snapshot)


@pytest.mark.parametrize('forced',['horizontal','vertical_rtl','vertical_ltr'])
def test_uniform_direction_overrides_region_settings_and_preserves_source_analysis(forced):
    original,source,data=fixture()
    document,support=MangaLetterPrepare().prepare(torch.from_numpy(original)[None],json.dumps(data))
    prepared=json.loads(document)
    prepared['regions'][0]['layout']={'direction':'vertical_rtl'}
    options=json.dumps({'r1':{'direction':'vertical_ltr'},'r2':{'direction':'horizontal'}})
    plan,_,report=hybrid.build_plan(original,np.full_like(original,.7),support[0].numpy(),json.dumps(prepared),
        region_options_json=options,page_direction=forced,line_breaks='reflow',fit_policy='readable')
    assert {row['options']['direction'] for row in plan['regions']}=={forced}
    assert all(sum(phase=='source-flow' for _,_,phase in row['phases'])==1 for row in plan['regions'])
    assert {r['direction'] for r in json.loads(report)['regions']}=={forced}
    output,alpha,_=hybrid.render_plan(plan)
    assert output.shape==original.shape and alpha.any()
    assert all('direction' in row['profile'] for row in plan['regions'])


@pytest.mark.parametrize('label,expected',[('가로 통일','horizontal'),('세로 통일 · 오른쪽 열부터','vertical_rtl'),('세로 통일 · 왼쪽 열부터','vertical_ltr'),('원문 따라 자동','auto')])
def test_direction_control_uses_closed_user_facing_choices(label,expected):
    from page_edit_tests.lettering.direction import MangaLetteringDirection
    assert MangaLetteringDirection().select(label)==(expected,)
    with pytest.raises(ValueError):MangaLetteringDirection().select('unknown')


def test_auto_retains_per_region_control():
    original,source,data=fixture()
    prepared,support=MangaLetterPrepare().prepare(torch.from_numpy(original)[None],json.dumps(data))
    plan,_,_=hybrid.build_plan(original,np.full_like(original,.7),support[0].numpy(),prepared,
        page_direction='auto',region_options_json='{"r1":{"direction":"vertical_ltr"}}')
    assert plan['regions'][0]['options']['direction']=='vertical_ltr'


def test_no_text_plan_is_an_unchanged_page_without_cleanup_work():
    original=np.full((40,60,3),.5,np.float32);zero=np.zeros((40,60),np.float32)
    doc=E.build({'regions':[],'page_status':'no_text_detected'},60,40,source_mask=zero)
    plan=T.make_plan(original,zero,zero,regions_json=json.dumps(doc))
    output,_=T.assemble(plan,[])
    assert not plan['tiles'] and np.array_equal(output,original)


@pytest.mark.parametrize('changed',[False,True])
def test_folder_collector_checks_source_preservation_without_calling_it_a_boundary_failure(tmp_path,changed):
    from io import BytesIO
    from PIL import Image
    from tests import test_project_runner as R
    class Client(R.FakeComfy):
        def submit(self,*args):
            result=super().submit(*args)
            job=self.jobs[args[1]];bind=R.P.workflow_bindings(args[0])
            value=json.loads(job['history']['outputs'][bind['target']]['text'][0])
            value=E.build(value,*Image.open(BytesIO(job['bytes'])).size,actions={'r1':'preserve'})
            for key in ('target','target_preview'):
                job['history']['outputs'][bind[key]]['text']=[json.dumps(value)]
            if changed:
                picture=Image.open(BytesIO(job['bytes'])).convert('RGB');picture.putpixel((6,6),(0,0,0))
                output=BytesIO();picture.save(output,format='PNG');job['bytes']=output.getvalue()
            return result
    inputs=tmp_path/'input';R.make_page(inputs/'page.png')
    project=R.P.Project(inputs,tmp_path/'project',R.graph(),Client(),poll_interval=.001)
    if changed:
        with pytest.raises(R.P.ProtocolError,match='preserved source'):
            project.run()
        assert not list((tmp_path/'project').glob('pages/*/attempt-*/result.png'))
    else:
        assert project.run()['counts']=={'completed':1}


def test_shipped_workflow_uses_saved_edit_plan_and_one_direction_source():
    graph=json.loads((ROOT/'lettering/example_workflows/08-integrated-tiled-cleanup-lettering.api.json').read_text())
    def node(kind):return next((k,v) for k,v in graph.items() if v['class_type']==kind)
    direction_id,direction=node('MangaLetteringDirection')
    edits_id,edits=node('MangaPageEditPlan')
    _,cleanup=node('MangaInpaintPlan')
    _,prepare=node('MangaLetterPrepare')
    _,lettering=node('MangaLetterPlan')
    assert direction['inputs']['lettering_direction']=='가로 통일'
    assert lettering['inputs']['page_direction']==[direction_id,0]
    def ancestors(ident):
        found=set()
        for value in graph[ident]['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and value[0] in graph:
                found.add(value[0]);found.update(ancestors(value[0]))
        return found
    for ident,value in graph.items():
        if value['class_type'] in ('MangaDetectorDetail','MangaOCRAdaptive','MangaTranslate','MangaPageEditPlan','MangaInpaintPlan','MangaInpaintAssemble'):
            assert direction_id not in ancestors(ident)
    assert cleanup['inputs']['regions_json']==prepare['inputs']['translated_json']
    assert cleanup['inputs']['source_mask']==[edits_id,1]
    assert cleanup['inputs']['cleanup_mask']==[edits_id,2]


def test_preserving_a_large_region_does_not_use_a_glyph_raster_budget():
    from page_edit_tests.lettering import core
    data={'image_width':6000,'image_height':6000,'regions':[
        {'id':'r1','bbox':[0,0,1000,1000],'source':'SOURCE','target':'번역'}]}
    with pytest.raises(ValueError,match='active lettering'):
        E.build(data,6000,6000)
    doc=E.build(data,6000,6000,{'r1':'preserve'})
    assert doc['page_edit_plan']['regions'][0]['action']=='preserve'
    prepared={'regions':[],'source_preservation':[{'id':'r1','bbox':[0,0,6000,6000],'reason':'manual_source_preservation'}]}
    assert core.source_preservation_boxes(prepared,(6000,6000,3))==[[0,0,6000,6000]]
