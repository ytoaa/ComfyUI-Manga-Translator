"""Build a lean install ZIP, or an explicit development source ZIP.

The repository manifest describes source integrity. Each archive gets its own
manifest; building a package never rewrites repository files.
"""
from argparse import ArgumentParser
import ast
import hashlib
from pathlib import Path, PurePosixPath
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = {'README.md','CHANGELOG.md','VALIDATION.md','requirements.txt','requirements-alternatives.txt','LICENSE',
                'LICENSE-THIRD-PARTY-APACHE','LICENSE-THIRD-PARTY-MIT',
                'THIRD_PARTY_NOTICES.md','provenance.json'}
WORKFLOW = '08-integrated-tiled-cleanup-lettering'


def source_files(root=ROOT):
    """Read and verify the registered source catalog without requiring Git."""
    root=Path(root);files=[];seen=set()
    for line in (root/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        expected,name=line.split('  ',1)
        path=PurePosixPath(name)
        if (not re.fullmatch('[0-9a-f]{64}',expected) or path.is_absolute()
                or '..' in path.parts or name in seen or name=='SHA256SUMS'
                or '.git' in path.parts or path.name.startswith('.env')):
            raise ValueError('Invalid source manifest entry: '+name)
        item=root.joinpath(*path.parts)
        if item.is_symlink() or not item.is_file() or root.resolve() not in item.resolve().parents:
            raise ValueError('Expected a regular source file: '+name)
        if hashlib.sha256(item.read_bytes()).hexdigest()!=expected:
            raise ValueError('Source checksum mismatch: '+name+'; review the change before updating SHA256SUMS')
        seen.add(name);files.append(item)
    if not files:raise ValueError('Empty source manifest')
    return files


def runtime_file(relative):
    parts=relative.parts
    if len(parts)==1:return relative.suffix=='.py' or relative.name in RUNTIME_ROOT
    if parts[0]=='adapters':return relative.suffix=='.py'
    if parts[0]=='web':return relative.suffix=='.js'
    if parts[0]=='docs':return relative.suffix=='.md' and parts[1]!='history'
    if relative.as_posix()=='tools/run_project.py':return True
    if parts[0]!='lettering':return False
    return (relative.suffix=='.py' or parts[1]=='fonts'
            or relative.as_posix() in {f'lettering/example_workflows/{WORKFLOW}{suffix}'
                                      for suffix in ('.json','.api.json')})


def version():
    # Avoid importing the ComfyUI runtime merely to name a source archive.
    tree=ast.parse((ROOT/'workflow_native.py').read_text(encoding='utf-8'))
    values=[ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
            and any(isinstance(target,ast.Name) and target.id=='VERSION' for target in node.targets)]
    if len(values)!=1 or not isinstance(values[0],str) or not re.fullmatch(r'\d+\.\d+\.\d+',values[0]):
        raise ValueError('workflow_native.VERSION must be one semantic version')
    return values[0]


def package(destination,include_development=False):
    files=[p for p in source_files() if include_development or runtime_file(p.relative_to(ROOT))]
    files.sort()
    required={'__init__.py','workflow_native.py','tools/run_project.py',
              f'lettering/example_workflows/{WORKFLOW}.json'}
    if not required<={p.relative_to(ROOT).as_posix() for p in files}:
        raise ValueError('Package is missing required runtime files')
    sums=''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.relative_to(ROOT).as_posix()+'\n'
                 for path in files)
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    profile='-source' if include_development else ''
    output=destination/f'ComfyUI-Manga-Translator-integrated-v{version()}{profile}.zip'
    temporary=output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:archive.write(path,'ComfyUI-Manga-Translator/'+path.relative_to(ROOT).as_posix())
        archive.writestr('ComfyUI-Manga-Translator/SHA256SUMS',sums)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:raise ValueError('Corrupt package ZIP')
        for line in sums.splitlines():
            expected,name=line.split('  ',1)
            if hashlib.sha256(archive.read('ComfyUI-Manga-Translator/'+name)).hexdigest()!=expected:
                raise ValueError('Archive checksum mismatch: '+name)
    temporary.replace(output)
    output.with_suffix('.zip.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n',encoding='utf-8')
    print(output)
    print(f'{len(files)+1} files; profile={"source" if include_development else "runtime"}; ZIP and file SHA256 verified')
    return output


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--destination',required=True)
    parser.add_argument('--include-development',action='store_true',help='Include tests, developer tools and historical records')
    args=parser.parse_args();package(args.destination,args.include_development)
