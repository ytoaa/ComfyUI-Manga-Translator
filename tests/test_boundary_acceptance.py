"""Regressions for page ownership, resumed revisions and empty OCR evidence."""
from copy import deepcopy
import json
import types
import uuid

import pytest
import torch

from tests.test_document_stages import D,C as Cache,row
from tests.test_canvas_execution import C,CanvasClient,setup_book,execute_visible_graph
from tests.test_project_runner import P,FakeComfy,make_page,graph


def context(owner='project/a/page/1',sha='a'*64):
    return json.dumps({'review_identity':{'page_key':owner,'input_sha256':sha}})


def edit(data,owner='project/a/page/1'):
    identity=json.loads(context(owner))['review_identity']
    revision=D.review_revision(data,identity,'target')
    return json.dumps({'pages':{revision:{'r1':{'target':'제목\n\n사람이 고침'}}},'identities':{revision:owner}})


@pytest.mark.parametrize('owner',['project/a/page/2','project/b/page/1'])
def test_identical_documents_never_share_human_edits_across_page_or_project(owner):
    data={'regions':[row()]};edits=edit(data);node=D.MangaReviewDocument()
    own=json.loads(node.review(json.dumps(data),'target',edits,context())['result'][0])
    other=json.loads(node.review(json.dumps(data),'target',edits,context(owner))['result'][0])
    assert own['regions'][0]['target']=='제목\n\n사람이 고침'
    assert other['regions'][0]['target']==row()['target']


def test_diagnostics_preserve_edits_but_content_changes_report_a_conflict():
    data={'regions':[row()]};edits=edit(data);node=D.MangaReviewDocument()
    changed=deepcopy(data);changed['regions'][0]['ocr_diagnostics']={'patch_budget':512}
    out=node.review(json.dumps(changed),'target',edits,context())
    assert json.loads(out['result'][0])['regions'][0]['target']=='제목\n\n사람이 고침'
    changed['regions'][0]['source']='Changed source'
    out=node.review(json.dumps(changed),'target',edits,context())
    assert json.loads(out['result'][0])['regions'][0]['target']==row()['target']
    assert json.loads(out['result'][1])['stale_edits'] and out['ui']['manga_document'][0]['warnings']


def test_legacy_and_unbound_edits_are_preserved_as_explicit_conflicts():
    data={'regions':[row()]};legacy=json.dumps({'pages':{D.digest(data):{'r1':{'target':'old correction'}}}})
    for ctx in ('{}',context()):
        out=D.MangaReviewDocument().review(json.dumps(data),'target',legacy,ctx)
        assert json.loads(out['result'][0])['regions'][0]['target']==row()['target']
        assert json.loads(out['result'][1])['legacy_edits']
        assert out['ui']['manga_document'][0]['warnings']
    assert 'old correction' in legacy


def test_lazy_cache_generation_survives_eviction_and_keeps_its_diagnostics(tmp_path,monkeypatch):
    monkeypatch.setattr(Cache,'root',lambda:tmp_path)
    node=Cache.MangaCleanupCheckpoint();image=torch.rand(1,8,12,3)
    g={'1':{'class_type':'MangaCleanupCheckpoint','inputs':{}}}
    node.checkpoint(image,image,prompt=g,unique_id='1',report_json='{"evidence":"generation A"}')
    assert node.check_lazy_status(image,prompt=g,unique_id='1')==[]
    key=node._key(image,g,'1','',None)
    (tmp_path/key[:2]/key/'value.bin').unlink()
    (tmp_path/key[:2]/key/'manifest.json').unlink()
    out=node.checkpoint(image,prompt=g,unique_id='1')
    assert torch.equal(out['result'][0],image)
    assert json.loads(out['result'][1])['evidence']=='generation A'
    assert node.check_lazy_status(image,prompt=g,unique_id='1')==['value']


@pytest.mark.parametrize('guard',[False,True])
def test_empty_crop_never_loads_or_calls_model_and_is_protected_by_collector(guard):
    from tests.test_empty_pages import S
    image=torch.ones(1,30,50,3);ocr=S.plugin.NODE_CLASS_MAPPINGS['MangaOCRAdaptive']()
    class Model:
        def ocr(self,*args,**kwargs):pytest.fail('Uniform empty crop reached OCR')
    assert ocr.check_lazy_status(image)==[]
    text,report,_=ocr.read(image,Model(),quality_guard=guard)['result']
    assert text=='' and json.loads(report)['empty_crop_verified']['method']=='uniform_rgb_pixels'
    manifest={'image_width':100,'image_height':80,'regions':[
        {'id':'r1','bbox':[100,100,600,600],'edit_bbox_pixels':[10,8,60,48]},
        {'id':'r2','bbox':[650,100,950,600],'edit_bbox_pixels':[65,8,95,48]}]}
    out=json.loads(S.N.MangaCollectOCR().collect([text,'読めた文字'],[json.dumps(manifest)],[report,'{}'])[0])
    assert [r['id'] for r in out['regions']]==['r2']
    assert out['needs_review'] and out['boundary_review']['protected_boxes_pixels']==[[10,8,60,48]]


def test_page_edits_select_only_their_owner_after_project_reload(tmp_path):
    client=FakeComfy();make_page(tmp_path/'input/1.png');make_page(tmp_path/'input/2.png')
    book=P.Project(tmp_path/'input',tmp_path/'project',graph(),client);book.run()
    changed=graph();review=next(n for n in changed.values() if n['class_type']=='MangaReviewDocument' and n['inputs']['stage']=='target')
    owner=f'project/{book.project_id}/page/{book.pages[0]["id"]}'
    review['inputs']['edits_json']=edit({'regions':[row()]},owner)
    resumed=P.Project(tmp_path/'input',tmp_path/'project',changed,client);resumed._prepare_project()
    engine=C.CanvasExecution()
    assert engine._eligible(resumed,resumed.pages[0],False)
    assert not engine._eligible(resumed,resumed.pages[1],False)
    resumed.run()
    assert len(client.submissions)==3  # two initial pages, only one edited page


def test_blocked_second_tab_preserves_first_completion_ticket(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path,1);g=graph();source=P.workflow_bindings(g)['load'];pid=str(uuid.uuid4())
    first=engine.begin(inputs,folder,g,client,pid,source,'시작·재개');run=first['ticket']['run_id']
    state=P.read_json(next(folder.glob('pages/*/attempt-*/state.json')))
    client.server.prompt_queue.running=[[0,pid,g,{'manga_project':state['submission_token']},[]]]
    blocked=engine.begin(inputs,folder,g,client,str(uuid.uuid4()),source,'시작·재개')
    assert not blocked['ticket'] and P.read_json(folder/'canvas_run.json')['run_id']==run
    execute_visible_graph(client,pid,first)
    client.server.prompt_queue.running=[]
    result=engine.resolve(folder,run,pid,client)
    assert result['report']['counts']=={'completed':1}
