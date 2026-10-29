"""Actual POSIX termination and contention; not power-loss durability."""
import json
import multiprocessing as mp
import time
import pytest
from tests.test_project_runner import P
from tools.simulate_ownership_scenarios import module
K=module('stage_cache')
pytestmark=pytest.mark.skipif('fork' not in mp.get_all_start_methods(),reason='POSIX fork evidence only')


def stop(child):
    if child.is_alive():child.kill()
    child.join(5)
    assert not child.is_alive()


def test_other_process_lock_excludes_runner_and_kill_releases(tmp_path):
    ctx=mp.get_context('fork');recv,send=ctx.Pipe(False)
    def hold():
        with P.project_lock(tmp_path):send.send(True);time.sleep(15)
    child=ctx.Process(target=hold);child.start()
    try:
        assert recv.poll(5) and recv.recv()
        with pytest.raises(P.ProjectError,match='already'):
            with P.project_lock(tmp_path):pass
    finally:stop(child);recv.close();send.close()
    with P.project_lock(tmp_path):pass


@pytest.mark.parametrize('after',[False,True])
def test_killed_atomic_writer_leaves_one_complete_generation(tmp_path,after):
    path=tmp_path/'state.json';path.write_text('{"generation":"old"}')
    ctx=mp.get_context('fork');recv,send=ctx.Pipe(False)
    def write():
        original=P.os.replace
        def replace(a,b):
            if after:original(a,b)
            send.send(True);time.sleep(15)
            if not after:original(a,b)
        P.os.replace=replace
        P.atomic_write(path,b'{"generation":"new"}')
    child=ctx.Process(target=write);child.start()
    try:assert recv.poll(5) and recv.recv()
    finally:stop(child);recv.close();send.close()
    assert json.loads(path.read_text())['generation']==('new' if after else 'old')
    P.atomic_write(path,b'{"generation":"next"}')
    assert json.loads(path.read_text())['generation']=='next'


def test_competing_cache_writers_never_pair_different_generations(tmp_path,monkeypatch):
    monkeypatch.setattr(K,'root',lambda:tmp_path)
    key='b'*64;ctx=mp.get_context('fork');start=ctx.Event()
    def write(prefix):
        assert start.wait(5)
        for i in range(20):
            text=f'{prefix}-{i}';K.write(key,'text',text,json.dumps({'value':text}))
    children=[ctx.Process(target=write,args=(p,)) for p in ('a','b')]
    for c in children:c.start()
    start.set();reads=0;deadline=time.monotonic()+15
    try:
        while any(c.is_alive() for c in children) and time.monotonic()<deadline:
            entry=K.read_entry(key,'text');reads+=1
            if entry is not None:assert entry[0]==entry[1]['value']
        for c in children:c.join(1);assert c.exitcode==0
    finally:
        for c in children:stop(c)
    assert reads
    entry=K.read_entry(key,'text')
    if entry is not None:assert entry[0]==entry[1]['value']
