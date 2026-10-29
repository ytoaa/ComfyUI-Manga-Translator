"""Explicit OpenAI-compatible text calls; no secret is stored in workflows."""
import json
from http.client import IncompleteRead
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from .core import clean_text, integer, finite


def translate(text, base_url='http://127.0.0.1:8000/v1', model='', source_language='Japanese',
              target_language='Korean', max_tokens=1024, temperature=.2, timeout=120,
              key_environment='MANGA_LLM_API_KEY'):
    text = clean_text(text)
    integer(max_tokens, 16, 8192, 'max_tokens'); integer(timeout, 1, 600, 'timeout')
    finite(temperature, 0, 2, 'temperature')
    url = base_url.rstrip('/')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an HTTP(S) /v1 base URL without credentials, query or fragment')
    if not parsed.path.endswith('/v1'):
        raise ValueError('Translation base URL must end with /v1')
    if not isinstance(model, str) or len(model) > 256:
        raise ValueError('Invalid translation model')
    for language in (source_language, target_language):
        if not isinstance(language, str) or not language.strip() or len(language) > 64:
            raise ValueError('Invalid language name')
    if not isinstance(key_environment, str) or (key_environment and not key_environment.replace('_', '').isalnum()):
        raise ValueError('Invalid API key environment variable name')
    key = os.environ.get(key_environment, '') if key_environment else ''
    if '\r' in key or '\n' in key:
        raise ValueError('API key contains a line break')
    headers = {'Content-Type': 'application/json'}

    def call(path, payload=None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        request = Request(url+path, data=body, headers=headers, method='GET' if body is None else 'POST')
        if key: request.add_unredirected_header('Authorization', 'Bearer '+key)
        try:
            with urlopen(request, timeout=timeout) as response:
                data = response.read(1024*1024+1)
                if type(getattr(response,'length',None)) is int and response.length>0 and len(data)<=1024*1024:
                    raise ConnectionError('Incomplete translation response')
            if len(data) > 1024*1024:
                raise ValueError('Translation response exceeds 1 MiB')
            result = json.loads(data)
            if not isinstance(result,dict):
                raise ValueError('Translation server response must be a JSON object')
            return result
        except HTTPError as exc:
            # Do not echo server bodies/headers; they may contain credentials or user text.
            raise RuntimeError(f'Translation server HTTP {exc.code}') from None
        except (URLError, TimeoutError, ConnectionError, IncompleteRead) as exc:
            raise RuntimeError(f'Translation server unavailable ({type(exc).__name__})') from None

    if not model:
        models = call('/models').get('data', [])
        if (not isinstance(models,list) or len(models) != 1 or not isinstance(models[0],dict)
                or not isinstance(models[0].get('id'), str) or not models[0]['id'].strip()):
            raise ValueError('Set an explicit model when the server exposes zero or multiple models')
        model = models[0]['id']
    response = call('/chat/completions', {
        'model': model, 'temperature': temperature, 'max_tokens': max_tokens,
        'messages': [
            {'role': 'system', 'content': f'Translate comic dialogue from {source_language} to {target_language}. '
             'Return only the translated text. Preserve tone, sound effects and meaningful line breaks. '
             'Do not include explanations, quotation wrappers, reasoning or XML tags.'},
            {'role': 'user', 'content': text}]})
    choices = response.get('choices', [])
    if (not isinstance(choices,list) or len(choices) != 1 or not isinstance(choices[0],dict)
            or choices[0].get('finish_reason') != 'stop'):
        raise ValueError('Translation did not finish normally; increase token budget or check server output')
    message = choices[0].get('message')
    content = message.get('content') if isinstance(message,dict) else None
    if not isinstance(content, str) or '<think' in content.lower() or '</think>' in content.lower():
        raise ValueError('Translation contains reasoning or has no text content; check model settings')
    from ..text_contract import translation_text
    return clean_text(translation_text(text,content.strip())[0])
