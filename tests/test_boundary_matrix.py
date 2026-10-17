"""Source-edge and tile-budget invariants over varied page geometries."""
import importlib.util
from pathlib import Path
import random
import sys

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boundary_matrix_plugin',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec); sys.modules[spec.name] = plugin; spec.loader.exec_module(plugin)
from boundary_matrix_plugin import detection_policy as D


@pytest.mark.parametrize('tile', [384,576,1152])
@pytest.mark.parametrize('overlap', [0,64,384])
def test_random_and_exact_threshold_axes_have_no_gaps_or_outside_crops(tile,overlap):
    rng = random.Random(51)
    lengths = [1,2,383,384,385,575,576,577,1151,1152,1153,4096]
    lengths += [rng.randint(1,6000) for _ in range(60)]
    for length in lengths:
        windows = D._sliding_windows(length,tile,overlap)
        assert windows[0][0] == 0 and windows[-1][1] == length
        assert all(0 <= a < b <= length for a,b in windows)
        assert len(set(windows)) == len(windows)
        assert all(a < c <= b for (a,b),(c,d) in zip(windows,windows[1:]))
        assert all(b-a == min(length,tile) for a,b in windows)


@pytest.mark.parametrize('size', [(1,1),(1,1153),(1153,1),(575,577),(576,576),
                                 (577,1152),(1152,1153),(4000,200),(200,4000)])
def test_no_detection_geometry_keeps_exact_dimensions_and_bounded_model_work(size):
    class EmptyModel:
        calls = 0
        def detect(self,image,thresholds):
            self.calls += 1
            return {'protocol':1,'image_width':image.width,'image_height':image.height,'detections':[]}
    model = EmptyModel()
    result = D.detail_detect(Image.new('RGB',size),model,{},'auto',64,False)
    assert [result['image_width'],result['image_height']] == list(size)
    assert result['detections'] == []
    assert model.calls <= 65
    assert result['detection_audit']['selected_text_detections'] == 0


@pytest.mark.parametrize('edges', [('right','bottom'),('left','top'),('left','bottom')])
def test_unresolved_corner_is_not_certified_by_single_axis_stitching(edges):
    fragments = [{'label':'text','score':.9,'bbox':[20,20,100,100],
        'tile_provenance':{'window':[0,0,100,100],'clipped_edges':list(edges)}},
        {'label':'text','score':.9,'bbox':[30,30,120,120],
        'tile_provenance':{'window':[20,20,140,140],'clipped_edges':list(edges)}}]
    assert D._stitch_fragments(fragments,200,200) == []
    class EmptyModel:
        calls=0
        def detect(self,image,_):
            self.calls += 1
            return {'protocol':1,'image_width':image.width,'image_height':image.height,'detections':[]}
    model = EmptyModel()
    with pytest.raises(ValueError,match='unresolved clipped text'):
        D._recover_boundaries(Image.new('RGB',(200,200)),model,{},fragments)
    assert model.calls <= 8
