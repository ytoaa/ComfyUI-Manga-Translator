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
    assert report['selected_regions'] == 6 and report['ocr_line_calls'] == 8
    assert report['detector_calls'] == 9
    assert report['qwen_tile_calls'] == (1 if fill else 5)
    assert report['final_saved'] and not report['full_page_qwen_was_called']
    assert report['outside_mask_unchanged']
    assert (tmp_path/'final.png').is_file()
    assert len(list((tmp_path/'manga_translator').glob('*.json'))) == 2


def test_failed_cleanup_never_reaches_final_save(tmp_path):
    runner = S.GraphRunner(tmp_path, uniform_fill=False, failed_qwen=True)
    with pytest.raises(ValueError, match='retained nearly all source ink'):
        runner.execute()
    assert not runner.saved and not (tmp_path/'final.png').exists()


def test_uniform_page_bypasses_the_entire_qwen_branch(tmp_path):
    report = S.GraphRunner(tmp_path, patterned_header=False).execute()
    assert report['qwen_tile_calls'] == 0 and report['final_saved']
    assert 'UNETLoader' not in report['calls']
