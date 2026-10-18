"""User edits, dependency invalidation, real font frames and atomic OCR acquisition."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import numpy as np
import pytest
import torch
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('document_stage_tests',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from document_stage_tests import document as D, stage_cache as C, translation_context as T, ocr_engines as E
from document_stage_tests.lettering import frame,core,hybrid


def row():
    return {'id':'r1','bbox':[100,100,800,800],'crop_bbox_pixels':[20,20,220,180],
            'source':'Title\nBody','target':'제목\n\n본문','blocks':[
            {'id':'b1','source':'Title','target':'제목','bbox_local':[0,0,180,40],'coordinate_frame':'source_crop_pixels','role':'heading'},
            {'id':'b2','source':'Body','target':'본문','bbox_local':[0,50,180,150],'coordinate_frame':'source_crop_pixels','role':'body'}]}


def test_authorship_approval_preserves_paragraphs_and_coordinates():
    data={'regions':[row()]};approved=D.apply_edits(data,{'r1':{'target':row()['target']}},'target')
    assert approved['regions'][0]['authored']['target']['origin']=='human'
    assert approved['regions'][0]['blocks']==row()['blocks']
    assert approved['document']['regions'][0]['analysis']['bbox_normalized_1000']==row()['bbox']
    assert data=={'regions':[row()]}


def test_source_correction_invalidates_translation_and_old_edit_plan():
    data={'regions':[row()],'page_edit_plan':{'stale':True}}
    edited=D.apply_edits(data,{'r1':{'source':'Corrected'}},'source')
    assert not {'blocks','target'} & edited['regions'][0].keys()
    assert 'page_edit_plan' not in edited


def test_review_is_bound_to_page_revision_and_same_value_can_approve():
    data={'regions':[row()]};node=D.MangaReviewDocument();identity={'page_key':'project/a/page/1','input_sha256':'a'*64}
    revision=D.review_revision(data,identity,'target');context=json.dumps({'review_identity':identity})
    edits=json.dumps({'pages':{revision:{'r1':{'target':'제목\n\n수정'}}},'identities':{revision:identity['page_key']}})
    out=json.loads(node.review(json.dumps(data),'target',edits,context)['result'][0])
    assert out['regions'][0]['blocks'][1]['target']=='수정'
    other=deepcopy(data);other['regions'][0]['source']='Different'
    assert json.loads(node.review(json.dumps(other),'target',edits,context)['result'][0])['regions'][0]['target']==row()['target']


@pytest.mark.parametrize('text',['<UNK_SPAN>','<br>','\x00',''])
def test_human_edit_still_obeys_plain_text_contract(text):
    with pytest.raises(ValueError):D.apply_edits({'regions':[row()]},{'r1':{'target':text}},'target')


def test_translation_paragraph_ids_survive_reordered_response():
    original={'regions':[row()]};units,mapping=D.translation_units(original)
    translated={'regions':[{**r,'target':f'번역{i}'} for i,r in enumerate(reversed(units['regions']))]}
    result=D.merge_translations(original,translated,mapping)
    assert result['regions'][0]['blocks'][0]['target']=='번역1'
    assert result['regions'][0]['blocks'][1]['target']=='번역0'


@pytest.mark.parametrize('change',[{'source':'Other'},{'bbox_local':[0,0,1,1]},{'coordinate_frame':'rectified_crop_pixels'}])
def test_target_review_cannot_change_source_or_geometry(change):
    b=deepcopy(row()['blocks']);b[0].update(change)
    with pytest.raises(ValueError):D.apply_edits({'regions':[row()]},{'r1':{'blocks':b}},'target')


def test_geometry_hierarchy_uses_supported_bands_not_whitespace_partitions():
    r=row();r['ocr_region_plan']={'rows':[[0,0,180,80],[0,80,180,160]],'evidence':{'row_validation':{'bands_pixels':[[10,50],[90,110]]}}}
    blocks=D.blocks_from_ocr(r,{'line_texts':['Title','Body']})
    assert [b['role'] for b in blocks]==['heading','body']
    del r['ocr_region_plan']['evidence']
    assert D.blocks_from_ocr(r,{'line_texts':['Title','Body']})==[]


@pytest.fixture
def cache(tmp_path,monkeypatch):
    monkeypatch.setattr(C,'root',lambda:tmp_path/'cache');return tmp_path


def graph():
    return {'1':{'class_type':'MangaWorkflowInput','inputs':{'image':'ignored.png','action':'start'}},
            '2':{'class_type':'Detector','inputs':{'images':['1',0],'threshold':.2}},
            '3':{'class_type':'MangaDetectionCheckpoint','inputs':{'original':['1',0],'value':['2',0],'cache_policy':'reuse'}},
            '4':{'class_type':'Font','inputs':{'font':'one'}}}


def test_checkpoint_laziness_and_downstream_font_independence(cache):
    image=torch.rand(1,20,30,3);g=graph();node=C.MangaDetectionCheckpoint()
    assert node.check_lazy_status(image,prompt=g,unique_id='3')==['value']
    value={'protocol':1,'detections':[]};node.checkpoint(image,value,prompt=g,unique_id='3')
    assert node.check_lazy_status(image,prompt=g,unique_id='3')==[]
    assert node.checkpoint(image,prompt=g,unique_id='3')['result'][0]==value
    h=deepcopy(g);h['4']['inputs']['font']='two';assert C.identity(image,g,'3','detection')==C.identity(image,h,'3','detection')
    h['2']['inputs']['threshold']=.3;assert node.check_lazy_status(image,prompt=h,unique_id='3')==['value']
    assert node.check_lazy_status(image,prompt=g,unique_id='3',cache_policy='refresh')==['value']


def test_cache_hash_binds_all_pixels_and_rejects_corrupt_payload(cache):
    image=torch.rand(1,4,6,3);key=C.identity(image,None,None,'text','source')
    C.write(key,'text','exact text');assert C.read(key,'text')=='exact text'
    (C.root()/key[:2]/key/'value.bin').write_bytes(b'corrupt');assert C.read(key,'text') is None
    changed=image.clone();changed[0,-1,-1,0]+=.0001
    assert C.identity(changed,None,None,'text','source')!=key
    assert C.identity(image,None,None,'text','different')!=key


def test_cleanup_cache_is_lossless_and_unbound_calls_never_reuse(cache):
    image=torch.rand(1,8,12,3);key=C.identity(image,None,None,'image')
    C.write(key,'image',image);assert torch.equal(C.read(key,'image'),image)
    node=C.MangaCleanupCheckpoint();assert node.check_lazy_status(image)==['value']
    assert node.checkpoint(image,image)['result'][0] is image


def test_effective_cleanup_not_translation_words_controls_background_key(cache):
    image=torch.rand(1,8,12,3);plan={'version':1,'original':image[0].numpy(),'base':image[0].numpy(),'source_mask':np.zeros((8,12)),'cleanup_mask':np.ones((8,12)),'tiles':[]}
    key=C.cleanup_identity('',plan);other=deepcopy(plan);other['report']={'text':'changed'}
    assert C.cleanup_identity('',other)==key
    other['cleanup_mask'][0,0]=0;assert C.cleanup_identity('',other)!=key


def test_other_page_review_edits_do_not_invalidate_current_translation(cache):
    g=graph();g['5']={'class_type':'MangaReviewDocument','inputs':{'document_json':['3',0],'edits_json':'{}'}}
    g['6']={'class_type':'MangaTextCheckpoint','inputs':{'value':['5',0]}}
    image=torch.ones(1,4,5,3);key=C.identity(image,g,'6','text','source revision A')
    g['5']['inputs']['edits_json']='{"pages":{"unrelated":{}}}'
    assert C.identity(image,g,'6','text','source revision A')==key
    assert C.identity(image,g,'6','text','source revision B')!=key


def test_glossary_conflicts_and_literal_matching():
    assert len(T.glossary('[{"source":"NAME","target":"이름"},{"source":"name","target":"이름"}]'))==1
    with pytest.raises(ValueError):T.glossary('[{"source":"Name","target":"A"},{"source":"name","target":"B"}]')
    context=json.loads(T.MangaTranslationContext().build(json.dumps({'regions':[{'source':'Name'}]}),'[{"source":"Name","target":"이름"}]')[0])
    assert len(context['glossary'])==1 and not context['reviewed_history']


def test_only_hash_verified_human_approved_prior_pages_enter_book_context(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    folder=tmp_path/'manga_translator/workflow_projects/book';attempt=folder/'pages/p1/attempt-000001';attempt.mkdir(parents=True)
    data={'regions':[row()],'translation_metadata':{'target_language':'Korean'}}
    data=D.apply_edits(data,{'r1':{'target':row()['target']}},'target');raw=json.dumps(data).encode()
    (attempt/'target.json').write_bytes(raw);(attempt/'state.json').write_text(json.dumps({'artifacts':{'target.json':hashlib.sha256(raw).hexdigest()}}))
    report={'project_folder':str(folder),'current_page':'2.png','pages':[{'relative_path':'1.png','status':'completed','state_file':'pages/p1/attempt-000001/state.json'},{'relative_path':'2.png','status':'running'}]}
    assert len(T.history(report,'Korean',10000))==1
    assert T.history(report,'English',10000)==[] and T.history(report,'Korean',2)==[]
    (attempt/'target.json').write_bytes(raw+b' ');assert T.history(report,'Korean',10000)==[]


@pytest.mark.parametrize('angle',[-18,13.5,25])
def test_real_font_renders_in_local_rotated_frame_without_stretch_or_page_loss(angle):
    # Build the same physical frame at each angle; local fit must stay identical.
    theta=np.radians(angle);u=np.array([np.cos(theta),-np.sin(theta)]);v=np.array([np.sin(theta),np.cos(theta)])
    p=np.array([100,150]);quad=[p,p+u*260,p+u*260+v*90,p+v*90];quad=[q.tolist() for q in quad]
    original=np.ones((100,270,3),np.float32);original[20:50,20:240]=0;clean=np.ones_like(original)
    style,_=core.analyze_style(original,clean,(original[:,:,0]==0).astype(float))
    bounds,rgb,alpha,report=frame.render('기울어진 제목',style,'NanumGothic-Bold.ttf',quad,(500,600,3),min_font=22,max_font=22,padding=4)
    assert report['font_size']==22 and abs(report['local_size'][0]-260)<=1
    assert rgb.shape[:2]==alpha.shape and alpha.max()>.9 and min(bounds)>=0
    assert not alpha[0].any() and not alpha[-1].any()


def test_offpage_local_glyphs_are_rejected_even_if_raster_would_clip_them():
    a=np.ones((60,200,3),np.float32);a[10:40,10:180]=0;style,_=core.analyze_style(a,np.ones_like(a),1-a[:,:,0])
    with pytest.raises(ValueError,match='page boundary'):
        frame.render('바깥 글자',style,'NanumGothic-Bold.ttf',[[-100,-100],[100,-100],[100,-40],[-100,-40]],(300,300,3),min_font=20,max_font=20,padding=4)


def test_atomic_download_verification_reuse_and_bad_hash_cleanup(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(models_dir=str(tmp_path)))
    payload=b'pinned model';files={'weights.bin':hashlib.sha256(payload).hexdigest()}
    monkeypatch.setattr(E,'spec',lambda engine:('repo','revision',files,{'weights.bin':'https://example.invalid/model'},'test'))
    calls=[]
    monkeypatch.setattr(E,'urlopen',lambda url,timeout:(calls.append(url) or io.BytesIO(payload)))
    folder=E.ensure(E.ENGINES[1]);assert (folder/'weights.bin').read_bytes()==payload
    assert E.ensure(E.ENGINES[1],False)==folder and len(calls)==1
    (folder/'weights.bin').write_bytes(b'modified')
    with pytest.raises(ValueError,match='incomplete or modified'):E.ensure(E.ENGINES[1])
    other=tmp_path/'other';monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(models_dir=str(other)))
    monkeypatch.setattr(E,'urlopen',lambda *a,**kw:io.BytesIO(b'bad'))
    with pytest.raises(ValueError,match='SHA256'):E.ensure(E.ENGINES[1])
    assert not list((other/'manga_translator/ocr').iterdir())


def test_heading_body_flow_collect_translate_prepare_and_oriented_render(monkeypatch):
    from document_stage_tests import nodes as N,text_geometry as G
    from document_stage_tests.lettering.nodes import MangaLetterPrepare,tensor
    base=Image.new('RGB',(480,180),(220,205,215));mask=Image.new('L',base.size)
    for y,size,text in [(10,40,'MY PROFILE'),(80,22,'NAME CLASS'),(120,22,'OTHER BODY')]:
        font=ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Bold.ttf'),size)
        ImageDraw.Draw(base).text((24,y),text,font=font,fill=(70,25,65));ImageDraw.Draw(mask).text((24,y),text,font=font,fill=255)
    source=base.rotate(13.5,Image.Resampling.BICUBIC,expand=True,fillcolor=(220,205,215))
    ink=np.asarray(mask.rotate(13.5,Image.Resampling.NEAREST,expand=True))>0
    plan,evidence=G.plan(source,ink,'r1');assert evidence['accepted']
    w,h=source.size;manifest={'image_width':w,'image_height':h,'regions':[{'id':'r1','bbox':[0,0,1000,1000],
        'crop_bbox_pixels':[0,0,w,h],'edit_bbox_pixels':[0,0,w,h],'ocr_region_plan':plan}]}
    collected=json.loads(N.MangaCollectOCR().collect(['MY PROFILE\nNAME CLASS\nOTHER BODY'],[json.dumps(manifest)],
        [json.dumps({'region_plan':plan,'line_texts':['MY PROFILE','NAME CLASS','OTHER BODY']})])[0])
    assert [b['role'] for b in collected['regions'][0]['blocks']]==['heading','body']
    def api(base,path,key,timeout,payload=None):
        request=json.loads(payload['messages'][1]['content'])
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'translations':[
            {'id':r['id'],'target':'제목' if i==0 else '본문 설명'} for i,r in enumerate(request['regions'])]})}}]}
    monkeypatch.setattr(N,'api_json',api)
    translated=N.MangaTranslate().translate(json.dumps(collected),'http://localhost:8000/v1','test','Korean','ENV',4096,300)[0]
    original=np.asarray(source,np.float32)/255;clean=np.full_like(original,np.array([220,205,215])/255)
    prepared,support=MangaLetterPrepare().prepare(tensor(original),translated,0,'{}',tensor(ink.astype(float)))
    children=json.loads(prepared)['regions'];assert len(children)==2 and all(c['parent_id']=='r1' for c in children)
    typography,preview,report=hybrid.build_plan(original,clean,support[0].numpy(),prepared,min_font=8,min_scale=.3,
        line_breaks='reflow',fit_policy='readable',oriented_fit=True,page_direction='horizontal')
    result,alpha,report=hybrid.render_plan(typography);report=json.loads(report)
    assert len(report['regions'])==2 and report['regions'][0]['source_profile']['font_cap']>report['regions'][1]['source_profile']['font_cap']
    assert all(r['render']['coordinate_frame']=='oriented_local_pixels' for r in report['regions'])
    assert np.array_equal(result[alpha==0],clean[alpha==0])


def test_repeated_graph_and_font_only_change_reuse_detector_and_cleanup(tmp_path):
    from tests.test_integrated_simulation import S
    first=S.GraphRunner(tmp_path);first.ocr.cache_identity={'oracle_revision':1};first.execute()
    again=S.GraphRunner(tmp_path);again.ocr.cache_identity={'oracle_revision':1};second=again.execute()
    assert second['detector_calls']==0 and second['qwen_tile_calls']==0
    assert again.ocr.calls==0
    changed=S.GraphRunner(tmp_path);changed.ocr.cache_identity={'oracle_revision':1}
    next(n for n in changed.graph.values() if n['class_type']=='MangaLetterPlan')['inputs']['default_font']='NanumGothic-Regular.ttf'
    report=changed.execute()
    assert report['detector_calls']==0 and report['qwen_tile_calls']==0 and changed.ocr.calls==0


def test_changed_settings_cannot_replace_an_active_project_identity(tmp_path):
    import uuid
    from tests.test_project_runner import P,project,FakeComfy,make_page,graph as project_graph
    make_page(tmp_path/'input/1.png');client=FakeComfy();runner=project(tmp_path,client);runner._prepare_project()
    state=runner._new(runner.pages[0]);state.update(status='running',prompt_id=str(uuid.uuid4()),
        output_prefix=f"manga_translator/projects/{runner.project_id}/{state['id']}/a{state['attempt']:06d}")
    runner._save(state)
    changed=project_graph();next(n for n in changed.values() if n['class_type']=='MangaLetterPlan')['inputs']['min_font']=9
    with pytest.raises(P.ProjectError,match='settings changed'):
        P.Project(runner.inputs,runner.destination,changed,client)._prepare_project()
    assert json.loads((runner.destination/'project.json').read_text())['config']==runner.config


def test_same_local_model_filename_with_new_weights_invalidates_stage(cache,monkeypatch):
    weight=cache/'model.safetensors';weight.write_bytes(b'first')
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_full_path=lambda category,name:str(weight)))
    g={'1':{'class_type':'UNETLoader','inputs':{'unet_name':'same.safetensors'}},
       '2':{'class_type':'MangaCleanupCheckpoint','inputs':{'value':['1',0]}}}
    image=torch.ones(1,3,4,3);a=C.identity(image,g,'2','image')
    native=C.MangaCleanupCheckpoint.IS_CHANGED(prompt=g,unique_id='2')
    weight.write_bytes(b'other');assert C.identity(image,g,'2','image')!=a
    assert C.MangaCleanupCheckpoint.IS_CHANGED(prompt=g,unique_id='2')!=native


def test_malformed_manifest_becomes_cache_miss(cache):
    key='a'*64;folder=C.root()/key[:2]/key;folder.mkdir(parents=True)
    (folder/'manifest.json').write_text('[]');assert C.read(key,'text') is None


def test_machine_retranslation_clears_previous_human_approval():
    approved=D.apply_edits({'regions':[row()]},{'r1':{'target':row()['target']}},'target')
    edited=D.apply_edits(approved,{'r1':{'source':'Corrected'}},'source')
    assert edited['regions'][0]['authored'].get('target') is None
    units,mapping=D.translation_units(approved)
    for r in units['regions']:r['target']='새 번역'
    machine=D.merge_translations(approved,units,mapping)
    assert machine['regions'][0]['authored'].get('target') is None


def test_refresh_ocr_runs_through_native_cache_each_time():
    from document_stage_tests.recognition_cache import MangaOCRAdaptiveCached
    assert np.isnan(MangaOCRAdaptiveCached.IS_CHANGED(cache_policy='refresh'))
    assert np.isnan(MangaOCRAdaptiveCached.IS_CHANGED(cache_policy='off'))


def test_cleanup_cache_retains_inspectable_diagnostics_without_reexecuting_model(cache):
    original=torch.ones(1,8,12,3);g={'1':{'class_type':'Assemble','inputs':{}},
        '2':{'class_type':'MangaCleanupCheckpoint','inputs':{'value':['1',0],'report_json':['1',1]}}}
    node=C.MangaCleanupCheckpoint();report=json.dumps({'tiles':[{'source_ink_retained':.01}],'outside_mask_unchanged':True})
    assert node.check_lazy_status(original,prompt=g,unique_id='2')==['value','report_json']
    node.checkpoint(original,original,prompt=g,unique_id='2',report_json=report)
    assert node.check_lazy_status(original,prompt=g,unique_id='2')==[]
    reused=json.loads(node.checkpoint(original,prompt=g,unique_id='2')['result'][1])
    assert reused['tiles'][0]['source_ink_retained']==.01 and reused['stage_cache']['state']=='reused'
