"""Checkpoint files cannot redirect reads/writes or escape read budgets."""
import hashlib
import json
from pathlib import Path
import sys
import types
import pytest
from tools.simulate_ownership_scenarios import module
C=module('stage_cache')
KEY='a'*64


@pytest.fixture
def cache(tmp_path,monkeypatch):
    output=tmp_path/'output';output.mkdir()
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(output)))
    return output


@pytest.mark.parametrize('level',['manga_translator','manga_translator/stage_cache','manga_translator/stage_cache/aa','manga_translator/stage_cache/aa/'+KEY])
def test_redirected_cache_directory_never_writes_outside(cache,tmp_path,level):
    outside=tmp_path/'outside';outside.mkdir()
    link=cache/level;link.parent.mkdir(parents=True,exist_ok=True);link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='outside'):
        C.write(KEY,'text','private page')
    assert not list(outside.iterdir())
    assert C.read(KEY,'text') is None


@pytest.mark.parametrize('name',['value.bin','manifest.json'])
def test_redirected_cache_file_is_a_miss(cache,tmp_path,name):
    C.write(KEY,'text','private page')
    target=C.root()/KEY[:2]/KEY/name
    outside=tmp_path/name;outside.write_bytes(target.read_bytes())
    target.unlink();target.symlink_to(outside)
    assert C.read(KEY,'text') is None


def test_manifest_and_payload_reads_are_bounded(cache,monkeypatch):
    C.write(KEY,'text','approved cached text')
    original=Path.open;calls=[]
    class Reader:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):self.stream.close()
        def read(self,n=-1):
            assert 0<n<=C.MAX_BYTES+1,'unbounded cache read'
            calls.append(n);return self.stream.read(n)
    monkeypatch.setattr(Path,'open',lambda path,*a,**kw:Reader(original(path,*a,**kw)))
    assert C.read(KEY,'text')=='approved cached text'
    assert len(calls)==2


def test_configured_output_root_may_itself_be_a_symlink(tmp_path,monkeypatch):
    actual=tmp_path/'actual';actual.mkdir();output=tmp_path/'output';output.symlink_to(actual,target_is_directory=True)
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(output)))
    C.write(KEY,'text','normal');assert C.read(KEY,'text')=='normal'


@pytest.mark.parametrize('shape',[(1,10**10,10**10,3),(1,0,4,3),(1,2,2,4)])
def test_invalid_array_shape_is_rejected_before_numpy_allocation(cache,monkeypatch,shape):
    import io
    import numpy as np
    C.write(KEY,'text','placeholder')
    folder=C.root()/KEY[:2]/KEY
    buffer=io.BytesIO()
    np.lib.format.write_array_header_1_0(buffer,{'descr':'<f4','fortran_order':False,'shape':shape})
    raw=buffer.getvalue();(folder/'value.bin').write_bytes(raw)
    (folder/'manifest.json').write_text(json.dumps({'key':KEY,'kind':'image','sha256':hashlib.sha256(raw).hexdigest()}))
    def forbidden(*a,**kw):raise AssertionError('np.load attempted to allocate an invalid shape')
    monkeypatch.setattr(C.np,'load',forbidden)
    assert C.read(KEY,'image') is None


@pytest.mark.parametrize('name',['manifest.json','value.bin'])
def test_fifo_cache_artifact_is_rejected_without_opening(cache,monkeypatch,name):
    import os
    if not hasattr(os,'mkfifo'):pytest.skip('FIFO unavailable on this platform')
    C.write(KEY,'text','normal');path=C.root()/KEY[:2]/KEY/name
    path.unlink();os.mkfifo(path)
    original=Path.open
    def guard(candidate,*a,**kw):
        assert candidate!=path,'cache attempted blocking FIFO open'
        return original(candidate,*a,**kw)
    monkeypatch.setattr(Path,'open',guard)
    assert C.read(KEY,'text') is None
