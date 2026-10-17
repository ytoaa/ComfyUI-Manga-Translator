"""Unverified seams remain visible, protected, and explicitly incomplete."""
from copy import deepcopy
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('boundary_review_tests',ROOT/'__init__.py',
                                         submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from boundary_review_tests import detection_policy as D, boundary_review as B, region_policy as R
from boundary_review_tests import mask_nodes as M, inpaint_tiles as I
from boundary_review_tests.lettering import hybrid as H
from boundary_review_tests.adapters.model import rle


def item(box,score=.9):
    return {'label':'text','score':score,'bbox':list(box)}


def review(boxes):
    return {'schema':1,'reason':'unresolved_detection_boundary','protected_boxes_pixels':boxes}


def detection(size,items,protected):
    return {'protocol':1,'image_width':size[0],'image_height':size[1],
            'detections':items,'boundary_review':review(protected)}


class EmptyDetector:
    def detect(self,image,_):
        return {'image_width':image.width,'image_height':image.height,'detections':[]}


@pytest.mark.parametrize('box,edge,score',[
    ([1088,1556.7964,1122.7858,1600.1074],'left',.33832),
    ([465.2399,946.4260,747.2825,1152],'bottom',.25772),
    ([2392.6438,4048.0710,2446.8579,4416],'bottom',.26532),
    ([1791.9966,1088,2012.6008,1135.9130],'top',.25185),
])
def test_reported_fragments_are_preserved_without_claiming_recovery(box,edge,score,monkeypatch):
    # Coordinates from actual logs; model responses here are geometry doubles.
    monkeypatch.setattr(D,'_save_recovery_failure',lambda *_:'diagnostic.json')
    fragment={**item(box,score),'tile_provenance':{'window':[0,0,1152,1152],'clipped_edges':[edge]}}
    safe=item([3000,2000,3300,2300])
    kept,report=D._recover_boundaries(Image.new('RGB',(4200,6030)),EmptyDetector(),{},
                                     [safe,fragment],'preserve_review')
    assert kept==[safe] and report['unresolved_regions']==1
    audit=report['boundary_review']
    assert audit['fragments'][0]['coverage']==0 and audit['diagnostic_path']=='diagnostic.json'
    assert B.intersects(box,audit['protected_boxes_pixels'][0])


def test_touching_complete_regions_are_quarantined_transitively(monkeypatch):
    monkeypatch.setattr(D,'_save_recovery_failure',lambda *_:None)
    fragment={**item([100,100,180,180]),'tile_provenance':{'window':[0,0,180,180],'clipped_edges':['right']}}
    # Partial support, and a second paragraph touching its expanded protection.
    a=item([150,120,280,180]);b=item([285,130,340,175]);safe=item([500,400,580,460])
    kept,report=D._recover_boundaries(Image.new('RGB',(800,600)),EmptyDetector(),{},
                                     [fragment,a,b,safe],'preserve_review')
    assert kept==[safe] and report['boundary_review']['excluded_complete_regions']==2
    assert 0<report['boundary_review']['fragments'][0]['coverage']<.98
    assert len(report['boundary_review']['protected_boxes_pixels'])==3


def test_strict_mode_still_fails_and_bad_policy_is_rejected(monkeypatch):
    monkeypatch.setattr(D,'_save_recovery_failure',lambda *_:None)
    fragment={**item([100,100,180,180]),'tile_provenance':{'window':[0,0,180,180],'clipped_edges':['right']}}
    with pytest.raises(ValueError,match='unresolved clipped text'):
        D._recover_boundaries(Image.new('RGB',(800,600)),EmptyDetector(),{},[fragment],'strict')
    with pytest.raises(ValueError,match='Invalid boundary'):
        D.detail_detect(Image.new('RGB',(800,600)),EmptyDetector(),{},boundary_policy='skip')


def test_region_manifest_marks_partial_page_and_refuses_overlapping_resolution():
    data=detection((800,600),[item([400,100,600,200])],[[100,100,200,200]])
    manifest=json.loads(R.MangaDetectionRegionsResolved().convert(data)[0])
    assert len(manifest['regions'])==1 and manifest['needs_review']
    assert manifest['review_reason']=='unresolved_detection_boundary'
    data['detections']=[]
    empty=json.loads(R.MangaDetectionRegionsResolved().convert(data)[0])
    assert empty['no_text_reason']=='unresolved_detection_boundary'
    data['detections']=[item([150,100,300,200])]
    with pytest.raises(ValueError,match='overlaps preserved'):
        R.MangaDetectionRegionsResolved().convert(data)


def test_pixel_masks_and_grown_cleanup_cannot_erase_protected_artwork():
    data=detection((140,100),[],[[60,20,90,80]])
    mask=np.ones((60,100),bool)
    data['mask_fragments']=[{**item([20,20,120,80]),'mask':{
        'x':20,'y':20,'width':100,'height':60,'runs':rle(mask)}}]
    raw=M.MangaDetectionMask().make(data)[0].numpy()[0]
    assert not raw[20:80,60:90].any() and raw.sum()>0
    original=np.full((100,140,3),.7,np.float32)
    original[25:70,65:85]=.1
    doc=json.dumps({'regions':[],'image_width':140,'image_height':100,'boundary_review':data['boundary_review']})
    grown=np.ones((100,140),np.float32)
    plan=I.make_plan(original,raw,grown,uniform_fill=False,regions_json=doc)
    assert not plan['cleanup_mask'][20:80,60:90].any()
    assert all(not tile['mask'][max(0,20-tile['crop'][1]):max(0,80-tile['crop'][1]),
                                max(0,60-tile['crop'][0]):max(0,90-tile['crop'][0])].any()
               for tile in plan['tiles'])
    generated=[np.ones((*tile['mask'].shape,3),np.float32) for tile in plan['tiles']]
    output,_=I.assemble(plan,generated,strict_cleanup=False)
    assert np.array_equal(output[20:80,60:90],original[20:80,60:90])


def test_uniform_recovery_cannot_expand_back_into_protected_pixels():
    original=np.ones((100,180,3),np.float32)
    original[30:55,30:65]=0;original[30:55,75:100]=0
    raw=np.zeros((100,180),bool);raw[30:55,30:65]=True
    protected=[[75,20,110,65]]
    doc=json.dumps({'regions':[{'id':'r1','kind':'text','bbox':[100,150,650,700]}],
                    'image_width':180,'image_height':100,'boundary_review':review(protected)})
    plan=I.make_plan(original,raw,raw,regions_json=doc,recover_uniform_ink=True)
    assert np.array_equal(plan['base'][20:65,75:110],original[20:65,75:110])
    assert not plan['source_mask'][20:65,75:110].any()
    assert not plan['cleanup_mask'][20:65,75:110].any()


def test_lettering_restores_original_pixels_and_never_places_alpha_on_protection():
    spec=importlib.util.spec_from_file_location('review_lettering_fixture',ROOT/'tests/test_hybrid_lettering.py')
    T=importlib.util.module_from_spec(spec);spec.loader.exec_module(T)
    original,clean,mask,doc=T.fixture('번역',width=400,height=200,box=[50,50,300,100])
    original=original.copy();original[70:130,315:340]=.15
    protected=[[315,70,340,130]]
    data=json.loads(doc);data['boundary_review']=review(protected)
    plan,_,report=H.build_plan(original,clean,mask,json.dumps(data),fit_policy='readable')
    output,alpha,render=H.render_plan(plan)
    assert np.array_equal(output[70:130,315:340],original[70:130,315:340])
    assert not alpha[70:130,315:340].any() and alpha.sum()>0
    assert json.loads(report)['needs_review'] and json.loads(render)['needs_review']
    detected=detection((400,200),[],protected)
    with pytest.raises(ValueError,match='protection missing or changed'):
        H.build_plan(original,clean,mask,doc,detection_result=detected)


def test_lettering_refuses_every_fit_that_would_touch_protection():
    spec=importlib.util.spec_from_file_location('review_lettering_blocked_fixture',ROOT/'tests/test_hybrid_lettering.py')
    T=importlib.util.module_from_spec(spec);spec.loader.exec_module(T)
    original,clean,mask,doc=T.fixture('번역')
    data=json.loads(doc);data['boundary_review']=review([[0,0,320,120]])
    plan,_,_=H.build_plan(original,clean,mask,json.dumps(data))
    with pytest.raises(ValueError,match='preserved boundary pixels'):
        H.render_plan(plan)


def test_letter_prepare_propagates_protection_and_crop_margin_cannot_cross_it():
    import torch
    from boundary_review_tests.nodes import MangaRegionCrops
    from boundary_review_tests.lettering.nodes import MangaLetterPrepare
    picture=torch.ones((1,100,200,3))
    source={'image_width':200,'image_height':100,'regions':[
        {'id':'r1','bbox':[100,200,400,800],'source':'SOURCE','target':'번역'}],
        'needs_review':True,'boundary_review':review([[85,20,110,80]])}
    # The logical box ends at x=80; its normal 8px edit margin is unsafe.
    with pytest.raises(ValueError,match='margin overlaps'):
        MangaRegionCrops().crop(picture,json.dumps(source))
    with pytest.raises(ValueError,match='margin overlaps'):
        MangaRegionCrops().crop(picture,json.dumps(source),ocr_padding=12,edit_margin=0)
    prepared,_=MangaLetterPrepare().prepare(picture,json.dumps(source),region_padding=0)
    assert json.loads(prepared)['boundary_review']==source['boundary_review']


@pytest.mark.parametrize('box',[[0,0,900,100],[-1,0,10,10],[0,0,0,10],[0,0,float('nan'),10]])
def test_malformed_protection_is_not_silently_ignored(box):
    with pytest.raises(ValueError,match='Boundary protection'):
        B.boxes({'boundary_review':review([box])},800,600)


def load_runner_tests():
    spec=importlib.util.spec_from_file_location('review_runner_fixture',ROOT/'tests/test_project_runner.py')
    T=importlib.util.module_from_spec(spec);sys.modules[spec.name]=T;spec.loader.exec_module(T)
    return T


def test_optional_default_preserves_existing_project_fingerprint():
    T=load_runner_tests();graph=T.graph();old=deepcopy(graph)
    detector=next(n for n in graph.values() if n['class_type']=='MangaDetectorDetail')
    old_detector=next(n for n in old.values() if n['class_type']=='MangaDetectorDetail')
    old_detector['inputs'].pop('boundary_policy',None)
    assert T.P.workflow_fingerprint(old)==T.P.workflow_fingerprint(graph)
    detector['inputs']['boundary_policy']='strict'
    assert T.P.workflow_fingerprint(old)!=T.P.workflow_fingerprint(graph)


@pytest.mark.parametrize('change_pixels,change_metadata,empty',[
    (False,False,False),(True,False,False),(False,True,False),(False,False,True)])
def test_project_checks_actual_preserved_pixels_and_marks_review(tmp_path,change_pixels,change_metadata,empty):
    T=load_runner_tests()
    class Client(T.FakeComfy):
        def submit(self,*args):
            result=super().submit(*args)
            job=self.jobs[args[1]];bind=T.P.workflow_bindings(args[0])
            for key in ('source','target'):
                value=json.loads(job['history']['outputs'][bind[key]]['text'][0])
                value.update(needs_review=not empty,boundary_review=review([[5,5,20,20]]))
                if change_metadata and key=='target':value['boundary_review']=review([[5,5,21,21]])
                job['history']['outputs'][bind[key]]['text']=[json.dumps(value)]
                preview=bind[key+'_preview']
                job['history']['outputs'][preview]['text']=[json.dumps(value)]
            if change_pixels:
                picture=Image.open(BytesIO(job['bytes'])).convert('RGB');picture.putpixel((6,6),(0,0,0))
                encoded=BytesIO();picture.save(encoded,format='PNG');job['bytes']=encoded.getvalue()
            return result
    inputs=tmp_path/'input';T.make_page(inputs/'page.png',blank=empty)
    project=T.P.Project(inputs,tmp_path/'project',T.graph(),Client(['no_text'] if empty else []),poll_interval=.001)
    if change_pixels or change_metadata:
        with pytest.raises(T.P.ProtocolError,match='boundary'):
            project.run()
        assert project.state(project.pages[0])['status']=='collecting'
    else:
        summary=project.run()
        state=project.state(project.pages[0])
        assert summary['counts']=={'needs_review':1}
        assert state['reason']=='unresolved_detection_boundary'
