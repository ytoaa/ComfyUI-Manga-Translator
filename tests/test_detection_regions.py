from pathlib import Path
import importlib.util
import json
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('manga_detection_region_tests')
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location(pkg.__name__+'.nodes', ROOT/'nodes.py')
N = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = N
spec.loader.exec_module(N)


def test_detector_mask_extent_expands_ocr_region():
    result = {
        'protocol': 1,
        'image_width': 100,
        'image_height': 100,
        'detections': [{
            'label': 'text',
            'score': 0.9,
            'bbox': [20, 20, 40, 40],
            'mask': {'x': 18, 'y': 19, 'width': 26, 'height': 24, 'runs': [624]},
        }],
    }
    value = json.loads(N.MangaDetectionRegions().convert(result)[0])
    assert value['regions'][0]['bbox'] == [180.0, 190.0, 440.0, 430.0]


def test_duplicate_boxes_merge_instead_of_losing_lower_score_extent():
    result = {
        'protocol': 1,
        'image_width': 100,
        'image_height': 100,
        'detections': [
            {'label': 'text', 'score': 0.9, 'bbox': [10, 10, 50, 50]},
            {'label': 'text', 'score': 0.8, 'bbox': [12, 12, 54, 54]},
        ],
    }
    value = json.loads(N.MangaDetectionRegions().convert(result, dedupe_iou=0.5)[0])
    assert len(value['regions']) == 1
    assert value['regions'][0]['bbox'] == [100.0, 100.0, 540.0, 540.0]


def test_effects_still_follow_include_sfx_user_choice():
    result = {
        'protocol': 1,
        'image_width': 100,
        'image_height': 100,
        'detections': [
            {'label': 'text', 'score': 0.9, 'bbox': [10, 10, 20, 20]},
            {'label': 'onomatopoeia', 'score': 0.9, 'bbox': [30, 30, 40, 40]},
        ],
    }
    assert len(json.loads(N.MangaDetectionRegions().convert(result, False)[0])['regions']) == 1
    rows = json.loads(N.MangaDetectionRegions().convert(result, True)[0])['regions']
    assert [row['kind'] for row in rows] == ['text', 'sfx']
