"""Original, deterministic image scenarios and independent reference metrics.

No user images, detector predictions or OCR answers are used to make references.
Font coverage is checked before drawing; missing glyphs are a fixture error.
"""
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT/'lettering/fonts/MangaSansKR-Fallback.ttf'
SEED = 9407


def normalized(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).strip()


def distance(a, b):
    previous = list(range(len(b)+1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(left != right)))
        previous = current
    return previous[-1]


def text_score(expected, actual):
    a, b = normalized(expected), normalized(actual)
    edits = distance(a, b)
    compact_a, compact_b = re.sub(r'\s', '', a), re.sub(r'\s', '', b)
    return {'normalization': 'NFKC and collapsed whitespace; case/punctuation retained',
            'reference_characters': len(a), 'edit_distance': edits,
            'cer': edits/len(a) if a else None, 'exact': a == b,
            'content_cer_without_whitespace': distance(compact_a, compact_b)/len(compact_a) if compact_a else None}


def raster_box(box, shape):
    if len(box)!=4 or not np.isfinite(box).all():raise ValueError('Expected four finite crop coordinates')
    a, b, c, d = box
    return [max(0, min(shape[1], int(np.floor(a)))), max(0, min(shape[0], int(np.floor(b)))),
            max(0, min(shape[1], int(np.ceil(c)))), max(0, min(shape[0], int(np.ceil(d))))]


def coverage(mask, boxes):
    selected = np.zeros(mask.shape, bool)
    for box in boxes:
        a, b, c, d = raster_box(box, mask.shape)
        if a>=c or b>=d:continue
        selected[b:d, a:c] = True
    total = int(mask.sum())
    return float((mask & selected).sum()/total) if total else None


def boxes_score(truths, masks, boxes, include_sfx=False):
    rows = []
    for row, mask in zip(truths, masks):
        if row.get('kind') == 'sfx' and not include_sfx:
            continue
        fraction = coverage(mask, boxes)
        rows.append({'id': row['id'], 'ink_coverage': fraction,
                     'complete': fraction is not None and fraction >= .98})
    crossings = []
    for index, box in enumerate(boxes):
        columns = sorted({row['column'] for row, mask in zip(truths, masks)
                          if row.get('column') and (coverage(mask, [box]) or 0) > .05})
        if len(columns)>1:crossings.append({'crop_index': index, 'columns': columns, 'crop': box})
    duplicates = 0.
    if masks:
        scoped = [m for r, m in zip(truths, masks) if include_sfx or r.get('kind')!='sfx']
        if scoped:
            ink = np.logical_or.reduce(scoped);owners = np.zeros(ink.shape, np.uint16)
            for box in boxes:
                a, b, c, d = raster_box(box, ink.shape)
                if a>=c or b>=d:continue
                owners[b:d, a:c] += 1
            duplicates = float(((owners>1) & ink).sum()/max(1, ink.sum()))
    return {'reference_regions': rows, 'missing_or_partial_ids': [r['id'] for r in rows if not r['complete']],
            'cross_column_crops': crossings, 'duplicate_reference_ink_fraction': duplicates,
            'unexpected_crops_on_blank': bool(not truths and boxes),
            'criterion': '>=98% reference ink retained, <=1% duplicate ink, no mixed body columns or blank false crops; not OCR accuracy or general detector precision'}


def localization_met(score):
    return (not score['missing_or_partial_ids'] and not score['cross_column_crops']
            and score['duplicate_reference_ink_fraction']<=.01 and not score['unexpected_crops_on_blank'])


@lru_cache(maxsize=1)
def supported_characters():
    with TTFont(FONT) as face:
        return frozenset(chr(c) for c in face.getBestCmap())


def font(size, text):
    missing = sorted(set(text)-set('\n\t\r')-supported_characters())
    if missing:
        raise ValueError('Fixture font lacks reference characters: '+repr(missing))
    return ImageFont.truetype(str(FONT), size)


def text_layer(text, size=28, color='black', background='white', angle=0, outline=0, vertical=False, texture=False):
    face = font(size, text)
    if vertical:
        canvas = Image.new('RGB', (size*3, (size+8)*len(text)+24), background)
        ink = Image.new('L', canvas.size)
        for i, char in enumerate(text):
            ImageDraw.Draw(ink).text((size, 12+i*(size+8)), char, font=face, fill=255, anchor='la')
    else:
        bounds = ImageDraw.Draw(Image.new('L', (1, 1))).multiline_textbbox((0, 0), text, font=face, spacing=10, stroke_width=outline)
        canvas = Image.new('RGB', (bounds[2]-bounds[0]+24, bounds[3]-bounds[1]+24), background)
        ink = Image.new('L', canvas.size)
        ImageDraw.Draw(ink).multiline_text((12-bounds[0], 12-bounds[1]), text, font=face, fill=255, spacing=10, stroke_width=outline)
    if texture:
        pixels = np.asarray(canvas).astype(np.int16)
        noise = np.random.default_rng(SEED).integers(-12, 13, (*pixels.shape[:2], 1))
        canvas = Image.fromarray((pixels+noise).clip(0, 255).astype('uint8'))
    canvas.paste(color, mask=ink)
    if angle:
        canvas = canvas.rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor=background)
        ink = ink.rotate(angle, Image.Resampling.BICUBIC, expand=True)
    return canvas, np.asarray(ink) > 0


class Page:
    def __init__(self, size, background='white'):
        self.image = Image.new('RGB', size, background)
        self.rows, self.masks = [], []

    def place(self, ident, text, xy, column=None, kind='text', **style):
        tile, mask = text_layer(text, **style)
        x, y = xy
        if x < 0 or y < 0 or x+tile.width > self.image.width or y+tile.height > self.image.height:
            raise ValueError('Generated reference is clipped: '+ident)
        self.image.paste(tile, xy)
        full = np.zeros(self.image.size[::-1], bool)
        full[y:y+tile.height, x:x+tile.width] = mask
        yy, xx = np.where(full)
        self.rows.append({'id': ident, 'text': text, 'kind': kind, 'column': column,
                          'bbox_pixels': [int(xx.min()), int(yy.min()), int(xx.max()+1), int(yy.max()+1)]})
        self.masks.append(full)


def column_page(sidebar=False, texture=False):
    page = Page((840, 760), '#ebe6da')
    if texture:
        pixels = np.asarray(page.image).astype(np.int16)
        noise = np.random.default_rng(SEED).integers(-16, 17, (*pixels.shape[:2], 1))
        page.image = Image.fromarray((pixels+noise).clip(0, 255).astype('uint8'))
    boxes = []
    for col, x in enumerate((120, 350, 580), 1):
        for para, y in enumerate((45, 275, 505), 1):
            text = '\n'.join(f'Column {col} line {r}' for r in range(1, 6))
            page.place(f'c{col}p{para}', text, (x, y), column=col, size=16, background='#ebe6da', texture=texture)
            if col == 1:boxes.append([x, y, x+180, y+150])
        if col != 1:boxes.append([x, 45, x+180, 655])
    boxes += [[120, 45, 530, 425], [350, 275, 760, 655]]
    if sidebar:
        page.place('sidebar', 'INDEX', (4, 360), size=15, background='#ebe6da')
        boxes.append([4, 360, 90, 405])
    data = {'origin': 'rfdetr', 'image_width': 840, 'image_height': 760,
            'regions': [{'id': f'r{i+1}', 'kind': 'text', 'bbox': [v*1000/[840, 760, 840, 760][j] for j, v in enumerate(box)]}
                        for i, box in enumerate(boxes)]}
    return page, data


def pages():
    page = Page((1100, 720), '#dddddd')
    draw = ImageDraw.Draw(page.image)
    for box in ([20, 20, 1080, 340], [20, 370, 1080, 700]):draw.rectangle(box, fill='#a8a8a8', outline='black', width=4)
    for box in ([50, 45, 470, 235], [620, 410, 1050, 610]):draw.ellipse(box, fill='white', outline='black', width=3)
    page.place('speech1', 'KEEP THE GATE\nOPEN UNTIL NINE.', (92, 88), size=28)
    page.place('speech2', 'WE CAN STILL\nCATCH THE TRAIN.', (650, 450), size=28)
    page.place('effect', 'SWISH!', (80, 525), size=52, angle=13.5, kind='sfx', background='#a8a8a8')
    yield 'dialogue-effects', page
    page = Page((1600, 640), '#e8e8e8')
    draw = ImageDraw.Draw(page.image)
    for x in range(0, 1600, 100):draw.polygon([(x, 0), (x+100, 0), (x+50, 115)], fill='#d0d0d0')
    draw.rectangle([410, 135, 1560, 605], fill='#777777')
    page.place('heading', '図書', (930, 25), size=48, background='#e8e8e8')
    page.place('label', 'NOTES', (55, 160), size=30, background='#e8e8e8')
    for index, (text, y) in enumerate([('明日は駅で友達を待ちます。', 180),
            ('先生は静かに話します。\n春の公園を友達と歩きます。', 280),
            ('今日は学校で新しい本を開きます。', 420), ('今夜は家で音楽を楽しみます。', 525)], 1):
        page.place(f'body{index}', text, (450, y), size=28, color='white', background='#777777')
    yield 'seam-paragraphs', page
    yield 'three-columns-sidebar', column_page(sidebar=True, texture=True)[0]
    page = Page((1000, 900), '#e7cfe4')
    page.place('profile', 'LIBRARY NOTES\n明日は駅で友達を待ちます。\n先生は静かに話します。', (100, 200),
               size=28, color='#693c65', background='#e7cfe4', angle=13.5, texture=True)
    page.place('small-label', 'Section B', (620, 650), size=16, color='#693c65', background='#e7cfe4')
    yield 'slanted-profile', page
    page = Page((840, 1100), '#a4c9d9')
    draw = ImageDraw.Draw(page.image)
    for x in range(-600, 1100, 160):draw.line([(x, 0), (x+600, 1100)], fill='#c6b5df', width=60)
    page.place('stand', 'STAND C7', (330, 40), size=52, background='#a4c9d9', outline=1)
    page.place('title', 'MOONLIGHT', (65, 260), size=80, angle=90, background='#a4c9d9', outline=2)
    yield 'rotated-cover', page
    yield 'blank-control', Page((640, 480))


def ocr_cases():
    jp = '明日は駅で友達を待ちます。'
    specs = [('english', 'The last train leaves at nine.', {'size': 24}),
             ('english-small', 'The last train leaves at nine.', {'size': 12}),
             ('english-outline', 'KEEP THE GATE OPEN.', {'size': 52, 'outline': 2}),
             ('japanese', jp, {'size': 28}), ('japanese-small', jp, {'size': 14}),
             ('japanese-large', jp, {'size': 42}),
             ('white-on-gray', jp, {'size': 28, 'color': 'white', 'background': '#777777'}),
             ('paragraph', jp+'\n先生は静かに話します。', {'size': 28}),
             ('textured', jp, {'size': 28, 'background': '#e7cfe4', 'texture': True}),
             ('slanted-positive', jp, {'size': 28, 'angle': 13.5}),
             ('slanted-negative', jp, {'size': 28, 'angle': -17}),
             ('rotated-latin', 'MOONLIGHT EXPRESS', {'size': 36, 'angle': 90}),
             ('vertical-japanese', '先生は静かに話します。', {'size': 30, 'vertical': True}),
             ('traditional-chinese', '今天下午我們一起去看電影。', {'size': 28}),
             ('vertical-chinese', '春天的公園很美。', {'size': 30, 'vertical': True})]
    for ident, text, style in specs:
        image, mask = text_layer(text, **style)
        yield ident, text, style, image, mask


def generate(destination):
    destination = Path(destination);destination.mkdir(parents=True, exist_ok=True)
    record = {'schema': 1, 'seed': SEED, 'source': 'original generated text/shapes; no user assets',
              'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'font_file': FONT.name, 'font_sha256': hashlib.sha256(FONT.read_bytes()).hexdigest(),
              'pages': [], 'ocr': []}
    for ident, page in pages():
        path = destination/(ident+'.png');page.image.save(path)
        np.savez_compressed(destination/(ident+'-truth.npz'), **{r['id']: m for r, m in zip(page.rows, page.masks)})
        record['pages'].append({'id': ident, 'image': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                'size': list(page.image.size), 'regions': page.rows})
    for ident, text, style, image, mask in ocr_cases():
        path = destination/('ocr-'+ident+'.png');image.save(path)
        record['ocr'].append({'id': ident, 'image': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                              'size': list(image.size), 'expected': text, 'style': style})
    (destination/'references.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record
