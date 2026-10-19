"""Independent evaluator controls: wrong words/blank false positives must fail."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import image_scenarios as S
import simulate_page_failures as A


@pytest.mark.parametrize('expected,actual,edits', [
    ('STATION', 'STATION', 0), ('STATION', 'STTION', 1), ('STATION', 'STATIONS', 1),
    ('春天的公園', '春天的公元', 1), ('ABC', 'XYZ', 3), ('A', 'ABCDE', 4),
])
def test_exact_reference_scores_do_not_confuse_normal_termination_with_accuracy(expected, actual, edits):
    score = S.text_score(expected, actual)
    assert score['edit_distance'] == edits
    assert score['exact'] is (edits == 0)
    assert score['cer'] == pytest.approx(edits/len(expected))


def test_layout_normalization_preserves_case_and_punctuation_errors():
    assert S.text_score('STAND C7', 'ＳＴＡＮＤ\n C7')['exact']
    assert not S.text_score('Train.', 'train')['exact']
    assert S.text_score('春の公園', '春の\n公園')['content_cer_without_whitespace'] == 0
    assert S.text_score('', 'hallucination')['cer'] is None


def test_coverage_requires_every_reference_region_and_respects_requested_effect_scope():
    a = np.zeros((20, 40), bool);a[4:10, 3:13] = True
    b = np.zeros_like(a);b[12:18, 25:35] = True
    refs = [{'id': 'body', 'kind': 'text'}, {'id': 'effect', 'kind': 'sfx'}]
    boxes = [[0, 0, 20, 20]]
    assert S.boxes_score(refs, [a, b], boxes)['missing_or_partial_ids'] == []
    assert S.boxes_score(refs, [a, b], boxes, True)['missing_or_partial_ids'] == ['effect']
    assert S.coverage(a, [[3, 4, 8, 10]]) == .5
    assert S.coverage(a, [[3, 4, 8, 10], [8, 4, 13, 10]]) == 1


def test_full_coverage_cannot_hide_duplicate_recognition_mixed_columns_or_blank_false_positives():
    a = np.zeros((20, 40), bool);a[3:10, 3:13] = True
    b = np.zeros_like(a);b[3:10, 25:35] = True
    refs = [{'id': 'a', 'column': 1}, {'id': 'b', 'column': 2}]
    assert S.localization_met(S.boxes_score(refs, [a, b], [[0, 0, 20, 20], [20, 0, 40, 20]]))
    mixed = S.boxes_score(refs, [a, b], [[0, 0, 40, 20]])
    assert mixed['missing_or_partial_ids'] == [] and not S.localization_met(mixed)
    duplicate = S.boxes_score([refs[0]], [a], [[0, 0, 20, 20], [0, 0, 20, 20]])
    assert duplicate['duplicate_reference_ink_fraction'] == 1 and not S.localization_met(duplicate)
    assert S.localization_met(S.boxes_score([], [], []))
    assert not S.localization_met(S.boxes_score([], [], [[0, 0, 10, 10]]))


def test_off_page_and_inverted_coordinates_cannot_wrap_numpy_slices_into_false_coverage():
    mask = np.ones((20, 40), bool)
    for box in ([-50, 0, -1, 20], [0, -50, 40, -1], [80, 0, 90, 20], [30, 10, 3, 2]):
        assert S.coverage(mask, [box]) == 0
    assert S.coverage(mask, [[-10, -10, 50, 30]]) == 1
    with pytest.raises(ValueError, match='finite'):
        S.coverage(mask, [[0, 0, float('nan'), 10]])


def test_original_fixtures_are_deterministic_complete_and_separate_from_model_outputs(tmp_path):
    left, right = tmp_path/'first', tmp_path/'second'
    a, b = S.generate(left), S.generate(right)
    assert a == b and len(a['pages']) == 6 and len(a['ocr']) == 15
    assert 'no user assets' in a['source']
    for row in a['pages']:
        assert (left/row['image']).read_bytes() == (right/row['image']).read_bytes()
        with np.load(left/(row['id']+'-truth.npz')) as masks:
            assert set(masks.files) == {r['id'] for r in row['regions']}
            for region in row['regions']:
                mask = masks[region['id']]
                assert mask.shape == tuple(reversed(row['size']))
                x, y, c, d = region['bbox_pixels']
                assert 0 < x < c < row['size'][0] and 0 < y < d < row['size'][1]
                assert S.coverage(mask, [[x, y, c, d]]) == 1
    for row in a['ocr']:
        assert Image.open(left/row['image']).size == tuple(row['size'])
        S.font(20, row['expected'])  # Missing glyph/tofu cannot become ground truth.


def test_missing_glyph_is_a_fixture_error_not_an_ocr_quality_gap():
    with pytest.raises(ValueError, match='lacks reference characters'):
        S.text_layer('\U0010ffff')


def test_audit_separates_unmet_criteria_from_unexpected_errors_and_never_whitelists_known_gaps(tmp_path):
    audit = A.Audit(tmp_path, 'unit')
    audit.case('correct', 'evaluator', 'met', lambda: (True, {'actual': 'A'}))
    audit.case('known-miss', 'evaluator', 'exact', lambda: (False, {'actual': 'B'}))
    assert audit.exit_code() == 1
    def crash():raise RuntimeError('injected harness failure')
    audit.case('crash', 'evaluator', 'no error', crash)
    assert audit.exit_code() == 2
    saved = json.loads((tmp_path/'unit-results.json').read_text())
    assert saved['counts'] == {'PASS': 1, 'GAP': 1, 'ERROR': 1}
    assert not saved['completed']
    assert not any(row['real_model'] for row in saved['results'])


def test_summary_cannot_report_an_interrupted_run_or_missing_model_modes_as_complete(tmp_path):
    audit = A.Audit(tmp_path, 'contracts')
    audit.case('partial', 'evaluator', 'met', lambda: (True, {}))
    A.summarize(tmp_path)
    result = (tmp_path/'summary.md').read_text()
    assert 'contracts (INCOMPLETE)' in result and 'detector (NOT RUN)' in result and 'ocr (NOT RUN)' in result


def test_new_audit_attempt_replaces_old_completed_report_before_model_loading(tmp_path):
    (tmp_path/'ocr-results.json').write_text('{"completed":true,"counts":{"PASS":15}}')
    A.Audit(tmp_path, 'ocr')
    report = json.loads((tmp_path/'ocr-results.json').read_text())
    assert not report['completed'] and report['results']==[] and report['counts']=={}
