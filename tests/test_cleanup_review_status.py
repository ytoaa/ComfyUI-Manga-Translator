"""Cleanup warnings must survive collection, cached reuse, and resume."""
import json
import pytest
import torch
from tests.test_project_runner import P, FakeComfy, make_page, project
from tools.simulate_ownership_scenarios import module
K=module('stage_cache')


class QualityClient(FakeComfy):
    def __init__(self,flag,foreign_report=False):
        super().__init__();self.flag=flag;self.foreign_report=foreign_report
    def history(self,ident):
        history=super().history(ident)
        if not history:return history
        graph=self.jobs[ident]['graph']
        node=next(k for k,v in graph.items() if v['class_type']=='MangaCleanupCheckpoint')
        if self.foreign_report:node='unrelated'
        history['outputs'][node]={'manga_cleanup_report':[{'schema':1,'needs_review':self.flag,'quality_warnings':[]}]}
        return history


@pytest.mark.parametrize('flag',[True,False])
def test_cleanup_quality_flag_persists_and_resume_does_not_resubmit(tmp_path,flag):
    make_page(tmp_path/'input/1.png');client=QualityClient(flag);runner=project(tmp_path,client)
    expected='needs_review' if flag else 'completed'
    assert runner.run()['counts']=={expected:1}
    state=runner.state(runner.pages[0])
    assert json.loads((runner._attempt_dir(state)/'cleanup-report.json').read_text())['needs_review'] is flag
    assert 'cleanup-report.json' in state['artifacts']
    assert runner.run()['counts']=={expected:1} and len(client.submissions)==1


@pytest.mark.parametrize('flag',['false',0,None])
def test_malformed_cleanup_flag_is_rejected(tmp_path,flag):
    make_page(tmp_path/'input/1.png');runner=project(tmp_path,QualityClient(flag))
    with pytest.raises(P.ProtocolError,match='cleanup quality'):runner.run()


def test_unrelated_report_cannot_change_page_outcome(tmp_path):
    make_page(tmp_path/'input/1.png');runner=project(tmp_path,QualityClient(True,True))
    assert runner.run()['counts']=={'completed':1}


def test_cached_review_flag_is_visible_on_computation_and_reuse(tmp_path,monkeypatch):
    monkeypatch.setattr(K,'root',lambda:tmp_path)
    node=K.MangaCleanupCheckpoint();image=torch.ones((1,8,9,3))
    graph={'1':{'class_type':'MangaCleanupCheckpoint','inputs':{}}}
    first=node.checkpoint(image,image,report_json='{"schema":1,"needs_review":true}',prompt=graph,unique_id='1')
    assert node.check_lazy_status(image,prompt=graph,unique_id='1')==[]
    second=node.checkpoint(image,prompt=graph,unique_id='1')
    for result in (first,second):
        assert result['ui']['manga_cleanup_report'][0]['needs_review'] is True
        assert result['ui']['manga_status'][0]['state']=='needs_review'
