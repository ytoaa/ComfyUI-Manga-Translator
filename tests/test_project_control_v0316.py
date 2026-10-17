"""v0.3.16 folder-project control-plane regressions.

These tests exercise policy/lifecycle boundaries that are easy to miss when the
Project runner and ComfyUI parent control prompt are tested separately.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import threading
import types

import pytest

from tests.test_project_runner import P, FakeComfy, Clock, graph, make_page, project

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('project_control_v0316_tests')
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
sys.modules[package.__name__ + '.tools.run_project'] = P
spec = importlib.util.spec_from_file_location(package.__name__ + '.workflow_project', ROOT/'workflow_project.py')
W = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = W
spec.loader.exec_module(W)


def wait(controller):
    controller.worker.join(10)
    assert not controller.worker.is_alive()


def load_id(value):
    return P.workflow_bindings(value)['load']


def test_source_safety_ceiling_is_separate_from_legacy_16mp_contract():
    assert P.LEGACY_PAGE_PIXELS == 16*1024*1024
    assert P.MAX_SOURCE_PIXELS == P.MAX_PAGE_PIXELS == 64*1024*1024
    assert P.MAX_SOURCE_PIXELS > P.LEGACY_PAGE_PIXELS


def test_control_widgets_do_not_change_semantic_workflow_identity():
    base = graph(); changed = deepcopy(base); ident = load_id(changed)
    changed[ident]['inputs'].update(input_mode='폴더 프로젝트', input_folder='manga_uploads/new/book',
                                    project_name='another-name', action='실패 재시도', image='other.png')
    assert P.workflow_fingerprint(base) == P.workflow_fingerprint(changed)
    next(n for n in changed.values() if n['class_type']=='MangaLetterPlan')['inputs']['min_font'] = 9
    assert P.workflow_fingerprint(base) != P.workflow_fingerprint(changed)


def test_same_book_can_resume_after_browser_reupload_changes_only_server_path(tmp_path):
    first = tmp_path/'upload-a'/'book'; second = tmp_path/'upload-b'/'book'
    make_page(first/'1.png'); make_page(first/'2.png')
    shutil.copytree(first, second)
    destination = tmp_path/'project'; client = FakeComfy(); clock = Clock()
    original = P.Project(first,destination,graph(),client,clock=clock.now,sleep=clock.sleep,page_timeout=3)
    assert original.run()['counts'] == {'completed':2}
    assert len(client.submissions) == 2
    moved = P.Project(second,destination,graph(),client,clock=clock.now,sleep=clock.sleep,page_timeout=3)
    assert moved.run()['counts'] == {'completed':2}
    assert len(client.submissions) == 2
    manifest = P.read_json(destination/'project.json')
    assert manifest['source_folder'] == str(second.resolve())
    assert 'input_folder' not in manifest['config']


def test_legacy_pixel_budget_project_migrates_and_retries_only_policy_failure(tmp_path):
    make_page(tmp_path/'input/1.png', size=(50,50))  # 2,500 pixels
    client = FakeComfy(); first = project(tmp_path,client,max_pixels=2_000)
    assert first.run()['counts'] == {'failed':1}
    assert not client.submissions
    manifest = P.read_json(first.destination/'project.json')
    # Reproduce the v0.3.15 identity persisted by the user's failed project.
    manifest['config'] = {
        'input_folder': str(first.inputs), 'server': client.base,
        'workflow_sha256': first.legacy_workflow_sha256, 'recursive': True,
        'max_pixels': 2_000, 'normalisation': 'exif_rgb_white_alpha_v1',
    }
    P.atomic_write(first.destination/'project.json', P.json_bytes(manifest))
    clock = Clock()
    upgraded = P.Project(first.inputs,first.destination,graph(),client,max_pixels=5_000,
                         clock=clock.now,sleep=clock.sleep,page_timeout=3)
    assert upgraded.run()['counts'] == {'completed':1}
    assert len(client.submissions) == 1
    states = sorted(upgraded.destination.glob('pages/*/attempt-*/state.json'))
    assert len(states) == 2
    assert P.read_json(states[0])['reason'] == 'invalid_input'
    assert P.read_json(states[1])['status'] == 'completed'
    config = P.read_json(upgraded.destination/'project.json')['config']
    assert config['identity_version'] == 2 and config['source_pixel_limit'] == 5_000


def test_child_prompt_is_single_image_job_and_does_not_revalidate_source_folder(tmp_path):
    make_page(tmp_path/'input/1.png'); client = FakeComfy(); runner = project(tmp_path,client)
    assert runner.run()['counts'] == {'completed':1}
    submitted = client.submissions[0][1]; ident = load_id(submitted); inputs = submitted[ident]['inputs']
    assert inputs['input_mode'] == '이미지 한 장'
    assert inputs['input_folder'] == ''
    assert inputs['action'] == '상태 확인'
    assert inputs['image'].startswith('manga_translator/'+runner.project_id+'/')


def test_no_empty_export_edition_is_claimed_when_every_page_is_invalid(tmp_path):
    make_page(tmp_path/'input/1.png', size=(50,50))
    runner = project(tmp_path,FakeComfy(),max_pixels=2_000)
    report = runner.run(export=True)
    assert report['counts'] == {'failed':1}
    assert report['export'] is None
    assert not list((runner.destination/'exports').glob('*')) if (runner.destination/'exports').exists() else True


def test_real_processing_setting_change_still_requires_new_project(tmp_path):
    make_page(tmp_path/'input/1.png'); client=FakeComfy(); runner=project(tmp_path,client)
    runner.run(plan_only=True)
    changed=graph(); next(n for n in changed.values() if n['class_type']=='MangaLetterPlan')['inputs']['min_font']=9
    with pytest.raises(P.ProjectError,match='model/workflow settings changed'):
        P.Project(runner.inputs,runner.destination,changed,client).run()


def test_controller_waits_for_parent_gate_before_any_child_submission(tmp_path):
    make_page(tmp_path/'input/1.png'); folder=tmp_path/'output'/'project'; entered=threading.Event(); release=threading.Event()
    class Gated(FakeComfy):
        def wait_for_parent_success(self, should_stop):
            entered.set(); assert not self.submissions; assert release.wait(5); assert not should_stop()
    client=Gated(); controller=W.WorkflowProjects(); controller.start(folder,tmp_path/'input',graph(),client)
    assert entered.wait(5) and not client.submissions
    release.set(); wait(controller)
    assert len(client.submissions) == 1 and controller.snapshot(folder)['status'] == 'completed'


def test_parent_failure_or_pause_never_submits_a_child_page(tmp_path):
    make_page(tmp_path/'input/1.png'); folder=tmp_path/'output'/'project'
    class FailedParent(FakeComfy):
        def wait_for_parent_success(self, should_stop):
            raise P.Paused('parent failed before child queue')
    client=FailedParent(); controller=W.WorkflowProjects(); controller.start(folder,tmp_path/'input',graph(),client)
    wait(controller)
    report=controller.snapshot(folder)
    assert report['status']=='paused' and 'parent failed' in report['message']
    assert not client.submissions


def test_native_parent_reconciler_accepts_success_and_rejects_error_or_stop():
    client = object.__new__(W.NativeComfyClient); client.parent_prompt_id='parent'
    client.history=lambda ident:{'status':{'status_str':'success','completed':True}}
    client.queue=lambda:{'queue_running':[],'queue_pending':[]}
    client.wait_for_parent_success(timeout=.01)
    client.history=lambda ident:{'status':{'status_str':'error','completed':False}}
    with pytest.raises(P.Paused,match='실패'):
        client.wait_for_parent_success(timeout=.01)
    client.history=lambda ident:None
    client.queue=lambda:{'queue_running':[[0,'parent',{},{}]],'queue_pending':[]}
    with pytest.raises(P.Paused,match='일시정지'):
        client.wait_for_parent_success(lambda:True, timeout=.01)
