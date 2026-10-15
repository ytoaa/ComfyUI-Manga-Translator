from pathlib import Path
import importlib.util
import sys
import types

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('manga_ocr_line_tests')
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location(pkg.__name__+'.models', ROOT/'models.py')
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)


def test_horizontal_detector_crop_is_split_into_lines():
    image = Image.new('RGB', (120, 80), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 8, 110, 20), fill='black')
    draw.rectangle((10, 52, 110, 64), fill='black')
    crops = M._ocr_line_images(image)
    assert len(crops) == 2
    assert all(crop.width == 120 for crop in crops)
    assert sum(crop.height for crop in crops) >= image.height


def test_manga_ocr_joins_split_line_results(monkeypatch):
    source = Image.new('RGB', (80, 80), 'white')
    first = Image.new('RGB', (80, 38), 'white')
    second = Image.new('RGB', (80, 44), 'white')
    monkeypatch.setattr(M, 'pil_image', lambda images: source)
    monkeypatch.setattr(M, '_ocr_line_images', lambda image: [first, second])

    calls = []
    class Model:
        def ocr(self, image, options, max_patches):
            calls.append((image.size, options.max_new_tokens, max_patches))
            return {'text': '一行目' if len(calls) == 1 else '二行目'}

    value = M.MangaOCR().read(object(), Model(), max_new_tokens=256, max_patches=512)
    assert value == ('一行目\n二行目',)
    assert calls == [((80, 38), 256, 512), ((80, 44), 256, 512)]
