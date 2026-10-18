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
    catalog = (source/'SHA256SUMS').read_bytes()
    archive = tool.package(tmp_path/'archive')
    assert (source/'SHA256SUMS').read_bytes() == catalog
    with zipfile.ZipFile(archive) as z:
        assert 'ComfyUI-Manga-Translator/workflow_project.py' in z.namelist()
        assert 'ComfyUI-Manga-Translator/web/folder_upload.js' in z.namelist()
        assert not any(name.endswith('/project_ui.py') or name.endswith('/web/projects.js') for name in z.namelist())
        examples = sorted(name for name in z.namelist()
                          if '/example_workflows/' in name and name.endswith('.json'))
        assert examples == [
            'ComfyUI-Manga-Translator/lettering/example_workflows/08-integrated-tiled-cleanup-lettering.api.json',
            'ComfyUI-Manga-Translator/lettering/example_workflows/08-integrated-tiled-cleanup-lettering.json']
        assert not any('/workflows/' in name for name in z.namelist())
        assert 'ComfyUI-Manga-Translator/tools/run_project.py' in z.namelist()
        assert 'ComfyUI-Manga-Translator/source_recovery.py' in z.namelist()
        assert not any('/tests/' in name or '/docs/history/' in name or '/lettering/examples/' in name
                       for name in z.namelist())
        assert 'ComfyUI-Manga-Translator/tools/package_style_lettering.py' not in z.namelist()
        assert 'ComfyUI-Manga-Translator/docs/configuration.md' in z.namelist()
        z.extractall(tmp_path/'installed')
    development = tool.package(tmp_path/'archive',include_development=True)
    assert development != archive and '-source.zip' in development.name
    with zipfile.ZipFile(development) as z:
        assert 'ComfyUI-Manga-Translator/tests/test_packaging.py' in z.namelist()
        assert 'ComfyUI-Manga-Translator/tools/check_repository.py' in z.namelist()
        assert 'ComfyUI-Manga-Translator/docs/history/validation.md' in z.namelist()
    assert (source/'SHA256SUMS').read_bytes() == catalog
    installed = tmp_path/'installed/ComfyUI-Manga-Translator'
    name = 'installed_integrated_package'
    spec = importlib.util.spec_from_file_location(name, installed/'__init__.py', submodule_search_locations=[str(installed)])
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[name] = plugin
    spec.loader.exec_module(plugin)
    assert {'MangaWorkflowInput','MangaInpaintPlan', 'MangaInpaintAssemble', 'MangaDetectionMask', 'MangaDetectorDetail', 'MangaLetterPlan', 'MangaLetterApply'} <= set(plugin.NODE_CLASS_MAPPINGS)
    assert plugin.NODE_CLASS_MAPPINGS['MangaDetectorDetail'].__module__.startswith(name+'.')
    assert plugin.WEB_DIRECTORY == './web'
