"""Selectable OCR handles must not attribute inference to replaced disk files."""
import hashlib
import pytest
from tools.simulate_ownership_scenarios import module

E = module('ocr_engines')


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    path = tmp_path/'weights.bin'; path.write_bytes(b'pinned')
    files = {'weights.bin': hashlib.sha256(b'pinned').hexdigest()}
    monkeypatch.setattr(E, 'spec', lambda engine: ('controlled', 'revision', files, {}, 'fixture'))
    monkeypatch.setattr(E, '_RESIDENT', {})
    calls = []
    class Backend:
        def __init__(self, folder, device): calls.append('load')
        def ocr(self, *args, **kwargs): calls.append('infer'); return {'text': 'controlled'}
    monkeypatch.setattr(E, 'MangaBackend', Backend)
    return path, files, calls, Backend


@pytest.mark.parametrize('resident', [False, True])
def test_changed_weights_are_rejected_before_next_inference(bundle, resident):
    path, _, calls, _ = bundle
    model = E.LazyOCR(E.ENGINES[1], path.parent, 'cpu')
    if resident: model.ocr(None, None)
    before = calls.copy(); path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='bundle changed'):
        model.ocr(None, None)
    assert calls == before


def test_replacement_during_load_never_enters_resident_cache(bundle, monkeypatch):
    path, _, calls, backend = bundle
    class Changed(backend):
        def __init__(self, *args): super().__init__(*args); path.write_bytes(b'changed')
    monkeypatch.setattr(E, 'MangaBackend', Changed)
    model = E.LazyOCR(E.ENGINES[1], path.parent, 'cpu')
    with pytest.raises(ValueError, match='bundle changed'): model.ocr(None, None)
    assert calls == ['load'] and not E._RESIDENT


def test_replacement_during_inference_does_not_return_mislabeled_result(bundle, monkeypatch):
    path, _, _, backend = bundle
    class Changed(backend):
        def ocr(self, *args, **kwargs): path.write_bytes(b'changed'); return {'text':'uncertified'}
    monkeypatch.setattr(E, 'MangaBackend', Changed)
    model = E.LazyOCR(E.ENGINES[1], path.parent, 'cpu')
    with pytest.raises(ValueError, match='bundle changed'): model.ocr(None, None)


def test_deleted_bundle_is_an_explicit_reload_error(bundle):
    path, _, calls, _ = bundle
    model = E.LazyOCR(E.ENGINES[1], path.parent, 'cpu'); path.unlink()
    with pytest.raises(ValueError, match='bundle changed'): model.ocr(None, None)
    assert not calls


def test_handle_cannot_be_created_from_unverified_files(bundle):
    path, _, calls, _ = bundle; path.write_bytes(b'bad')
    with pytest.raises(ValueError, match='SHA256'): E.LazyOCR(E.ENGINES[1], path.parent, 'cpu')
    assert not calls


def test_stable_handles_share_backend_and_keep_their_own_identity(bundle):
    path, files, calls, _ = bundle
    first = E.LazyOCR(E.ENGINES[1], path.parent, 'cpu')
    second = E.LazyOCR(E.ENGINES[1], path.parent, 'cpu')
    first.ocr(None, None); second.ocr(None, None)
    expected = files.copy(); files['weights.bin'] = '0'*64
    assert first.cache_identity['files'] == expected
    assert second.cache_identity['files'] == expected
    assert calls == ['load', 'infer', 'infer']
