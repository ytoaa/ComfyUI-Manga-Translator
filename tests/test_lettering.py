"""Pixel invariants and actual Korean font rendering; no diffusion model needed."""
import importlib.util
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'lettering'
spec = importlib.util.spec_from_file_location('manga_lettering_test_extension', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
core = sys.modules['manga_lettering_test_extension.lettering.core']
nodes = sys.modules['manga_lettering_test_extension.lettering.nodes']


@pytest.fixture
def fixture():
    clean = np.full((180, 400, 3), .65, np.float32)
    picture = Image.fromarray((clean*255).round().astype('uint8'))
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype(str(PACKAGE/'fonts/NanumGothic-Bold.ttf'), 80)
    draw.text((30, 30), 'BOOM!', font=font, fill=(180, 20, 30), stroke_width=4, stroke_fill='white')
    original = np.asarray(picture, np.float32)/255
    mask = (np.max(np.abs(original-clean), axis=2) > .02).astype(np.float32)
    style, _ = core.analyze_style(original, clean, mask)
    return original, clean, mask, style


def test_reference_pigment_and_outline_are_measured(fixture):
    original, clean, mask, style = fixture
    assert np.allclose(style['foreground'], [180/255, 20/255, 30/255], atol=.01)
    assert style['outline_width'] > 0
    assert np.allclose(style['outline_color'], 1)
    assert style['sample_pixels'] > 100


def test_real_korean_render_and_exact_background_preservation(fixture):
    original, clean, oldmask, style = fixture
    layer, alpha, report = core.render_text('쾅! 정말 괜찮아?', style, rotation=8, shear=.12)
    assert layer.shape == clean.shape and alpha.shape == oldmask.shape
    assert alpha.max() > .99 and (alpha > 0).sum() > 100
    assert json.loads(report)['text'] == '쾅! 정말 괜찮아?'
    placement = {'version': 1, 'bbox_xywh': [0, 0, 400, 180], 'page_size': [400, 180]}
    result, fullmask = core.composite(clean, layer, alpha, placement)
    assert np.array_equal(result[fullmask == 0], clean[fullmask == 0])
    # The target letters must not be intersected with the source letters.
    assert ((alpha > .5) & (oldmask == 0)).any()
    assert np.any(result[(alpha > .5) & (oldmask == 0)] != clean[(alpha > .5) & (oldmask == 0)])


@pytest.mark.parametrize('direction', ['horizontal', 'vertical_ltr', 'vertical_rtl'])
def test_layouts_preserve_text_and_do_not_clip_region_edges(fixture, direction):
    style = fixture[3]
    _, alpha, report = core.render_text('괜찮아!\n정말?', style, direction=direction, max_font=72)
    assert json.loads(report)['text'] == '괜찮아!\n정말?'
    assert max(alpha[0].max(), alpha[-1].max(), alpha[:, 0].max(), alpha[:, -1].max()) < .001


@pytest.mark.parametrize('alignment',['left','right'])
@pytest.mark.parametrize('size',[10,15])
def test_dense_small_type_keeps_resampling_tails_off_frame_edges(fixture,alignment,size):
    style={**fixture[3],'size':[589,219],'outline_width':0.}
    text=('가로 문장과 12/28 항목을 확인합니다. '*18).strip()
    _,alpha,raw=core.render_text(text,style,min_font=size,max_font=size,padding=2,
                               alignment=alignment,supersample=2)
    report=json.loads(raw)
    assert report['text']==text and report['font_size']==size
    assert not alpha[0].any() and not alpha[-1].any()
    assert not alpha[:,0].any() and not alpha[:,-1].any()
    assert report['requested_padding']==2 and report['effective_padding']==4


def test_larger_requested_padding_is_preserved(fixture):
    _,_,raw=core.render_text('여백 확인',fixture[3],padding=8)
    report=json.loads(raw)
    assert report['requested_padding']==report['effective_padding']==8


def test_composition_uses_page_coordinates_and_preserves_all_other_pixels(fixture):
    style = fixture[3]
    layer, alpha, _ = core.render_text('안녕!', style)
    page = np.random.default_rng(1).random((400, 700, 3), dtype=np.float32)
    placement = {'version': 1, 'bbox_xywh': [100, 80, 400, 180], 'page_size': [700, 400]}
    result, cover = core.composite(page, layer, alpha, placement)
    assert np.array_equal(result[cover == 0], page[cover == 0])
    assert np.array_equal(page, core.composite(page, layer, alpha, placement, opacity=0)[0])
    assert cover[:80].sum() == 0


def test_style_analysis_never_mutates_inputs(fixture):
    original, clean, mask, _ = fixture
    copies = [v.copy() for v in (original, clean, mask)]
    core.analyze_style(original, clean, mask)
    assert all(np.array_equal(a, b) for a, b in zip((original, clean, mask), copies))


def test_candidate_texture_cannot_rewrite_glyph_alpha_or_exterior(fixture):
    layer, alpha, _ = core.render_text('한국어', fixture[3])
    candidate = np.random.default_rng(4).random(layer.shape, dtype=np.float32)
    output, kept = core.apply_candidate_texture(layer, alpha, candidate, strength=1., max_shift=.1)
    assert np.array_equal(kept, alpha)
    assert np.array_equal(output[alpha == 0], layer[alpha == 0])
    assert np.max(np.abs(output-layer)) <= .100001
    assert np.array_equal(core.apply_candidate_texture(layer, alpha, candidate, strength=0)[0], layer)


def test_missing_font_glyphs_are_rejected():
    with pytest.raises(ValueError, match='lacks requested characters'):
        core.font_path('NanumGothic-Bold.ttf', '😀')


def test_unfit_translation_is_not_truncated(fixture):
    with pytest.raises(ValueError, match='does not fit'):
        core.render_text('가'*500, fixture[3], min_font=80, max_font=80)


@pytest.mark.parametrize('text', ['', '   ', 'a\x00b', '가'*2049, 'a\tb', '미인식<UNK_SPAN>'])
def test_invalid_or_control_text_rejected(text):
    with pytest.raises(ValueError):
        core.clean_text(text)


def test_multiline_korean_reserves_outline_space_between_rows(fixture):
    style = core.adjust_style(fixture[3], outline_width=8, shadow_x=0, shadow_y=0)
    _, alpha, _ = core.render_text('가가가\n가가가', style, max_font=48)
    occupied = np.flatnonzero((alpha > .1).any(axis=1))
    assert np.diff(occupied).max() >= 4, 'Outlined text rows collided'


def test_region_and_mask_mismatch_rejected(fixture):
    original, clean, mask, _ = fixture
    with pytest.raises(ValueError, match='outside'):
        core.crop_region(original, clean, mask, [399, 0, 2, 20])
    with pytest.raises(ValueError, match='Mask dimensions'):
        core.crop_region(original, clean, mask[:100], [0, 0, 100, 100])
    with pytest.raises(ValueError):
        core.crop_region(original, clean, mask, [False, 0, 20, 20])


def test_page_regions_read_pristine_references_even_when_overlapping(fixture):
    original, clean, mask, _ = fixture
    data = {'schema': 1, 'coordinate_format': 'xywh', 'page_size': [400, 180], 'regions': [
        {'id': 'a', 'bbox': [0, 0, 400, 180], 'text': '한국어'},
        {'id': 'b', 'bbox': [0, 0, 400, 180], 'text': '번역', 'style': {'foreground': '#00aa00'}}]}
    seen = []
    analyze = core.analyze_style
    def track(reference, cleaned, *args, **kwargs):
        seen.append((reference.copy(), cleaned.copy()))
        return analyze(reference, cleaned, *args, **kwargs)
    with patch.object(core, 'analyze_style', track):
        result, alpha, report = core.render_page(original, clean, mask, json.dumps(data))
    assert len(seen) == 2
    assert all(np.array_equal(a, original) and np.array_equal(b, clean) for a, b in seen)
    assert len(json.loads(report)['regions']) == 2
    assert np.array_equal(result[alpha == 0], clean[alpha == 0])
    data['regions'][1]['id'] = 'a'
    with pytest.raises(ValueError, match='unique'):
        core.render_page(original, clean, mask, json.dumps(data))


def test_node_schemas_and_outputs_are_consistent():
    assert len(nodes.NODE_CLASS_MAPPINGS) == 13
    assert set(nodes.NODE_CLASS_MAPPINGS) == set(nodes.NODE_DISPLAY_NAME_MAPPINGS)
    for name, cls in nodes.NODE_CLASS_MAPPINGS.items():
        schema = cls.INPUT_TYPES()
        for key, field in schema['required'].items():
            assert field[1].get('tooltip'), (name, key)
        assert len(cls.RETURN_NAMES) == len(cls.RETURN_TYPES)


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value, np.float32)
    def detach(self): return self
    def cpu(self): return self
    def numpy(self): return self.value
    def __getitem__(self, key): return Tensor(self.value[key])


def test_actual_node_path_without_gpu(fixture, monkeypatch):
    monkeypatch.setitem(sys.modules, 'torch', types.SimpleNamespace(from_numpy=Tensor))
    original, clean, oldmask, _ = fixture
    a, b, m, placement = nodes.MangaLetterRegion().extract(
        Tensor(original[None]), Tensor(clean[None]), Tensor(oldmask[None]), 0, 0, 400, 180)
    style, _ = nodes.MangaLetterAnalyze().analyze(a, b, m)
    style, = nodes.MangaLetterStyleAdjust().adjust(style, outline_width=2.)
    layer, alpha, report = nodes.MangaLetterRender().render('번역 완료!', style)
    out, cover = nodes.MangaLetterComposite().composite(Tensor(clean[None]), layer, alpha, placement)
    assert out.value.shape == (1, 180, 400, 3)
    assert np.array_equal(out.value[0][cover.value[0] == 0], clean[cover.value[0] == 0])


def test_translation_http_contract_and_token_limit(monkeypatch):
    from manga_lettering_test_extension.lettering import translate as module
    calls = []
    class Response:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, n): return json.dumps(self.data).encode()
    def serve(request, timeout):
        calls.append(request)
        if request.full_url.endswith('/models'):
            return Response({'data': [{'id': 'existing-gemma'}]})
        assert json.loads(request.data)['model'] == 'existing-gemma'
        return Response({'choices': [{'finish_reason': 'stop', 'message': {'content': '안녕!'}}]})
    monkeypatch.setattr(module, 'urlopen', serve)
    monkeypatch.setenv('MANGA_LLM_API_KEY', 'test-key')
    assert module.translate('Hello!') == '안녕!'
    assert calls[-1].get_header('Authorization') == 'Bearer test-key'
    monkeypatch.setattr(module, 'urlopen', lambda *a, **k: Response({'choices': [{'finish_reason': 'length', 'message': {'content': '잘림'}}]}))
    with pytest.raises(ValueError, match='finish normally'):
        module.translate('Hello!', model='gemma')


def test_existing_translation_json_bridges_to_lettering(fixture, monkeypatch):
    monkeypatch.setitem(sys.modules, 'torch', types.SimpleNamespace(from_numpy=Tensor))
    original, clean, _, _ = fixture
    translated = {'image_width': 400, 'image_height': 180, 'regions': [
        {'id': 'r1', 'bbox': [0, 0, 1000, 1000], 'source': 'BOOM!', 'target': '쾅!',
         'edit_bbox_pixels': [0, 0, 400, 180]}]}
    document, support = nodes.MangaLetterPrepare().prepare(Tensor(original[None]), json.dumps(translated),
        region_options_json='{"r1":{"layout":{"max_lines":1,"rotation":5}}}')
    assert json.loads(document)['regions'][0]['text'] == '쾅!'
    assert json.loads(document)['regions'][0]['bbox'] == [0, 0, 400, 180]
    assert support.value.min() == support.value.max() == 1
    final, _, report = nodes.MangaLetterPage().render(Tensor(original[None]), Tensor(clean[None]), support, document)
    assert final.value.shape == original[None].shape
    assert json.loads(report)['regions'][0]['id'] == 'r1'
    prompt = nodes.MangaCleanupPrompt().build(json.dumps(translated))[0]
    assert 'BOOM!' in prompt and '쾅!' not in prompt
    assert 'Do not write translations' in prompt
    translated['image_width'] = 200
    with pytest.raises(ValueError, match='different page'):
        nodes.MangaLetterPrepare().prepare(Tensor(original[None]), json.dumps(translated))


def test_all_example_workflow_links_api_and_new_node_schemas():
    files = sorted((PACKAGE/'example_workflows').glob('*.api.json'))
    assert len(files) == 1
    for path in files:
        prompt = json.loads(path.read_text())
        ui = json.loads(path.with_name(path.name.replace('.api.json', '.json')).read_text())
        graph = {str(n['id']): n for n in ui['nodes'] if n['type'] != 'Note'}
        links = {l[0]: l for l in ui['links']}
        assert set(graph) == set(prompt), path.name
        for identifier, api in prompt.items():
            visual = graph[identifier]
            assert api['class_type'] == visual['type']
            for slot, item in enumerate(visual.get('inputs', [])):
                if item.get('link') is None:
                    continue
                link = links[item['link']]
                assert link[3:5] == [int(identifier), slot]
                assert api['inputs'][item['name']] == [str(link[1]), link[2]]
                assert link[0] in graph[str(link[1])]['outputs'][link[2]]['links']
            cls = nodes.NODE_CLASS_MAPPINGS.get(api['class_type'])
            if cls:
                schema = cls.INPUT_TYPES()
                fields = {**schema['required'], **schema.get('optional', {})}
                assert set(schema['required']) <= set(api['inputs']), (path.name, identifier)
                for field, value in api['inputs'].items():
                    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                        source, port = value
                        expected = fields[field][0]
                        if not isinstance(expected, list) and expected not in ('INT', 'FLOAT', 'BOOLEAN'):
                            assert graph[source]['outputs'][port]['type'] == expected
        # DFS from every node detects missing references and accidental cycles.
        visiting, done = set(), set()
        def visit(identifier):
            assert identifier not in visiting
            if identifier in done: return
            visiting.add(identifier)
            for value in prompt[identifier]['inputs'].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    assert value[0] in prompt
                    visit(value[0])
            visiting.remove(identifier)
            done.add(identifier)
        for identifier in prompt: visit(identifier)


def test_integrated_workflow_uses_cleanup_then_exact_lettering():
    graph = json.loads((PACKAGE/'example_workflows/08-integrated-tiled-cleanup-lettering.api.json').read_text())
    kinds = {n['class_type'] for n in graph.values()}
    assert 'MangaCleanupPrompt' not in kinds and 'MangaEditPrompt' not in kinds
    encoder = next(n for n in graph.values() if n['class_type'] == 'TextEncodeQwenImage21')
    assert encoder['inputs']['resolution'] == 0
    assert 'Remove all visible text and lettering' in encoder['inputs']['prompt']
    crop_id = next(i for i, n in graph.items() if n['class_type'] == 'ImageCrop')
    assert encoder['inputs']['images.image_1'] == [crop_id, 0]
    page_id = next(i for i, n in graph.items() if n['class_type'] == 'MangaLetterApply')
    saved = next(n for n in graph.values() if n['class_type'] == 'SaveImage')
    assert saved['inputs']['images'] == [page_id, 0]
    assert {'MangaTranslate', 'MangaOCRAdaptive', 'MangaInpaintAssemble', 'MangaLetterPlan'} <= kinds
