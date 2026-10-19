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


@pytest.fixture(autouse=True)
def diagnostic_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(N.translation_protocol, 'failure_root', lambda: tmp_path/'diagnostics')


@pytest.mark.parametrize('wrapped', [BODY, '```json\n'+BODY+'\n```', '```\n'+BODY+'\n```',
    '```JSON\r\n'+BODY+'\r\n```', '```json '+BODY+'```', '```json\n'+BODY,
    '\ufeff'+BODY, '```'+BODY+'```'])
def test_one_complete_json_value_can_have_optional_markdown_fences(wrapped):
    assert N.decode_translation(wrapped) == VALID


@pytest.mark.parametrize('bad', ['```json\n'+BODY[:-2], '```json\n'+BODY+'\n``',
    BODY+' '+BODY, 'Commentary: '+BODY, '```json\n'+BODY+'\n```\nMore commentary',
    '```python\n'+BODY+'\n```', '{"translations": NaN}', '', 'x'*200001],
    ids=['truncated', 'broken-fence', 'multiple-json', 'leading-prose', 'trailing-prose',
         'wrong-language', 'nonfinite', 'empty', 'oversized'])
def test_partial_json_extra_answers_and_unexpected_text_are_not_repaired(bad):
    with pytest.raises(ValueError): N.decode_translation(bad)


def test_literal_backticks_and_escaped_lines_inside_target_are_preserved():
    expected = {'translations': [{'id': 'a', 'target': '문자 ``` 그대로\n"다음 줄"'}]}
    assert N.decode_translation('```json\n'+N.encode(expected)) == expected


def reply(content=BODY, reason='stop'):
    return {'choices': [{'finish_reason': reason, 'message': {'content': content}}],
            'usage': {'completion_tokens': 85}}


def run(monkeypatch, responses, length_recovery="stop"):
    calls = []
    def api(base, path, key, timeout, payload=None):
        calls.append(payload)
        assert path == '/chat/completions'
        return responses[len(calls)-1]
    monkeypatch.setattr(N, 'api_json', api)
    return calls, lambda: N.MangaTranslate().translate(N.encode(SOURCE), 'http://unused/v1',
        'fixture-model', 'Korean', '', 4096, 300, length_recovery=length_recovery)[0]


def test_model_html_breaks_become_real_newlines_with_visible_evidence(monkeypatch):
    answer = {'translations': [{'id': 'a', 'target': '선생님<br>안녕<BR/>다음<br />끝'},
                               {'id': 'b', 'target': '안녕하세요'}]}
    calls, invoke = run(monkeypatch, [reply(N.encode(answer))])
    row = json.loads(invoke())['regions'][0]
    assert row['target'] == '선생님\n안녕\n다음\n끝'
    assert row['translation_diagnostics']['html_breaks_to_newlines'] == 3
    assert row['translation_diagnostics']['raw_target'] == answer['translations'][0]['target']
    assert 'plain text' in calls[0]['messages'][0]['content']
    assert len(calls) == 1


@pytest.mark.parametrize('text', ['a < b > c', '<3 &amp; <b>literal</b>', '<br class="x">'])
def test_plain_text_is_not_interpreted_as_general_html(text):
    source = {'regions': [{'id': 'a', 'source': '原文'}]}
    assert N.translations(source, {'translations': [{'id': 'a', 'target': text}]})['regions'][0]['target'] == text


def test_literal_source_break_tag_and_manual_override_are_preserved(monkeypatch):
    source = {'regions': [{'id': 'a', 'bbox': [0, 0, 100, 100], 'source': 'Use <br> literally.'}]}
    answer = {'translations': [{'id': 'a', 'target': '<br> 태그'}]}
    assert N.translations(source, answer)['regions'][0]['target'] == '<br> 태그'
    source['regions'][0]['source'] = '原文'
    monkeypatch.setattr(N, 'api_json', lambda *a, **k: pytest.fail('manual override must not call API'))
    result = N.MangaTranslate().translate(N.encode(source), '', '', '', '', 4096, 300, N.encode(answer))
    assert json.loads(result[0])['regions'][0]['target'] == '<br> 태그'


def test_cached_unreadable_ocr_requires_rerecognition_or_reviewed_override(monkeypatch):
    source = {'regions': [{'id': 'a', 'bbox': [0, 0, 100, 100], 'source': '文<UNK_SPAN>字'}]}
    monkeypatch.setattr(N, 'api_json', lambda *a, **k: pytest.fail('unresolved OCR must not reach API'))
    node = N.MangaTranslate()
    with pytest.raises(ValueError, match='ocr_unrecognized_span: a'):
        node.translate(N.encode(source), '', '', '', '', 4096, 300)
    override = N.encode({'translations': [{'id': 'a', 'target': '검수한 원문 번역'}]})
    assert json.loads(node.translate(N.encode(source), '', '', '', '', 4096, 300, override)[0])['regions'][0]['target'] == '검수한 원문 번역'


def test_generated_unknown_marker_retries_once_and_keeps_failure_evidence(monkeypatch, tmp_path):
    bad = {'translations': [{'id': 'a', 'target': '<UNK_SPAN>'}, {'id': 'b', 'target': '안녕'}]}
    calls, invoke = run(monkeypatch, [reply(N.encode(bad)), reply(N.encode(bad))])
    with pytest.raises(ValueError, match='ocr_unrecognized_span'):
        invoke()
    assert len(calls) == 2
    report = json.loads(next((tmp_path/'diagnostics').glob('*.json')).read_text())
    assert len(report['attempts']) == 2
    assert '<UNK_SPAN>' in report['attempts'][0]['content']


def test_break_only_target_cannot_pass_as_nonempty_translation():
    source = {'regions': [{'id': 'a', 'source': '原文'}]}
    with pytest.raises(ValueError, match='empty after line-break'):
        N.translations(source, {'translations': [{'id': 'a', 'target': '<br><br/>'}]})


def test_introduced_brace_n_retries_once_instead_of_being_printed(monkeypatch):
    source = {'regions': [{'id': 'a', 'bbox': [0, 0, 100, 100], 'source': '名前\nクラス'}]}
    responses = [reply(N.encode({'translations': [{'id': 'a', 'target': '이름{n}클래스'}]})),
                 reply(N.encode({'translations': [{'id': 'a', 'target': '이름\n클래스'}]}))]
    calls = []
    def api(*args):
        calls.append(args[-1])
        return responses[len(calls)-1]
    monkeypatch.setattr(N, 'api_json', api)
    result = N.MangaTranslate().translate(N.encode(source), 'http://unused', 'fixture', 'Korean', '', 4096, 300)
    assert json.loads(result[0])['regions'][0]['target'] == '이름\n클래스'
    assert len(calls) == 2


def test_literal_template_tokens_and_other_angle_text_are_preserved():
    answer = {'translations': [{'id': 'a', 'target': '코드 {n}\n<unknown>'}]}
    source = {'regions': [{'id': 'a', 'source': 'code {n}\n<unknown>'}]}
    assert N.translations(source, answer)['regions'][0]['target'] == answer['translations'][0]['target']
    source['regions'][0]['source'] = '原文\n名前'
    assert N.translations(source, answer, normalize_breaks=False)['regions'][0]['target'] == answer['translations'][0]['target']


@pytest.mark.parametrize('marker', ['<UNK><UNK>', '<unk>', '[UNK]'])
def test_unknown_marker_variants_are_rejected_before_translation(monkeypatch, marker):
    source = {'regions': [{'id': 'a', 'bbox': [0, 0, 100, 100], 'source': marker}]}
    monkeypatch.setattr(N, 'api_json', lambda *a, **k: pytest.fail('unknown source must not reach API'))
    with pytest.raises(ValueError, match='ocr_unrecognized_span'):
        N.MangaTranslate().translate(N.encode(source), '', 'fixture', 'Korean', '', 4096, 300)


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
def test_non_normal_completion_in_stop_policy_is_not_salvaged_or_retried(monkeypatch, reason):
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


def test_schema_constrains_requested_ids_and_keeps_client_validation(monkeypatch):
    calls, translate = run(monkeypatch, [reply(N.encode({'translations': [VALID['translations'][0]]})), reply()])
    translate()
    schema = calls[0]['response_format']['json_schema']['schema']
    rows = schema['properties']['translations']
    assert rows['minItems'] == rows['maxItems'] == 2
    assert rows['items']['properties']['id']['enum'] == ['a', 'b']
    assert rows['items']['additionalProperties'] is False
    assert len(calls) == 2  # A server ignoring the schema cannot bypass ID checks.


@pytest.mark.parametrize('mode,expected', [('json_object', {'type':'json_object'}), ('prompt_only', None)])
def test_compatibility_modes_are_explicit(monkeypatch, mode, expected):
    calls, _ = run(monkeypatch, [reply()])
    N.MangaTranslate().translate(N.encode(SOURCE), 'http://unused/v1', 'fixture-model', 'Korean', '', 4096, 300,
                                 response_format=mode)
    assert calls[0].get('response_format') == expected


def test_failed_attempts_save_actual_answers_without_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv('MANGA_LLM_API_KEY', 'secret-token-test')
    bad = '{"translations":[{"id":"a","target":"깨진 "인용문""}]}'
    calls, translate = run(monkeypatch, [reply(bad), reply('{"translations":')])
    with pytest.raises(ValueError, match='diagnostics=') as exc: translate()
    path, = (tmp_path/'diagnostics').glob('*.json')
    raw = path.read_text()
    saved = json.loads(raw)
    assert [a['content'] for a in saved['attempts']] == [bad, '{"translations":']
    assert saved['attempts'][0]['completion_tokens'] == 85
    assert saved['settings']['response_format'] == 'json_schema'
    assert saved['regions'][0]['source'] == '先生'
    assert str(path) in str(exc.value)
    assert 'secret-token-test' not in raw and 'http://' not in raw
    assert len(calls) == 2


def test_http_rejection_never_silently_downgrades(monkeypatch, tmp_path):
    calls = []
    def rejected(*args):
        calls.append(args[-1])
        raise RuntimeError('Translation API returned HTTP 400; check URL, model, and server log')
    monkeypatch.setattr(N, 'api_json', rejected)
    with pytest.raises(RuntimeError, match='response_format=json_schema'):
        N.MangaTranslate().translate(N.encode(SOURCE), 'http://unused/v1', 'fixture-model', 'Korean', '', 4096, 300)
    assert len(calls) == 1
    saved = json.loads(next((tmp_path/'diagnostics').glob('*.json')).read_text())
    assert saved['code'] == 'api_error' and 'content' not in saved['attempts'][0]


def test_non_normal_completion_also_saves_evidence(monkeypatch, tmp_path):
    calls, translate = run(monkeypatch, [reply(BODY, 'length')])
    with pytest.raises(ValueError): translate()
    saved = json.loads(next((tmp_path/'diagnostics').glob('*.json')).read_text())
    assert saved['attempts'][0]['content'] == BODY
    assert saved['attempts'][0]['finish_reason'] == 'length'
    assert len(calls) == 1


def test_diagnostic_failure_keeps_original_translation_error(monkeypatch):
    def broken(): raise OSError('no disk')
    monkeypatch.setattr(N.translation_protocol, 'failure_root', broken)
    calls, translate = run(monkeypatch, [reply('{'), reply('{')])
    with pytest.raises(ValueError, match='after one retry.*diagnostics=unavailable'): translate()
    assert len(calls) == 2


def test_diagnostics_bound_large_answer_and_exclude_provider_extras():
    response = reply('x'*200001)
    response['choices'][0]['message']['reasoning_content'] = 'excluded'
    response['headers'] = {'Authorization':'secret'}
    saved = N.translation_protocol.evidence(response)
    assert saved['content_truncated'] and len(saved['content']) == 200000
    assert saved['content_chars'] == 200001
    assert 'excluded' not in N.encode(saved) and 'secret' not in N.encode(saved)
