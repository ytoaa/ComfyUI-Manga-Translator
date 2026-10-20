"""The raw-candidate guard must not count certified source aliases twice."""
import importlib.util
import sys
import types
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
ROOT=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('source_budget_tests');pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
import importlib
P=importlib.import_module(pkg.__name__+'.detection_policy')

def region(pixels=None, **extra):
    if pixels is None:pixels=np.ones((10,10),dtype=bool)
    return {'label':'text','score':.9,'bbox':[20,20,30,30],
        'mask':{'x':20,'y':20,'width':10,'height':10,'runs':P.rle(pixels)},**extra}

def test_alias_compaction_unions_every_observed_pixel_and_keeps_origins():
    a=np.ones((10,10),dtype=bool);a[0,0]=False
    b=np.ones((10,10),dtype=bool);b[-1,-1]=False
    items=[region(a,tile_provenance={'stage':'full','clipped_edges':[]}),
           region(b,tile_provenance={'stage':'detail','clipped_edges':[],'window':[0,0,100,100]})]
    result=P._compact_complete_sources(items,100,100)
    assert len(result)==1
    decoded,_=P._decode_mask(result[0]['mask'],100,100)
    assert np.array_equal(decoded>.5,a|b)
    assert len(result[0]['source_provenance'])==2

@pytest.mark.parametrize('change', ['position','label','clipped','different_ink','missing_mask'])
def test_distinct_or_uncertified_sources_are_never_compacted(change):
    a,b=region(),region()
    if change=='position':b['bbox']=[21,20,31,30];b['mask']['x']=21
    if change=='label':b['label']='onomatopoeia'
    if change=='clipped':b['tile_provenance']={'clipped_edges':['left'],'window':[20,0,100,100]}
    if change=='different_ink':
        x=np.zeros((10,10),bool);x[:,:4]=True
        y=np.zeros((10,10),bool);y[:,6:]=True
        a,b=region(x),region(y)
    if change=='missing_mask':b.pop('mask')
    assert len(P._compact_complete_sources([a,b],100,100))==2

def test_budget_compacts_only_when_needed_and_still_rejects_unique_overflow(monkeypatch):
    monkeypatch.setattr(P,'_MAX_REGIONS',4)
    class Model:
        def __init__(self, unique=False):self.unique=unique;self.calls=0
        def detect(self,image,_):
            self.calls+=1
            origins=[(0,0),(0,0),(448,0),(0,0),(512,0),(1024,0),(0,64),(512,64),(1024,64)]
            ox,oy=origins[self.calls-1]
            x,y=550-ox,100-oy
            rows=[]
            if self.unique:
                for i in range(4):
                    r=region();x=20+self.calls*30+i*12
                    r['bbox']=[x,20,x+10,30];r['mask']['x']=x;rows.append(r)
            elif 0<=x and x+10<image.width and 0<=y and y+10<image.height:
                for i in range(4):
                    r=region();r['bbox']=[x,y,x+10,y+10];r['mask'].update(x=x,y=y);rows.append(r)
            return {'image_width':image.width,'image_height':image.height,'detections':rows}
    output=P.detail_detect(Image.new('RGB',(1600,640)),Model(),{},boundary_policy='preserve_review')
    budget=output['detail_detection']['candidate_budget']
    assert budget['raw_candidates']>4
    assert budget['retained_candidates']<=4
    assert budget['consolidated_sources']>0
    with pytest.raises(ValueError,match='too many regions'):
        P.detail_detect(Image.new('RGB',(1600,640)),Model(True),{},boundary_policy='preserve_review')
