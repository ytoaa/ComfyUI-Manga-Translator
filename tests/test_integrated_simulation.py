"""Run the complete shipped API graph, with model responses explicitly mocked."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('integrated_simulation_driver', ROOT/'tools/simulate_integrated.py')
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)


@pytest.mark.parametrize('fill', [True, False])
def test_complete_api_graph_preserves_regions_and_unmasked_pixels(tmp_path, fill):
    report = S.GraphRunner(tmp_path, uniform_fill=fill).execute()
    assert report['simulation_only'] is True
    assert report['selected_regions'] == 6 and report['ocr_line_calls'] == 9
    assert report['detector_calls'] == 9 + report['boundary_recovery']['recovery_calls']
    assert report['qwen_tile_calls'] == (1 if fill else 5)
    assert report['final_saved'] and not report['full_page_qwen_was_called']
    assert report['outside_mask_unchanged']
    assert (tmp_path/'final.png').is_file()
    assert len(list((tmp_path/'manga_translator').glob('*.json'))) == 2
    source=__import__('json').loads(next((tmp_path/'manga_translator').glob('ocr*.json')).read_text())
    assert sum(row['ocr_diagnostics']['chunk_count'] for row in source['regions']) == 9
    assert sum(row['ocr_diagnostics']['line_count'] for row in source['regions']) == 8
    # Six OCR crop reports map through one preview node; other debug stages
    # are page-level. Ten visible PreviewAny nodes produce fifteen calls here.
    assert report['calls']['PreviewAny']==15
    graph=__import__('json').loads((ROOT/'lettering/example_workflows/08-integrated-tiled-cleanup-lettering.api.json').read_text())
    for node in graph.values():
        if node['class_type']=='PreviewAny':
            saved_source=node['inputs']['source'][0]
            assert (graph[saved_source]['class_type']=='MangaSaveReview' or
                    (graph[saved_source]['class_type']=='MangaWorkflowInput' and node['inputs']['source'][1]==2) or
                    graph[saved_source]['class_type']=='MangaDebugInspect' or
                    (graph[saved_source]['class_type']=='MangaPageEditPlan' and node['inputs']['source'][1]==4))
    selectors=[(ident,node) for ident,node in graph.items() if node['class_type']=='PrimitiveBoolean']
    assert len(selectors)==1
    ident,node=selectors[0]
    assert node['inputs']['value'] is False
    for target in graph.values():
        if target['class_type'] in ('MangaDetectorDetail','MangaDetectionRegions','MangaDetectionMask'):
            assert target['inputs']['include_sfx']==[ident,0]


def test_failed_cleanup_never_reaches_final_save(tmp_path):
    runner = S.GraphRunner(tmp_path, uniform_fill=False, failed_qwen=True)
    with pytest.raises(ValueError, match='retained nearly all source ink'):
        runner.execute()
    assert not runner.saved and not (tmp_path/'final.png').exists()
    # Both review files were saved before rendering failed. Their direct UI
    # output must survive even though downstream PreviewAny never executes.
    saves=[key for key,node in runner.graph.items() if node['class_type']=='MangaSaveReview']
    previews=[key for key,node in runner.graph.items() if node['class_type']=='PreviewAny']
    assert all(runner.ui_outputs[key]['text'] and runner.ui_outputs[key]['manga_review_files'] for key in saves)
    assert all(key not in runner.ui_outputs for key in previews)


def test_short_repeating_ocr_stops_before_translation_cleanup_and_final_save(tmp_path):
    runner=S.GraphRunner(tmp_path)
    class BadOCR:
        calls=0
        def ocr(self,*args,**kwargs):
            self.calls+=1
            return {'text':'顔の集の集の集の集の集落'}
    runner.ocr=BadOCR()
    with pytest.raises(ValueError,match='short_repetition'):
        runner.execute()
    assert runner.ocr.calls == 2
    assert not runner.calls['MangaTranslate'] and runner.qwen_calls == 0 and not runner.saved


def test_persistent_ocr_token_limit_never_reaches_translation_or_final_save(tmp_path):
    from integrated_simulation.adapters.hayai import HayaiOutputError
    runner=S.GraphRunner(tmp_path)
    class LimitedOCR:
        calls=[]
        def ocr(self,image,options,**kwargs):
            self.calls.append(options.max_new_tokens)
            raise HayaiOutputError('ocr_token_limit')
    runner.ocr=LimitedOCR()
    with pytest.raises(ValueError,match='ocr_token_limit'):
        runner.execute()
    assert runner.ocr.calls == [256,512]
    assert not runner.calls['MangaTranslate'] and runner.qwen_calls == 0 and not runner.saved


def test_shipped_graph_removes_white_residue_missing_from_detector_mask(tmp_path):
    runner=S.GraphRunner(tmp_path)
    # An explicit omitted source fleck inside the detected gray paragraph.
    # Detector segmentation deliberately lacks these pixels; models are doubles.
    for y in range(211,214):
        for x in range(1000,1003):runner.original.putpixel((x,y),(255,255,255))
    runner.detector=S.DetectorOracle(runner.records,runner.original)
    runner.ocr=S.OCROracle(runner.original,runner.records)
    report=runner.execute()
    assert report['final_saved']
    plan_id=next(k for k,n in runner.graph.items() if n['class_type']=='MangaInpaintPlan')
    plan=runner.cache[plan_id][6][0]
    assert plan['source_mask'][211:214,1000:1003].all()
    cleaned=S.Image.open(tmp_path/'cleaned.png')
    assert cleaned.getpixel((1001,212)) == runner.clean.getpixel((1001,212))


def test_uniform_page_bypasses_the_entire_qwen_branch(tmp_path):
    report = S.GraphRunner(tmp_path, patterned_header=False).execute()
    assert report['qwen_tile_calls'] == 0 and report['final_saved']
    assert 'UNETLoader' not in report['calls']


def test_full_graph_recovers_cross_row_strip_before_ocr(tmp_path):
    report = S.GraphRunner(tmp_path, seam_case=True,require_recovery=True).execute()
    assert report['boundary_recovery']['recovery_calls'] > 0
    assert report['boundary_recovery']['unresolved_regions'] == 0
    assert report['selected_regions'] == 6 and report['ocr_line_calls'] == 9
    assert report['outside_mask_unchanged'] and report['final_saved']
    source = __import__('json').loads(next((tmp_path/'manga_translator').glob('ocr*.json')).read_text())
    assert len(source['regions']) == 6
    assert all(row['bbox'][2]-row['bbox'][0] > row['bbox'][3]-row['bbox'][1]
               for row in source['regions'][2:])


def test_unresolved_seam_stops_full_graph_before_ocr_translation_qwen_and_save(tmp_path):
    runner = S.GraphRunner(tmp_path, seam_case=True, failed_recovery=True)
    next(n for n in runner.graph.values() if n['class_type']=='MangaDetectorDetail')['inputs']['boundary_policy']='strict'
    with pytest.raises(ValueError, match='unresolved clipped text'):
        runner.execute()
    assert runner.ocr.calls == runner.qwen_calls == 0 and not runner.saved
    assert not runner.calls['MangaTranslate']
    assert not list((tmp_path/'manga_translator').glob('*.json'))


def test_default_graph_preserves_unknown_paragraphs_and_finishes_review_output(tmp_path):
    runner=S.GraphRunner(tmp_path,seam_case=True,failed_recovery=True)
    report=runner.execute()
    assert report['needs_review'] and report['final_saved']
    assert report['selected_regions']==2 and report['protected_boxes_pixels']
    assert report['all_unprotected_ink_masked'] and not report['all_fixture_ink_masked']
    source=__import__('json').loads(next((tmp_path/'manga_translator').glob('ocr*.json')).read_text())
    assert source['needs_review'] and source['review_reason']=='unresolved_detection_boundary'


def test_full_graph_uses_complementary_fragments_when_wide_inference_misses_text(tmp_path):
    report=S.GraphRunner(tmp_path,seam_case=True,empty_recovery=True).execute()
    assert report['boundary_recovery']['stitched_regions']>0
    assert report['boundary_recovery']['recovery_calls']==0
    assert report['selected_regions']==6 and report['ocr_line_calls']==9
    assert report['all_fixture_ink_masked'] and report['outside_mask_unchanged'] and report['final_saved']


@pytest.mark.parametrize('amount', [0, 1, -1])
def test_native_grow_mask_simulation_handles_zero_and_negative_without_filling_page(tmp_path, amount):
    import numpy as np
    import torch
    runner = S.GraphRunner(tmp_path)
    source = np.zeros((12, 14), np.float32)
    source[4:8, 5:9] = 1
    result = runner.native('GrowMask', {'mask': torch.from_numpy(source)[None], 'expand': amount})[0][0].numpy()
    assert not result[0].any() and not result[-1].any()
    assert (np.array_equal(result, source) if amount == 0 else
            result.sum() > source.sum() if amount > 0 else result.sum() < source.sum())
