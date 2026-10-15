"""Complete JSON vs. Markdown wrapping, completion limits, and bounded retry."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('translation_response_plugin', ROOT/'nodes.py')
N = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = N
spec.loader.exec_module(N)
SOURCE = {'regions': [{'id': 'a', 'bbox': [0, 0, 100, 100], 'source': '先生'},
                      {'id': 'b', 'bbox': [200, 200, 300, 300], 'source': 'こんにちは'}]}
VALID = {'translations': [{'id': 'b', 'target': '안녕하세요'}, {'id': 'a', 'target': '선생님'}]}
BODY = json.dumps(VALID, ensure_ascii=False)


@pytest.mark.parametrize('wrapped', [BODY, '```json\n'+BODY+'\n```', '```\n'+BODY+'\n```',
    '```JSON\r\n'+BODY+'\r\n```', '```json '+BODY+'```', '```json\n'+BODY,
    '\ufeff'+BODY, '```'+BODY+'```'])
def test_one_complete_json_value_can_have_optional_markdown_fences(wrapped):
    assert N.decode_translation(wrapped) == VALID


@pytest.mark.parametrize('bad', ['```json\n'+BODY[:-2], '```json\n'+BODY+'\n``',
    BODY+' '+BODY, 'Commentary: '+BODY, '```json\n'+BODY+'\n```\nMore commentary',
    '```python\n'+BODY+'\n```', '{"translations": NaN}', '', 'x'*200001])
def test_partial_json_extra_answers_and_unexpected_text_are_not_repaired(bad):
    with pytest.raises(ValueError): N.decode_translation(bad)


def test_literal_backticks_and_escaped_lines_inside_target_are_preserved():
    expected = {'translations': [{'id': 'a', 'target': '문자 ``` 그대로\n"다음 줄"'}]}
    assert N.decode_translation('```json\n'+N.encode(expected)) == expected


def reply(content=BODY, reason='stop'):
    return {'choices': [{'finish_reason': reason, 'message': {'content': content}}],
            'usage': {'completion_tokens': 85}}


def run(monkeypatch, responses):
    calls = []
    def api(base, path, key, timeout, payload=None):
        calls.append(payload)
        assert path == '/chat/completions'
        return responses[len(calls)-1]
    monkeypatch.setattr(N, 'api_json', api)
    return calls, lambda: N.MangaTranslate().translate(N.encode(SOURCE), 'http://unused/v1',
        'fixture-model', 'Korean', '', 4096, 300)[0]


def test_complete_json_without_closing_fence_is_accepted_without_regeneration(monkeypatch):
    calls, translate = run(monkeypatch, [reply('```json\n'+BODY)])
    result = json.loads(translate())
    assert [row['target'] for row in result['regions']] == ['선생님', '안녕하세요']
    assert len(calls) == 1


@pytest.mark.parametrize('bad', ['```json\n'+BODY[:-2], N.encode({'translations': VALID['translations'][:1]}),
    N.encode({'translations': [VALID['translations'][0], VALID['translations'][0]]})])
def test_format_or_region_contract_failure_retries_only_translation_once(monkeypatch, bad):
    calls, translate = run(monkeypatch, [reply(bad), reply()])
    result = json.loads(translate())
    assert len(calls) == 2 and [row['id'] for row in result['regions']] == ['a', 'b']
    assert calls[0]['messages'][:2] == calls[1]['messages'][:2]
    assert len(calls[1]['messages']) == 3
    assert bad not in [message['content'] for message in calls[1]['messages']]
    assert all(payload['max_tokens'] == 4096 for payload in calls)


def test_two_bad_responses_stop_with_metadata_and_no_partial_output(monkeypatch):
    calls, translate = run(monkeypatch, [reply('```json\n{"translations":'), reply('```json\n{"translations":')])
    with pytest.raises(ValueError, match='after one retry') as exc:
        translate()
    assert len(calls) == 2 and 'completion_tokens=85' in str(exc.value)
    assert 'line 1, column' in str(exc.value)


@pytest.mark.parametrize('reason', ['length', 'content_filter', 'error'])
def test_non_normal_completion_is_not_salvaged_or_retried(monkeypatch, reason):
    calls, translate = run(monkeypatch, [reply(BODY, reason)])
    with pytest.raises(ValueError, match='did not finish normally') as exc:
        translate()
    assert 'finish_reason='+repr(reason) in str(exc.value) and len(calls) == 1


def test_reasoning_only_response_is_not_used_as_translation(monkeypatch):
    response = reply(None)
    response['choices'][0]['message']['reasoning_content'] = BODY
    calls, translate = run(monkeypatch, [response])
    with pytest.raises(ValueError, match='no answer content'):
        translate()
    assert len(calls) == 1
