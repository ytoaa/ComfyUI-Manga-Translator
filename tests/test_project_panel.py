"""ComfyUI-facing project controls; model and core API responses are doubles."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import types

from PIL import Image
import pytest
from tests.test_project_runner import P, FakeComfy, graph, make_page

ROOT = Path(__file__).resolve().parents[1]
namespace = types.ModuleType('manga_panel_tests'); namespace.__path__ = [str(ROOT)]
sys.modules[namespace.__name__] = namespace
sys.modules[namespace.__name__+'.tools.run_project'] = P
spec = importlib.util.spec_from_file_location(namespace.__name__+'.project_ui', ROOT/'project_ui.py')
UI = importlib.util.module_from_spec(spec); sys.modules[spec.name] = UI; spec.loader.exec_module(UI)


def panel(tmp_path, client=None):
    inputs, outputs = tmp_path/'input',tmp_path/'output'
    make_page(inputs/'book'/'2.png'); make_page(inputs/'book'/'10.png')
    return UI.ProjectPanel(inputs,outputs,lambda:client or FakeComfy())


def wait(service):
    service.worker.join(8)
    assert not service.worker.is_alive()


def test_panel_uses_saved_graph_and_resume_without_resubmission(tmp_path):
    client = FakeComfy(); service = panel(tmp_path,client)
    configured = graph(); configured['1']['_meta'] = {'title':'configured in ComfyUI'}
    ident = service.create('book','1권',configured)
    assert service.snapshot(ident)['status'] == 'ready'
    service.start(ident); wait(service)
    report = service.snapshot(ident)
    assert report['status'] == 'completed'
    assert [p['relative_path'] for p in report['pages']] == ['2.png','10.png']
    assert report['counts'] == {'completed':2}
    assert all('result.png' in p['artifacts'] for p in report['pages'])
    assert report['export']
    service.start(ident); wait(service)
    assert len(client.submissions) == 2
    assert P.read_json(service.directory(ident)/'workflow.api.json') == configured


def test_pause_finishes_owned_page_and_resume_skips_it(tmp_path):
    entered,release = threading.Event(),threading.Event()
    class Slow(FakeComfy):
        def submit(self,*args):
            entered.set(); assert release.wait(5)
            return super().submit(*args)
    client = Slow(); service = panel(tmp_path,client)
    ident = service.create('book','책',graph())
    service.start(ident); assert entered.wait(5)
    assert service.stop(ident)['status'] == 'stopping'
    release.set(); wait(service)
    report = service.snapshot(ident)
    assert report['status'] == 'paused'
    assert report['counts'] == {'completed':1,'pending':1}
    service.start(ident); wait(service)
    assert len(client.submissions) == 2
    assert service.snapshot(ident)['status'] == 'completed'


def test_only_one_project_active(tmp_path):
    entered,release = threading.Event(),threading.Event()
    class Slow(FakeComfy):
        def object_info(self):
            entered.set(); assert release.wait(5); return super().object_info()
    service = panel(tmp_path,Slow())
    first = service.create('book','책1',graph()); second = service.create('book','책2',graph())
    service.start(first); assert entered.wait(5)
    try:
        with pytest.raises(P.ProjectError,match='진행 중'): service.start(second)
    finally:
        release.set(); wait(service)


def test_failed_pages_can_be_retried_without_repeating_completed(tmp_path):
    client = FakeComfy(['ocr_error','success','success']); service = panel(tmp_path,client)
    ident = service.create('book','책',graph()); service.start(ident); wait(service)
    assert service.snapshot(ident)['status'] == 'review'
    service.start(ident,retry_failed=True); wait(service)
    assert service.snapshot(ident)['counts'] == {'completed':2}
    assert len(client.submissions) == 3


@pytest.mark.parametrize('relative',['../output','/tmp','book/../../../tmp','book\\x'])
def test_folder_paths_stay_in_comfy_input(tmp_path,relative):
    service = panel(tmp_path)
    with pytest.raises(P.ProjectError): service.browse(relative)


def test_browse_orders_and_rejects_outside_symlink(tmp_path):
    service = panel(tmp_path)
    (service.inputs/'10').mkdir(); (service.inputs/'2').mkdir()
    (service.inputs/'outside').symlink_to(tmp_path,target_is_directory=True)
    listing = service.browse()
    assert listing['path'] == ''
    assert [p['name'] for p in listing['folders']] == ['2','10','book']
    with pytest.raises(P.ProjectError): service.browse('outside')


def test_server_restart_marks_active_project_paused(tmp_path):
    service = panel(tmp_path)
    ident = service.create('book','책',graph())
    service._metadata(ident,status='running')
    assert service.snapshot(ident)['status'] == 'paused'
    assert service.listing()[0]['name'] == '책'


def test_artifact_path_validation(tmp_path):
    service = panel(tmp_path)
    ident = service.create('book','책',graph()); service.start(ident); wait(service)
    page = service.snapshot(ident)['pages'][0]
    assert service.artifact(ident,page['id'],str(page['attempt']),'result.png').is_file()
    for name in ('../../panel.json','workflow.api.json','result.png/..'):
        with pytest.raises(P.ProjectError): service.artifact(ident,page['id'],'1',name)
    with pytest.raises(P.ProjectError): service.directory('../')


def test_empty_folder_pauses_without_queueing(tmp_path):
    client = FakeComfy(); service = panel(tmp_path,client)
    (service.inputs/'empty').mkdir()
    ident = service.create('empty','빈 폴더',graph()); service.start(ident); wait(service)
    assert service.snapshot(ident)['status'] == 'paused'
    assert not client.submissions


def test_real_routes_upload_start_status_stop_validation(tmp_path,monkeypatch):
    from aiohttp import web, FormData
    from aiohttp.test_utils import TestClient,TestServer
    service = panel(tmp_path)
    fake_server = types.SimpleNamespace(routes=web.RouteTableDef(),address='127.0.0.1',port=8188)
    monkeypatch.setitem(sys.modules,'server',types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=fake_server)))
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_input_directory=lambda:str(service.inputs),get_output_directory=lambda:str(service.root.parents[1])))
    monkeypatch.setattr(UI,'ComfyClient',lambda base:FakeComfy())
    UI.register_routes()
    async def exercise():
        application = web.Application(); application.add_routes(fake_server.routes)
        async with TestClient(TestServer(application)) as client:
            response = await client.get('/manga/projects/folders'); assert response.status == 200
            response = await client.post('/manga/projects/import',headers={'Origin':'https://evil.test'})
            assert response.status == 403
            response = await client.post('/manga/projects/import'); imported = await response.json()
            ident = imported['input'].split('/')[-1]
            data = FormData(); data.add_field('image',(service.inputs/'book/2.png').read_bytes(),filename='2.png')
            response = await client.post(f'/manga/projects/import/{ident}?path=chapter/2.png',data=data)
            assert response.status == 200
            assert (service.inputs/imported['input']/'chapter/2.png').is_file()
            duplicate = FormData(); duplicate.add_field('image',b'changed',filename='2.png')
            response = await client.post(f'/manga/projects/import/{ident}?path=chapter/2.png',data=duplicate)
            assert response.status == 400
            assert (service.inputs/imported['input']/'chapter/2.png').read_bytes() == (service.inputs/'book/2.png').read_bytes()
            response = await client.post(f'/manga/projects/import/{ident}?path=../2.png')
            assert response.status == 400
            response = await client.post('/manga/projects',json={'input':imported['input'],'name':'업로드 책','graph':graph()})
            assert response.status == 200; project = (await response.json())['id']
            response = await client.post(f'/manga/projects/{project}/start',json={}); assert response.status == 200
            for _ in range(100):
                response = await client.get(f'/manga/projects/{project}'); report = await response.json()
                if not report['running']: break
                await asyncio.sleep(.03)
            assert report['counts'] == {'completed':1},report
            page = report['pages'][0]
            response = await client.get(f'/manga/projects/{project}/file/{page["id"]}/1/result.png')
            assert response.status == 200 and response.content_type == 'image/png'
            response = await client.post(f'/manga/projects/{project}/stop'); assert response.status == 400
            response = await client.post(f'/manga/projects/{project}/start',json={'retry_failed':'yes'})
            assert response.status == 400
    asyncio.run(exercise())


def test_corrupt_project_record_does_not_hide_other_projects(tmp_path):
    service = panel(tmp_path)
    healthy = service.create('book','정상 책',graph())
    damaged = service.create('book','손상된 기록',graph())
    (service.directory(damaged)/'panel.json').write_text('{broken')
    rows = {r['id']:r for r in service.listing()}
    assert rows[healthy]['name'] == '정상 책'
    assert rows[damaged]['status'] == 'paused'
    with pytest.raises(ValueError): service.snapshot(damaged)


def test_manual_graph_does_not_run_over_a_folder(tmp_path):
    client = FakeComfy(); service = panel(tmp_path,client)
    manual = P.read_json(ROOT/'lettering/example_workflows/09-manual-regions-integrated-cleanup-lettering.api.json')
    with pytest.raises(P.ProjectError): service.create('book','수동 프레임',manual)
    assert not client.submissions
    assert not service.listing()


@pytest.mark.parametrize('relative',['','manga_translator'])
def test_internal_uploads_cannot_feed_back_into_project(tmp_path,relative):
    service = panel(tmp_path)
    (service.inputs/'manga_translator').mkdir()
    with pytest.raises(P.ProjectError,match='하위 폴더'):
        service.create(relative,'원본',graph())
    assert not service.listing()
