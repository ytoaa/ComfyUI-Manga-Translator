"""Keep mixed-page failure isolation in the full regression, not just a demo."""
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_mixed_folder_runs_actual_08_nodes_and_resumes_without_extra_submissions(tmp_path):
    result = subprocess.run([sys.executable,str(ROOT/'tools/simulate_project.py'),
                             '--destination',str(tmp_path/'simulation')],
                            cwd=ROOT,capture_output=True,text=True,timeout=90)
    assert result.returncode == 0, result.stderr[-8000:]
    report = json.loads((tmp_path/'simulation/simulation-summary.json').read_text())
    assert report['simulation_only'] is True
    assert report['counts'] == {'completed':4,'failed':5,'needs_review':1,'unchanged_blank':1}
    assert report['resume_extra_submissions'] == 0 and report['submitted_pages'] == 10
    assert report['layout_boundary_probe']['scope'] == 'real_CPU_font_pixels_not_model_inference'
    assert report['page_order'][0]=='chapter/1.png' and report['page_order'][-2:] == ['chapter/10.png','extra/1.png']
