"""Regression checks for positional UI settings, separately from API edges."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('widget_contract_plugin', ROOT/'__init__.py',
                                             submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
FILES = sorted((ROOT/'workflows').glob('*.json')) + sorted((ROOT/'lettering/example_workflows').glob('*.json'))
FILES = [path for path in FILES if not path.name.endswith('.api.json')]


@pytest.mark.parametrize('path', FILES, ids=lambda path: path.stem)
def test_widget_positions_match_runtime_schema_and_api_literals(path):
    workflow = json.loads(path.read_text())
    prompt = json.loads(path.with_name(path.stem+'.api.json').read_text())
    for node in workflow['nodes']:
        cls = plugin.NODE_CLASS_MAPPINGS.get(node['type'])
        if cls is None or node['type'] in ('MangaDetectorLoader', 'MangaOCRLoader'):
            continue
        schema = cls.INPUT_TYPES()
        fields = {**schema.get('required', {}), **schema.get('optional', {})}
        # The frontend creates a widget for every primitive unless forceInput
        # is set, even when the workflow already has a connected input slot.
        expected = [name for name, field in fields.items()
                    if not (len(field) > 1 and field[1].get('forceInput'))
                    and (isinstance(field[0], list) or field[0] in ('STRING', 'INT', 'FLOAT', 'BOOLEAN'))]
        saved = node.get('widgets_values', [])
        assert len(saved) == len(expected), (path.name, node['type'], expected, saved)
        restored = dict(zip(expected, saved))
        assert restored == node.get('widgets_values_named', {}), (path.name, node['type'])
        sockets = {item['name']: item for item in node.get('inputs', [])}
        for name, value in restored.items():
            field = fields[name]
            if field[0] == 'STRING': assert isinstance(value, str), (path.name, node['type'], name)
            if field[0] == 'INT': assert type(value) is int, (path.name, node['type'], name)
            if field[0] == 'BOOLEAN': assert type(value) is bool
            if field[0] in ('INT', 'FLOAT'):
                opts = field[1]
                assert opts.get('min', -float('inf')) <= value <= opts.get('max', float('inf'))
            api_value = prompt[str(node['id'])]['inputs'][name]
            if not isinstance(api_value, list): assert value == api_value
            elif name in sockets: assert sockets[name].get('widget') == {'name': name}
        for name, field in fields.items():
            if len(field) > 1 and field[1].get('forceInput'):
                assert name in sockets and 'widget' not in sockets[name]


@pytest.mark.parametrize('path', FILES)
def test_translation_and_review_settings_do_not_shift(path):
    graph = json.loads(path.read_text())
    translate = next(node for node in graph['nodes'] if node['type'] == 'MangaTranslate')
    assert translate['widgets_values'] == ['http://127.0.0.1:8000/v1', '', 'Korean', 'MANGA_LLM_API_KEY', 4096, 300, '', '', 'json_schema']
    for node in graph['nodes']:
        if node['type'] == 'MangaSaveReview':
            assert len(node['widgets_values']) == 1
            assert node['widgets_values'][0].startswith('manga_translator/')
        if node['type'] in ('MangaEditPrompt', 'MangaCleanupPrompt'):
            assert len(node['widgets_values']) == 1 and node['widgets_values'][0]


def test_integrated_crops_and_compositing_use_native_nodes():
    prompt = json.loads(FILES[0].with_name(FILES[0].stem+'.api.json').read_text())
    kinds = [node['class_type'] for node in prompt.values()]
    assert kinds.count('ImageCrop') == 1 and kinds.count('ImageCompositeMasked') == 1
    assert kinds.count('ImageScale') == 1 and kinds.count('GrowMask') == 1
    assert 'MangaLetterRegion' not in kinds and 'MangaLetterComposite' not in kinds
    plan_id = next(i for i, node in prompt.items() if node['class_type'] == 'MangaInpaintPlan')
    crop_id, crop = next((i, n) for i, n in prompt.items() if n['class_type'] == 'ImageCrop')
    scale_id, scale = next((i, n) for i, n in prompt.items() if n['class_type'] == 'ImageScale')
    composite = next(node for node in prompt.values() if node['class_type'] == 'ImageCompositeMasked')
    assert crop['inputs']['image'] == [plan_id, 0]
    for field, slot in (('x', 1), ('y', 2), ('width', 3), ('height', 4)):
        assert crop['inputs'][field] == [plan_id, slot]
    for field in ('width', 'height'):
        assert scale['inputs'][field] == crop['inputs'][field]
    assert composite['inputs']['destination'] == [crop_id, 0]
    assert composite['inputs']['source'] == [scale_id, 0]
    assert composite['inputs']['mask'] == [plan_id, 5]
    assert composite['inputs']['resize_source'] is False


def test_upload_buttons_are_not_serialized_and_integer_controls_are_fixed():
    for path in FILES:
        for node in json.loads(path.read_text())['nodes']:
            if node['type'] in ('LoadImage', 'LoadImageMask'):
                assert 'upload' not in node['widgets_values_named']
            if node['type'] == 'PrimitiveInt':
                assert node['widgets_values'][1] == 'fixed'
