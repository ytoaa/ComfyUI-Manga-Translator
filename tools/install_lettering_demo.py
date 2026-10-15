"""Copy only synthetic demo inputs; never modify models, profiles or packages."""
from argparse import ArgumentParser
from pathlib import Path
import shutil


def install(comfy_root):
    root = Path(comfy_root).expanduser().resolve()
    if not (root/'main.py').is_file() or not (root/'custom_nodes').is_dir():
        raise ValueError('Select the ComfyUI root containing main.py and custom_nodes/')
    source = Path(__file__).resolve().parents[1]/'lettering/examples'
    target = root/'input/manga-lettering-demo'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('original.png', 'cleaned.png', 'source_mask.png'):
        path = target/name
        if path.exists() and path.read_bytes() != (source/name).read_bytes():
            raise ValueError(f'Existing different demo file is preserved: {path}')
    for name in ('original.png', 'cleaned.png', 'source_mask.png'):
        shutil.copyfile(source/name, target/name)
    return target


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--comfy-root', required=True)
    print(install(parser.parse_args().comfy_root))
