"""Native PromptQueue tuples and HTTP lists must have identical failure policy."""
import types

import pytest

from tests.test_project_runner import P, FakeComfy, project, make_page
from tests.test_workflow_projects import W, book, wait


class HistoryClient(FakeComfy):
    def __init__(self, modes=(), *, native=True, event=None, omit_error=False):
        super().__init__(modes)
        self.native, self.event, self.omit_error = native, event, omit_error

    def history(self, ident):
        history = super().history(ident)
        if not history or history['status']['status_str'] != 'error':
            return history
        messages = history['status']['messages']
        payload = messages[0][1]
        payload.update(node_id='8', traceback=['first traceback line\n', 'last traceback line\n'])
        if self.event == 'execution_interrupted':
            messages = [['execution_interrupted', {'node_id':'8','node_type':'MangaLetterApply'}]]
        elif self.omit_error:
            messages = [['execution_start', {'prompt_id':ident}]]
        if self.native:
            messages = [tuple(entry) for entry in messages]
        history['status']['messages'] = messages
        if self.native:
            # Exercise the native adapter directly. Core get_history preserves
            # Python tuple entries; it does not perform an HTTP JSON roundtrip.
            queue = types.SimpleNamespace(get_history=lambda key:{key:history})
            client = types.SimpleNamespace(server=types.SimpleNamespace(prompt_queue=queue))
            return W.NativeComfyClient.history(client, ident)
        return history


@pytest.mark.parametrize('native', [True, False], ids=['native-tuples','http-lists'])
def test_page_quality_error_preserves_diagnostics_and_continues(tmp_path, native):
    make_page(tmp_path/'input/1.png'); make_page(tmp_path/'input/2.png')
    client = HistoryClient(['ocr_error', 'success'], native=native)
    runner = project(tmp_path, client)
    report = runner.run()
    assert report['counts'] == {'failed':1, 'completed':1}
    failed = report['pages'][0]
    assert failed['reason'] == 'HayaiOutputError'
    assert failed['failure_node'] == 'MangaOCRAdaptive'
    assert failed['failure_node_id'] == '8' and failed['detail'] == 'simulated failure'
    state = runner.state(runner.pages[0])
    assert state['failure_event'] == 'execution_error'
    assert state['failure_traceback'] == 'first traceback line\nlast traceback line\n'
    assert state['failure_diagnostics_missing'] is False
    assert len(client.submissions) == 2


@pytest.mark.parametrize('native', [True, False], ids=['native-tuples','http-lists'])
@pytest.mark.parametrize('mode', ['oom', 'disk_full', 'missing_model', 'interrupted'])
def test_system_or_cancel_failure_stops_before_second_page(tmp_path, native, mode):
    make_page(tmp_path/'input/1.png'); make_page(tmp_path/'input/2.png')
    client = HistoryClient([mode, 'success'], native=native,
                           event='execution_interrupted' if mode=='interrupted' else None)
    runner = project(tmp_path, client)
    with pytest.raises(P.Paused): runner.run()
    assert len(client.submissions) == 1
    assert runner.state(runner.pages[0])['reason'] != 'execution_failed'
    assert P.read_json(runner.destination/'summary.json')['counts'] == {'failed':1, 'pending':1}


@pytest.mark.parametrize('native', [True, False], ids=['native-tuples','http-lists'])
def test_missing_error_details_pause_and_normal_resume_cannot_silently_continue(tmp_path, native):
    make_page(tmp_path/'input/1.png'); make_page(tmp_path/'input/2.png')
    client = HistoryClient(['oom', 'success'], native=native, omit_error=True)
    runner = project(tmp_path, client)
    for _ in range(2):
        with pytest.raises(P.Paused, match='오류 상세'): runner.run()
        assert len(client.submissions) == 1
    failed = runner.state(runner.pages[0])
    assert failed['failure_diagnostics_missing'] is True
    assert 'without usable execution_error details' in failed['failure_message']


def legacy_failure(runner):
    runner.run(plan_only=True)
    state = runner._new(runner.pages[0])
    state.update(status='failed', reason='execution_failed', failure_node=None,
                 failure_message='', prompt_id='e71315f5-9226-4a1d-874e-988b31c60303')
    runner._save(state)
    return state


def test_old_blank_failure_recovers_from_original_history_without_resubmission(tmp_path):
    make_page(tmp_path/'input/1.png')
    client = FakeComfy(); runner = project(tmp_path, client); state = legacy_failure(runner)
    client.history = lambda ident: {'outputs':{}, 'status':{'status_str':'error','completed':False,
        'messages':[('execution_error', {'node_id':'8', 'node_type':'MangaOCRAdaptive',
                    'exception_type':'HayaiOutputError','exception_message':'short_repetition'})]}}
    report = runner.run()
    assert report['pages'][0]['reason'] == 'HayaiOutputError'
    assert report['pages'][0]['detail'] == 'short_repetition'
    assert runner.state(runner.pages[0])['attempt'] == state['attempt']
    assert not client.submissions


def test_old_blank_resource_failure_stops_before_pending_page(tmp_path):
    make_page(tmp_path/'input/1.png'); make_page(tmp_path/'input/2.png')
    client = FakeComfy(); runner = project(tmp_path, client); legacy_failure(runner)
    client.history = lambda ident: {'outputs':{}, 'status':{'status_str':'error','completed':False,
        'messages':[('execution_error', {'node_type':'UNETLoader',
                    'exception_type':'OutOfMemoryError','exception_message':'CUDA out of memory'})]}}
    with pytest.raises(P.Paused, match='resource'): runner.run()
    assert runner.state(runner.pages[0])['reason'] == 'OutOfMemoryError'
    assert not client.submissions and runner.state(runner.pages[1]) is None


def test_lost_old_history_requires_explicit_retry_and_preserves_prior_attempt(tmp_path):
    make_page(tmp_path/'input/1.png')
    client = FakeComfy(); runner = project(tmp_path, client); state = legacy_failure(runner)
    before = (runner._attempt_dir(state)/'state.json').read_bytes()
    with pytest.raises(P.Paused, match='이력이 없어'): runner.run()
    assert not client.submissions
    runner.retry_failed = True
    assert runner.run()['counts'] == {'completed':1}
    assert runner.state(runner.pages[0])['attempt'] == 2
    assert (runner._attempt_dir(state)/'state.json').read_bytes() == before
    assert len(client.submissions) == 1


def test_all_failed_controller_message_distinguishes_resume_from_retry(tmp_path):
    _, inputs, folder = book(tmp_path)
    controller = W.WorkflowProjects(); client = HistoryClient(['ocr_error', 'ocr_error'])
    from tests.test_project_runner import graph
    controller.start(folder, inputs, graph(), client); wait(controller)
    report = controller.snapshot(folder)
    assert report['status'] == 'needs_review' and report['counts'] == {'failed':2}
    assert '성공한 페이지가 없습니다' in report['message'] and '실패 재시도' in report['message']
    controller.start(folder, inputs, graph(), client); wait(controller)
    assert len(client.submissions) == 2  # ordinary resume preserves known failures
