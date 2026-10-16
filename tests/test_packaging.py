import importlib.util
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def test_installable_zip_imports_all_integrated_nodes(tmp_path):
    source = tmp_path/'source'
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache'))
    spec = importlib.util.spec_from_file_location('packaging_regression', source/'tools/package_style_lettering.py')
    tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
    archive = tool.package(tmp_path/'archive')
    with zipfile.ZipFile(archive) as z:
        z.extractall(tmp_path/'installed')
    installed = tmp_path/'installed/ComfyUI-Manga-Translator'
    name = 'installed_integrated_package'
    spec = importlib.util.spec_from_file_location(name, installed/'__init__.py', submodule_search_locations=[str(installed)])
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[name] = plugin
    spec.loader.exec_module(plugin)
    assert {'MangaInpaintPlan', 'MangaInpaintAssemble', 'MangaDetectionMask', 'MangaDetectorDetail', 'MangaLetterPlan', 'MangaLetterApply'} <= set(plugin.NODE_CLASS_MAPPINGS)
    assert plugin.NODE_CLASS_MAPPINGS['MangaDetectorDetail'].__module__.startswith(name+'.')
