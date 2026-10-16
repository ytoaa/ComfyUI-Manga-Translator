"""Adversarial detector geometry, including the user's 1600x640 tile seams."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boundary_tests', ROOT/'__init__.py',
                                             submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
P = sys.modules[spec.name+'.detection_policy']
R = sys.modules[spec.name+'.region_policy']
from boundary_tests.adapters.model import rle


def item(box, mask=None, label='text'):
    value = {'label': label, 'score': .95, 'bbox': list(box)}
    if mask is not None: value['mask'] = mask
    return value


def result(size, items):
    return {'protocol': 1, 'image_width': size[0], 'image_height': size[1], 'detections': items}


def clipped(box=(462, 185, 576, 548), edges=('right',)):
    return {**item(box), 'tile_provenance': {
        'stage': 'detail', 'window': [0, 0, 576, 576], 'clipped_edges': list(edges)}}


@pytest.mark.parametrize('box,window,edge', [
    ([0, 10, 40, 40], [512, 0, 1088, 576], 'left'),
    ([20, 0, 40, 40], [0, 64, 576, 640], 'top'),
    ([20, 10, 576, 40], [0, 0, 576, 576], 'right'),
    ([20, 10, 40, 576], [0, 0, 576, 576], 'bottom'),
])
def test_only_internal_window_edges_are_clipped(box, window, edge):
    w, h = window[2]-window[0], window[3]-window[1]
    out = P._window_detections(result((w,h), [item(box)]), window, 1600, 640, 'detail')
    assert out[0]['tile_provenance']['clipped_edges'] == [edge]


def test_page_edge_is_valid_and_mask_extent_also_detects_clipping():
    value = item([5,10,570,40], {'x': 5, 'y': 10, 'width': 571, 'height': 30, 'runs': [0,17130]})
    out = P._window_detections(result((576,576), [value]), (0,0,576,576),1600,640,'detail')
    assert out[0]['tile_provenance']['clipped_edges'] == ['right']
    page = P._window_detections(result((1600,640), [item([0,0,1600,640])]),(0,0,1600,640),1600,640,'detail')
    assert page[0]['tile_provenance']['clipped_edges'] == []


def test_supported_fragment_never_adds_its_strip_to_the_ocr_regions():
    original = clipped((462,190,576,220))
    class Model:
        def detect(self, *_): pytest.fail('Already supported by complete detection')
    clean = item([460,188,1160,225])
    trusted, report = P._recover_boundaries(Image.new('RGB',(1600,640)), Model(), {}, [clean,original])
    assert trusted == [clean] and report['clipped_regions'] == 1
    assert report['recovery_calls'] == 0


def test_vertical_strip_can_be_replaced_by_separate_complete_rows_using_mask_support():
    fragment = clipped()
    support = np.zeros((363,114),bool)
    for top,bottom in [(5,35),(90,155),(210,275),(330,360)]: support[top:bottom] = True
    fragment['mask'] = {'x':462,'y':185,'width':114,'height':363,'runs':rle(support)}
    rows = [item([460,190,1160,220]),item([460,275,1500,340]),
            item([460,395,1490,460]),item([460,515,1300,545])]
    assert P._covered(fragment, rows, 1600,640)
    assert not P._covered(fragment, rows[:1], 1600,640)
    assert not P._covered({**fragment,'label':'onomatopoeia'},rows,1600,640)


def test_unrecovered_fragment_stops_instead_of_being_silently_discarded():
    class Model:
        calls = 0
        def detect(self, image, _):
            self.calls += 1
            return result(image.size, [])
    model = Model()
    with pytest.raises(ValueError,match='unresolved clipped text'):
        P._recover_boundaries(Image.new('RGB',(1600,640)),model,{},[clipped()])
    assert model.calls <= 3


def test_recovery_call_budget_is_enforced(monkeypatch):
    monkeypatch.setattr(P, '_MAX_RECOVERY_CALLS', 0)
    with pytest.raises(ValueError,match='boundary recovery limit'):
        P._recover_boundaries(Image.new('RGB',(1600,640)),object(),{},[clipped()])


def test_recovery_rejects_wrong_crop_dimensions():
    class Model:
        def detect(self,*_): return result((1,1),[])
    with pytest.raises(ValueError,match='dimensions differ from crop'):
        P._recover_boundaries(Image.new('RGB',(1600,640)),Model(),{},[clipped()])


def test_resolver_rejects_unresolved_provenance():
    with pytest.raises(ValueError,match='Unresolved clipped text'):
        R.MangaDetectionRegionsResolved().convert(result((1600,640),[clipped()]))


class SeamDetector:
    """Read crop origin from an integer coordinate image; no model inference."""
    boxes = [[894,35,1025,101],[113,139,228,181],[462,190,1160,225],
             [460,275,1490,345],[454,390,1487,468],[462,515,1294,552]]
    def __init__(self, fail=False): self.calls=0; self.fail=fail
    def detect(self, image, _):
        index = image.getpixel((0,0)); x,y=index%1600,index//1600
        w,h=image.size; self.calls+=1
        initial = self.calls <= 9
        found=[]
        if self.fail and not initial: return result(image.size,[])
        for i,(a,b,c,d) in enumerate(self.boxes):
            if initial and i==3 and w>576: continue  # Body missed in wide passes.
            a,b,c,d=max(a,x),max(b,y),min(c,x+w),min(d,y+h)
            if a>=c or b>=d: continue
            if initial and x==0 and w==576 and y==0 and i>=2: continue
            found.append(item([a-x,b-y,c-x,d-y]))
        if initial and (x,y,w)==(0,0,576):
            support=np.zeros((363,114),bool)
            for a,b,c,d in self.boxes[2:]:
                support[max(0,b-185):min(363,d-185),:] = True
            found.append(item([462,185,576,548],{'x':462,'y':185,'width':114,'height':363,'runs':rle(support)}))
        return result(image.size,found)


def coordinate_page():
    return Image.fromarray(np.arange(640*1600,dtype=np.int32).reshape(640,1600))


def test_user_seams_recover_full_body_and_remove_cross_row_vertical_strip():
    detector=SeamDetector()
    raw=P.detail_detect(coordinate_page(),detector,{},'auto',64)
    selected=json.loads(R.MangaDetectionRegionsResolved().convert(raw)[0])
    boxes=[np.array(row['bbox'])*[1.6,.64,1.6,.64] for row in selected['regions']]
    assert len(boxes)==6
    for actual,expected in zip(boxes,detector.boxes): assert np.allclose(actual,expected)
    report=selected['region_resolution']['boundary_recovery']
    assert report['clipped_regions'] > 0 and 0 < report['recovery_calls'] <= 16
    assert detector.calls == 9+report['recovery_calls']
    assert not any(row.get('tile_provenance',{}).get('clipped_edges') for row in raw['detections'])


def test_user_seams_failed_recovery_never_reaches_region_selection():
    with pytest.raises(ValueError,match='unresolved clipped text'):
        P.detail_detect(coordinate_page(),SeamDetector(fail=True),{},'auto',64)


def test_genuine_vertical_text_without_crop_clipping_is_preserved():
    class Model:
        def detect(self,image,_):
            return result(image.size,[item([800,100,850,550])])
    raw=P.detail_detect(Image.new('RGB',(1600,640)),Model(),{},'off',64)
    rows=json.loads(R.MangaDetectionRegionsResolved().convert(raw)[0])['regions']
    assert len(rows)==1 and rows[0]['bbox']==[500.,156.25,531.25,859.375]


def test_recovery_region_budget_stops_before_accepting_excessive_results(monkeypatch):
    monkeypatch.setattr(P,'_MAX_REGIONS',1)
    class Model:
        def detect(self,image,_): return result(image.size,[item([0,0,10,10])]*2)
    with pytest.raises(ValueError,match='too many regions during boundary recovery'):
        P._recover_boundaries(Image.new('RGB',(1600,640)),Model(),{},[clipped()])


def test_clipped_masks_survive_for_cleanup_but_never_become_ocr_boxes():
    import torch
    detector=SeamDetector()
    raw=P.detail_detect(coordinate_page(),detector,{},'auto',64)
    assert raw['mask_fragments']
    # Complete synthetic boxes have no masks: only the clipped strip supplies
    # these segmentation pixels. The cleanup bridge must still preserve them.
    mask=plugin.NODE_CLASS_MAPPINGS['MangaDetectionMask']().make(raw)[0]
    expected=torch.zeros_like(mask)
    K=sys.modules[spec.name+'.mask_nodes']
    for fragment in raw['mask_fragments']:
        if fragment.get('mask'):
            values,(x,y,w,h)=K._decode_mask(fragment['mask'],1600,640)
            expected[0,y:y+h,x:x+w]=torch.maximum(expected[0,y:y+h,x:x+w],torch.from_numpy(values))
    assert expected.sum()>0 and torch.equal(mask,expected)
    rows=json.loads(R.MangaDetectionRegionsResolved().convert(raw)[0])['regions']
    assert len(rows)==6
