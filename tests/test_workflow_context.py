"""Regression tests for resolving a running ComfyUI prompt without graph equality."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import types

import pytest
from tests.test_project_runner import P

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('workflow_context_tests')
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
sys.modules[package.__name__ + '.tools.run_project'] = P
spec = importlib.util.spec_from_file_location(
    package.__name__ + '.workflow_project', ROOT / 'workflow_project.py')
W = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = W
spec.loader.exec_module(W)


def prompt(node_id='7'):
    return {
        node_id: {
            'class_type': 'MangaWorkflowInput',
            'inputs': {
                'input_mode': '폴더 프로젝트',
                'image': '',
                'input_folder': 'manga_uploads/run/book',
                'project_name': 'book',
                'action': '시작·재개',
            },
        },
        '99': {'class_type': 'PreviewAny', 'inputs': {'source': [node_id, 2]}},
    }


class Queue:
    def __init__(self, running):
        self.running = running

    def get_current_queue(self):
        return self.running, []


class Server:
    def __init__(self, running):
        self.prompt_queue = Queue(running)


def row(ident, queued, client='browser'):
    return (0, ident, queued, {'client_id': client}, [])


def test_context_survives_execution_annotations_on_prompt():
    live = prompt()
    queued = deepcopy(live)
    # ComfyUI may annotate the working prompt after the queue item was deep-copied.
    live['99']['is_changed'] = [False]
    assert queued != live
    assert W._context(Server([row('parent-1', queued)]), live, '7') == ('parent-1', 'browser')


def test_context_survives_annotation_on_source_node():
    live = prompt()
    queued = deepcopy(live)
    live['7']['is_changed'] = [None]
    assert queued != live
    assert W._context(Server([row('parent-2', queued, None)]), live, 7) == ('parent-2', None)


def test_context_refuses_ambiguous_running_jobs():
    live = prompt()
    first, second = deepcopy(live), deepcopy(live)
    first['99']['is_changed'] = [False]
    second['99']['is_changed'] = [True]
    with pytest.raises(P.ProjectError, match='둘 이상'):
        W._context(Server([row('a', first), row('b', second)]), live, '7')


def test_context_does_not_fallback_to_wrong_node_type():
    live = prompt()
    wrong = deepcopy(live)
    wrong['7']['class_type'] = 'OtherNode'
    with pytest.raises(P.ProjectError, match='찾을 수 없습니다'):
        W._context(Server([row('wrong', wrong)]), live, '7')
