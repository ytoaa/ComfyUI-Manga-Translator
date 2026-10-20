"""Optional model contracts; model quality is measured separately on private inputs."""
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import types
import numpy as np
from PIL import Image
import pytest
ROOT=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('alternative_tests');pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
A=importlib.import_module(pkg.__name__+'.alternative_models');R=importlib.import_module(pkg.__name__+'.adapters.alternative_runtime');I=importlib.import_module(pkg.__name__+'.inpaint_tiles')


def test_ctc_collapse_repeats_with_blank_and_reject_invalid_probabilities():
    ids=[1,1,0,1,2,2,0];p=np.zeros((1,len(ids),3),np.float32)
    p[0,np.arange(len(ids)),ids]=1
    assert R.ctc_decode(p,['','あ','い'])==('ああい',1.)
    p[:]=0;p[:,:,0]=1;assert R.ctc_decode(p,['','あ','い'])==('',0.)
    p[0,1,2]=np.nan
    with pytest.raises(ValueError,match='probabilities'):R.ctc_decode(p,['','あ','い'])


def test_vertical_recognition_rotates_and_converts_bgr_with_zero_padding():
    im=np.zeros((40,10,3),np.uint8);im[:20]=[255,0,0];im[20:]=[0,0,255]
    x=R.recognition_input(Image.fromarray(im));assert x.shape==(1,3,48,320)
    assert x[0,2,20,10]>.9 and x[0,0,20,10]<-.9
    assert x[0,0,20,180]>.9 and x[0,2,20,180]<-.9
    assert np.all(x[:,:,:,192:]==0)


def test_candidates_without_actual_ink_protect_source_not_fake_rectangle_masks():
    image=Image.new('RGB',(80,60));ink=np.zeros((60,80),bool)
    result=R.detection_result('ctd',image,[[10,12,40,42]],[.9],ink,'test')
    assert result['detections']==[] and result['needs_review']
    assert result['boundary_review']['protected_boxes_pixels']==[[10,12,40,42]]
    ink[20:25,22:25]=True
    found=R.detection_result('ctd',image,[[10,12,40,42]],[.9],ink,'test')['detections'][0]
    K=importlib.import_module(pkg.__name__+'.mask_nodes');local,bounds=K._decode_mask(found['mask'],80,60)
    assert tuple(bounds)==(10,12,30,30) and int(local.sum())==15
    assert result['capabilities']['bubble'] is False and result['capabilities']['sfx_classification'] is False


def test_acquisition_hashes_then_reuses_and_preserves_modified_bundle(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(models_dir=str(tmp_path)))
    payload=b'pinned';spec={'repository':'test','revision':'one','files':{'x.bin':hashlib.sha256(payload).hexdigest()},'urls':{'x.bin':'https://invalid.example/model'}}
    monkeypatch.setitem(A.SPECS,'fixture',spec);calls=[]
    monkeypatch.setattr(A,'urlopen',lambda *a,**k:(calls.append(a)or io.BytesIO(payload)))
    folder=A.ensure('fixture');assert A.ensure('fixture',False)==folder and len(calls)==1
    (folder/'x.bin').write_bytes(b'edited')
    with pytest.raises(ValueError,match='incomplete or modified'):A.ensure('fixture')
    assert (folder/'x.bin').read_bytes()==b'edited'


def test_failed_sha_never_installs_partial_bundle(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(models_dir=str(tmp_path)))
    monkeypatch.setitem(A.SPECS,'bad',{'repository':'test','revision':'one','files':{'x':'0'*64},'urls':{'x':'https://invalid.example/model'}})
    monkeypatch.setattr(A,'urlopen',lambda *a,**k:io.BytesIO(b'wrong'))
    with pytest.raises(ValueError,match='SHA256'):A.ensure('bad')
    assert not list((tmp_path/'manga_translator/alternatives').iterdir())


def test_generation_bound_handle_refuses_changed_weights_before_runtime(tmp_path,monkeypatch):
    (tmp_path/'model.bin').write_bytes(b'pinned');monkeypatch.setitem(A.SPECS,'bound',{'repository':'test','revision':'one','files':{'model.bin':hashlib.sha256(b'pinned').hexdigest()},'urls':{}})
    model=A.Model('bound',tmp_path);(tmp_path/'model.bin').write_bytes(b'changed')
    with pytest.raises(ValueError,match='bundle changed'):model.inpaint(None,None)


def test_changed_dependency_also_refuses_inference(tmp_path,monkeypatch):
    parent_folder=tmp_path/'parent';child_folder=tmp_path/'child'
    for folder in (parent_folder,child_folder):folder.mkdir();(folder/'x').write_bytes(b'pinned')
    monkeypatch.setitem(A.SPECS,'dependency',{'repository':'test','revision':'one','files':{'x':hashlib.sha256(b'pinned').hexdigest()},'urls':{}})
    model=A.Model('dependency',child_folder);parent=A.Model('dependency',parent_folder,{'child':model})
    (child_folder/'x').write_bytes(b'changed')
    with pytest.raises(ValueError,match='bundle changed'):parent._verify()


def test_empty_plan_skips_unconnected_lazy_model():
    page=np.ones((60,80,3),np.float32);mask=np.zeros((60,80),bool);plan=I.make_plan(page,mask,mask)
    node=A.MangaLocalInpaint();assert node.check_lazy_status(plan,model=None)==[]
    output,raw=node.finish(plan);assert np.array_equal(output[0].numpy(),page)
    assert json.loads(raw)['local_model_tiles']==0


def test_actual_assembly_masks_candidates_and_preserves_protected_source():
    page=np.full((100,160,3),.8,np.float32);page[20:35,20:60]=0;page[60:75,100:130]=0
    source=np.zeros((100,160),bool);source[20:35,20:60]=True;source[60:75,100:130]=True
    doc=json.dumps({'image_width':160,'image_height':100,'regions':[],'boundary_review':{'schema':1,'reason':'test','protected_boxes_pixels':[[95,55,140,85]]}})
    plan=I.make_plan(page,source,source,uniform_fill=False,regions_json=doc)
    class Model:
        key='test';cache_identity={}
        def inpaint(self,image,mask):return np.ones_like(image)
    output,raw=A.MangaLocalInpaint().finish(plan,Model(),blend_width=0);result=output[0].numpy()
    assert np.array_equal(result[~plan['cleanup_mask']],page[~plan['cleanup_mask']])
    assert np.array_equal(result[55:85,95:140],page[55:85,95:140])
    assert np.all(result[20:35,20:60]==1) and json.loads(raw)['local_model_tiles']>0


def test_unchanged_prediction_refused_before_lettering():
    page=np.ones((60,100,3),np.float32);page[20:35,20:60]=0;mask=np.zeros((60,100),bool);mask[20:35,20:60]=True
    plan=I.make_plan(page,mask,mask,uniform_fill=False)
    class Model:
        key='unchanged';cache_identity={}
        def inpaint(self,image,mask):return image.copy()
    with pytest.raises(ValueError,match='retained nearly all'):A.MangaLocalInpaint().finish(plan,Model())


def test_alternative_dependencies_in_checkpoint_identity(monkeypatch):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace())
    S=importlib.import_module(pkg.__name__+'.stage_cache')
    value=S.model_identity('MangaAlternativeDetectorModel',{'engine':'PP-OCRv6 + CTD ink'})
    assert set(value)=={'ctd','pp-det'} and value['ctd']['files']==A.SPECS['ctd']['files']
    assert S.model_identity('MangaOCRModel',{'engine':A.PADDLE_ENGINE})['files']==A.SPECS['pp-rec']['files']


def test_optional_declarations_dont_eagerly_import_inference_and_requirements_ship():
    import ast
    parsed=ast.parse((ROOT/'adapters/alternative_runtime.py').read_text());imports=[n for n in parsed.body if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert not any('onnxruntime' in ast.unparse(n)or 'transformers' in ast.unparse(n)for n in imports)
    requirements=(ROOT/'requirements-alternatives.txt').read_text().lower();assert 'onnxruntime' not in requirements
    sys.path.insert(0,str(ROOT/'tools'));from package_style_lettering import runtime_file
    assert runtime_file(Path('requirements-alternatives.txt'))
