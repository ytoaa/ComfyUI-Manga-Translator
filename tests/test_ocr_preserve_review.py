"""Rejected OCR is preserved, never a partial source or a successful empty crop."""
import importlib
import json
from pathlib import Path
import sys
import types

import numpy as np
from PIL import Image, ImageDraw
import pytest
import torch

ROOT=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('ocr_preserve_tests');pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
M=importlib.import_module(pkg.__name__+'.models')
N=importlib.import_module(pkg.__name__+'.nodes')
H=importlib.import_module(pkg.__name__+'.adapters.hayai')


def crop():
    image=Image.new('RGB',(120,60),'white');draw=ImageDraw.Draw(image)
    for x in range(10,110,15):draw.rectangle((x,10,x+8,40),outline='black',width=2)
    return torch.from_numpy(np.asarray(image,np.float32)/255)[None]


@pytest.mark.parametrize('adapter_code',[None,'ocr_repetition_loop','ocr_token_limit'])
def test_rejected_region_reaches_collector_as_protected_review_not_translation(monkeypatch,adapter_code):
    monkeypatch.setattr(M,'_save_ocr_failure',lambda *a:'diagnostic.json')
    class Model:
        calls=0
        def ocr(self,*a,**kw):
            self.calls+=1
            if adapter_code:raise H.HayaiOutputError(adapter_code)
            return {'text':'<UNK>'}
    model=Model()
    text,raw,previews=M.MangaOCRAdaptive().read(crop(),model,line_split=False,
        quality_guard=True,failure_policy='preserve_review')
    report=json.loads(raw)
    assert text=='' and len(previews)==1 and model.calls<=2
    assert report['status']=='ocr_quality_rejected' and report['needs_review']
    assert not report['ocr_skipped']
    data={'image_width':400,'image_height':200,'regions':[
        {'id':'bad','bbox':[100,100,300,400],'edit_bbox_pixels':[40,20,120,80]},
        {'id':'good','bbox':[600,100,900,400],'edit_bbox_pixels':[240,20,360,80]}]}
    output=json.loads(N.MangaCollectOCR().collect([text,'확인한 원문'],[json.dumps(data)],[raw,'{}'])[0])
    assert [r['id'] for r in output['regions']]==['good']
    assert output['needs_review'] and output['review_reason']=='ocr_quality_rejected'
    assert output['boundary_review']['protected_boxes_pixels']==[[40,20,120,80]]
    assert output['ocr_rejected_regions'][0]['id']=='bad'


def test_later_line_failure_discards_earlier_text_in_same_region(monkeypatch):
    source=M.pil_image(crop())
    monkeypatch.setattr(M,'_ocr_line_images',lambda _: [source,source])
    monkeypatch.setattr(M,'_save_ocr_failure',lambda *a:'diagnostic.json')
    class Model:
        calls=0
        def ocr(self,*a,**kw):
            self.calls+=1
            return {'text':'확인한 첫 행' if self.calls==1 else '<UNK>'}
    text,raw,_=M.MangaOCRAdaptive().read(crop(),Model(),failure_policy='preserve_review')
    assert text=='' and json.loads(raw)['status']=='ocr_quality_rejected'


@pytest.mark.parametrize('failure',[RuntimeError('model failed'),H.HayaiOutputError('ocr_invalid_output')])
def test_runtime_and_malformed_model_output_still_fail(monkeypatch,failure):
    monkeypatch.setattr(M,'_save_ocr_failure',lambda *a:None)
    class Model:
        def ocr(self,*a,**kw):raise failure
    with pytest.raises(type(failure),match=str(failure)):
        M.MangaOCRAdaptive().read(crop(),Model(),failure_policy='preserve_review')


def test_rejected_region_closes_overlapping_edit_ownership_before_cleanup():
    data={'image_width':400,'image_height':200,'regions':[
        {'id':'a','bbox':[0,0,100,100],'edit_bbox_pixels':[10,10,90,60]},
        {'id':'b','bbox':[0,0,100,100],'edit_bbox_pixels':[80,20,150,70]},
        {'id':'c','bbox':[0,0,100,100],'edit_bbox_pixels':[140,20,190,70]},
        {'id':'d','bbox':[600,500,900,900],'edit_bbox_pixels':[240,100,360,180]}]}
    rejected={'status':'ocr_quality_rejected','ocr_skipped':False,'needs_review':True,
              'quality_failure':{'code':'ocr_unrecognized_span','policy':'preserve_review'}}
    result=json.loads(N.MangaCollectOCR().collect(['','둘','셋','넷'],[json.dumps(data)],
        [json.dumps(rejected),'{}','{}','{}'])[0])
    assert [r['id'] for r in result['regions']]==['d']
    assert result['ocr_empty_regions']==['a','b','c'] and len(result['boundary_review']['protected_boxes_pixels'])==3


def test_forged_empty_rejection_and_invalid_plans_are_not_accepted():
    data={'image_width':400,'image_height':200,'regions':[{'id':'a','bbox':[0,0,100,100]}]}
    with pytest.raises(ValueError,match='empty/invalid OCR'):
        N.MangaCollectOCR().collect([''],[json.dumps(data)],[json.dumps({'status':'ocr_quality_rejected'})])
    with pytest.raises(ValueError,match='region plan'):
        M.MangaOCRAdaptive().read(crop(),None,region_plan_json='[]',failure_policy='preserve_review')
