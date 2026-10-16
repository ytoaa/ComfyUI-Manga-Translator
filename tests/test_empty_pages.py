"""No-text success must not hide inference errors or empty recognized text."""
import json
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('empty_page_simulation_driver',ROOT/'tools/simulate_integrated.py')
S=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=S
spec.loader.exec_module(S)


@pytest.mark.parametrize('extra', ['none','bubble','excluded_sfx'])
def test_no_selected_text_runs_shipped_graph_without_models_or_http(tmp_path,monkeypatch,extra):
    runner=S.GraphRunner(tmp_path,no_text=True)
    if extra != 'none':
        def detect(image,thresholds):
            runner.detector.calls += 1
            return {'protocol':1,'image_width':image.width,'image_height':image.height,
                    'detections':[{'label':'bubble' if extra=='bubble' else 'onomatopoeia',
                                   'score':.99,'bbox':[10,10,60,40]}]}
        runner.detector.detect=detect
    original_native=runner.native
    def native(kind,args):
        if kind in ('MangaOCRLoader','UNETLoader','CLIPLoader','VAELoader'):
            pytest.fail('Unused model loader evaluated: '+kind)
        return original_native(kind,args)
    monkeypatch.setattr(runner,'native',native)
    # services() normally installs a translation oracle. Replace it after entry
    # so even /models must fail if the empty-page bypass regresses.
    original_services=runner.services
    from contextlib import contextmanager
    @contextmanager
    def services():
        with original_services():
            S.N.api_json=lambda *a,**kw:pytest.fail('Translation API called for an empty page')
            yield
    monkeypatch.setattr(runner,'services',services)
    report=runner.execute()
    assert report['selected_regions']==0 and report['ocr_line_calls']==0 and report['qwen_tile_calls']==0
    assert report['final_saved'] and report['cleanup']['cleanup_skipped']
    assert report['lettering']['lettering_skipped']
    assert np.array_equal(np.asarray(S.Image.open(tmp_path/'final.png')),np.asarray(runner.original))
    for path in (tmp_path/'manga_translator').glob('*.json'):
        data=json.loads(path.read_text())
        assert data['regions']==[] and data['page_status']=='no_text_detected'
    assert runner.calls['PreviewImage']>0


def test_empty_manifest_rejects_wrong_page_and_unexpected_text():
    page=S.tensor(S.Image.new('RGB',(100,80)))
    source=S.N.encode({'regions':[],'origin':'rfdetr','image_width':100,'image_height':80})
    crops,manifest,mask=S.N.MangaRegionCrops().crop(page,source,allow_empty_page=True)
    ocr=S.plugin.NODE_CLASS_MAPPINGS['MangaOCRAdaptive']()
    assert ocr.check_lazy_status(images=crops[0],manifest_json=manifest)==[]
    assert ocr.check_lazy_status(images=crops[0])==['model']
    assert not mask.any()
    with pytest.raises(ValueError,match='matching'):
        ocr.read(S.tensor(S.Image.new('RGB',(99,80))),manifest_json=manifest)
    with pytest.raises(ValueError,match='Unexpected OCR text'):
        S.N.MangaCollectOCR().collect(['invented text'],[manifest])
    with pytest.raises(ValueError,match='updated 08'):
        S.N.MangaRegionCrops().crop(page,source)


def test_detector_failure_still_stops_before_final_save(tmp_path):
    runner=S.GraphRunner(tmp_path,no_text=True)
    def detect(*a,**kw):
        raise RuntimeError('detector unavailable')
    runner.detector.detect=detect
    with pytest.raises(RuntimeError,match='detector unavailable'):
        runner.execute()
    assert not runner.saved and runner.ocr.calls==0 and runner.qwen_calls==0


def test_missing_regions_field_is_not_a_no_text_page():
    with pytest.raises(ValueError):
        S.N.layout('{}')
    with pytest.raises(ValueError):
        S.plugin.NODE_CLASS_MAPPINGS['MangaDetectionRegions']().convert(
            {'protocol':1,'image_width':100,'image_height':80})


@pytest.mark.parametrize('fault_on',[1,2])
def test_missing_detection_list_is_not_silently_empty(tmp_path,fault_on):
    runner=S.GraphRunner(tmp_path,no_text=True)
    def detect(image,thresholds):
        runner.detector.calls+=1
        result={'protocol':1,'image_width':image.width,'image_height':image.height}
        if runner.detector.calls!=fault_on:
            result['detections']=[]
        return result
    runner.detector.detect=detect
    with pytest.raises(ValueError,match='explicit detections list'):
        runner.execute()
    assert not runner.saved and runner.ocr.calls==0 and runner.qwen_calls==0
