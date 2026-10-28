"""Final typography warnings must survive page collection and resume."""
import json
import pytest
from tests.test_project_runner import P, FakeComfy, make_page, project


class QualityClient(FakeComfy):
    def __init__(self, flag): super().__init__(); self.flag = flag
    def history(self, ident):
        history = super().history(ident)
        if not history: return history
        graph = self.jobs[ident]['graph']
        final = P.workflow_bindings(graph)['final']
        apply = graph[final]['inputs']['images'][0]
        history['outputs'][apply] = {'manga_lettering_report': [{
            'schema': 1, 'needs_review': self.flag, 'lettering_review': [],
            'regions': [{'id': 'r1', 'warning': 'source_ratio_relaxed'}] if self.flag is True else []}]}
        return history


@pytest.mark.parametrize('flag', [True, False])
def test_final_warning_without_preserved_regions_is_retained(tmp_path, flag):
    make_page(tmp_path/'input/1.png'); client = QualityClient(flag); runner = project(tmp_path, client)
    report = runner.run()
    expected = 'needs_review' if flag else 'completed'
    assert report['counts'] == {expected: 1}
    state = runner.state(runner.pages[0])
    path = runner._attempt_dir(state)/'lettering-report.json'
    assert json.loads(path.read_text())['needs_review'] is flag
    assert 'lettering-report.json' in state['artifacts']
    assert runner.run()['counts'] == {expected: 1}
    assert len(client.submissions) == 1


@pytest.mark.parametrize('flag', ['false', 0, 1, None, []])
def test_invalid_final_review_flag_never_becomes_completed(tmp_path, flag):
    make_page(tmp_path/'input/1.png'); runner = project(tmp_path, QualityClient(flag))
    with pytest.raises(P.ProtocolError, match='quality report'):
        runner.run()
    assert runner.state(runner.pages[0])['status'] != 'completed'
