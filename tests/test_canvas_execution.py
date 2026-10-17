"""Folder pages execute the visible graph, with no background dispatcher or child submission."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import types
import uuid

import pytest

from tests.test_project_runner import P, graph
from tests.test_workflow_projects import W
from tests.test_integrated_simulation import S

C = importlib.import_module(W.__package__+'.workflow_native')


class Queue:
    def __init__(self): self.histories={}; self.running=[]; self.pending=[]
    def get_history(self, ident): return {ident:deepcopy(self.histories[ident])} if ident in self.histories else {}
    def get_current_queue(self): return deepcopy(self.running),deepcopy(self.pending)


class CanvasClient(W.NativeComfyClient):
    def __init__(self, root):
        self.input_root=root/'input'; self.output_root=root/'output'
        self.input_root.mkdir(parents=True,exist_ok=True); self.output_root.mkdir(parents=True,exist_ok=True)
        self.server=types.SimpleNamespace(prompt_queue=Queue())
        self.execution_context=None
    def submit(self,*args): pytest.fail('Canvas execution must never submit a hidden child prompt')


def setup_book(tmp_path, count=2):
    client=CanvasClient(tmp_path)
    inputs=client.input_root/'book'; inputs.mkdir()
    image,_,_,_=S.fixture()
    for i in range(count): image.save(inputs/f'{i+1}.png')
    folder=client.output_root/'manga_translator/workflow_projects/book'
    return C.CanvasExecution(),client,inputs,folder


def begin(engine,client,inputs,folder,continuation=None,action='시작·재개'):
    ident=str(uuid.uuid4()); g=graph(); source=P.workflow_bindings(g)['load']
    return ident,engine.begin(inputs,folder,g,client,ident,source,action,continuation)


def execute_visible_graph(client, ident, result, mode='success'):
    runner=S.GraphRunner(client.output_root)
    reference=result['image_reference']
    image=S.Image.open(client._path(reference)).convert('RGB')
    import torch
    import numpy as np
    runner.page_input=lambda args:(torch.from_numpy(np.asarray(image,np.float32)/255)[None],
        torch.zeros((1,image.height,image.width)),json.dumps(result['report']),*result['prefixes'])
    report=runner.execute()
    status={'status_str':'success','completed':True,'messages':[('execution_success',{'prompt_id':ident})]}
    if mode != 'success':
        status={'status_str':'error','completed':False,'messages':[('execution_error',{
            'node_type':'MangaOCRAdaptive','exception_type':'OutOfMemoryError' if mode=='oom' else 'HayaiOutputError',
            'exception_message':'CUDA out of memory' if mode=='oom' else 'short_repetition'})]}
    client.server.prompt_queue.histories[ident]={'outputs':runner.ui_outputs,'status':status}
    return report


def test_first_run_returns_real_page_and_only_canvas_success_advances(tmp_path,monkeypatch):
    engine,client,inputs,folder=setup_book(tmp_path)
    monkeypatch.setattr(W.WorkflowProjects,'start',lambda *a,**k:pytest.fail('Background worker started'))
    ident,result=begin(engine,client,inputs,folder)
    assert result['image_reference'] and result['ticket']['index']==1
    state=P.read_json(next(folder.glob('pages/*/attempt-*/state.json')))
    assert state['prompt_id']==ident and state['status']=='running'
    assert not list(folder.glob('pages/*/attempt-*/result.png'))
    pending=engine.resolve(folder,result['ticket']['run_id'],ident,client)
    assert pending['pending'] and not pending['continue']
    assert execute_visible_graph(client,ident,result)['final_saved']
    settled=engine.resolve(folder,result['ticket']['run_id'],ident,client)
    assert settled['continue'] and settled['report']['counts']=={'completed':1,'pending':1}
    assert len(list(folder.glob('pages/*/attempt-*/state.json')))==1
    assert engine.resolve(folder,result['ticket']['run_id'],ident,client)['continue'] is False


def test_next_page_is_another_normal_canvas_prompt_and_inventory_is_not_rescanned(tmp_path,monkeypatch):
    engine,client,inputs,folder=setup_book(tmp_path)
    first,result=begin(engine,client,inputs,folder)
    execute_visible_graph(client,first,result)
    assert engine.resolve(folder,result['ticket']['run_id'],first,client)['continue']
    monkeypatch.setattr(P,'scan_images',lambda *a,**k:pytest.fail('Continuation rescanned the book'))
    continuation={'run_id':result['ticket']['run_id'],'source_node':result['ticket']['source_node']}
    second,next_page=begin(engine,client,inputs,folder,continuation)
    assert second!=first and next_page['ticket']['index']==2 and next_page['ticket']['relative_path']=='2.png'
    execute_visible_graph(client,second,next_page)
    report=engine.resolve(folder,continuation['run_id'],second,client)
    assert not report['continue'] and report['report']['counts']=={'completed':2}
    assert report['report']['status']=='completed' and report['report']['export']


@pytest.mark.parametrize('mode,continues',[('quality',True),('oom',False)])
def test_actual_error_history_controls_continuation(tmp_path,mode,continues):
    engine,client,inputs,folder=setup_book(tmp_path)
    ident,result=begin(engine,client,inputs,folder)
    client.server.prompt_queue.histories[ident]={'outputs':{},'status':{'status_str':'error','completed':False,
        'messages':[('execution_error',{'node_type':'MangaOCRAdaptive',
            'exception_type':'OutOfMemoryError' if mode=='oom' else 'HayaiOutputError',
            'exception_message':'CUDA out of memory' if mode=='oom' else 'short_repetition'})]}}
    report=engine.resolve(folder,result['ticket']['run_id'],ident,client)
    assert report['continue'] is continues
    assert report['report']['pages'][0]['failure_node']=='MangaOCRAdaptive'
    assert len(list(folder.glob('pages/*/attempt-*/state.json')))==1


def test_pause_prevents_next_page_without_cancelling_current_job(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path)
    ident,result=begin(engine,client,inputs,folder)
    run_id=result['ticket']['run_id']; engine.pause(folder,run_id)
    execute_visible_graph(client,ident,result)
    report=engine.resolve(folder,run_id,ident,client)
    assert not report['continue'] and report['report']['status']=='paused'
    assert report['report']['counts']=={'completed':1,'pending':1}
    blocked=engine.begin(inputs,folder,graph(),client,str(uuid.uuid4()),result['ticket']['source_node'],
                         '시작·재개',{'run_id':run_id,'source_node':result['ticket']['source_node']})
    assert not blocked['ticket'] and len(list(folder.glob('pages/*/attempt-*/state.json')))==1


def test_reload_reconciles_completed_native_prompt_without_rerunning_page(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path)
    ident,result=begin(engine,client,inputs,folder)
    execute_visible_graph(client,ident,result)
    # Browser closed before resolve. The next manual canvas Run collects that
    # exact job and loads page two, rather than re-running page one.
    second,next_page=begin(engine,client,inputs,folder)
    assert next_page['ticket']['relative_path']=='2.png' and second!=ident
    summary=P.read_json(folder/'summary.json')
    assert summary['counts']=={'completed':1,'running':1}
    assert len(list(folder.glob('pages/*/attempt-*/state.json')))==2


def test_bad_continuation_or_old_workflow_is_rejected_before_page_execution(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path)
    with pytest.raises(P.Paused): begin(engine,client,inputs,folder,{'run_id':'bad','source_node':'1'})
    legacy=graph(); legacy[P.workflow_bindings(legacy)['final']]['inputs']['filename_prefix']='old'
    with pytest.raises(P.ProjectError,match='새 통합'): engine.begin(inputs,folder,legacy,client,str(uuid.uuid4()),'1','시작·재개')
    assert not list(folder.glob('pages/*/attempt-*/state.json'))


def test_status_refresh_collects_closed_browser_page_without_submitting_next(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path)
    ident,result=begin(engine,client,inputs,folder)
    execute_visible_graph(client,ident,result)
    report=engine.refresh(folder,client)
    assert report['counts']=={'completed':1,'pending':1}
    assert report['phase']=='awaiting_canvas' and not report['running']
    assert len(list(folder.glob('pages/*/attempt-*/state.json')))==1


def test_status_refresh_marks_missing_execution_paused_without_claiming_it_failed(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path)
    ident,result=begin(engine,client,inputs,folder)
    report=engine.refresh(folder,client)
    assert report['status']=='paused' and not report['running']
    state=P.read_json(next(folder.glob('pages/*/attempt-*/state.json')))
    assert state['status']=='running' and state['prompt_id']==ident


def test_real_input_node_returns_native_image_and_ticket_without_dispatch(tmp_path,monkeypatch):
    import sys
    engine,client,inputs,folder=setup_book(tmp_path)
    g=graph();source=P.workflow_bindings(g)['load'];ident=str(uuid.uuid4())
    client.server.prompt_queue.running=[[0,ident,g,{'client_id':'browser'},[]]]
    client.server.routes=[types.SimpleNamespace(method='POST',path='/prompt',handler=lambda:None)]
    monkeypatch.setattr(C,'CANVAS',engine)
    monkeypatch.setattr(W.WorkflowProjects,'start',lambda *a,**k:pytest.fail('Hidden project worker'))
    monkeypatch.setattr(W.NativeComfyClient,'submit',lambda *a,**k:pytest.fail('Hidden prompt submission'))
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(
        get_input_directory=lambda:str(client.input_root),get_output_directory=lambda:str(client.output_root)))
    monkeypatch.setitem(sys.modules,'server',types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=client.server)))
    monkeypatch.setitem(sys.modules,'comfy_execution.graph',types.SimpleNamespace(ExecutionBlocker=type('Blocker',(),{})))
    class Load:
        def load_image(self,name): return S.tensor(S.Image.open(client.input_root/name).convert('RGB')),'mask'
    monkeypatch.setitem(sys.modules,'nodes',types.SimpleNamespace(LoadImage=Load))
    result=W.MangaWorkflowInput().load('폴더 프로젝트','','book','book','시작·재개',prompt=g,unique_id=source)
    assert result['result'][0].shape[0]==1 and len(result['result'])==6
    ticket=result['ui']['manga_workflow'][0]
    assert ticket['prompt_id']==ident and ticket['relative_path']=='1.png'
    assert result['result'][3].endswith('/result') and result['result'][4].endswith('/ocr')
    assert not client.server.prompt_queue.pending


def test_unknown_programming_error_pauses_canvas_sequence(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path)
    ident,result=begin(engine,client,inputs,folder)
    client.server.prompt_queue.histories[ident]={'outputs':{},'status':{'status_str':'error','messages':[
        ('execution_error',{'exception_type':'TypeError','exception_message':'unexpected argument','node_type':'MangaOCRAdaptive'})]}}
    resolved=engine.resolve(folder,result['ticket']['run_id'],ident,client)
    assert not resolved['continue'] and resolved['report']['status']=='paused'


def test_native_interruption_stops_sequence_and_preserves_attempt(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path)
    ident,result=begin(engine,client,inputs,folder)
    client.server.prompt_queue.histories[ident]={'outputs':{},'status':{'status_str':'error','completed':False,
        'messages':[('execution_interrupted',{'prompt_id':ident})]}}
    report=engine.resolve(folder,result['ticket']['run_id'],ident,client)
    assert not report['continue'] and report['report']['status']=='paused'
    assert report['report']['counts']=={'failed':1,'pending':1}
    assert len(list(folder.glob('pages/*/attempt-*/state.json')))==1
