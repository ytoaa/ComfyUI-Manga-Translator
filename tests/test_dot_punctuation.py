"""Pure dot geometry, normal OCR fallbacks and exact source-pixel preservation."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image,ImageDraw
import pytest
import torch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dot_tests',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from dot_tests import models as M, nodes as N, ocr_policy as P
from dot_tests.lettering import core,hybrid
from dot_tests.lettering.nodes import MangaLetterPrepare


def dots(count=9,horizontal=False,bright=False,hollow=False):
    picture=Image.new('RGB',(34,max(268,(count-1)*29+36)),'#777777' if bright else 'white')
    draw=ImageDraw.Draw(picture)
    for i in range(count):
        box=(12,9+i*29,24,21+i*29)
        if hollow:draw.ellipse(box,outline='white' if bright else 'black',width=2)
        else:draw.ellipse(box,fill='white' if bright else 'black')
    return picture.rotate(90,expand=True) if horizontal else picture


def tensor(image):return torch.from_numpy(np.asarray(image,np.float32).copy()/255)[None]


@pytest.mark.parametrize('horizontal,bright',[(False,False),(True,False),(False,True),(True,True)])
def test_round_aligned_dots_have_observed_count_and_orientation(horizontal,bright):
    picture=dots(horizontal=horizontal,bright=bright)
    original=picture.tobytes();evidence=P.dot_punctuation(picture)
    assert evidence['count']==9 and evidence['text']=='・'*9
    assert evidence['axis']==('horizontal' if horizontal else 'vertical')
    assert len(evidence['component_boxes'])==9 and picture.tobytes()==original
    assert P.text_problem('・'*9,picture) is None
    assert P.text_problem('・'*12,picture)=='short_repetition'
    assert P.text_problem('内'*12,picture)=='short_repetition'


@pytest.mark.parametrize('case',['two','too_many','hollow','mixed','square','uneven','misaligned','cropped','faint','blank','speck'])
def test_ambiguous_or_non_dot_inputs_keep_normal_ocr(case):
    picture=dots(2 if case=='two' else 25 if case=='too_many' else 9,hollow=case=='hollow')
    draw=ImageDraw.Draw(picture)
    if case=='mixed':draw.line((3,80,3,120),fill='black',width=2)
    if case=='square':draw.rectangle((12,9,24,21),fill='black')
    if case in ('uneven','misaligned','cropped'):
        draw.rectangle((10,6,26,23),fill='white')
        y=1 if case=='cropped' else 20 if case=='uneven' else 9
        x=3 if case=='misaligned' else 12
        draw.ellipse((x,y,x+12,y+12),fill='black')
    if case in ('faint','blank'):
        picture=Image.new('RGB',picture.size,'white');draw=ImageDraw.Draw(picture)
        if case=='faint':
            for i in range(9):draw.ellipse((12,9+29*i,24,21+29*i),fill='#dddddd')
    if case=='speck':draw.point((2,130),fill='black')
    assert P.dot_punctuation(picture) is None


def recognize(picture):
    class NoModel:
        def ocr(self,*args,**kwargs):pytest.fail('Verified pure dots must not invoke Hayai')
    return M.MangaOCRAdaptive().read(tensor(picture),NoModel(),quality_guard=True,
        split_long_lines=True,retry_on_layout_failure=True)


def source_document(picture):
    text,report,_=recognize(picture)
    manifest=N.encode({'image_width':picture.width,'image_height':picture.height,
        'regions':[{'id':'dots','kind':'text','bbox':[0,0,1000,1000],
                    'edit_bbox_pixels':[0,0,picture.width,picture.height]}]})
    return N.MangaCollectOCR().collect([text],[manifest],[report])[0]


def test_actual_report_dimensions_count_nine_without_generation_or_retry():
    picture=dots();assert picture.size==(34,268)
    text,raw,previews=recognize(picture)
    report=json.loads(raw)
    assert text=='・'*9 and report['verified_punctuation']['count']==9
    assert report['recognition_work_items']==1 and report['chunk_count']==1
    assert report['chunks'][0]['attempts'][0]['model_called'] is False
    assert len(previews)==1


def test_punctuation_only_translation_and_lettering_preserve_exact_original(monkeypatch):
    picture=dots();source=source_document(picture)
    monkeypatch.setattr(N,'api_json',lambda *a,**k:pytest.fail('No translation API for verified punctuation'))
    target=N.MangaTranslate().translate(source,'unused','', 'Korean','',4096,300)[0]
    value=json.loads(target)
    assert value['regions'][0]['target']=='・'*9 and value['translation_skipped']
    document,support=MangaLetterPrepare().prepare(tensor(picture),target)
    prepared=json.loads(document)
    assert prepared['regions']==[] and len(prepared['source_preservation'])==1
    original=tensor(picture).numpy()[0];clean=np.ones_like(original)
    plan,_,report=hybrid.build_plan(original,clean,support.numpy()[0],document)
    output,alpha,render=hybrid.render_plan(plan)
    assert np.array_equal(output,original) and not alpha.any()
    assert json.loads(render)['skip_reason']=='source_preserved'
    assert not json.loads(report)['needs_review']
    ordinary,alpha,_=core.render_page(original,clean,support.numpy()[0],document)
    assert np.array_equal(ordinary,original) and not alpha.any()


def test_mixed_page_sends_only_words_and_preserves_every_original_id(monkeypatch):
    value=json.loads(source_document(dots()))
    value['regions'].append({'id':'words','kind':'text','bbox':[10,10,100,100],'source':'先生'})
    calls=[]
    def api(base,path,key,timeout,payload=None):
        calls.append(payload)
        assert path=='/chat/completions'
        requested=json.loads(payload['messages'][1]['content'])['regions']
        assert requested==[{'id':'words','source':'先生'}]
        return {'choices':[{'finish_reason':'stop','message':{
            'content':json.dumps({'translations':[{'id':'words','target':'선생님'}]})}}]}
    monkeypatch.setattr(N,'api_json',api)
    result=json.loads(N.MangaTranslate().translate(N.encode(value),'unused','fixture','Korean','',4096,300)[0])
    assert [row['id'] for row in result['regions']]==['dots','words']
    assert [row['target'] for row in result['regions']]==['・'*9,'선생님'] and len(calls)==1


def test_manual_translation_override_can_explicitly_replace_punctuation(monkeypatch):
    source=source_document(dots())
    override=json.dumps({'translations':[{'id':'dots','target':'…'}]})
    target=N.MangaTranslate().translate(source,'unused','','Korean','',4096,300,override)[0]
    document,_=MangaLetterPrepare().prepare(tensor(dots()),target)
    assert len(json.loads(document)['regions'])==1 and 'preserved_punctuation' not in json.loads(document)


def test_tampered_count_marker_is_rejected():
    value=json.loads(source_document(dots()));row=value['regions'][0]
    row['source']='・'*12
    with pytest.raises(ValueError,match='verified punctuation'):
        N.MangaTranslate().translate(N.encode(value),'unused','fixture','Korean','',4096,300)


def test_normal_ocr_remains_available_when_quality_guard_is_off():
    class Model:
        calls=0
        def ocr(self,*args,**kwargs):self.calls+=1;return {'text':'MODEL OUTPUT'}
    model=Model();text,_,_=M.MangaOCRAdaptive().read(tensor(dots()),model,quality_guard=False)
    assert text=='MODEL OUTPUT' and model.calls==1


def test_punctuation_is_excluded_before_cleanup_and_not_reported_as_an_empty_page(monkeypatch):
    from dot_tests.page_edit import MangaPageEditPlan
    from dot_tests.inpaint_tiles import make_plan,assemble
    picture=dots();source=source_document(picture)
    monkeypatch.setattr(N,'api_json',lambda *a,**k:pytest.fail('Unexpected punctuation translation'))
    translated=N.MangaTranslate().translate(source,'unused','','Korean','',4096,300)[0]
    raw=torch.from_numpy((np.asarray(picture).mean(axis=2)<128).astype(np.float32))[None]
    doc,source_mask,cleanup_mask,_,_=MangaPageEditPlan().plan(tensor(picture),translated,raw,raw)
    assert not source_mask.any() and not cleanup_mask.any()
    original=tensor(picture).numpy()[0]
    plan=make_plan(original,source_mask[0].numpy(),cleanup_mask[0].numpy(),regions_json=doc,recover_uniform_ink=True)
    result,_=assemble(plan,[])
    assert not plan['tiles'] and np.array_equal(result,original)
    prepared,support=MangaLetterPrepare().prepare(tensor(picture),doc)
    lettering,_,_=hybrid.build_plan(original,result,support[0].numpy(),prepared)
    output,alpha,report=hybrid.render_plan(lettering)
    assert np.array_equal(output,original) and not alpha.any()
    assert json.loads(report)['skip_reason']=='source_preserved'
    assert 'page_status' not in json.loads(report)
