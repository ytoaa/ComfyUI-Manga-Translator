from pathlib import Path
import importlib.util
import sys
import types

from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('manga_detail_pipeline_tests')
pkg.__path__=[str(ROOT)]
sys.modules[pkg.__name__]=pkg

spec=importlib.util.spec_from_file_location(pkg.__name__+'.models',ROOT/'models.py')
M=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=M
spec.loader.exec_module(M)

mask_spec=importlib.util.spec_from_file_location(pkg.__name__+'.mask_nodes',ROOT/'mask_nodes.py')
K=importlib.util.module_from_spec(mask_spec)
sys.modules[mask_spec.name]=K
mask_spec.loader.exec_module(K)


def test_detail_detector_tiles_long_axis_and_maps_back_to_page(monkeypatch):
    source=Image.new('RGB',(1600,640),'white')
    monkeypatch.setattr(M,'pil_image',lambda images:source)

    calls=[]
    class Model:
        def detect(self,image,thresholds):
            calls.append(image.size)
            detections=[]
            if len(calls)==3:
                detections=[{'label':'text','score':0.9,'bbox':[164.,100.,264.,140.],
                             'mask':{'x':164,'y':100,'width':100,'height':40,'runs':[4000]}}]
            return {'protocol':1,'image_width':image.width,'image_height':image.height,
                    'model':'fake','revision':'test','detections':detections}

    result=M.MangaDetectorDetail().detect(object(),Model(),detail_mode='2x',detail_overlap=64,
        text=.25,onomatopoeia=.2,bubble=.5,panel=.5)[0]
    assert calls==[(1600,640),(864,640),(864,640)]
    assert result['detail_detection']['grid']==[2,1]
    assert result['detail_detection']['tiles']==2
    assert result['detections'][0]['bbox']==[900.,100.,1000.,140.]
    assert result['detections'][0]['mask']['x']==900


def test_tight_ocr_crop_removes_blank_margin():
    image=Image.new('RGB',(160,80),'white')
    draw=ImageDraw.Draw(image)
    draw.rectangle((50,25,110,50),fill='black')
    crop=M._tight_ocr_image(image)
    assert crop.width < image.width
    assert crop.height < image.height
    assert crop.width >= 61
    assert crop.height >= 26


def test_tight_crop_preserves_small_trailing_punctuation():
    import numpy as np
    image=Image.new('RGB',(1022,78),'white')
    draw=ImageDraw.Draw(image)
    for x in range(25,900,25): draw.rectangle((x,30,x+10,49),fill='black')
    draw.rectangle((1000,40,1001,42),fill='black')
    crop=M._tight_ocr_image(image)
    assert np.all(np.asarray(crop)==0,axis=2).sum() == np.all(np.asarray(image)==0,axis=2).sum()


def test_adaptive_ocr_uses_larger_patch_budget_for_small_text(monkeypatch):
    source=Image.new('RGB',(100,100),'white')
    source.putpixel((0,0),(0,0,0))  # Exercise sizing, not the uniform-crop bypass.
    small=Image.new('RGB',(160,32),'white')
    large=Image.new('RGB',(160,80),'white')
    monkeypatch.setattr(M,'pil_image',lambda images:source)
    monkeypatch.setattr(M,'_ocr_line_images',lambda image:[small,large])

    calls=[]
    class Model:
        def ocr(self,image,options,max_patches):
            calls.append((image.size,max_patches,options.max_new_tokens))
            return {'text':'small' if len(calls)==1 else 'large'}

    result=M.MangaOCRAdaptive().read(object(),Model(),max_new_tokens=256,base_patches=512,
        small_text_patches=1024,small_text_px=48,line_split=True,tight_crop=False,
        repetition_penalty=1.,retry_on_repetition=True)
    assert result[0]=='small\nlarge'
    assert __import__('json').loads(result[1])['chunk_count'] == 2
    assert calls==[((160,32),1024,256),((160,80),512,256)]


def test_detection_mask_decodes_rle_into_page_mask():
    result={'protocol':1,'image_width':4,'image_height':2,'detections':[
        {'label':'text','score':.9,'bbox':[1,0,3,2],
         'mask':{'x':1,'y':0,'width':2,'height':2,'runs':[0,4]}}]}
    mask=K.MangaDetectionMask().make(result,False)[0].numpy()
    assert mask.shape==(1,2,4)
    assert mask[0,:,1:3].sum()==4
    assert mask.sum()==4
