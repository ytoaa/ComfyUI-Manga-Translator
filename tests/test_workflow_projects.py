"""Workflow controls and native queue adapter; inference responses are doubles."""
import asyncio
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
import uuid

import pytest
from tests.test_project_runner import P,FakeComfy,graph,make_page

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('workflow_project_tests'); package.__path__=[str(ROOT)]
sys.modules[package.__name__]=package
sys.modules[package.__name__+'.tools.run_project']=P
spec=importlib.util.spec_from_file_location(package.__name__+'.workflow_project',ROOT/'workflow_project.py')
W=importlib.util.module_from_spec(spec);sys.modules[spec.name]=W;spec.loader.exec_module(W)


def source(g): return next(k for k,n in g.items() if n['class_type']=='MangaWorkflowInput')


def book(tmp_path):
    root=tmp_path/'input'
    make_page(root/'book/2.png');make_page(root/'book/10.png')
    return root,root/'book',W.WorkflowProjects.destination(tmp_path/'output','1권')


def wait(controller):
    controller.worker.join(10)
    assert not controller.worker.is_alive()


def test_same_08_has_image_folder_controls_and_native_report():
    g=graph();ident=source(g)
    assert g[ident]['inputs']['input_mode']=='이미지 한 장'
    assert any(n['class_type']=='PreviewAny' and n['inputs'].get('source')==[ident,2] for n in g.values())
    assert not (ROOT/'web/projects.js').exists()
    frontend=(ROOT/'web/folder_upload.js').read_text(encoding='utf-8')
    assert 'webkitdirectory' in frontend and '/upload/image' in frontend
    assert 'form.append("type", "input")' in frontend and 'input_folder' in frontend
    assert 'button.serialize = false' in frontend and 'options || {}), serialize: false' in frontend
    assert "WEB_DIRECTORY = './web'" in (ROOT/'__init__.py').read_text(encoding='utf-8')


def test_controller_saves_current_graph_and_resumes_without_repeating(tmp_path):
    _,inputs,folder=book(tmp_path);c=W.WorkflowProjects();client=FakeComfy()
    configured=graph();configured[source(configured)]['inputs']['input_mode']='폴더 프로젝트'
    c.start(folder,inputs,configured,client);wait(c)
    assert c.snapshot(folder)['counts']=={'completed':2}
    assert c.snapshot(folder)['export']
    edited=graph();edited[source(edited)]['inputs']['project_name']='changed but resume uses saved graph'
    c.start(folder,inputs,edited,client);wait(c)
    assert len(client.submissions)==2
    assert P.read_json(folder/'workflow.api.json')==configured


def test_pause_is_after_current_page_and_does_not_cancel_foreign_jobs(tmp_path):
    _,inputs,folder=book(tmp_path);c=W.WorkflowProjects()
    entered,release=threading.Event(),threading.Event()
    class Slow(FakeComfy):
        def submit(self,*args):
            entered.set();assert release.wait(5);return super().submit(*args)
    client=Slow();client.foreign=[[0,'unrelated',{}, {},[]]]
    c.start(folder,inputs,graph(),client);assert entered.wait(5)
    assert c.stop(folder)['status']=='stopping'
    release.set();wait(c)
    assert c.snapshot(folder)['counts']=={'completed':1,'pending':1}
    assert client.foreign[0][1]=='unrelated'
    c.start(folder,inputs,graph(),client);wait(c)
    assert len(client.submissions)==2


def test_page_failure_continues_and_retry_only_adds_failed_attempt(tmp_path):
    _,inputs,folder=book(tmp_path);c=W.WorkflowProjects();client=FakeComfy(['ocr_error','success','success'])
    c.start(folder,inputs,graph(),client);wait(c)
    assert c.snapshot(folder)['counts']=={'failed':1,'completed':1}
    assert c.snapshot(folder)['status']=='needs_review'
    c.start(folder,inputs,graph(),client,retry_failed=True);wait(c)
    assert c.snapshot(folder)['counts']=={'completed':2}
    assert len(client.submissions)==3


def test_resource_error_pauses_without_submitting_next_page(tmp_path):
    _,inputs,folder=book(tmp_path);c=W.WorkflowProjects();client=FakeComfy(['oom','success'])
    c.start(folder,inputs,graph(),client);wait(c)
    assert c.snapshot(folder)['status']=='paused'
    assert len(client.submissions)==1
    assert c.snapshot(folder)['counts']=={'failed':1,'pending':1}


def test_progress_is_published_and_restart_is_recognized(tmp_path):
    _,inputs,folder=book(tmp_path);c=W.WorkflowProjects();reports=[]
    c.start(folder,inputs,graph(),FakeComfy(),publish=lambda value:reports.append(deepcopy(value)));wait(c)
    assert reports[-1]['status']=='completed' and reports[-1]['counts']=={'completed':2}
    assert any(r['counts'].get('running') or r['counts'].get('queued') for r in reports)
    c._control(folder,'running','before restart')
    assert W.WorkflowProjects().snapshot(folder)['status']=='paused'


@pytest.mark.parametrize('relative',['','../outside','/tmp','book/../../tmp','book\\x','manga_translator'])
def test_project_input_stays_out_of_internal_uploads(tmp_path,relative):
    root,_,_=book(tmp_path);(root/'manga_translator').mkdir()
    with pytest.raises(P.ProjectError):W.WorkflowProjects.inputs(root,relative)


@pytest.mark.parametrize('name',['','../book','a/b','a\\b','.hidden',' name '])
def test_project_names_are_not_paths(tmp_path,name):
    with pytest.raises(P.ProjectError):W.WorkflowProjects.destination(tmp_path,name)


def test_only_one_project_worker_and_repeated_start_does_not_duplicate(tmp_path):
    _,inputs,folder=book(tmp_path);c=W.WorkflowProjects();entered,release=threading.Event(),threading.Event()
    class Slow(FakeComfy):
        def object_info(self):entered.set();assert release.wait(5);return super().object_info()
    client=Slow();c.start(folder,inputs,graph(),client);assert entered.wait(5)
    try:
        assert c.start(folder,inputs,graph(),client)['running']
        with pytest.raises(P.ProjectError):c.start(folder.with_name('other'),inputs,graph(),client)
    finally:release.set();wait(c)
    assert len(client.submissions)==2


def test_single_page_and_marked_page_use_native_loader_without_dispatch(monkeypatch):
    import torch
    calls=[];pixels,mask=torch.zeros(1,4,5,3),torch.zeros(1,4,5)
    class Load:
        def load_image(self,name):calls.append(name);return pixels,mask
        @classmethod
        def IS_CHANGED(cls,name):return 'native-hash:'+name
    monkeypatch.setitem(sys.modules,'nodes',types.SimpleNamespace(LoadImage=Load))
    args={'input_mode':'이미지 한 장','image':'page.png','input_folder':'','project_name':'','action':'시작·재개'}
    assert W.MangaWorkflowInput().load(**args)[:2]==(pixels,mask)
    args['input_mode']='폴더 프로젝트'
    marker={'source_node':'7','project':'a'*32,'page':'p'+'b'*20,'attempt':1}
    result=W.MangaWorkflowInput().load(**args,unique_id='7',extra_pnginfo={'manga_project_page':marker})
    assert result[:2]==(pixels,mask) and json.loads(result[2])['status']=='page_running'
    assert calls==['page.png','page.png']
    with pytest.raises(P.ProjectError):W.MangaWorkflowInput().load(**args,unique_id='8',extra_pnginfo={'manga_project_page':marker})
    assert W.MangaWorkflowInput.IS_CHANGED('이미지 한 장','page.png')=='native-hash:page.png'


class QueueDouble:
    def __init__(self):self.pending=[];self.history={};self.lock=threading.Lock()
    def get_current_queue(self):
        with self.lock:return [],deepcopy(self.pending)
    def get_history(self,ident):
        with self.lock:return {ident:deepcopy(self.history[ident])} if ident in self.history else {}


@contextmanager
def native_client(tmp_path,monkeypatch,status=200):
    from aiohttp import web
    loop=asyncio.new_event_loop();thread=threading.Thread(target=loop.run_forever);thread.start()
    queue=QueueDouble();calls=[];routes=web.RouteTableDef()
    @routes.post('/prompt')
    async def submit(request):
        payload=await request.json();calls.append(deepcopy(payload))
        if status!=200:return web.json_response({'error':'invalid workflow'},status=status)
        with queue.lock:queue.pending.append((0,payload['prompt_id'],payload['prompt'],payload['extra_data'],[],{}))
        return web.json_response({'prompt_id':payload['prompt_id'],'number':0,'node_errors':{}})
    server=types.SimpleNamespace(loop=loop,routes=routes,prompt_queue=queue)
    monkeypatch.setitem(sys.modules,'nodes',types.SimpleNamespace(NODE_CLASS_MAPPINGS={n['class_type']:object for n in graph().values()}))
    client=W.NativeComfyClient(server,tmp_path/'input',tmp_path/'output','1',{'workflow':{'nodes':[]}},'browser-client')
    try:yield client,queue,calls
    finally:loop.call_soon_threadsafe(loop.stop);thread.join();loop.close()


def test_native_adapter_calls_installed_handler_and_preserves_job_identity(tmp_path,monkeypatch):
    with native_client(tmp_path,monkeypatch) as (client,queue,calls):
        ident=str(uuid.uuid4());token={'project':'book','page':'p1','attempt':1}
        response=client.submit(graph(),ident,token)
        assert response['prompt_id']==ident and calls[0]['client_id']=='browser-client'
        assert calls[0]['extra_data']['manga_project']==token
        assert calls[0]['extra_data']['extra_pnginfo']['manga_project_page']=={'source_node':'1',**token}
        assert calls[0]['extra_data']['extra_pnginfo']['workflow']=={'nodes':[]}
        assert client.queue()['queue_pending'][0][1]==ident
        assert isinstance(client.queue()['queue_pending'][0],list)
        assert 'MangaWorkflowInput' in client.object_info()
        assert client.history(ident) is None
        queue.history[ident]={'outputs':{},'status':{'completed':True,'status_str':'success'}}
        assert client.history(ident)['status']['completed'] is True


def test_native_rejection_cannot_look_accepted(tmp_path,monkeypatch):
    with native_client(tmp_path,monkeypatch,status=400) as (client,queue,_):
        with pytest.raises(P.Rejected):client.submit(graph(),str(uuid.uuid4()),{'project':'book','page':'p1','attempt':1})
        assert not queue.pending


def test_native_file_transfer_is_local_bounded_and_does_not_overwrite(tmp_path,monkeypatch):
    with native_client(tmp_path,monkeypatch) as (client,_,__):
        uploaded=client.upload(b'image','page.png','manga_translator/book')
        descriptor={'type':'input','filename':uploaded['name'],'subfolder':uploaded['subfolder']}
        assert client.download(descriptor)==b'image'
        with pytest.raises(P.ProtocolError):client.upload(b'changed','page.png','manga_translator/book')
        assert client.download(descriptor)==b'image'
        for descriptor in ({'type':'input','filename':'../outside','subfolder':''},
                           {'type':'output','filename':'x','subfolder':'../../'},
                           {'type':'temp','filename':'x','subfolder':''}):
            with pytest.raises(P.ProtocolError):client.download(descriptor)


def test_folder_controls_return_blocker_and_native_status(monkeypatch,tmp_path):
    class Blocker:
        def __init__(self,message):self.message=message
    package=types.ModuleType('comfy_execution');package.__path__=[]
    monkeypatch.setitem(sys.modules,'comfy_execution',package)
    monkeypatch.setitem(sys.modules,'comfy_execution.graph',types.SimpleNamespace(ExecutionBlocker=Blocker))
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path/'output')))
    monkeypatch.setitem(sys.modules,'server',types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=object())))
    result=W.MangaWorkflowInput().load('폴더 프로젝트','','not needed for status','book','상태 확인')
    pixels,mask,report=result['result'][:3]
    assert isinstance(pixels,Blocker) and isinstance(mask,Blocker)
    assert json.loads(report)['status']=='ready'
    assert not W.PROJECTS.active


def test_native_interrupt_pauses_book_before_next_page(tmp_path):
    _,inputs,folder=book(tmp_path);c=W.WorkflowProjects();client=FakeComfy(['interrupted','success'])
    c.start(folder,inputs,graph(),client);wait(c)
    assert c.snapshot(folder)['status']=='paused'
    assert len(client.submissions)==1
    assert c.snapshot(folder)['counts']=={'failed':1,'pending':1}


def test_folder_validation_checks_project_folder_before_execution(tmp_path,monkeypatch):
    root,_,_=book(tmp_path)
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(
        get_input_directory=lambda:str(root),get_output_directory=lambda:str(tmp_path/'output'),
        exists_annotated_filepath=lambda name:(root/name).is_file()))
    validator=W.MangaWorkflowInput.VALIDATE_INPUTS
    assert validator('폴더 프로젝트','not-used.png','book','book','시작·재개') is True
    assert validator('폴더 프로젝트','','missing','book','상태 확인') is True
    assert isinstance(validator('폴더 프로젝트','','missing','book','시작·재개'),str)
    assert isinstance(validator('폴더 프로젝트','','book','../book','상태 확인'),str)
    assert isinstance(validator('이미지 한 장','','book','book','시작·재개'),str)


def test_cancelled_dispatch_never_submits_a_page(tmp_path,monkeypatch):
    with native_client(tmp_path,monkeypatch) as (client,queue,_):
        parent=str(uuid.uuid4());client.parent_prompt_id=parent
        queue.history[parent]={'status':{'status_str':'error','completed':False}}
        with pytest.raises(P.Paused,match='시작 작업'):client.wait_for_parent_success()
        assert not queue.pending
        queue.history[parent]['status']={'status_str':'success','completed':True}
        client.wait_for_parent_success()


def test_status_during_start_is_not_misread_as_server_restart(tmp_path,monkeypatch):
    _,inputs,folder=book(tmp_path);c=W.WorkflowProjects()
    writing,release_write,executing,release_work=map(lambda _:threading.Event(),range(4))
    original=c._control
    def control(path,status,message):
        original(path,status,message)
        if status=='running':writing.set();assert release_write.wait(5)
    monkeypatch.setattr(c,'_control',control)
    class Slow(FakeComfy):
        def object_info(self):executing.set();assert release_work.wait(5);return super().object_info()
    caller=threading.Thread(target=lambda:c.start(folder,inputs,graph(),Slow()))
    caller.start();assert writing.wait(5)
    snapshots=[];observed=threading.Event()
    def observe():snapshots.append(c.snapshot(folder));observed.set()
    reader=threading.Thread(target=observe);reader.start()
    try:
        assert not observed.wait(.05)
        release_write.set();assert executing.wait(5);assert observed.wait(5)
        assert snapshots[0]['status']=='running' and snapshots[0]['running']
    finally:
        release_write.set();release_work.set();caller.join(5);reader.join(5);wait(c)
