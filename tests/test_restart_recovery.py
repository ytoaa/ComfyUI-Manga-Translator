"""Explicit workflow retry after a proven native process restart; no live job duplication."""
from copy import deepcopy
from datetime import datetime, timezone
import os
import sys
import time
import types

import pytest
import psutil

from tests.test_project_runner import P, FakeComfy, project, make_page
from tests.test_workflow_projects import W


CONTEXT = {'kind':'native_process', 'pid':99, 'started_at':'2026-10-17T13:48:40+00:00'}


class RestartClient(FakeComfy):
    base = W.NativeComfyClient.base
    execution_context = CONTEXT
    restart_evidence = W.NativeComfyClient.restart_evidence


def interrupted(tmp_path, *, attempts=1, legacy=True):
    make_page(tmp_path/'input/1.png')
    client = RestartClient(['ocr_error']*(attempts-1)+['running', 'success'])
    runner = project(tmp_path, client, retry_failed=True)
    for _ in range(attempts-1):
        assert runner.run()['counts'] == {'failed':1}
    with pytest.raises(P.Paused, match='timed out'):
        runner.run()
    state = runner.state(runner.pages[0])
    state.update(created_at='2026-10-17T13:47:39+00:00', updated_at='2026-10-17T13:47:50+00:00')
    if legacy: state.pop('execution_context', None)
    else: state['execution_context'] = {**CONTEXT, 'pid':88, 'started_at':'2026-10-17T12:00:00+00:00'}
    # Preserve the user's actual pre-restart state, including second-precision timestamps.
    (runner._attempt_dir(state)/'state.json').write_bytes(P.json_bytes(state))
    old = deepcopy(client.jobs[state['prompt_id']])
    client.jobs.clear()  # A new process has neither the old queue nor history.
    return runner, client, state, old


def test_reported_attempt_three_retries_as_attempt_four_and_preserves_prior_records(tmp_path):
    runner, client, state, _ = interrupted(tmp_path, attempts=3)
    old_files = {p:p.read_bytes() for p in runner.destination.glob('pages/*/attempt-00000[12]/*')}
    normalized = (runner._attempt_dir(state)/'input.png').read_bytes()
    report = runner.run()
    assert report['counts'] == {'completed':1}
    current = runner.state(runner.pages[0])
    assert current['attempt'] == 4 and len(client.submissions) == 4
    assert current['execution_context'] == CONTEXT
    retired = P.read_json(runner._attempt_dir(state)/'state.json')
    assert retired['status'] == 'failed' and retired['reason'] == 'server_restarted_outcome_lost'
    assert retired['prompt_id'] == state['prompt_id'] and retired['submission_token'] == state['submission_token']
    assert retired['restart_recovery']['previous_updated_at'] == '2026-10-17T13:47:50+00:00'
    assert retired['restart_recovery']['requested_action'] == '실패 재시도'
    assert (runner._attempt_dir(state)/'input.png').read_bytes() == normalized
    assert all(path.read_bytes() == data for path,data in old_files.items())
    assert client.submissions[-1][2]['attempt'] == 4


def test_same_restart_recovery_works_with_process_stamp_written_by_new_version(tmp_path):
    runner, client, state, _ = interrupted(tmp_path, legacy=False)
    assert runner.run()['counts'] == {'completed':1}
    assert runner.state(runner.pages[0])['attempt'] == 2
    assert len(client.submissions) == 2


def test_ordinary_resume_does_not_retire_or_retry_missing_attempt(tmp_path):
    runner, client, state, _ = interrupted(tmp_path)
    runner.retry_failed = False
    before = (runner._attempt_dir(state)/'state.json').read_bytes()
    with pytest.raises(P.Paused, match='absent from both'): runner.run()
    assert (runner._attempt_dir(state)/'state.json').read_bytes() == before
    assert len(client.submissions) == 1


@pytest.mark.parametrize('change', ['same_process', 'newer_process_stamp', 'no_process_clock',
                                     'recent_update', 'missing_time', 'naive_time', 'invalid_time',
                                     'reversed_times'])
def test_unproven_restart_never_enables_retry(tmp_path, change):
    runner, client, state, _ = interrupted(tmp_path)
    if change == 'same_process': state['execution_context'] = deepcopy(CONTEXT)
    if change == 'newer_process_stamp': state['execution_context'] = {**CONTEXT, 'started_at':'2026-10-17T14:00:00+00:00'}
    if change == 'no_process_clock': client.execution_context = None
    if change == 'recent_update': state['updated_at'] = '2026-10-17T13:48:39+00:00'
    if change == 'missing_time': state.pop('updated_at')
    if change == 'naive_time': state['updated_at'] = '2026-10-17T13:47:50'
    if change == 'invalid_time': state['created_at'] = 'not a timestamp'
    if change == 'reversed_times': state['created_at'] = '2026-10-17T13:48:20+00:00'
    path = runner._attempt_dir(state)/'state.json'; path.write_bytes(P.json_bytes(state)); before=path.read_bytes()
    with pytest.raises(P.Paused, match='absent from both'): runner.run()
    assert path.read_bytes() == before and len(client.submissions) == 1


def test_still_running_owned_job_and_foreign_jobs_are_never_retired_or_cancelled(tmp_path):
    runner, client, state, old = interrupted(tmp_path)
    client.jobs[state['prompt_id']] = old
    foreign = [9, 'foreign-prompt', {}, {'manga_project':{'project':'other'}}, []]
    client.foreign = [foreign]
    with pytest.raises(P.Paused, match='timed out'): runner.run()
    assert runner.state(runner.pages[0])['status'] == 'running'
    assert len(client.submissions) == 1 and client.foreign == [foreign]
    assert 'restart_recovery' not in runner.state(runner.pages[0])


def test_completed_history_is_collected_without_resubmitting_after_restart(tmp_path):
    runner, client, state, old = interrupted(tmp_path)
    old['mode'] = 'success'; client.jobs[state['prompt_id']] = old
    assert runner.run()['counts'] == {'completed':1}
    assert runner.state(runner.pages[0])['attempt'] == 1 and len(client.submissions) == 1


def test_completion_arriving_at_final_absence_check_wins_over_restart_recovery(tmp_path):
    runner, client, state, old = interrupted(tmp_path)
    reads = []
    def history(ident):
        reads.append(ident)
        if len(reads) >= 7:
            old['mode'] = 'success'
            client.jobs[state['prompt_id']] = old
            return deepcopy(old['history'])
        return None
    client.history = history
    assert runner.run()['counts'] == {'completed':1}
    assert len(client.submissions) == 1 and runner.state(runner.pages[0])['attempt'] == 1


def test_queue_reappearing_at_final_check_is_not_retired(tmp_path):
    runner, client, state, old = interrupted(tmp_path)
    reads = []
    def queue():
        reads.append(1)
        return {'queue_running':[[0,state['prompt_id'],old['graph'],{'manga_project':state['submission_token']},[]]]
                if len(reads) >= 4 else [], 'queue_pending':[]}
    client.queue = queue
    with pytest.raises(P.Paused, match='timed out'): runner.run()
    assert runner.state(runner.pages[0])['status'] == 'running'
    assert len(client.submissions) == 1


def test_http_client_without_native_restart_proof_keeps_unknown_state(tmp_path):
    runner, client, state, _ = interrupted(tmp_path)
    client.restart_evidence = None
    with pytest.raises(P.Paused, match='absent from both'): runner.run()
    assert runner.state(runner.pages[0])['status'] == 'running' and len(client.submissions) == 1


def test_pause_request_blocks_retirement_and_retry(tmp_path):
    runner, client, state, _ = interrupted(tmp_path)
    runner.should_stop = lambda:True
    with pytest.raises(P.Paused): runner.run()
    assert runner.state(runner.pages[0])['status'] == 'running' and len(client.submissions) == 1


def test_removed_input_can_be_retired_but_is_never_resubmitted(tmp_path):
    runner, client, state, _ = interrupted(tmp_path)
    (tmp_path/'input/1.png').unlink()
    report = runner.run()
    assert report['counts'] == {} and report['removed_inputs'] == ['1.png']
    assert len(client.submissions) == 1
    assert P.read_json(runner._attempt_dir(state)/'state.json')['reason'] == 'server_restarted_outcome_lost'


def test_native_context_uses_os_process_creation_time(monkeypatch):
    started = time.time()-120
    calls = []
    def process(pid):
        calls.append(pid)
        return types.SimpleNamespace(create_time=lambda:started)
    monkeypatch.setitem(sys.modules, 'psutil', types.SimpleNamespace(Process=process, Error=RuntimeError))
    context = W.NativeComfyClient._execution_context()
    assert calls == [context['proc_pid']] and context['pid'] == os.getpid()
    assert datetime.fromisoformat(context['started_at']).timestamp() == pytest.approx(started)


def test_unavailable_native_process_clock_disables_restart_recovery(monkeypatch):
    monkeypatch.setitem(sys.modules, 'psutil', None)
    assert W.NativeComfyClient._execution_context() is None


def test_real_os_clock_proves_only_attempts_from_before_current_process():
    context = W.NativeComfyClient._execution_context()
    assert context is not None
    assert context['pid'] == os.getpid()
    boot = datetime.fromisoformat(context['started_at']).timestamp()
    assert 0 < boot <= time.time()
    state = {'prompt_id':'2ab78b68-6336-49cb-8af4-3dd4abfdeac0',
             'created_at':datetime.fromtimestamp(boot-70, timezone.utc).isoformat(),
             'updated_at':datetime.fromtimestamp(boot-60, timezone.utc).isoformat()}
    client = types.SimpleNamespace(execution_context=context)
    assert W.NativeComfyClient.restart_evidence(client, state)['kind'] == 'native_process_restart'
    state['execution_context'] = context
    assert W.NativeComfyClient.restart_evidence(client, state) is None
