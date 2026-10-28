"""Execution ownership, atomic cache snapshots and OCR positive controls."""
from copy import deepcopy
import json
from pathlib import Path
import uuid
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest
import torch

from tests.test_document_stages import D,C as K,row
from tests.test_canvas_execution import C,setup_book,execute_visible_graph
from tests.test_project_runner import P,graph
import importlib
M=importlib.import_module(D.__package__+'.models')


def tensor(image):return torch.from_numpy(np.asarray(image,np.float32).copy()/255)[None]


def start(tmp_path):
    engine,client,inputs,folder=setup_book(tmp_path);g=graph();source=P.workflow_bindings(g)['load'];pid=str(uuid.uuid4())
    first=engine.begin(inputs,folder,g,client,pid,source,'시작·재개')
    return engine,client,inputs,folder,g,source,pid,first


def test_rejected_continuation_changes_no_persisted_records(tmp_path):
    engine,client,inputs,folder,g,source,pid,first=start(tmp_path)
    execute_visible_graph(client,pid,first);engine.resolve(folder,first['ticket']['run_id'],pid,client)
    before={p.relative_to(folder):p.read_bytes() for p in folder.rglob('*.json')}
    changed=deepcopy(g)
    next(n for n in changed.values() if n['class_type']=='MangaLetterPlan')['inputs']['default_font']='NanumGothic-Regular.ttf'
    out=engine.begin(inputs,folder,changed,client,str(uuid.uuid4()),source,'시작·재개',{'run_id':first['ticket']['run_id'],'source_node':source})
    assert out['ticket'] is None
    assert before=={p.relative_to(folder):p.read_bytes() for p in folder.rglob('*.json')}


def test_resolver_uses_immutable_run_graph_when_compatibility_copy_changes(tmp_path):
    engine,client,_,folder,g,_,pid,first=start(tmp_path)
    (folder/'workflow.api.json').write_text('{}')
    execute_visible_graph(client,pid,first)
    assert engine.resolve(folder,first['ticket']['run_id'],pid,client)['continue']


def test_run_write_failure_keeps_attempt_identity_and_blocks_duplicate(tmp_path,monkeypatch):
    engine,client,inputs,folder=setup_book(tmp_path);g=graph();source=P.workflow_bindings(g)['load'];pid=str(uuid.uuid4())
    write=C._write_run;calls=[]
    def fail_once(*args):
        calls.append(1)
        if len(calls)==1:raise OSError('simulated run record write failure')
        return write(*args)
    monkeypatch.setattr(C,'_write_run',fail_once)
    out=engine.begin(inputs,folder,g,client,pid,source,'시작·재개')
    assert not out['ticket']
    state_path=next(folder.glob('pages/*/attempt-*/state.json'));state=P.read_json(state_path)
    assert state['prompt_id']==pid
    client.server.prompt_queue.running=[[0,pid,g,{'manga_project':state['submission_token']},[]]]
    saved=(folder/'canvas_run.json').read_bytes()
    retry=engine.begin(inputs,folder,g,client,str(uuid.uuid4()),source,'실패 재시도')
    assert retry['ticket'] is None and (folder/'canvas_run.json').read_bytes()==saved
    assert len(list(folder.glob('pages/*/attempt-*/state.json')))==1


def test_cache_refresh_during_read_cannot_mix_pixels_and_diagnostics(tmp_path,monkeypatch):
    monkeypatch.setattr(K,'root',lambda:tmp_path);key='a'*64;image=torch.ones(1,8,9,3)
    K.write(key,'image',image*0,'{"generation":"A"}')
    original=Path.open;swapped=[]
    class RefreshAfterRead:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):self.stream.close()
        def read(self,*args):
            raw=self.stream.read(*args)
            if not swapped:
                swapped.append(True);K.write(key,'image',image,'{"generation":"B"}')
            return raw
    def opening(path,*args,**kwargs):
        stream=original(path,*args,**kwargs)
        return RefreshAfterRead(stream) if path.name=='value.bin' and args==('rb',) else stream
    with patch.object(Path,'open',opening):value,report=K.read_entry(key,'image')
    assert swapped and value.mean()==0 and report['generation']=='A'
    value,report=K.read_entry(key,'image');assert value.mean()==1 and report['generation']=='B'


def test_interrupted_cache_refresh_is_a_miss_and_never_a_mixed_hit(tmp_path,monkeypatch):
    monkeypatch.setattr(K,'root',lambda:tmp_path);key='b'*64;image=torch.ones(1,8,9,3)
    K.write(key,'image',image*0,'{"generation":"A"}')
    replace=K.os.replace
    def fail_manifest(source,dest):
        if Path(dest).name=='manifest.json':raise OSError('simulated full disk')
        return replace(source,dest)
    with patch.object(K.os,'replace',fail_manifest),pytest.raises(OSError):
        K.write(key,'image',image,'{"generation":"B"}')
    assert K.read_entry(key,'image') is None
    assert not list(tmp_path.rglob('*.tmp'))


def test_latest_attempt_uses_numeric_order_after_width_overflow(tmp_path):
    from tests.test_project_runner import FakeComfy,make_page
    make_page(tmp_path/'input/1.png');book=P.Project(tmp_path/'input',tmp_path/'project',graph(),FakeComfy());book._prepare_project();page=book.pages[0]
    for number in (999999,1000000):
        state={**book._new(page),'attempt':number,'status':'failed'};book._save(state)
    assert book.state(page)['attempt']==1000000
    assert book._new(page)['attempt']==1000001


def positive_inputs():
    font=ImageFont.truetype(str(Path(__file__).resolve().parents[1]/'lettering/fonts/MangaSansKR-Fallback.ttf'),28)
    result={}
    for name,text,color in [('single-japanese','あ',0),('single-korean','가',0),('latin-I','I',0),
                            ('punctuation','… 。',0),('faint-text','あいうえお',253),('one-level-contrast','あいうえお',254)]:
        image=Image.new('RGB',(280,80),'white');ImageDraw.Draw(image).text((20,15),text,font=font,fill=(color,)*3);result[name]=image
    image=Image.new('RGB',(80,160),'white');draw=ImageDraw.Draw(image)
    for y,c in zip((10,50,90),'あいう'):draw.text((20,y),c,font=font,fill='black')
    result['vertical-text']=image
    image=Image.new('RGB',(280,80),'white');ImageDraw.Draw(image).line((120,20,120,50),fill='black',width=1);result['thin-stroke']=image
    return result


@pytest.mark.parametrize('name,image',positive_inputs().items())
def test_preflight_keeps_real_glyph_and_punctuation_controls(name,image):
    assert M._unverified_ocr_input(image) is None,name
    assert M.MangaOCRAdaptive().check_lazy_status(tensor(image),quality_guard=True)==['model']


@pytest.mark.parametrize('kind',['gradient','pixel','rule','noise'])
def test_weak_evidence_is_reviewed_not_certified_blank(kind):
    image=Image.new('RGB',(280,80),'white')
    if kind=='pixel':image.putpixel((3,3),(0,0,0))
    elif kind=='rule':ImageDraw.Draw(image).line((0,40,279,40),fill='black',width=1)
    elif kind=='gradient':image=Image.fromarray(np.broadcast_to(np.linspace(210,255,280,dtype=np.uint8)[None,:,None],(80,280,3)).copy())
    else:image=Image.fromarray(np.random.default_rng(2871).integers(252,256,size=(80,280,3),dtype=np.uint8))
    page=tensor(image);ocr=M.MangaOCRAdaptive()
    assert ocr.check_lazy_status(page,quality_guard=True)==[]
    text,raw,_=ocr.read(page,quality_guard=True)
    report=json.loads(raw)
    assert text=='' and report['status']=='unverified_input' and report['needs_review']
    assert 'empty_crop_verified' not in report
    N=importlib.import_module(D.__package__+'.nodes')
    manifest={'image_width':280,'image_height':80,'regions':[{'id':'r1','bbox':[0,0,1000,1000],'edit_bbox_pixels':[0,0,280,80]}]}
    out=json.loads(N.MangaCollectOCR().collect([text],[json.dumps(manifest)],[raw])[0])
    assert out['needs_review'] and out['review_reason']=='insufficient_ocr_input_evidence'
    assert out['boundary_review']['protected_boxes_pixels']==[[0,0,280,80]]


def test_empty_source_blocks_reject_without_mutating_document():
    data={'regions':[row()]};saved=deepcopy(data)
    with pytest.raises(ValueError,match='cannot be empty'):D.apply_edits(data,{'r1':{'blocks':[]}},'source')
    assert data==saved


def test_shared_document_budget_is_checked_at_emission_and_decode():
    N=importlib.import_module(D.__package__+'.nodes');limit=N.MAX_DOCUMENT_CHARACTERS
    with pytest.raises(ValueError,match='transport budget'):N.encode({'data':'a'*limit})
    with pytest.raises(ValueError,match='transport budget'):N.decode(' '* (limit+1))


def test_resident_backend_rejects_file_changes_before_inference(tmp_path,monkeypatch):
    weight=tmp_path/'model.safetensors';weight.write_bytes(b'old')
    class Backend:
        def detect(self,*args):pytest.fail('Changed resident model reached inference')
    backend=M._GenerationBoundBackend(Backend(),tmp_path,M._bundle_generation(tmp_path))
    weight.write_bytes(b'new')
    with pytest.raises(ValueError,match='Resident model bundle changed'):backend.detect(None,{})


def test_lazy_hit_freezes_one_generation_but_next_selection_checks_new_files(tmp_path,monkeypatch):
    import sys,types
    weight=tmp_path/'weights.bin';weight.write_bytes(b'old')
    g={'1':{'class_type':'UNETLoader','inputs':{'unet_name':'weights.bin'}},'2':{'class_type':'MangaCleanupCheckpoint','inputs':{'value':['1',0]}}}
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_full_path=lambda *a:str(weight)))
    monkeypatch.setattr(K,'root',lambda:tmp_path/'cache');node=K.MangaCleanupCheckpoint();image=torch.ones(1,8,9,3)
    first=node.checkpoint(image,image,prompt=g,unique_id='2');old_key=json.loads(first['result'][1])['stage_cache']['key']
    assert node.check_lazy_status(image,prompt=g,unique_id='2')==[]
    weight.write_bytes(b'new')
    frozen=node.checkpoint(image,prompt=g,unique_id='2');report=json.loads(frozen['result'][1])['stage_cache']
    assert report['key']==old_key and report['generation_frozen']
    assert node.check_lazy_status(image,prompt=g,unique_id='2')==['value']
    assert node._key(image,g,'2','',None)!=old_key


def test_auto_continuation_also_freezes_authored_edits(tmp_path):
    engine,client,inputs,folder,g,source,pid,first=start(tmp_path)
    execute_visible_graph(client,pid,first);engine.resolve(folder,first['ticket']['run_id'],pid,client)
    before={p.relative_to(folder):p.read_bytes() for p in folder.rglob('*.json')};changed=deepcopy(g)
    next(n for n in changed.values() if n['class_type']=='MangaReviewDocument')['inputs']['edits_json']='{"pages":{"new":{}},"identities":{}}'
    out=engine.begin(inputs,folder,changed,client,str(uuid.uuid4()),source,'시작·재개',{'run_id':first['ticket']['run_id'],'source_node':source})
    assert not out['ticket']
    assert before=={p.relative_to(folder):p.read_bytes() for p in folder.rglob('*.json')}


def test_corrupt_cache_diagnostics_invalidates_entire_entry(tmp_path,monkeypatch):
    monkeypatch.setattr(K,'root',lambda:tmp_path);key='c'*64
    K.write(key,'image',torch.ones(1,8,9,3),'{"quality":"A"}')
    path=tmp_path/key[:2]/key/'manifest.json';meta=json.loads(path.read_text());meta['report_json']='{"quality":"B"}';path.write_text(json.dumps(meta))
    assert K.read_entry(key,'image') is None


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-.1,1.1])
def test_empty_manifest_does_not_bypass_rgb_validation(value):
    image=torch.full((1,8,9,3),value)
    manifest=json.dumps({'regions':[],'crop_passthrough':True,'page_status':'no_text_detected','image_width':9,'image_height':8})
    with pytest.raises(ValueError,match='finite RGB'):M.MangaOCRAdaptive().read(image,manifest_json=manifest)
