"""Keep UI widget positions consistent with ComfyUI's node input declarations."""
from copy import deepcopy


def widget_field(spec):
    kind = spec[0]
    options = spec[1] if len(spec) > 1 else {}
    return not options.get('forceInput', False) and (
        isinstance(kind, list) or kind in ('STRING', 'INT', 'FLOAT', 'BOOLEAN'))


def normalize_workflow(workflow, prompt, registry):
    """Use input declarations, including connected widgets, rather than socket count.

    forceInput fields have no widget. A normal widget converted to a connected
    input still occupies a widgets_values position, even when hidden in the UI.
    Named values are additional metadata, not a substitute for that position.
    """
    result = deepcopy(workflow)
    for node in result['nodes']:
        if node['type'] == 'Note':
            continue
        api = prompt[str(node['id'])]['inputs']
        if node['type'] in ('LoadImage', 'LoadImageMask'):
            # The upload button has serialize:false; it is not an API input.
            names = ('image', 'channel') if node['type'] == 'LoadImageMask' else ('image',)
            node['widgets_values_named'] = {name: api[name] for name in names}
            node['widgets_values'] = list(node['widgets_values_named'].values())
        cls = registry.get(node['type'])
        if cls is None:
            continue
        if node['type'] in ('MangaDetectorLoader', 'MangaOCRLoader'):
            # Catalogs require a live ComfyUI folder_paths module; preserve the
            # saved model selection when regenerating examples offline.
            schema = {'required': {'model_name': ([api['model_name']],)}}
        else:
            schema = cls.INPUT_TYPES()
        fields = {**schema.get('required', {}), **schema.get('optional', {})}
        old_inputs = {item['name']: item for item in node.get('inputs', [])}
        named, sockets, converted = {}, [], []
        for name, spec in fields.items():
            options = spec[1] if len(spec) > 1 else {}
            kind = spec[0]
            old = old_inputs.get(name, {})
            if widget_field(spec):
                if name in node.get('widgets_values_named', {}):
                    value = node['widgets_values_named'][name]
                elif name in api and not isinstance(api[name], list):
                    value = api[name]
                else:
                    value = options.get('default', kind[0] if isinstance(kind, list) else '')
                named[name] = value
                if old.get('link') is not None:
                    converted.append({**old, 'name': name, 'widget': {'name': name}})
            else:
                slot = {**old, 'name': name, 'type': kind, 'link': old.get('link')}
                slot.pop('widget', None)
                sockets.append(slot)
        node['inputs'] = sockets + converted
        node['widgets_values_named'] = named
        node['widgets_values'] = list(named.values())
        for index, item in enumerate(node['inputs']):
            if item.get('link') is not None:
                link = next(link for link in result['links'] if link[0] == item['link'])
                link[4] = index
    result['revision'] = 1
    result.setdefault('extra', {})['frontendVersion'] = '1.53.10'
    return result
