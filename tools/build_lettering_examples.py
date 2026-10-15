"""Reproducible synthetic fixtures and ComfyUI UI/API workflows (no GPU)."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT/'lettering'
spec = importlib.util.spec_from_file_location('lettering_examples', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from lettering_examples.lettering import core, nodes


def save_rgb(path, value):
    Image.fromarray((np.clip(value, 0, 1)*255).round().astype('uint8')).save(path)


def demo():
    folder = PACK/'examples'
    folder.mkdir(exist_ok=True)
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


CORE_SCHEMAS = {
    'LoadImage': {'required': {'image': ([''], {'default': ''}), 'upload': ('STRING', {'default': 'image'})}},
    'LoadImageMask': {'required': {'image': ([''], {'default': ''}), 'channel': (['alpha', 'red', 'green', 'blue'], {'default': 'red'}), 'upload': ('STRING', {'default': 'image'})}},
    'PreviewImage': {'required': {'images': ('IMAGE',)}},
    'SaveImage': {'required': {'images': ('IMAGE',), 'filename_prefix': ('STRING', {'default': 'manga_lettering'})}},
    'ImageScale': {'required': {'image': ('IMAGE',), 'upscale_method': (['lanczos'], {'default': 'lanczos'}),
                              'width': ('INT', {'default': 512}), 'height': ('INT', {'default': 256}),
                              'crop': (['disabled'], {'default': 'disabled'})}}}
CORE_RETURNS = {'LoadImage': ('IMAGE', 'MASK'), 'LoadImageMask': ('MASK',), 'PreviewImage': (), 'SaveImage': (), 'ImageScale': ('IMAGE',)}


class Graph:
    def __init__(self):
        self.nodes, self.prompt, self.links = [], {}, []

    def add(self, kind, values=None, pos=(0, 0), title=None):
        values = values or {}
        node_id = len(self.nodes)+1
        cls = nodes.NODE_CLASS_MAPPINGS.get(kind) or module.NODE_CLASS_MAPPINGS.get(kind)
        schema = cls.INPUT_TYPES() if cls else CORE_SCHEMAS[kind]
        returns = cls.RETURN_TYPES if cls else CORE_RETURNS[kind]
        inputs, widgets, named, api = [], [], {}, {}
        for name, field in schema['required'].items():
            t, options = field[0], field[1] if len(field) > 1 else {}
            widget = isinstance(t, list) or t in ('STRING', 'INT', 'FLOAT', 'BOOLEAN')
            if widget:
                default = options.get('default', t[0] if isinstance(t, list) else '')
                val = values.get(name, default)
                widgets.append(val)
                named[name] = val
                # upload is a UI-only button, not an API input.
                if name != 'upload': api[name] = val
            else:
                inputs.append({'name': name, 'type': t, 'link': None})
        node = {'id': node_id, 'type': kind, 'pos': list(pos), 'size': [330, max(100, 60+30*len(widgets))],
                'flags': {}, 'order': node_id-1, 'mode': 0, 'inputs': inputs,
                'outputs': [{'name': cls.RETURN_NAMES[i] if cls else t, 'type': t, 'links': []} for i, t in enumerate(returns)],
                'properties': {'Node name for S&R': kind}, 'widgets_values': widgets,
                'widgets_values_named': named, 'title': title or nodes.NODE_DISPLAY_NAME_MAPPINGS.get(kind, kind)}
        self.nodes.append(node)
        self.prompt[str(node_id)] = {'class_type': kind, 'inputs': api}
        return node_id

    def connect(self, source, slot, target, field):
        dest, origin = self.nodes[target-1], self.nodes[source-1]
        match = next((i for i, item in enumerate(dest['inputs']) if item['name'] == field), None)
        if match is None:
            match = len(dest['inputs'])
            dest['inputs'].append({'name': field, 'type': origin['outputs'][slot]['type'], 'link': None, 'widget': {'name': field}})
        link_id = len(self.links)+1
        dest['inputs'][match]['link'] = link_id
        origin['outputs'][slot]['links'].append(link_id)
        self.links.append([link_id, source, slot, target, match, origin['outputs'][slot]['type']])
        self.prompt[str(target)]['inputs'][field] = [str(source), slot]

    def import_model_node(self, template, node, pos):
        item = deepcopy(next(n for n in template['nodes'] if n['id'] == node))
        new_id = len(self.nodes)+1
        item['id'], item['pos'], item['order'] = new_id, list(pos), new_id-1
        for i in item.get('inputs', []): i['link'] = None
        for i in item.get('outputs', []): i['links'] = []
        self.nodes.append(item)
        fields = dict(item.get('widgets_values_named', {}))
        fields.pop('control_after_generate', None)
        self.prompt[str(new_id)] = {'class_type': item['type'], 'inputs': fields}
        return new_id

    def note(self, text, pos=(0, 850)):
        i = len(self.nodes)+1
        self.nodes.append({'id': i, 'type': 'Note', 'pos': list(pos), 'size': [500, 270], 'flags': {}, 'order': i-1,
                           'mode': 0, 'inputs': [], 'outputs': [], 'properties': {}, 'widgets_values': [text]})

    def save(self, name):
        ui = {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'manga-lettering/'+name)), 'revision': 0,
              'last_node_id': len(self.nodes), 'last_link_id': len(self.links), 'nodes': self.nodes,
              'links': self.links, 'groups': [], 'config': {}, 'extra': {'ds': {'scale': .55, 'offset': [20, 20]}}, 'version': .4}
        folder = PACK/'example_workflows'
        folder.mkdir(exist_ok=True)
        (folder/(name+'.json')).write_text(json.dumps(ui, ensure_ascii=False, indent=2), encoding='utf-8')
        (folder/(name+'.api.json')).write_text(json.dumps(self.prompt, ensure_ascii=False, indent=2), encoding='utf-8')


def sources(g):
    a = g.add('LoadImage', {'image': 'manga-lettering-demo/original.png'}, (0, 0), '① 원본 · 지우기 전')
    b = g.add('LoadImage', {'image': 'manga-lettering-demo/cleaned.png'}, (0, 300), '② 원문 제거 결과')
    c = g.add('LoadImageMask', {'image': 'manga-lettering-demo/source_mask.png', 'channel': 'red'}, (0, 600), '③ 원문 마스크 · 흰색=글자')
    return a, b, c


def single(kind='manual'):
    g = Graph()
    a, b, c = sources(g)
    region = g.add('MangaLetterRegion', {'x': 85, 'y': 95, 'width': 420, 'height': 150}, (390, 0))
    for src, slot, name in ((a, 0, 'original'), (b, 0, 'cleaned'), (c, 0, 'source_mask')): g.connect(src, slot, region, name)
    analyze = g.add('MangaLetterAnalyze', pos=(790, 0))
    for slot, name in enumerate(('reference', 'cleaned', 'source_mask')): g.connect(region, slot, analyze, name)
    adjust = g.add('MangaLetterStyleAdjust', pos=(1190, 0))
    g.connect(analyze, 0, adjust, 'style')
    render = g.add('MangaLetterRender', {'text': '정말 괜찮아?', 'font_name': 'NanumGothic-Regular.ttf', 'max_font': 72, 'padding': 12, 'max_lines': 1}, (1590, 0))
    g.connect(adjust, 0, render, 'style')
    composite = g.add('MangaLetterComposite', pos=(2020, 0))
    g.connect(b, 0, composite, 'cleaned_page'); g.connect(render, 0, composite, 'lettering')
    g.connect(render, 1, composite, 'lettering_alpha'); g.connect(region, 3, composite, 'placement')
    preview = g.add('SaveImage', {'filename_prefix': 'manga_lettering/'+kind}, (2440, 0))
    g.connect(composite, 0, preview, 'images')
    if kind == 'vllm':
        tr = g.add('MangaLetterTranslate', {'source_text': 'Are you okay?', 'source_language': 'English'}, (1190, 600))
        g.connect(tr, 0, render, 'text')
    g.note('설치 스크립트가 입력 예제를 ComfyUI/input/manga-lettering-demo에 복사합니다.\n'
           '실제 작업: 원본·지운 배경·원문 마스크 선택 → 원본 좌표로 영역 지정 → 번역문/폰트/스타일 조절.\n'
           '글자 알파는 원문 마스크와 별개입니다. 이 그래프를 기존 01/02 모델 편집 그래프와 별도로 수동 식자를 검증할 수 있습니다.\n'
           '원본 폰트 자동 복제/학습형 스타일 전이는 포함하지 않습니다.', (390, 550))
    return g, (region, render, composite)


def build_workflows(document):
    for kind, filename in [('manual', '01-single-region'), ('vllm', '03-vllm-translation')]:
        g, _ = single(kind)
        g.save(filename)
    page = Graph()
    a, b, c = sources(page)
    p = page.add('MangaLetterPage', {'regions_json': json.dumps(document, ensure_ascii=False, indent=2)}, (420, 0))
    for src, field in ((a, 'original'), (b, 'cleaned'), (c, 'source_mask')): page.connect(src, 0, p, field)
    out = page.add('SaveImage', {'filename_prefix': 'manga_lettering/page'}, (870, 0))
    page.connect(p, 0, out, 'images')
    page.note('여러 영역의 번역문·xywh 좌표·스타일·레이아웃을 JSON으로 지정합니다.\n'
              'region.text는 확정된 번역문입니다. OCR·번역·원문 제거는 별도 기존 단계에서 준비하세요.\n'
              '입력 마스크는 원문 스타일 분석에 사용하고, 최종 합성에는 새 글자 알파를 사용합니다.', (420, 450))
    page.save('02-page-regions')
    g, (region, render, composite) = single('qwen-texture')
    ref = g.add('MangaLetterAIReference', {'text': '정말 괜찮아?', 'source_text': 'Are you okay?'}, (1590, 800))
    g.connect(region, 0, ref, 'reference'); g.connect(render, 0, ref, 'lettering'); g.connect(render, 1, ref, 'lettering_alpha')
    template = json.loads((ROOT/'workflows/01-rfdetr-hayai-qwen21.json').read_text())
    q = {}
    for old, pos in [(2, (2020, 600)), (3, (2020, 800)), (4, (2020, 1000)), (6, (2400, 600)),
                      (5, (2400, 850)), (7, (2400, 1200)), (8, (2400, 1350)), (9, (2820, 800)), (10, (3220, 800))]:
        q[old] = g.import_model_node(template, old, pos)
    g.connect(q[2], 0, q[6], 'model'); g.connect(q[3], 0, q[5], 'clip'); g.connect(q[4], 0, q[5], 'vae')
    g.connect(ref, 0, q[5], 'images.image_1'); g.connect(ref, 1, q[5], 'images.image_2')
    g.connect(ref, 2, q[5], 'prompt')
    for src, slot, field in [(q[6], 0, 'model'), (q[5], 0, 'positive'), (q[5], 1, 'negative'),
                             (q[7], 0, 'sampler'), (q[8], 0, 'sigmas'), (q[5], 2, 'latent_image')]:
        g.connect(src, slot, q[9], field)
    g.connect(q[9], 0, q[10], 'samples'); g.connect(q[4], 0, q[10], 'vae')
    scale = g.add('ImageScale', {'width': 420, 'height': 150}, (3600, 800), '후보 → 식자 크기 정렬 · 영역 크기 변경 시 수정')
    g.connect(q[10], 0, scale, 'image')
    pigment = g.add('MangaLetterCandidateTexture', pos=(4000, 800))
    g.connect(render, 0, pigment, 'lettering'); g.connect(render, 1, pigment, 'lettering_alpha'); g.connect(scale, 0, pigment, 'candidate')
    # Replace links rather than leaving stale UI edges on the composite sockets.
    for field, slot in [('lettering', 0), ('lettering_alpha', 1)]:
        dest = g.nodes[composite-1]
        inp = next(i for i in dest['inputs'] if i['name'] == field)
        old_link = next(l for l in g.links if l[0] == inp['link'])
        g.nodes[old_link[1]-1]['outputs'][old_link[2]]['links'].remove(old_link[0])
        old_link[1], old_link[2] = pigment, slot
        g.nodes[pigment-1]['outputs'][slot]['links'].append(old_link[0])
        g.prompt[str(composite)]['inputs'][field] = [str(pigment), slot]
    candidate_preview = g.add('PreviewImage', pos=(3600, 1100), title='AI 후보 확인 · 페이지에 직접 붙이지 않음')
    g.connect(scale, 0, candidate_preview, 'images')
    g.note('선택형 GPU 실험: 기존 Qwen 2.1 Turbo INT8·인코더·VAE와 8스텝을 재사용합니다.\n'
           '참조1=원본 스타일, 참조2=정확한 한글 렌더링. 생성된 후보의 미세 밝기 질감만 사용합니다.\n'
           '번역문 획/외곽선/알파는 기본 렌더링을 유지합니다. 원본 폰트 형태를 복제하는 모델은 아닙니다.\n'
           '실제 Qwen 노드/GPU 실행은 이 환경에서 미검증. 먼저 01/02를 실행하세요.\n'
           '영역 크기를 변경하면 ImageScale의 width/height도 동일하게 맞추세요.', (2820, 1250))
    g.save('04-qwen-pigment-experimental')


def integrated_workflow(manual=False):
    """Fork the existing OCR/translation graph, keeping its JSON/ID contracts."""
    stem = '02-manual-regions-hayai-qwen21' if manual else '01-rfdetr-hayai-qwen21'
    ui = json.loads((ROOT/'workflows'/(stem+'.json')).read_text())
    api = json.loads((ROOT/'workflows'/(stem+'.api.json')).read_text())
    g = Graph()
    mapping = {}
    for item in ui['nodes']:
        old = str(item['id'])
        if old not in api:
            continue
        new = deepcopy(item)
        new_id = len(g.nodes)+1
        mapping[old] = new_id
        new['id'], new['order'] = new_id, new_id-1
        for i in new.get('inputs', []): i['link'] = None
        for o in new.get('outputs', []): o['links'] = []
        g.nodes.append(new)
        g.prompt[str(new_id)] = deepcopy(api[old])
    for old, node in api.items():
        for field, value in node['inputs'].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                g.connect(mapping[value[0]], value[1], mapping[old], field)
    prompt_id = mapping['55']
    g.prompt[str(prompt_id)]['class_type'] = 'MangaCleanupPrompt'
    instructions = 'Preserve original artwork, speech bubble borders, screen tones, colors, gradients and texture. Do not add lettering or a solid replacement background.'
    g.prompt[str(prompt_id)]['inputs']['instructions'] = instructions
    prompt_ui = g.nodes[prompt_id-1]
    prompt_ui['type'], prompt_ui['title'] = 'MangaCleanupPrompt', '이미지 모델 · 원문만 제거'
    prompt_ui['properties'] = {'Node name for S&R': 'MangaCleanupPrompt'}
    prompt_ui['widgets_values'] = [instructions]
    prompt_ui['widgets_values_named'] = {'instructions': instructions}
    prepare = g.add('MangaLetterPrepare', pos=(2450, 900))
    g.connect(mapping['19'], 0, prepare, 'original')
    g.connect(mapping['54'], 0, prepare, 'translated_json')
    page = g.add('MangaLetterPage', pos=(2900, 900))
    g.connect(mapping['19'], 0, page, 'original')
    g.connect(mapping['60'], 0, page, 'cleaned')
    g.connect(prepare, 0, page, 'regions_json'); g.connect(prepare, 1, page, 'source_mask')
    final = g.nodes[mapping['61']-1]
    field = next(i for i in final['inputs'] if i['name'] == 'images')
    old_link = next(l for l in g.links if l[0] == field['link'])
    g.nodes[old_link[1]-1]['outputs'][old_link[2]]['links'].remove(old_link[0])
    old_link[1], old_link[2] = page, 0
    g.nodes[page-1]['outputs'][0]['links'].append(old_link[0])
    g.prompt[str(mapping['61'])]['inputs']['images'] = [str(page), 0]
    g.prompt[str(mapping['61'])]['inputs']['filename_prefix'] = 'manga_translator/style_lettering'
    final['widgets_values'] = ['manga_translator/style_lettering']
    final['widgets_values_named'] = {'filename_prefix': 'manga_translator/style_lettering'}
    g.note('기존 OCR/번역 JSON 계약을 그대로 사용합니다.\n'
           'Qwen은 원문 제거만 수행 → 스타일 식자 노드가 번역문을 한글 폰트로 렌더링합니다.\n'
           'Qwen 배경 복원 품질은 별도 검수하세요. 원본 폰트 형태의 완전 자동 복제는 아닙니다.\n'
           '원본·원문 제거 결과의 차이로 잉크색/외곽선을 추정합니다. 배경 변화가 크면 정확한 text_pixel_mask를 추가하세요.\n'
           '영역별 폰트/회전/기울기/외곽선 설정은 번역 JSON 연결 노드의 region_options_json에서 지정합니다.\n'
           '이 통합 그래프의 GPU/번역 서버 실행은 미검증입니다.', (2900, 1500))
    filename = '06-manual-ocr-cleanup-lettering' if manual else '05-rfdetr-ocr-cleanup-lettering'
    g.save(filename)


if __name__ == '__main__':
    build_workflows(demo())
    integrated_workflow()
    integrated_workflow(manual=True)
    print(PACK/'examples/comparison.png')
