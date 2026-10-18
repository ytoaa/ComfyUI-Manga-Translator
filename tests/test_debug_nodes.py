"""Inspection is bounded, read-only and independent of processing identity."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest
import torch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('debug_node_tests',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from debug_node_tests import debug_nodes as D, detection_policy as DP
from tests.test_project_runner import P, graph


def test_detection_overlay_exposes_selection_and_exclusion_without_changing_source():
    original=torch.full((1,120,180,3),.5)
    before=original.clone()
    result={'protocol':1,'image_width':180,'image_height':120,'detections':[],
            'detection_audit':{'excluded_onomatopoeia_detections':31,
                'excluded_candidates':[{'label':'onomatopoeia','bbox_pixels':[100,60,150,100],'stage':'detail'}]}}
    regions={'image_width':180,'image_height':120,'regions':[{'id':'r1','bbox':[100,100,400,400]}]}
    report,preview=D.MangaDebugInspect().inspect('detection',json.dumps(regions),original,detection_result=result)
    data=json.loads(report)
    assert data['report']['detection_audit']['excluded_onomatopoeia_detections']==31
    assert data['report']['selected_regions'][0]['id']=='r1'
    assert np.allclose(preview[0,60,100].numpy(),[1,160/255,30/255])
    assert torch.equal(original,before)


def test_ocr_debug_preserves_null_issue_without_certifying_recognition():
    report={'source_size':[612,221],'line_count':1,'chunk_count':1,
            'chunks':[{'attempts':[{'model_size':[400,160],'characters':74,'issue':None}]}]}
    output,_=D.MangaDebugInspect().inspect('ocr',json.dumps(report))
    output=json.loads(output)
    assert output['report']==report
    assert output['quality_scope']=='heuristic_checks_not_recognition_accuracy'


def test_new_alpha_preview_is_mask_only_and_read_only():
    alpha=torch.zeros((1,80,120));alpha[:,20:35,30:65]=1
    before=alpha.clone()
    _,preview=D.MangaDebugInspect().inspect('letter_render','{"regions":[]}',preview_mask=alpha)
    assert preview.shape==(1,80,120,3)
    assert torch.equal(preview[0,...,0],alpha[0])
    assert torch.equal(alpha,before)


def test_high_resolution_detection_preview_is_bounded_and_retains_page_coordinates():
    original=np.ones((2200,4000,3),np.float32)
    raw={'protocol':1,'image_width':4000,'image_height':2200,'detections':[]}
    regions=json.dumps({'image_width':4000,'image_height':2200,'regions':[]})
    report,preview=D.detection_report(raw,regions,original)
    assert max(preview.shape[:2])<=2048
    assert report['image_width']==4000 and report['preview_stride']==2


@pytest.mark.parametrize('bad',['[]','{"value":NaN}','x'*2_000_001])
def test_invalid_reports_do_not_reach_preview(bad):
    with pytest.raises(ValueError):D.MangaDebugInspect().inspect('ocr',bad)


def test_excluded_candidates_use_page_coordinates_and_never_carry_masks():
    class Model:
        def detect(self,image,_):
            return {'protocol':1,'image_width':image.width,'image_height':image.height,
                'detections':[{'label':'onomatopoeia','score':.7,'bbox':[10,20,30,40],
                               'mask':{'unneeded':'not for debug'}}]}
    raw=DP.detail_detect(Image.new('RGB',(1600,640)),Model(),{},'auto',64,False)
    rows=raw['detection_audit']['excluded_candidates']
    assert any(row['stage']=='detail' and row['bbox_pixels']==[458,20,478,40] for row in rows)
    assert all('mask' not in row for row in rows)
    assert not raw['detections']


def test_excluded_candidate_sampling_is_bounded_without_changing_count():
    class Model:
        def detect(self,image,_):
            return {'protocol':1,'image_width':image.width,'image_height':image.height,
                    'detections':[{'label':'onomatopoeia','score':.7,'bbox':[5,5,20,20]}]*300}
    raw=DP.detail_detect(Image.new('RGB',(100,100)),Model(),{},'off',64,False)
    audit=raw['detection_audit']
    assert audit['excluded_onomatopoeia_detections']==300
    assert len(audit['excluded_candidates'])==256 and audit['excluded_candidates_omitted']==44


def test_debug_branches_preserve_legacy_identity_but_processing_consumers_do_not():
    current=graph();old=deepcopy(current)
    ignored=P.debug_observers(current)
    assert len(ignored)==15
    for key in ignored:old.pop(key)
    assert P.workflow_fingerprint(current)==P.workflow_fingerprint(old)
    debug=next(k for k,n in current.items() if n['class_type']=='MangaDebugInspect')
    translate=next(n for n in current.values() if n['class_type']=='MangaTranslate')
    translate['inputs']['target_language']=[debug,0]
    assert P.workflow_fingerprint(current)!=P.workflow_fingerprint(old)


def test_shipped_debug_reports_cover_every_stage_and_masks():
    value=graph()
    observers={n['inputs']['stage']:n for n in value.values() if n['class_type']=='MangaDebugInspect'}
    assert set(observers)==set(D.STAGES)
    assert 'detection_result' in observers['detection']['inputs']
    assert 'preview_mask' in observers['letter_plan']['inputs']
    assert 'preview_mask' in observers['letter_render']['inputs']
