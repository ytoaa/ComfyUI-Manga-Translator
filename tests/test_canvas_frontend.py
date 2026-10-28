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


def test_native_canvas_frontend_faults():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for frontend fault verification')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, str(root/'tools/check_canvas_faults.cjs')], cwd=root,
                   check=True, capture_output=True, text=True, timeout=30)


def test_folder_upload_faults():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for upload fault verification')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, str(root/'tools/check_folder_upload.cjs')], cwd=root,
                   check=True, capture_output=True, text=True, timeout=30)
