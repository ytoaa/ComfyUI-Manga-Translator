"""Domain containment failures preserve pixels; truncated translations commit atomically."""
from copy import deepcopy
from io import BytesIO
import importlib,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
import pytest

from tests.test_bubble_containment import T,detector
from tests.test_translation_response import N,reply
from tests.test_project_runner import P,FakeComfy,make_page,project


def bubble_values():
    clean=np.full((240,800,3),.65,np.float32);picture=Image.fromarray((clean*255).round().astype('uint8'))
    draw=ImageDraw.Draw(picture);font=ImageFont.truetype(T.core.font_path('NanumGothic-Bold.ttf','SOURCE'),40)
    for x in (200,600):draw.text((x,120),'SOURCE',font=font,fill='black',anchor='mm')
    original=np.asarray(picture,np.float32)/255;support=(abs(original-clean).max(2)>.03).astype(np.float32)
    rows=[{'id':'r1','bbox':[100,20,200,200],'text':'번역','source_text':'SOURCE'},
          {'id':'r2','bbox':[500,20,200,200],'text':'안녕','source_text':'SOURCE'}]
    doc={'schema':1,'coordinate_format':'xywh','page_size':[800,240],'regions':rows}
    mask=np.zeros((240,800),np.float32);mask[20:220,80:215]=1;mask[20:220,480:720]=1
    return (original,clean,support,json.dumps(doc)),mask


def test_crossing_region_restores_source_and_other_region_stays_contained():
    values,bubble=bubble_values()
    plan,out,alpha,report,_,build=T.run(values,respect_bubbles=True,bubble_mask=bubble,bubble_failure_policy='preserve_review')
    assert [r['id'] for r in report['regions']]==['r2']
    assert np.array_equal(out[20:220,100:300],values[0][20:220,100:300]) and not alpha[20:220,100:300].any()
    assert alpha[:,500:700].any() and not alpha[bubble==0].any()
    item=report['lettering_review'][0]
    assert item['id']=='r1' and item['diagnostic']['code']=='bubble_source_crossing'
    assert .5<=item['diagnostic']['candidates'][0]['source_ink_coverage']<.95
    assert report['needs_review'] and build['lettering_review']==report['lettering_review']


@pytest.mark.parametrize('options',[{'bubble_failure_policy':'stop'}, {'bubble_failure_policy':'preserve_review','region_options_json':'{"r1":{"require_bubble":true}}'}])
def test_explicit_strict_bubble_requirement_still_stops(options):
    values,bubble=bubble_values()
    with pytest.raises(ValueError,match='crosses'):T.run(values,respect_bubbles=True,bubble_mask=bubble,**options)


def test_preservation_propagates_to_overlapping_source_frames():
    values,bubble=bubble_values();original,clean,support,raw=values;doc=json.loads(raw)
    doc['regions'].append({'id':'r3','bbox':[190,20,200,200],'text':'겹침','source_text':'SOURCE'})
    _,out,alpha,report,_,_=T.run((original,clean,support,json.dumps(doc)),respect_bubbles=True,bubble_mask=bubble,bubble_failure_policy='preserve_review')
    assert {r['id'] for r in report['lettering_review']}=={'r1','r3'}
    assert any(r['diagnostic']['code']=='overlaps_preserved_bubble_region' for r in report['lettering_review'])
    assert np.array_equal(out[20:220,100:390],original[20:220,100:390]) and not alpha[20:220,100:390].any()


def test_all_preserved_is_review_not_verified_no_text():
    values,bubble=bubble_values();doc=json.loads(values[3]);doc['regions']=doc['regions'][:1]
    _,out,alpha,report,_,_=T.run((*values[:3],json.dumps(doc)),respect_bubbles=True,bubble_mask=bubble,bubble_failure_policy='preserve_review')
    assert not report['regions'] and report['needs_review'] and not alpha.any()
    assert report.get('page_status')!='no_text_detected' and report['skip_reason']=='bubble_regions_preserved'


class ReviewClient(FakeComfy):
    def history(self,ident):
        history=super().history(ident)
        if not history:return history
        g=self.jobs[ident]['graph'];final=P.workflow_bindings(g)['final'];apply=g[final]['inputs']['images'][0]
        history['outputs'][apply]={'manga_lettering_report':[{'schema':1,'needs_review':True,'protected_boxes_pixels':[[20,15,70,40]],
            'lettering_review':[{'id':'r1','parent_id':'r1','bbox_pixels':[20,15,70,40],'reason':'unverified_bubble_ownership','diagnostic':{'code':'bubble_source_crossing'}}]}]}
        return history


def test_folder_does_not_report_preserved_lettering_as_completed(tmp_path):
    make_page(tmp_path/'input/1.png');runner=project(tmp_path,ReviewClient());report=runner.run()
    assert report['counts']=={'needs_review':1}
    state=runner.state(runner.pages[0]);assert state['reason']=='unverified_bubble_ownership' and state['lettering_review'][0]['id']=='r1'


def test_folder_checks_new_preservation_pixels_against_original(tmp_path):
    class Broken(ReviewClient):
        def submit(self,prompt,ident,token):
            answer=super().submit(prompt,ident,token)
            data=BytesIO();Image.new('RGB',(140,90),'red').save(data,format='PNG');self.jobs[ident]['bytes']=data.getvalue();return answer
    make_page(tmp_path/'input/1.png');runner=project(tmp_path,Broken())
    with pytest.raises(P.ProtocolError,match='preserved source pixels'):runner.run()


def source(count=9):
    return {'regions':[{'id':f'r{i+1}','bbox':[0,0,100,100],'source':'短い原文です'} for i in range(count)]}


def invoke(data,**opts):return N.MangaTranslate().translate(N.encode(data),'http://fixture/v1','model','Korean','',4096,300,**opts)[0]


def test_short_page_length_response_splits_ids_keeps_context_and_discards_partial(monkeypatch):
    calls=[];page=source();monkeypatch.setattr(N.translation_protocol,'failure_root',lambda:pytest.fail('Successful recovery wrote failure'))
    def api(*args):
        payload=args[-1];calls.append(payload);body=json.loads(payload['messages'][1]['content']);ids=[r['id'] for r in body['regions']]
        if len(ids)>4:return reply('{"translations":[{"id":"r1","target":"LEAK"}'+('x'*8203),'length')
        assert len(body['page_context'])==9
        return reply(N.encode({'translations':[{'id':i,'target':'정상 번역'} for i in reversed(ids)]}))
    monkeypatch.setattr(N,'api_json',api);result=json.loads(invoke(page))
    assert [r['id'] for r in result['regions']]==[r['id'] for r in page['regions']]
    assert len(calls)==5 and result['translation_metadata']['requests']==5
    assert all(c['max_tokens']==4096 for c in calls) and all(r['target']=='정상 번역' for r in result['regions'])
    assert 'LEAK' not in json.dumps(result)
    for call in calls:
        ids=[r['id'] for r in json.loads(call['messages'][1]['content'])['regions']]
        assert call['response_format']['json_schema']['schema']['properties']['translations']['items']['properties']['id']['enum']==ids


def test_request_budget_bounds_recovery_and_records_all_attempts(monkeypatch,tmp_path):
    calls=[];monkeypatch.setattr(N.translation_protocol,'failure_root',lambda:tmp_path)
    def api(*args):calls.append(args[-1]);return reply('truncated','length')
    monkeypatch.setattr(N,'api_json',api)
    with pytest.raises(ValueError,match='budget exhausted'):invoke(source(),request_budget=3)
    saved=json.loads(next(tmp_path.glob('*.json')).read_text())
    assert len(calls)==len(saved['attempts'])==3 and all(a['region_ids'] for a in saved['attempts'])


def test_single_region_regenerates_once_without_continuing_broken_answer(monkeypatch):
    calls=[]
    def api(*args):
        calls.append(args[-1]);return reply('partial','length') if len(calls)==1 else reply('{"translations":[{"id":"r1","target":"번역"}]}')
    monkeypatch.setattr(N,'api_json',api);result=json.loads(invoke(source(1)))
    assert len(calls)==2 and result['regions'][0]['target']=='번역'
    assert 'partial' not in json.dumps(calls[1]['messages'])


def test_child_failure_never_returns_partial_page(monkeypatch,tmp_path):
    calls=[];monkeypatch.setattr(N.translation_protocol,'failure_root',lambda:tmp_path)
    def api(*args):
        calls.append(args[-1]);ids=[r['id'] for r in json.loads(args[-1]['messages'][1]['content'])['regions']]
        if len(calls)==1:return reply('partial','length')
        if ids==['r1']:return reply('{"translations":[{"id":"r1","target":"번역"}]}')
        return reply('partial','length')
    monkeypatch.setattr(N,'api_json',api)
    with pytest.raises(ValueError,match='did not finish normally'):invoke(source(2))
    saved=json.loads(next(tmp_path.glob('*.json')).read_text());assert len(calls)==4 and len(saved['attempts'])==4


@pytest.mark.parametrize('change',[{'parent_id':['r1']},{'bbox_pixels':[0,0,9000,10]}])
def test_malformed_lettering_review_cannot_waive_preservation_checks(tmp_path,change):
    class Invalid(ReviewClient):
        def history(self,ident):
            value=super().history(ident)
            if value:
                for output in value['outputs'].values():
                    if 'manga_lettering_report' in output:output['manga_lettering_report'][0]['lettering_review'][0].update(change)
            return value
    make_page(tmp_path/'input/1.png');runner=project(tmp_path,Invalid())
    with pytest.raises(P.ProtocolError):runner.run()


def test_server_ignoring_paragraph_output_budget_retries_only_translation(monkeypatch,tmp_path):
    calls=[];monkeypatch.setattr(N.translation_protocol,'failure_root',lambda:tmp_path)
    def api(*args):
        calls.append(args[-1]);return reply(json.dumps({'translations':[{'id':'r1','target':'가'*2049}]}))
    monkeypatch.setattr(N,'api_json',api)
    with pytest.raises(ValueError,match='2048-character'):invoke(source(1))
    assert len(calls)==2
    assert calls[0]['response_format']['json_schema']['schema']['properties']['translations']['items']['properties']['target']['maxLength']==2048
