"""Folder orchestration and interruption contracts; API/model responses are doubles."""
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
import threading
from urllib import parse

from PIL import Image, ImageDraw
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project_runner_tests', ROOT/'tools/run_project.py')
P = importlib.util.module_from_spec(spec); sys.modules[spec.name] = P; spec.loader.exec_module(P)


def graph(): return P.read_json(P.DEFAULT_WORKFLOW)


def make_page(path, size=(140, 90), blank=False, mode='RGB'):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new(mode, size, (255,255,255,0) if mode == 'RGBA' else 'white')
    if not blank: ImageDraw.Draw(image).rectangle((25,20,65,35), fill='black')
    image.save(path)
    return image


class FakeComfy:
    """Tests scheduling and results, NOT detector/OCR/image-edit accuracy."""
    base = 'http://comfy.test'
    def __init__(self, modes=()):
        self.modes, self.uploads, self.jobs = deque(modes), {}, {}
        self.submissions, self.downloads, self.drop_reply = [], 0, False
        self.available = {n['class_type']:{} for n in graph().values()}
        self.download_error = False
        self.foreign = []
    def object_info(self): return self.available
    def upload(self, data, name, subfolder):
        self.uploads[subfolder+'/'+name] = data
        return {'name':name,'subfolder':subfolder,'type':'input'}
    def submit(self, prompt, ident, token):
        bindings = P.workflow_bindings(prompt)
        encoded = self.uploads[prompt[bindings['load']]['inputs']['image']]
        size = list(Image.open(BytesIO(encoded)).size)
        mode = self.modes.popleft() if self.modes else 'success'
        self.submissions.append((ident, deepcopy(prompt), deepcopy(token)))
        if mode == 'rejected': raise P.Rejected('Invalid workflow')
        empty = mode in ('no_text','excluded')
        source = {'image_width':size[0],'image_height':size[1], 'regions':[] if empty else [
            {'id':'r1','kind':'text','bbox':[10,10,900,900],'source':'SAMPLE'}]}
        if empty: source.update(page_status='no_text_detected',ocr_skipped=True)
        if mode == 'excluded': source.update(needs_review=True,no_text_reason='excluded_onomatopoeia_present')
        target = deepcopy(source)
        if empty: target['translation_skipped'] = True
        else: target['regions'][0]['target'] = '번역문'
        if mode == 'mismatched_ids': target['regions'][0]['id'] = 'different'
        if mode == 'changed_geometry': target['regions'][0]['bbox'] = [0,0,1000,1000]
        if mode == 'duplicate_ids': source['regions'].append(deepcopy(source['regions'][0]))
        if mode == 'unhashable_id': source['regions'][0]['id'] = ['invalid']
        prefix = prompt[bindings['final']]['inputs']['filename_prefix'].rsplit('/',1)[0]
        descriptor = {'filename':'result_00001_.png','subfolder':prefix,'type':'output'}
        if mode=='windows_subfolder': descriptor['subfolder']=prefix.replace('/','\\')
        output = {bindings['source_preview']:{'text':[json.dumps(source)]},
                  bindings['target_preview']:{'text':[json.dumps(target)]}, bindings['final']:{'images':[descriptor]}}
        for key, value, basename in (('source',source,'ocr'),('target',target,'translation')):
            output[bindings[key]] = {'text':[json.dumps(value)], 'manga_review_files':[
                {'filename':basename+'_00001.json','subfolder':prefix,'type':'output'}]}
        status = {'status_str':'success','completed':True,'messages':[]}
        if mode in ('ocr_error','lettering_error','oom','interrupted','disk_full','missing_model'):
            kind = {'ocr_error':'HayaiOutputError','lettering_error':'ValueError',
                    'oom':'OutOfMemoryError','interrupted':'InterruptProcessingException',
                    'disk_full':'OSError','missing_model':'FileNotFoundError'}[mode]
            status = {'status_str':'error','completed':False,'messages':[['execution_error',
                {'exception_type':kind,'node_type':'MangaOCRAdaptive' if mode=='ocr_error' else 'MangaLetterApply',
                 'exception_message':'no safe fit' if mode=='lettering_error' else
                                     'No space left on device' if mode=='disk_full' else 'simulated failure'}]]}
            output.pop(bindings['final'])
            output.pop(bindings['source_preview']); output.pop(bindings['target_preview'])
            if mode=='ocr_error':
                output.pop(bindings['source']); output.pop(bindings['target'])
        if mode == 'missing_final': output.pop(bindings['final'])
        if mode == 'bad_completed_flag': status['completed']='false'
        if mode == 'incomplete_success': status['completed']=False
        if mode == 'bad_json': output[bindings['target']]['text'] = ['{bad']
        if mode == 'wrong_review_owner': output[bindings['source']]['manga_review_files'][0]['subfolder'] = 'other/page'
        if mode == 'wrong_owner': descriptor['subfolder'] = 'another/project'
        if mode == 'wrong_size':
            data = BytesIO(); Image.new('RGB',(size[0]+1,size[1])).save(data,format='PNG'); encoded = data.getvalue()
        if mode == 'bad_image': encoded = b'not an image'
        if mode == 'mask_image':
            data=BytesIO(); Image.new('L',size,255).save(data,format='PNG'); encoded=data.getvalue()
        if mode == 'changed_empty':
            source.update(regions=[],page_status='no_text_detected',ocr_skipped=True)
            target = {**source,'translation_skipped':True}
            output[bindings['source_preview']]['text'] = [json.dumps(source)]
            output[bindings['target_preview']]['text'] = [json.dumps(target)]
            output[bindings['source']]['text'] = [json.dumps(source)]
            output[bindings['target']]['text'] = [json.dumps(target)]
            data = BytesIO(); Image.new('RGB',size,'red').save(data,format='PNG'); encoded = data.getvalue()
        self.jobs[ident] = {'history':{'outputs':output,'status':status},'bytes':encoded,
                           'descriptor':descriptor,'mode':mode,'token':token,'graph':prompt}
        if self.drop_reply:
            self.drop_reply = False
            raise OSError('connection dropped AFTER accepting prompt')
        return {'prompt_id':ident,'number':0,'node_errors':{}}
    def history(self, ident):
        job = self.jobs.get(ident)
        return None if not job or job['mode'] in ('running','lost_history') else deepcopy(job['history'])
    def queue(self):
        return {'queue_running':[[0,ident,job['graph'],{'manga_project':job['token']},[]]
                for ident,job in self.jobs.items() if job['mode']=='running'], 'queue_pending':self.foreign}
    def download(self, descriptor):
        self.downloads += 1
        if self.download_error:
            self.download_error = False; raise OSError('download connection dropped')
        if descriptor.get('type') == 'input':
            return self.uploads[descriptor['subfolder']+'/'+descriptor['filename']]
        return next(job['bytes'] for job in self.jobs.values() if job['descriptor']==descriptor)


class Clock:
    value = 0
    def now(self): return self.value
    def sleep(self, amount): self.value += amount


def project(tmp_path, client=None, **kwargs):
    clock = Clock()
    return P.Project(tmp_path/'input',tmp_path/'project',graph(),client or FakeComfy(),
                     clock=clock.now,sleep=clock.sleep,page_timeout=3,**kwargs)


def test_natural_order_recursive_duplicate_basenames_and_identical_pages_are_preserved(tmp_path):
    for name in ('10.png','2.png','1.png','a/1.png','b/1.png'):
        make_page(tmp_path/'input'/name)
    client = FakeComfy(); runner = project(tmp_path,client)
    report = runner.run()
    assert report['counts'] == {'completed':5}
    assert [p['relative_path'] for p in report['pages']] == ['1.png','2.png','10.png','a/1.png','b/1.png']
    assert len({p['id'] for p in report['pages']}) == len(client.submissions) == 5
    prefixes = [g[P.workflow_bindings(g)['final']]['inputs']['filename_prefix'] for _,g,_ in client.submissions]
    assert len(set(prefixes)) == 5
    for page in report['pages']: assert (runner.destination/page['result']).is_file()
    assert runner.run()['counts'] == {'completed':5}
    assert len(client.submissions) == 5


def test_corrupt_page_and_model_failures_do_not_stop_later_pages_or_publish_partial_success(tmp_path):
    for name in ('1.png','2.png','3.png','4.png'): make_page(tmp_path/'input'/name)
    (tmp_path/'input/2.png').write_bytes(b'corrupt')
    client = FakeComfy(('ocr_error','lettering_error','success'))
    runner = project(tmp_path,client); report = runner.run()
    assert report['counts'] == {'failed':3,'completed':1}
    assert len(client.submissions) == 3
    assert all('result' not in row for row in report['pages'][:3])
    assert not list((runner.destination/'pages'/report['pages'][0]['id']).glob('*/source.json'))
    assert list((runner.destination/'pages'/report['pages'][2]['id']).glob('*/source.json'))
    assert not list((runner.destination/'pages'/report['pages'][0]['id']).glob('*/result.png'))


def test_no_text_is_not_called_blank_without_uniform_pixel_evidence(tmp_path):
    make_page(tmp_path/'input/1.png',blank=True)
    make_page(tmp_path/'input/2.png')
    make_page(tmp_path/'input/3.png',blank=True)
    runner = project(tmp_path,FakeComfy(('no_text','no_text','excluded')))
    report = runner.run()
    assert [r['status'] for r in report['pages']] == ['unchanged_blank','needs_review','needs_review']
    assert report['pages'][1]['reason'] == 'no_text_detected_not_verified_blank'
    assert report['pages'][2]['reason'] == 'excluded_onomatopoeia_present'


def test_lost_submission_reply_resumes_same_prompt_without_duplicate_gpu_jobs(tmp_path):
    make_page(tmp_path/'input/1.png'); make_page(tmp_path/'input/2.png')
    client = FakeComfy(); client.drop_reply = True
    runner = project(tmp_path,client)
    with pytest.raises(P.Paused,match='reply was lost'): runner.run()
    assert len(client.submissions) == 1
    original_id = client.submissions[0][0]
    assert runner.state(runner.pages[0])['prompt_id'] == original_id
    report = runner.run()
    assert report['counts'] == {'completed':2} and len(client.submissions) == 2
    assert runner.state(runner.pages[0])['prompt_id'] == original_id


@pytest.mark.parametrize('failure',['running','lost_history','oom','rejected','disk_full','missing_model'])
def test_uncertain_running_resource_or_configuration_failure_stops_new_submissions(tmp_path,failure):
    for name in ('1.png','2.png'): make_page(tmp_path/'input'/name)
    client = FakeComfy((failure,'success'))
    client.foreign = [[9,'foreign-prompt',{}, {'manga_project':{'project':'someone-else'}},[]]]
    runner = project(tmp_path,client)
    with pytest.raises((P.Paused,P.Rejected)): runner.run()
    assert len(client.submissions) == 1
    assert client.foreign[0][1] == 'foreign-prompt'
    assert P.read_json(runner.destination/'summary.json')['halted']
    if failure == 'running':
        ident = client.submissions[0][0]; client.jobs[ident]['mode'] = 'success'
        assert runner.run()['counts'] == {'completed':2}
        assert len(client.submissions) == 2


@pytest.mark.parametrize('mode',['missing_final','bad_json','wrong_owner','wrong_size','bad_image',
                                'mismatched_ids','changed_geometry','duplicate_ids','changed_empty','wrong_review_owner',
                                'unhashable_id','mask_image','bad_completed_flag','incomplete_success'])
def test_partial_stale_or_malformed_artifacts_never_become_completed_pages(tmp_path,mode):
    make_page(tmp_path/'input/1.png'); make_page(tmp_path/'input/2.png')
    client = FakeComfy((mode,'success')); runner = project(tmp_path,client)
    with pytest.raises(P.ProtocolError): runner.run()
    assert len(client.submissions) == 1
    assert runner.state(runner.pages[0])['status'] in ('collecting','queued')
    assert not list(runner.destination.glob('pages/*/*/result.png'))


def test_download_retry_recovers_same_job_without_rerunning_models(tmp_path):
    make_page(tmp_path/'input/1.png')
    client = FakeComfy(); client.download_error = True; runner = project(tmp_path,client)
    with pytest.raises(OSError): runner.run()
    assert runner.state(runner.pages[0])['status'] == 'collecting'
    assert runner.run()['counts'] == {'completed':1}
    assert len(client.submissions) == 1 and client.downloads == 2


def test_deleted_artifact_is_recovered_but_user_modified_result_is_preserved(tmp_path):
    make_page(tmp_path/'input/1.png'); client = FakeComfy(); runner = project(tmp_path,client)
    report = runner.run(); path = runner.destination/report['pages'][0]['result']
    path.unlink()
    assert runner.run()['counts'] == {'completed':1} and path.exists()
    path.write_bytes(b'user modification')
    assert runner.run()['counts'] == {'needs_review':1}
    assert path.read_bytes() == b'user modification' and len(client.submissions) == 1


def test_changed_source_gets_new_attempt_and_keeps_previous_results(tmp_path):
    source = tmp_path/'input/1.png'; make_page(source)
    client = FakeComfy(); runner = project(tmp_path,client)
    before = runner.run(); old = runner.destination/before['pages'][0]['result']; old_bytes = old.read_bytes()
    make_page(source,size=(160,110))
    after = runner.run(); new = runner.destination/after['pages'][0]['result']
    assert old != new and old.read_bytes() == old_bytes and Image.open(new).size == (160,110)
    assert len(client.submissions) == 2


def test_retry_failed_is_explicit_and_bounded(tmp_path):
    make_page(tmp_path/'input/1.png'); client = FakeComfy(('ocr_error','success'))
    runner = project(tmp_path,client)
    assert runner.run()['counts'] == runner.run()['counts'] == {'failed':1}
    assert len(client.submissions) == 1
    assert project(tmp_path,client,retry_failed=True).run()['counts'] == {'completed':1}
    assert len(client.submissions) == 2


def test_workflow_change_missing_nodes_and_parallel_project_lock_fail_before_submission(tmp_path):
    make_page(tmp_path/'input/1.png'); client = FakeComfy(); runner = project(tmp_path,client)
    runner.run(plan_only=True)
    changed = graph(); next(n for n in changed.values() if n['class_type']=='MangaLetterPlan')['inputs']['min_font'] = 9
    with pytest.raises(P.ProjectError,match='settings changed'):
        P.Project(runner.inputs,runner.destination,changed,client).run()
    with P.project_lock(runner.destination):
        with pytest.raises(P.ProjectError,match='already being run'): runner.run()
    client.available = {}
    with pytest.raises(P.ProjectError,match='missing required'): runner.run()
    assert not client.submissions


def test_missing_detector_gui_json_empty_folder_and_recursive_output_cannot_start_project(tmp_path):
    make_page(tmp_path/'input/1.png')
    with pytest.raises(P.ProjectError,match='outside'): P.Project(tmp_path/'input',tmp_path/'input/output',graph())
    manual = {i:n for i,n in graph().items() if n['class_type'] != 'MangaDetectorDetail'}
    with pytest.raises(P.ProjectError,match='MangaDetectorDetail'): P.Project(tmp_path/'input',tmp_path/'out',manual)
    with pytest.raises(P.ProjectError,match='API-format'): P.Project(tmp_path/'input',tmp_path/'out',{'nodes':[]})
    (tmp_path/'empty').mkdir()
    with pytest.raises(P.InputError,match='No supported'): P.scan_images(tmp_path/'empty')


def test_exif_grayscale_cmyk_transparency_and_heterogeneous_sizes_are_normalized(tmp_path):
    folder = tmp_path/'input'
    make_page(folder/'gray.png',size=(90,60),mode='L')
    alpha = make_page(folder/'alpha.png',size=(75,120),mode='RGBA')
    make_page(folder/'cmyk.jpg',size=(100,90),mode='CMYK')
    exif = Image.Exif(); exif[274] = 6
    Image.new('RGB',(80,130),'white').save(folder/'rotated.jpg',exif=exif)
    client = FakeComfy(); runner = project(tmp_path,client); report = runner.run()
    assert report['counts'] == {'completed':4}
    sizes = {}
    for row in report['pages']:
        state = runner.state(row); image = Image.open(runner._attempt_dir(state)/'input.png')
        assert image.mode == 'RGB'
        sizes[row['relative_path']] = image.size
        if row['relative_path'] == 'alpha.png': assert image.getpixel((0,0)) == (255,255,255)
    assert sizes['rotated.jpg'] == (130,80) and sizes['alpha.png'] == alpha.size


def test_multiframe_pixel_budget_high_bit_depth_symlink_and_changed_input_are_explicit_errors(tmp_path):
    folder = tmp_path/'input'; folder.mkdir()
    a,b = Image.new('RGB',(30,40),'white'),Image.new('RGB',(30,40),'black')
    a.save(folder/'animation.gif',save_all=True,append_images=[b])
    Image.new('I;16',(40,40)).save(folder/'depth.png')
    make_page(folder/'large.png',size=(201,201))
    outside = tmp_path/'outside.png'; make_page(outside)
    (folder/'linked.png').symlink_to(outside)
    client = FakeComfy(); runner = project(tmp_path,client,max_pixels=40_000)
    assert runner.run()['counts'] == {'failed':4} and not client.submissions
    sha = P.digest(outside.read_bytes()); make_page(outside,size=(120,80))
    with pytest.raises(P.InputError,match='changed after'): P.normalise_image(outside,sha,40_000)


@contextmanager
def local_api(fake):
    routes = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a): pass
        def reply(self,value,raw=False):
            encoded = value if raw else json.dumps(value).encode()
            self.send_response(200); self.send_header('Content-Length',str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
        def do_GET(self):
            route = parse.urlsplit(self.path); routes.append(('GET',route.path))
            if route.path=='/object_info': self.reply(fake.object_info())
            elif route.path=='/queue': self.reply(fake.queue())
            elif route.path.startswith('/history/'):
                ident = route.path.split('/')[-1]; history = fake.history(ident); self.reply({ident:history} if history else {})
            elif route.path=='/view': self.reply(fake.download({k:v[0] for k,v in parse.parse_qs(route.query).items()}),True)
            else: self.send_error(404)
        def do_POST(self):
            routes.append(('POST',self.path)); body = self.rfile.read(int(self.headers['Content-Length']))
            if self.path=='/upload/image':
                message = BytesParser(policy=policy.default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
                fields = {part.get_param('name',header='content-disposition'):part for part in message.iter_parts()}
                part = fields['image']; assert fields['type'].get_content()=='input'
                self.reply(fake.upload(part.get_payload(decode=True),part.get_filename(),fields['subfolder'].get_content()))
            elif self.path=='/prompt':
                payload = json.loads(body); self.reply(fake.submit(payload['prompt'],payload['prompt_id'],payload['extra_data']['manga_project']))
            else: self.send_error(404)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True); thread.start()
    try: yield 'http://127.0.0.1:'+str(server.server_port), routes
    finally: server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_real_http_multipart_prompt_history_and_view_contract(tmp_path):
    make_page(tmp_path/'input/1.png')
    fake = FakeComfy()
    with local_api(fake) as (url,routes):
        runner = project(tmp_path,P.ComfyClient(url))
        assert runner.run()['counts'] == {'completed':1}
        assert {('POST','/upload/image'),('POST','/prompt'),('GET','/view')} <= set(routes)
        assert not any(path in ('/interrupt','/free') or (method,path)==('POST','/queue') for method,path in routes)
    assert len(fake.submissions) == 1


def test_ordered_export_keeps_failed_page_gaps_and_previous_edition_after_insert(tmp_path):
    for name in ('1.png','2.png','10.png'): make_page(tmp_path/'input'/name)
    client = FakeComfy(('success','ocr_error','success'))
    runner = project(tmp_path,client); report = runner.run(export=True)
    edition = runner.destination/report['export']
    assert sorted(p.name for p in edition.glob('*.png')) == ['000001.png','000003.png']
    assert P.read_json(edition/'index.json')['missing_or_review_pages'] == [2]
    old = (edition/'000003.png').read_bytes()
    assert runner.run(export=True)['export'] == report['export']
    make_page(tmp_path/'input/3.png')
    after = runner.run(export=True)
    assert after['export'] != report['export'] and (edition/'000003.png').read_bytes() == old
    assert len(client.submissions) == 4


def test_stop_policy_and_corrupt_state_do_not_continue_or_overwrite_state(tmp_path):
    for name in ('1.png','2.png'): make_page(tmp_path/'input'/name)
    client = FakeComfy(('ocr_error','success')); runner = project(tmp_path,client,stop_on_error=True)
    with pytest.raises(P.Paused,match='policy'): runner.run()
    assert len(client.submissions) == 1
    path = next(runner.destination.glob('pages/*/*/state.json'))
    state = P.read_json(path); state['id'] = '../wrong'; path.write_bytes(P.json_bytes(state)); before=path.read_bytes()
    with pytest.raises(P.ProjectError,match='Invalid project page state'): runner.run()
    assert path.read_bytes() == before and len(client.submissions) == 1


def test_new_page_before_inflight_page_cannot_bypass_reconciliation(tmp_path):
    make_page(tmp_path/'input/2.png'); client = FakeComfy(('running',))
    runner = project(tmp_path,client)
    with pytest.raises(P.Paused,match='timed out'): runner.run()
    make_page(tmp_path/'input/1.png')
    with pytest.raises(P.Paused,match='timed out'): runner.run()
    assert len(client.submissions) == 1
    client.jobs[client.submissions[0][0]]['mode'] = 'success'
    assert runner.run()['counts'] == {'completed':2} and len(client.submissions) == 2


def test_removed_inflight_input_and_missing_normalized_copy_recover_without_resubmission(tmp_path):
    source = tmp_path/'input/1.png'; make_page(source)
    client = FakeComfy(); client.drop_reply = True; runner = project(tmp_path,client)
    with pytest.raises(P.Paused): runner.run()
    state = runner.state(runner.pages[0]); (runner._attempt_dir(state)/'input.png').unlink(); source.unlink()
    report = runner.run()
    assert report['counts'] == {} and report['removed_inputs'] == ['1.png']
    assert (runner._attempt_dir(state)/'result.png').is_file() and len(client.submissions)==1


def test_input_change_while_submission_reply_is_lost_preserves_both_versions(tmp_path):
    source=tmp_path/'input/1.png'; make_page(source)
    client=FakeComfy(); client.drop_reply=True; runner=project(tmp_path,client)
    with pytest.raises(P.Paused): runner.run()
    make_page(source,size=(150,115))
    assert runner.run()['counts']=={'completed':1} and len(client.submissions)==2
    assert len(list(runner.destination.glob('pages/*/*/result.png')))==2


def test_equivalent_json_key_order_can_resume_without_resubmission(tmp_path):
    make_page(tmp_path/'input/1.png'); client=FakeComfy(); runner=project(tmp_path,client); runner.run()
    reordered={key:{**node,'inputs':dict(reversed(list(node['inputs'].items())))}
               for key,node in reversed(list(graph().items()))}
    assert P.Project(runner.inputs,runner.destination,reordered,client).run()['counts']=={'completed':1}
    assert len(client.submissions)==1


def test_empty_or_corrupt_project_manifest_is_not_silently_reset(tmp_path):
    make_page(tmp_path/'input/1.png'); client=FakeComfy(); runner=project(tmp_path,client)
    runner.run(plan_only=True)
    path=runner.destination/'project.json'; path.write_text('{}')
    with pytest.raises(P.ProjectError,match='Invalid existing project'): runner.run()
    assert path.read_text()=='{}' and not client.submissions


def test_windows_server_output_separator_is_supported_without_changing_download_reference(tmp_path):
    make_page(tmp_path/'input/1.png'); client=FakeComfy(('windows_subfolder',))
    assert project(tmp_path,client).run()['counts']=={'completed':1}


@pytest.mark.parametrize('mode', ['ocr_error','no_text'])
def test_cli_partial_failure_is_visible_to_automation_as_nonzero_exit(tmp_path,monkeypatch,mode):
    make_page(tmp_path/'input/1.png'); client=FakeComfy((mode,))
    monkeypatch.setattr(P,'ComfyClient',lambda _:client)
    monkeypatch.setattr(sys,'argv',['run_project','--input',str(tmp_path/'input'),'--project',str(tmp_path/'project')])
    with pytest.raises(SystemExit) as outcome: P.main()
    assert outcome.value.code==3 and len(client.submissions)==1


def test_unsettled_checkpoint_cannot_be_followed_by_another_submission(tmp_path,monkeypatch):
    for name in ('1.png','2.png'): make_page(tmp_path/'input'/name)
    client=FakeComfy(); runner=project(tmp_path,client); save=runner._save
    def omit_terminal_checkpoint(state):
        if state['status'] in P.FINISHED | {'failed'}: return
        save(state)
    monkeypatch.setattr(runner,'_save',omit_terminal_checkpoint)
    with pytest.raises(P.Paused,match='durably settled'): runner.run()
    assert len(client.submissions)==1


def test_linked_subfolder_or_scan_permission_error_cannot_silently_omit_pages(tmp_path,monkeypatch):
    make_page(tmp_path/'outside/1.png'); (tmp_path/'input').mkdir()
    link=tmp_path/'input/linked'; link.symlink_to(tmp_path/'outside',target_is_directory=True)
    client=FakeComfy()
    with pytest.raises(P.InputError,match='Linked input subfolder'): project(tmp_path,client).run()
    link.unlink()
    def inaccessible(*args,**kwargs):
        kwargs['onerror'](PermissionError('unreadable nested directory'))
        yield
    monkeypatch.setattr(P.os,'walk',inaccessible)
    with pytest.raises(P.InputError,match='Cannot scan complete'): project(tmp_path,client).run()
    assert not client.submissions
