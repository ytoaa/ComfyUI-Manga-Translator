"""Evidence exports stay in configured output, including disk-failure cases."""
from pathlib import Path
import numpy as np
import pytest
from tools.simulate_ownership_scenarios import module
R=module('reproduction')


def save(output):
    return R.save(np.ones((8,8,3),np.float32),{'protocol':1,'image_width':8,'image_height':8,'detections':[]},'{"regions":[]}',output)


@pytest.mark.parametrize('relative',['manga_translator','manga_translator/reproduction'])
def test_export_cannot_follow_redirected_output_subdirectory(tmp_path,relative):
    output=tmp_path/'output';output.mkdir();outside=tmp_path/'outside';outside.mkdir()
    link=output/relative;link.parent.mkdir(parents=True,exist_ok=True);link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='outside'):save(output)
    assert not list(outside.iterdir())


def test_configured_output_symlink_still_exports(tmp_path):
    output=tmp_path/'output';actual=tmp_path/'actual';actual.mkdir();output.symlink_to(actual,target_is_directory=True)
    result=save(output)
    assert Path(result['path']).resolve().is_relative_to(actual)
    assert Path(result['path']).is_file()


def test_failed_export_does_not_leave_zip_or_temporary(tmp_path,monkeypatch):
    def fail(*args,**kwargs):raise OSError('injected archive disk failure')
    monkeypatch.setattr(R.zipfile.ZipFile,'writestr',fail)
    with pytest.raises(OSError,match='disk failure'):save(tmp_path)
    assert not list(tmp_path.rglob('*.zip')) and not list(tmp_path.rglob('*.tmp'))
