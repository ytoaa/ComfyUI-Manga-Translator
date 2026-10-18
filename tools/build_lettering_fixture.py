"""Rebuild synthetic lettering images; does not create workflow variants."""
from argparse import ArgumentParser
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from workflow_graph import PACK, core

def save_rgb(path, value):
    Image.fromarray((np.clip(value, 0, 1)*255).round().astype('uint8')).save(path)


def demo(destination):
    folder = Path(destination)
    folder.mkdir(parents=True,exist_ok=True)
    canvas = Image.new('RGB', (1024, 768), '#faf8f2')
    d = ImageDraw.Draw(canvas)
    d.rectangle((28, 28, 560, 330), fill='#eeeeec', outline='#151515', width=4)
    d.rectangle((580, 28, 995, 330), fill='#d5d7d5', outline='#151515', width=4)
    d.rectangle((28, 355, 995, 740), fill='#aaaeb2', outline='#151515', width=4)
    for y in range(364, 735, 7):
        for x in range(35+(y//7 % 2)*3, 990, 7):
            d.ellipse((x, y, x+1, y+1), fill='#777c83')
    d.ellipse((55, 60, 530, 285), fill='white', outline='#222222', width=3)
    d.ellipse((610, 48, 970, 310), fill='#f9f9f4', outline='#222222', width=3)
    cleaned = np.asarray(canvas, np.float32)/255
    original = cleaned.copy()
    old_alpha = np.zeros(cleaned.shape[:2], np.float32)
    regions = [
        {'id': 'dialogue', 'bbox': [85, 95, 420, 150], 'source_text': 'Are you okay?', 'text': '정말 괜찮아?',
         'font': 'NanumGothic-Regular.ttf', 'layout': {'max_font': 72, 'padding': 12, 'max_lines': 1}},
        {'id': 'vertical', 'bbox': [660, 72, 265, 220], 'source_text': 'WAIT!', 'text': '잠깐!\n기다려!',
         'layout': {'direction': 'vertical_rtl', 'max_font': 60, 'padding': 10, 'max_lines': 2}},
        {'id': 'effect', 'bbox': [100, 435, 820, 220], 'source_text': 'BOOOM!', 'text': '콰아앙!',
         'layout': {'max_font': 138, 'padding': 16, 'rotation': 5, 'shear': .16, 'max_lines': 1},
         'style': {'shadow_x': 4., 'shadow_y': 5., 'shadow_blur': .5}}]
    for i, item in enumerate(regions):
        x, y, w, h = item['bbox']
        style = {'version': 1, 'size': [w, h], 'foreground': [0.08]*3 if i < 2 else [.7, .06, .09],
                 'outline_color': [1.]*3, 'outline_width': 0. if i < 2 else 4.,
                 'texture': (np.random.default_rng(11).normal(0, .012, (32, 32)).astype(np.float32)),
                 'texture_strength': 1., 'weight_px': 0., 'shadow_x': 0., 'shadow_y': 0.,
                 'shadow_blur': 0., 'shadow_color': [0.]*3}
        layout = dict(item['layout'])
        if i == 1:
            layout['direction'] = 'horizontal'
        style.update(item.get('style', {}))
        layer, alpha, _ = core.render_text(item['source_text'], style,
            font_name=item.get('font', 'NanumGothic-Bold.ttf'), **layout)
        placement = {'version': 1, 'bbox_xywh': item['bbox'], 'page_size': [1024, 768]}
        original, changed = core.composite(original, layer, alpha, placement)
        old_alpha = np.maximum(old_alpha, changed)
    document = {'schema': 1, 'coordinate_format': 'xywh', 'page_size': [1024, 768], 'regions': regions}
    output, new_alpha, report = core.render_page(original, cleaned, old_alpha, json.dumps(document))
    save_rgb(folder/'original.png', original)
    save_rgb(folder/'cleaned.png', cleaned)
    Image.fromarray((old_alpha*255).round().astype('uint8')).save(folder/'source_mask.png')
    Image.fromarray((new_alpha*255).round().astype('uint8')).save(folder/'target_alpha.png')
    save_rgb(folder/'translated.png', output)
    (folder/'regions.json').write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder/'render_report.json').write_text(report, encoding='utf-8')
    # Contact sheet labels are explicitly a synthetic fixture, not a live model result.
    sheet = Image.new('RGB', (1536, 620), 'white')
    sd = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(PACK/'fonts/NanumGothic-Bold.ttf'), 24)
    sd.text((24, 12), '합성 테스트 이미지 · 생성 모델 결과 아님', font=font, fill='#111111')
    for i, (title, name) in enumerate([('원문 스타일', 'original.png'), ('원문 제거 배경', 'cleaned.png'), ('한국어 스타일 식자', 'translated.png')]):
        sd.text((i*512+20, 57), title, font=font, fill='#111111')
        im = Image.open(folder/name).resize((512, 384), Image.Resampling.LANCZOS)
        sheet.paste(im, (i*512, 100))
    small = ImageFont.truetype(str(PACK/'fonts/NanumGothic-Regular.ttf'), 20)
    sd.text((24, 510), '원본 잉크색·외곽선·미세 질감 측정 + 한글 폰트 / 세로쓰기·회전·기울기·그림자', font=small, fill='#333333')
    sd.text((24, 547), '새 번역문의 알파로 합성 · 원문 마스크와 교차하지 않음 · 원본 폰트 자동 복제는 미지원', font=small, fill='#333333')
    sheet.save(folder/'comparison.png')
    return document



if __name__ == '__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--destination',required=True)
    demo(parser.parse_args().destination)
