from pathlib import Path
import importlib.util
import json
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('manga_region_policy_tests')
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg

nodes_spec = importlib.util.spec_from_file_location(pkg.__name__ + '.nodes', ROOT / 'nodes.py')
nodes = importlib.util.module_from_spec(nodes_spec)
sys.modules[nodes_spec.name] = nodes
nodes_spec.loader.exec_module(nodes)

policy_spec = importlib.util.spec_from_file_location(pkg.__name__ + '.region_policy', ROOT / 'region_policy.py')
policy = importlib.util.module_from_spec(policy_spec)
sys.modules[policy_spec.name] = policy
policy_spec.loader.exec_module(policy)


def _item(box, score):
    return {'label': 'text', 'bbox': box, 'score': score}


def test_user_detail_pass_example_resolves_ten_boxes_to_five_logical_regions():
    # Normalized 0..1000 coordinates from the failing 1600x640 page are used
    # directly as a synthetic 1000x1000 detector coordinate system. The
    # overlap relationships are therefore identical to the real run.
    boxes = [
        ([73.125,223.63414764404297,140.0,275.0], .99),
        ([463.36486607789993,298.01251888275146,728.75,345.654034614563], .80),
        ([291.5976905822754,298.9295482635498,727.5,344.43368911743164], .95),
        ([290.99029541015625,299.05967712402344,540.0,344.0858840942383], .82),
        ([290.56480407714844,433.15672874450684,540.0,541.6065216064453], .91),
        ([286.5542221069336,614.605188369751,926.25,723.3467102050781], .96),
        ([288.93848419189453,617.3882484436035,540.0,723.968505859375], .84),
        ([291.30748748779297,807.171630859375,805.8956909179688,854.9080848693848], .94),
        ([460.0,807.3809623718262,804.4815826416016,854.1842460632324], .86),
        ([290.3610610961914,809.375,540.0,854.6875], .83),
    ]
    raw = {'protocol': 1, 'image_width': 1000, 'image_height': 1000,
           'detections': [_item(box, score) for box, score in boxes]}

    result = json.loads(policy.MangaDetectionRegionsResolved().convert(raw)[0])
    assert len(result['regions']) == 5
    assert result['region_resolution']['input_regions'] == 10
    assert result['region_resolution']['resolved_regions'] == 5

    # The first paragraph is the transitive union of three full/detail boxes.
    first_paragraph = result['regions'][1]['bbox']
    assert first_paragraph == [290.99029541015625, 298.01251888275146,
                               728.75, 345.654034614563]


def test_containment_merge_does_not_join_separate_rows():
    raw = {'protocol': 1, 'image_width': 1000, 'image_height': 1000,
           'detections': [
               _item([100, 100, 800, 150], .9),
               _item([200, 102, 500, 148], .8),
               _item([100, 220, 800, 270], .9),
           ]}
    result = json.loads(policy.MangaDetectionRegionsResolved().convert(raw)[0])
    assert len(result['regions']) == 2


def test_containment_overlap_handles_nested_boxes_with_low_iou():
    outer = [0, 0, 100, 100]
    inner = [0, 0, 55, 100]
    assert nodes.iou(outer, inner) == 0.55
    assert policy.containment_overlap(outer, inner) == 1.0


def test_reported_split_rows_group_but_neighboring_paragraphs_do_not():
    boxes=[[465,190,1166,220],[467,278,1494,307],[466,318,745,346],
           [467,392,1481,463],[467,518,1299,548]]
    raw={'protocol':1,'image_width':1600,'image_height':640,
         'detections':[_item(box,.9) for box in boxes]}
    data=json.loads(policy.MangaDetectionRegionsResolved().convert(raw,merge_adjacent_lines=True)[0])
    assert len(data['regions']) == 4
    assert data['region_resolution']['grouped_lines'] == 1
    assert data['regions'][1]['line_bboxes_pixels'] == boxes[1:3]
    assert len(json.loads(policy.MangaDetectionRegionsResolved().convert(raw)[0])['regions']) == 5


def test_close_rows_in_different_bubbles_stay_separate():
    rows=[_item([10,10,210,30],.9),_item([10,40,210,60],.9)]
    bubbles=[{'bbox':[0,0,220,35]},{'bbox':[0,36,220,70]}]
    assert len(policy.group_adjacent_lines(rows,bubbles)) == 2


def test_group_gap_does_not_increase_with_the_accumulated_paragraph_height():
    rows=[_item([10,y,210,y+20],.9) for y in (10,40,70,110)]
    assert [len(row['line_bboxes']) for row in policy.group_adjacent_lines(rows,[])] == [3,1]


def test_two_multiline_blocks_are_not_joined_as_single_rows():
    from numpy import zeros
    from manga_region_policy_tests.adapters.model import rle
    rows=[]
    for y in (100,210):
        pixels=zeros((75,500),bool);pixels[8:28,5:490]=True;pixels[44:64,5:300]=True
        rows.append({**_item([10,y,510,y+75],.9),'mask':{'x':10,'y':y,'width':500,'height':75,'runs':rle(pixels)}})
    assert len(policy.group_adjacent_lines(rows,[])) == 2
