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


def test_failed_cleanup_never_reaches_final_save(tmp_path):
    runner = S.GraphRunner(tmp_path, uniform_fill=False, failed_qwen=True)
    with pytest.raises(ValueError, match='retained nearly all source ink'):
        runner.execute()
    assert not runner.saved and not (tmp_path/'final.png').exists()


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
    with pytest.raises(ValueError, match='unresolved clipped text'):
        runner.execute()
    assert runner.ocr.calls == runner.qwen_calls == 0 and not runner.saved
    assert not runner.calls['MangaTranslate']
    assert not list((tmp_path/'manga_translator').glob('*.json'))


def test_full_graph_uses_complementary_fragments_when_wide_inference_misses_text(tmp_path):
    report=S.GraphRunner(tmp_path,seam_case=True,empty_recovery=True).execute()
    assert report['boundary_recovery']['stitched_regions']>0
    assert report['boundary_recovery']['recovery_calls']==0
    assert report['selected_regions']==6 and report['ocr_line_calls']==9
    assert report['all_fixture_ink_masked'] and report['outside_mask_unchanged'] and report['final_saved']
