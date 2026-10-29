"""Failure evidence stays within configured output and never leaves partial JSON."""
from pathlib import Path
import sys
import types
import pytest
from tools.simulate_ownership_scenarios import module
T=module('translation_protocol')


@pytest.mark.parametrize('level',['manga_translator','manga_translator/translation_failures'])
def test_failure_evidence_rejects_ancestor_symlink(tmp_path,monkeypatch,level):
    output=tmp_path/'output';output.mkdir();outside=tmp_path/'outside';outside.mkdir()
    link=output/level;link.parent.mkdir(parents=True,exist_ok=True);link.symlink_to(outside,target_is_directory=True)
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(output)))
    assert T.save_failure({'regions':[]},{},[],'test')=='unavailable'
    assert not list(outside.iterdir())


@pytest.mark.parametrize('fault',['replace','partial_write'])
def test_failed_evidence_write_leaves_no_json_or_temp(tmp_path,monkeypatch,fault):
    monkeypatch.setattr(T,'failure_root',lambda:tmp_path)
    if fault=='replace':
        def fail(*a):raise OSError('disk full')
        monkeypatch.setattr(T.os,'replace',fail)
    else:
        original=Path.open
        class Writer:
            def __init__(self,s):self.s=s
            def __enter__(self):return self
            def __exit__(self,*args):self.s.close()
            def write(self,raw):self.s.write(raw[:20]);self.s.flush();raise OSError('disk full')
        monkeypatch.setattr(Path,'open',lambda p,*a,**k:Writer(original(p,*a,**k)) if a==('xb',) else original(p,*a,**k))
    assert T.save_failure({'regions':[]},{},[],'test')=='unavailable'
    assert not list(tmp_path.iterdir())
