"""Previous-page context is bounded, owned, and must precede a known page."""
import hashlib
import json
from pathlib import Path
import sys
import types
import pytest
from tools.simulate_ownership_scenarios import module

T = module('translation_context')


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'folder_paths', types.SimpleNamespace(get_output_directory=lambda: str(tmp_path)))
    root = tmp_path/'manga_translator/workflow_projects/book'
    folder = root/'pages/p1/attempt-000001'; folder.mkdir(parents=True)
    value = {'translation_metadata': {'target_language': 'Korean'}, 'regions': [
        {'source':'Original', 'target':'번역', 'authored':{'target':{'origin':'human'}}}]}
    def write(value):
        raw = json.dumps(value).encode(); (folder/'target.json').write_bytes(raw)
        (folder/'state.json').write_text(json.dumps({'artifacts':{'target.json':hashlib.sha256(raw).hexdigest()}}))
    write(value)
    report = {'project_folder':str(root), 'current_page':'2.png', 'pages':[
        {'relative_path':'1.png', 'status':'completed', 'state_file':'pages/p1/attempt-000001/state.json'},
        {'relative_path':'2.png', 'status':'running'}]}
    return root, folder, report, write


@pytest.mark.parametrize('value', [[], None, {'regions':[None]},
    {'translation_metadata':None, 'regions':[]},
    {'translation_metadata':{'target_language':'Korean'}, 'regions':[{'authored':None}]}])
def test_malformed_history_document_is_skipped(history, value):
    _, _, report, write = history; write(value)
    assert T.history(report, 'Korean', 12000) == []


@pytest.mark.parametrize('current', [None, 'missing.png'])
def test_unknown_current_page_never_includes_future_context(history, current):
    _, _, report, _ = history; report['current_page'] = current
    assert T.history(report, 'Korean', 12000) == []


def test_target_symlink_cannot_read_outside_project(history, tmp_path):
    _, folder, report, _ = history
    raw = (folder/'target.json').read_bytes()
    outside = tmp_path/'outside.json'; outside.write_bytes(raw)
    (folder/'target.json').unlink(); (folder/'target.json').symlink_to(outside)
    assert T.history(report, 'Korean', 12000) == []


def test_redirected_project_root_cannot_read_outside_output(tmp_path, monkeypatch):
    output = tmp_path/'output'; output.mkdir()
    outside = tmp_path/'outside'; outside.mkdir()
    (output/'manga_translator').symlink_to(outside, target_is_directory=True)
    monkeypatch.setitem(sys.modules, 'folder_paths', types.SimpleNamespace(get_output_directory=lambda: str(output)))
    with pytest.raises(ValueError, match='outside'):
        T.history({'project_folder':str(outside/'workflow_projects/book'), 'current_page':'2.png', 'pages':[]}, 'Korean', 12000)


def test_reads_are_bounded_and_old_pages_are_not_loaded_after_budget_fills(history, monkeypatch):
    _, folder, report, _ = history
    first = report['pages'][0].copy(); first['relative_path'] = 'older.png'
    first['state_file'] = 'must-not-open/state.json'
    report['pages'].insert(0, first)
    expected = [{'page':'1.png','regions':[{'source':'Original','target':'번역'}]}]
    budget = len(json.dumps(expected[0], ensure_ascii=False).encode())
    calls = []; opening = Path.open
    class Bounded:
        def __init__(self, handle): self.handle = handle
        def __enter__(self): return self
        def __exit__(self, *args): self.handle.close()
        def read(self, n=-1):
            assert 0 < n <= 4*1024*1024+1, 'Unbounded history file read'
            return self.handle.read(n)
    def tracked(path, *args, **kwargs):
        assert 'must-not-open' not in str(path), 'Read older history after budget filled'
        calls.append(path.name)
        return Bounded(opening(path, *args, **kwargs))
    monkeypatch.setattr(Path, 'open', tracked)
    assert T.history(report, 'Korean', budget) == expected
    assert calls == ['state.json','target.json']


def test_malformed_page_rows_do_not_crash_valid_preceding_context(history):
    _, _, report, _ = history; report['pages'].insert(0, None)
    assert len(T.history(report, 'Korean', 12000)) == 1


@pytest.mark.parametrize('name,limit',[('state.json',2*1024*1024),('target.json',4*1024*1024)])
def test_oversized_history_artifact_is_skipped(history,name,limit):
    _,folder,report,_=history
    (folder/name).write_bytes(b' '*(limit+1))
    assert T.history(report,'Korean',12000)==[]


def test_duplicate_current_page_is_ambiguous(history):
    _,_,report,_=history;report['pages'].append(dict(report['pages'][-1]))
    assert T.history(report,'Korean',12000)==[]


def test_selected_history_remains_chronological(history):
    root,folder,report,_=history
    older=root/'pages/older/attempt-000001';older.mkdir(parents=True)
    for name in ('state.json','target.json'):(older/name).write_bytes((folder/name).read_bytes())
    report['pages'].insert(0,{'relative_path':'0.png','status':'completed','state_file':'pages/older/attempt-000001/state.json'})
    assert [p['page'] for p in T.history(report,'Korean',12000)]==['0.png','1.png']


@pytest.mark.parametrize('name',['state.json','target.json'])
def test_fifo_history_artifact_is_skipped_without_opening(history,monkeypatch,name):
    import os
    if not hasattr(os,'mkfifo'):pytest.skip('FIFO unavailable on this platform')
    _,folder,report,_=history;path=folder/name;path.unlink();os.mkfifo(path)
    original=Path.open
    def guard(candidate,*a,**kw):
        assert candidate!=path,'history attempted blocking FIFO open'
        return original(candidate,*a,**kw)
    monkeypatch.setattr(Path,'open',guard)
    assert T.history(report,'Korean',12000)==[]
