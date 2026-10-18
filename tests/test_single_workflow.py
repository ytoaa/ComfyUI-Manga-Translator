"""The shipped workflow is unique and can be rebuilt without retired examples."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = '08-integrated-tiled-cleanup-lettering'


def test_only_one_workflow_is_shipped():
    files = sorted(path.relative_to(ROOT).as_posix()
                   for folder in ('workflows', 'lettering/example_workflows')
                   for path in (ROOT/folder).rglob('*.json'))
    assert files == [f'lettering/example_workflows/{NAME}.api.json',
                     f'lettering/example_workflows/{NAME}.json']
    graph = json.loads((ROOT/files[0]).read_text())
    kinds = [node['class_type'] for node in graph.values()]
    assert kinds.count('MangaWorkflowInput') == kinds.count('SaveImage') == 1
    assert kinds.count('PreviewAny') == 10
    previews = [node['inputs']['source'] for node in graph.values() if node['class_type'] == 'PreviewAny']
    source_id = next(i for i,n in graph.items() if n['class_type'] == 'MangaWorkflowInput')
    assert [source_id, 2] in previews
    for ident, node in graph.items():
        if node['class_type'] == 'MangaSaveReview':
            assert [ident, 0] in previews


def test_generator_rebuilds_identically_with_only_model_declarations(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'tools'))
    spec = importlib.util.spec_from_file_location('single_workflow_builder', ROOT/'tools/build_integrated_workflow.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    (tmp_path/'tools').mkdir()
    (tmp_path/'lettering').mkdir()
    shutil.copyfile(ROOT/'tools/integrated_model_nodes.json', tmp_path/'tools/integrated_model_nodes.json')
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(sys.modules[builder.Graph.__module__], 'PACK', tmp_path/'lettering')
    builder.build()
    for suffix in ('.json', '.api.json'):
        relative = Path('lettering/example_workflows')/(NAME+suffix)
        assert (tmp_path/relative).read_bytes() == (ROOT/relative).read_bytes()
