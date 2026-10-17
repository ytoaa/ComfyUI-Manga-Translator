"""Build an installable plugin ZIP with source, fonts, examples and checksums."""
from argparse import ArgumentParser
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = {'__init__.py', 'nodes.py', 'models.py', 'requirements.txt', 'README.md', 'LICENSE',
       'LICENSE-THIRD-PARTY-APACHE', 'LICENSE-THIRD-PARTY-MIT', 'THIRD_PARTY_NOTICES.md',
       'VALIDATION.md', 'provenance.json', 'pytest.ini', '.gitattributes', '.gitignore',
       'detection_policy.py', 'region_policy.py', 'mask_nodes.py', 'inpaint_tiles.py', 'ocr_policy.py', 'layout_refinement.py', 'workflow_project.py'}
DIRECTORIES = ('adapters', 'docs', 'examples', 'lettering', 'tests', 'tools', 'workflows')


def package(destination):
    files = [ROOT/name for name in TOP]
    for directory in DIRECTORIES:
        for path in (ROOT/directory).rglob('*'):
            if not path.is_file() or any(part in ('__pycache__', '.pytest_cache', '.venv', 'profiles', 'state') for part in path.relative_to(ROOT).parts):
                continue
            if path.name.startswith('.env') or path.suffix in ('.pyc', '.zip', '.safetensors', '.pth', '.ckpt'):
                continue
            files.append(path)
    files = sorted(set(files))
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Expected a regular source file: {path}')
    sums = ''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.relative_to(ROOT).as_posix()+'\n' for path in files)
    (ROOT/'SHA256SUMS').write_text(sums, encoding='utf-8', newline='\n')
    files.append(ROOT/'SHA256SUMS')
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    output = destination/'ComfyUI-Manga-Translator-integrated-v0.3.14.zip'
    temporary = output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'ComfyUI-Manga-Translator/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt package ZIP')
        for line in sums.splitlines():
            expected, name = line.split('  ', 1)
            actual = hashlib.sha256(archive.read('ComfyUI-Manga-Translator/'+name)).hexdigest()
            if actual != expected:
                raise ValueError('Archive checksum mismatch: '+name)
    temporary.replace(output)
    output.with_suffix('.zip.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n', encoding='utf-8', newline='\n')
    print(output)
    print(f'{len(files)} source/example files; ZIP integrity and per-file SHA256 verified')
    return output


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    package(parser.parse_args().destination)
