"""GUI/API graph primitives for the single integrated workflow (no inference)."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import uuid

from workflow_widgets import normalize_workflow, widget_field


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT/'lettering'
spec = importlib.util.spec_from_file_location('lettering_examples', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from lettering_examples.lettering import core, nodes



CORE_SCHEMAS = {
    'PrimitiveInt': {'required': {'value': ('INT', {'default': 0, 'control_after_generate': True})}},
    'ImageCrop': {'required': {'image': ('IMAGE',), 'width': ('INT', {'default': 512}),
                              'height': ('INT', {'default': 512}), 'x': ('INT', {'default': 0}), 'y': ('INT', {'default': 0})}},
    'CropMask': {'required': {'mask': ('MASK',), 'x': ('INT', {'default': 0}), 'y': ('INT', {'default': 0}),
                             'width': ('INT', {'default': 512}), 'height': ('INT', {'default': 512})}},
    'ImageCompositeMasked': {'required': {'destination': ('IMAGE',), 'source': ('IMAGE',),
        'x': ('INT', {'default': 0}), 'y': ('INT', {'default': 0}), 'resize_source': ('BOOLEAN', {'default': False})},
        'optional': {'mask': ('MASK',)}},
    'LoadImage': {'required': {'image': ([''], {'default': ''}), 'upload': ('STRING', {'default': 'image'})}},
    'LoadImageMask': {'required': {'image': ([''], {'default': ''}), 'channel': (['alpha', 'red', 'green', 'blue'], {'default': 'red'}), 'upload': ('STRING', {'default': 'image'})}},
    'PreviewImage': {'required': {'images': ('IMAGE',)}},
    'SaveImage': {'required': {'images': ('IMAGE',), 'filename_prefix': ('STRING', {'default': 'manga_lettering'})}},
    'ImageScale': {'required': {'image': ('IMAGE',), 'upscale_method': (['lanczos'], {'default': 'lanczos'}),
                              'width': ('INT', {'default': 512}), 'height': ('INT', {'default': 256}),
                              'crop': (['disabled'], {'default': 'disabled'})}}}
CORE_RETURNS = {'LoadImage': ('IMAGE', 'MASK'), 'LoadImageMask': ('MASK',), 'PreviewImage': (), 'SaveImage': (),
                'ImageScale': ('IMAGE',), 'PrimitiveInt': ('INT',), 'ImageCrop': ('IMAGE',),
                'CropMask': ('MASK',), 'ImageCompositeMasked': ('IMAGE',)}


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
        for name, field in {**schema['required'], **schema.get('optional', {})}.items():
            t, options = field[0], field[1] if len(field) > 1 else {}
            widget = widget_field(field)
            if widget:
                default = options.get('default', t[0] if isinstance(t, list) else '')
                val = values.get(name, default)
                widgets.append(val)
                named[name] = val
                # upload is a UI-only button, not an API input.
                if name != 'upload': api[name] = val
                if options.get('control_after_generate'):
                    widgets.append('fixed')
                    named['control_after_generate'] = 'fixed'
            else:
                inputs.append({'name': name, 'type': t, 'link': None})
        node = {'id': node_id, 'type': kind, 'pos': list(pos), 'size': [330, max(100, 60+30*len(widgets))],
                'flags': {}, 'order': node_id-1, 'mode': 0, 'inputs': inputs,
                'outputs': [{'name': getattr(cls, 'RETURN_NAMES', returns)[i] if cls else t, 'type': t, 'links': []} for i, t in enumerate(returns)],
                'properties': {'Node name for S&R': kind}, 'widgets_values': widgets,
                'widgets_values_named': named, 'title': title or nodes.NODE_DISPLAY_NAME_MAPPINGS.get(kind, kind)}
        self.nodes.append(node)
        self.prompt[str(node_id)] = {'class_type': kind, 'inputs': api}
        return node_id

    def connect(self, source, slot, target, field):
        def depends(ident,visited):
            if ident==str(target):return True
            if ident in visited:return False
            visited.add(ident)
            return any(depends(v[0],visited) for v in self.prompt[ident]['inputs'].values()
                       if isinstance(v,list) and len(v)==2 and isinstance(v[0],str) and v[0] in self.prompt)
        if depends(str(source),set()):raise ValueError('Workflow connection would create a cycle')
        dest, origin = self.nodes[target-1], self.nodes[source-1]
        match = next((i for i, item in enumerate(dest['inputs']) if item['name'] == field), None)
        if match is None:
            match = len(dest['inputs'])
            dest['inputs'].append({'name': field, 'type': origin['outputs'][slot]['type'], 'link': None, 'widget': {'name': field}})
        old=dest['inputs'][match].get('link')
        if old is not None:
            link=next(l for l in self.links if l[0]==old)
            self.nodes[link[1]-1]['outputs'][link[2]]['links'].remove(old)
            self.links.remove(link)
        link_id = max((link[0] for link in self.links),default=0)+1
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
              'last_node_id': len(self.nodes), 'last_link_id': max((link[0] for link in self.links),default=0), 'nodes': self.nodes,
              'links': self.links, 'groups': [], 'config': {}, 'extra': {'ds': {'scale': .55, 'offset': [20, 20]}}, 'version': .4}
        ui = normalize_workflow(ui, self.prompt, module.NODE_CLASS_MAPPINGS)
        folder = PACK/'example_workflows'
        folder.mkdir(exist_ok=True)
        (folder/(name+'.json')).write_text(json.dumps(ui, ensure_ascii=False, indent=2), encoding='utf-8')
        (folder/(name+'.api.json')).write_text(json.dumps(self.prompt, ensure_ascii=False, indent=2), encoding='utf-8')
