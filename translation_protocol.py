"""Translation transport contracts and bounded, credential-free failure evidence."""
import json
import logging
import os
from pathlib import Path
import uuid

MODES = ['json_schema', 'json_object', 'prompt_only']


def response_format(mode, regions):
    if mode not in MODES:
        raise ValueError('Unknown translation response_format')
    if mode == 'prompt_only':
        return {}
    if mode == 'json_object':
        return {'response_format': {'type': 'json_object'}}
    schema = {
        'type': 'object', 'additionalProperties': False, 'required': ['translations'],
        'properties': {'translations': {
            'type': 'array', 'minItems': len(regions), 'maxItems': len(regions),
            'items': {'type': 'object', 'additionalProperties': False,
                      'required': ['id', 'target'], 'properties': {
                          'id': {'type': 'string', 'enum': [r['id'] for r in regions]},
                          'target': {'type': 'string', 'minLength': 1, 'maxLength': 2048}}}}}}
    return {'response_format': {'type': 'json_schema', 'json_schema': {
        'name': 'manga_page_translation', 'strict': True, 'schema': schema}}}


def evidence(response):
    """Whitelist answer evidence, excluding headers, reasoning and provider extras."""
    response = response if isinstance(response, dict) else {}
    choices = response.get('choices')
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    usage = response.get('usage')
    reason, tokens = choice.get('finish_reason'), usage.get('completion_tokens') if isinstance(usage, dict) else None
    return {'content': content[:200000] if isinstance(content, str) else None,
            'content_chars': len(content) if isinstance(content, str) else 0,
            'content_truncated': isinstance(content, str) and len(content) > 200000,
            'finish_reason': reason if isinstance(reason, str) else None,
            'completion_tokens': tokens if type(tokens) is int else None}


def failure_root():
    import folder_paths
    output = Path(folder_paths.get_output_directory()).resolve()
    root = output / 'manga_translator' / 'translation_failures'
    if not root.resolve().is_relative_to(output):
        raise ValueError('Translation evidence directory is outside configured output')
    return root


def save_failure(source, settings, attempts, code):
    """A failure to save evidence must never replace the translation exception."""
    try:
        root = failure_root()
        root.mkdir(parents=True, exist_ok=True)
        path = root / ('translation_' + uuid.uuid4().hex + '.json')
        rows = [{k: row[k] for k in ('id', 'bbox', 'crop_bbox_pixels', 'edit_bbox_pixels', 'source') if k in row}
                for row in source['regions']]
        report = {'schema': 1, 'code': code, 'regions': rows,
                  'image_width': source.get('image_width'), 'image_height': source.get('image_height'),
                  'settings': settings, 'attempts': attempts[:32]}
        raw = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
        if len(raw)>8*1024*1024: raise ValueError('Translation evidence exceeds 8 MiB')
        temporary = path.with_suffix('.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        logging.getLogger(__name__).error('Translation failure response saved: %s', path)
        return str(path)
    except Exception as exc:
        logging.getLogger(__name__).error('Translation failure diagnostics could not be saved (%s)', type(exc).__name__)
        return 'unavailable'
