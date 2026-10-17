"""Exercise the shipped extension against ComfyUI's native event/queue contract."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_native_canvas_frontend_contract():
    node=shutil.which('node')
    if not node: pytest.skip('Node.js is required for frontend contract verification')
    root=Path(__file__).resolve().parents[1]
    subprocess.run([node,str(root/'tools/check_canvas_frontend.cjs')],cwd=root,check=True,capture_output=True,text=True)
