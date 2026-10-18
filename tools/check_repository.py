"""Check registered source, current documentation links and release invariants."""
from argparse import ArgumentParser
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

if __package__:
    from .package_style_lettering import source_files, WORKFLOW
else:
    from package_style_lettering import source_files, WORKFLOW

ROOT=Path(__file__).resolve().parents[1]


def write_checksums():
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    paths=[ROOT/name for name in names if name and name!='SHA256SUMS']
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Stage additions/deletions before updating checksums: '+str(path.relative_to(ROOT)))
    content=''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.relative_to(ROOT).as_posix()+'\n'
                    for path in sorted(paths))
    (ROOT/'SHA256SUMS').write_text(content,encoding='utf-8')


def check():
    files=source_files();registered={p.relative_to(ROOT).as_posix() for p in files}
    # Git checkouts must not carry a stale catalog that silently omits new files.
    if (ROOT/'.git').exists():
        tracked=set(filter(None,subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')))-{'SHA256SUMS'}
        if tracked!=registered:raise ValueError('SHA256SUMS does not match registered Git paths')
    links=0
    for file in files:
        if file.suffix!='.md':continue
        for target in re.findall(r'\[[^\]]+\]\(([^\s)]+)\)',file.read_text(encoding='utf-8')):
            url=urlsplit(target)
            if url.scheme or url.netloc or not url.path:continue
            path=(file.parent/unquote(url.path)).resolve()
            if not path.exists() or (path.is_file() and path.relative_to(ROOT).as_posix() not in registered):
                raise ValueError(f'Broken local documentation link: {file.relative_to(ROOT)} -> {target}')
            links+=1
    examples=sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'lettering/example_workflows').glob('*.json'))
    expected=sorted(f'lettering/example_workflows/{WORKFLOW}{s}' for s in ('.json','.api.json'))
    if examples!=expected:raise ValueError('Ship exactly one integrated GUI/API workflow')
    for row in json.loads((ROOT/'provenance.json').read_text())['files']:
        actual=hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()
        if actual!=row['sha256']:raise ValueError('Current adapter provenance hash differs: '+row['path'])
        if row['modified']!=(row['source_sha256']!=row['sha256']):
            raise ValueError('Adapter modified flag differs from source hash: '+row['path'])
    print(f'{len(files)} registered files verified; {links} local documentation links; one GUI/API workflow; adapter provenance verified')


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--write-checksums',action='store_true',help='Explicitly regenerate from staged Git path inventory')
    args=parser.parse_args()
    if args.write_checksums:write_checksums()
    check()
