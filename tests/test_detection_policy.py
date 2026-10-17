from pathlib import Path
import importlib.util
import sys
import types

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('manga_detection_policy_tests')
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg

models_spec = importlib.util.spec_from_file_location(pkg.__name__ + '.models', ROOT / 'models.py')
models = importlib.util.module_from_spec(models_spec)
sys.modules[models_spec.name] = models
models_spec.loader.exec_module(models)

policy_spec = importlib.util.spec_from_file_location(pkg.__name__ + '.detection_policy', ROOT / 'detection_policy.py')
policy = importlib.util.module_from_spec(policy_spec)
sys.modules[policy_spec.name] = policy
policy_spec.loader.exec_module(policy)


def test_1600_wide_auto_page_uses_two_native_width_windows():
    assert policy._sliding_windows(1600, 1152, 64) == [(0, 1152), (448, 1600)]


def test_auto_detail_keeps_both_overlapping_tile_results_for_resolver():
    calls = []

    class Model:
        def detect(self, image, thresholds):
            calls.append(image.size)
            width, height = image.size
            # One synthetic region per inference. Tile coordinates deliberately
            # overlap after restoration; the next region-resolver stage owns
            # deduplication rather than center-ownership dropping detections.
            return {
                'protocol': 1,
                'image_width': width,
                'image_height': height,
                'detections': [{
                    'label': 'text', 'score': .9,
                    'bbox': [max(10, width - 700), 100, width - 50, 150],
                }],
            }

    page = Image.new('RGB', (1600, 640), 'white')
    result = policy.detail_detect(page, Model(),
                                  {'text': .25, 'onomatopoeia': .2, 'bubble': .5, 'panel': .5},
                                  'auto', 64)
    assert calls[:3] == [(1600, 640), (1152, 640), (1152, 640)]
    assert calls[3:] == [(576, 576)] * 6
    assert result['detail_detection']['windows'][:2] == [[0, 1152, 0, 640], [448, 1600, 0, 640]]
    assert result['detail_detection']['detail_regions'] == 8
    assert len(result['detections']) == 9


def test_maximum_overlap_does_not_create_one_pixel_stride():
    x = policy._sliding_windows(1600, policy._tile_size('3x'), 384)
    y = policy._sliding_windows(640, policy._tile_size('3x'), 384)
    assert len(x)*len(y) <= 64


def test_excessive_detail_windows_stop_before_tile_inference():
    import pytest
    class Model:
        calls = 0
        def detect(self, image, thresholds):
            self.calls += 1
            return {'image_width': image.width, 'image_height': image.height, 'detections': []}
    model = Model()
    with pytest.raises(ValueError, match='limit=64'):
        policy.detail_detect(Image.new('RGB', (6000, 6000)), model, {}, '3x', 384)
    assert model.calls == 1


def test_large_auto_page_adapts_detail_scale_to_execution_budget():
    class Model:
        calls = 0
        def detect(self, image, thresholds):
            self.calls += 1
            return {'image_width': image.width, 'image_height': image.height, 'detections': []}
    model = Model()
    result = policy.detail_detect(Image.new('RGB', (4000, 4000)), model, {}, 'auto', 64)
    assert result['detail_detection']['tiles'] <= 64
    assert model.calls == 1+result['detail_detection']['tiles']


def test_small_page_with_no_selected_text_gets_compact_retry_without_duplicate_full():
    class Model:
        def __init__(self): self.calls = 0
        def detect(self, image, thresholds):
            self.calls += 1
            return {'protocol': 1, 'image_width': image.width, 'image_height': image.height, 'detections': []}

    model = Model()
    result = policy.detail_detect(Image.new('RGB', (1000, 800), 'white'), model,
                                  {'text': .25, 'onomatopoeia': .2, 'bubble': .5, 'panel': .5},
                                  'auto', 64)
    assert model.calls == 5
    assert result['detail_detection']['tiles'] == 4
    assert result['detail_detection']['zero_selected_compact_retry']


def test_small_page_with_text_keeps_single_full_pass():
    class Model:
        calls=0
        def detect(self,image,_):
            self.calls+=1
            return {'protocol':1,'image_width':image.width,'image_height':image.height,
                    'detections':[{'label':'text','score':.9,'bbox':[50,50,300,100]}]}
    model=Model()
    result=policy.detail_detect(Image.new('RGB',(1000,800)),model,{},'auto',64)
    assert model.calls==1 and result['detail_detection']['tiles']==0
    assert result['detection_audit']['raw_counts_by_stage']['full']=={'text':1}


def test_cover_sized_page_retries_small_crops_when_full_pass_has_no_text():
    class Model:
        calls=[]
        def detect(self,image,_):
            self.calls.append(image.size)
            return {'protocol':1,'image_width':image.width,'image_height':image.height,
                'detections':[] if image.size==(800,1125) else
                    [{'label':'text','score':.9,'bbox':[20,20,200,100]}]}
    model=Model()
    result=policy.detail_detect(Image.new('RGB',(800,1125)),model,{},'auto',64,False)
    assert model.calls.count((800,1125))==1 and len(model.calls)==7
    assert result['detection_audit']['raw_counts_by_stage']['full']=={}
    assert result['detection_audit']['selected_text_detections']==6


def test_excluded_cover_effect_is_reported_as_a_selection_choice_not_no_raw_detection():
    class Model:
        def detect(self,image,_):
            return {'protocol':1,'image_width':image.width,'image_height':image.height,
                'detections':[{'label':'onomatopoeia','score':.9,'bbox':[30,40,200,300]}]}
    region=importlib.import_module(pkg.__name__+'.region_policy')
    import json
    excluded=policy.detail_detect(Image.new('RGB',(400,500)),Model(),{},'auto',64,False)
    data=json.loads(region.MangaDetectionRegionsResolved().convert(excluded,False)[0])
    assert not data['regions'] and data['needs_review']
    assert data['no_text_reason']=='excluded_onomatopoeia_present'
    assert data['region_resolution']['detection_audit']['raw_counts_by_stage']['full']=={'onomatopoeia':1}
    included=policy.detail_detect(Image.new('RGB',(400,500)),Model(),{},'auto',64,True)
    data=json.loads(region.MangaDetectionRegionsResolved().convert(included,True)[0])
    assert len(data['regions'])==1 and data['regions'][0]['kind']=='sfx'
