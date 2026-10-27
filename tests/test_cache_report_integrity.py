"""Cache reuse must not erase user-visible review evidence."""
import json
import pytest
import torch
from tools.simulate_ownership_scenarios import module
S=module('stage_cache')

@pytest.mark.parametrize('report',[json.dumps({'needs_review':True,'reason':'가'*700000},ensure_ascii=False),'[]','{broken'],ids=['oversized','array','malformed'])
def test_unpersistable_report_cannot_become_successful_reportless_cache(monkeypatch,tmp_path,report):
    monkeypatch.setattr(S,'root',lambda:tmp_path)
    key='a'*64
    S.write(key,'image',torch.ones(1,4,4,3),report)
    assert S.read_entry(key,'image') is None
    assert not list(tmp_path.rglob('*.tmp'))

def test_review_report_survives_cache_roundtrip(monkeypatch,tmp_path):
    monkeypatch.setattr(S,'root',lambda:tmp_path)
    details={'needs_review':True,'regions':[{'id':'r1','reason':'원문 잔존'}]}
    S.write('b'*64,'image',torch.ones(1,4,4,3),json.dumps(details,ensure_ascii=False))
    image,report=S.read_entry('b'*64,'image')
    assert report==details and image.eq(1).all()

def test_unicode_report_within_byte_budget_is_reusable(monkeypatch,tmp_path):
    monkeypatch.setattr(S,'root',lambda:tmp_path)
    details={'needs_review':True,'reason':'가'*400000}
    S.write('c'*64,'image',torch.ones(1,4,4,3),json.dumps(details,ensure_ascii=False))
    assert S.read_entry('c'*64,'image')[1]==details

def test_invalid_refresh_invalidates_old_report(monkeypatch,tmp_path):
    monkeypatch.setattr(S,'root',lambda:tmp_path)
    S.write('d'*64,'image',torch.ones(1,4,4,3),'{}')
    S.write('d'*64,'image',torch.zeros(1,4,4,3),'[]')
    assert S.read_entry('d'*64,'image') is None

@pytest.mark.parametrize('payload',[None,{}, {'text':'cached','report':'[]','previews':['bad']},
 {'text':'cached','report':'{}','previews':['not base64']}, {'text':'cached','report':'{}','previews':[]}],ids=['null','missing','report','image','empty'])
def test_corrupt_nested_ocr_payload_recomputes(monkeypatch,payload):
    import types
    R=module('recognition_cache');calls=[]
    original=torch.ones(1,4,4,3)
    monkeypatch.setattr(R.stage_cache,'read',lambda *args:json.dumps(payload))
    monkeypatch.setattr(R.stage_cache,'write',lambda *args:None)
    def recognize(*args,**kwargs):
        calls.append(1);return 'recomputed','{"status":"ok"}',[original]
    monkeypatch.setattr(R.MangaOCRAdaptive,'read',recognize)
    result=R.MangaOCRAdaptiveCached().read(original,types.SimpleNamespace(cache_identity={'model':'test'}))
    assert calls==[1] and result['result'][0]=='recomputed'
    assert result['ui']['manga_status'][0]['state']=='computed'
