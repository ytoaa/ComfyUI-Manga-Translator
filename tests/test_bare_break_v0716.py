"""Previously accepted real-shaped model outputs must not reach rasterization."""
from copy import deepcopy
import json
import pytest
from tests.test_translation_response import N,VALID,reply,run


@pytest.mark.parametrize('bad,good',[
    ('질문...?n다음 문장','질문...?\n다음 문장'),
    ('계속하면n새 문장','계속하면 새 문장'),
    ('確認したn次の文','確認した\n次の文'),
    ('확인했다!n그리고','확인했다! 그리고')])
def test_bare_n_model_output_retries_before_lettering(monkeypatch,bad,good):
    a=deepcopy(VALID);b=deepcopy(VALID)
    a['translations'][0]['target']=bad;b['translations'][0]['target']=good
    calls,invoke=run(monkeypatch,[reply(N.encode(a)),reply(N.encode(b))])
    result=json.loads(invoke());assert result['regions'][1]['target']==good and len(calls)==2


def test_repeated_bare_n_never_returns_a_partial_translation(monkeypatch,tmp_path):
    monkeypatch.setattr(N.translation_protocol,'failure_root',lambda:tmp_path)
    a=deepcopy(VALID);a['translations'][0]['target']='확인n다음'
    calls,invoke=run(monkeypatch,[reply(N.encode(a)),reply(N.encode(a))])
    with pytest.raises(ValueError,match='translation_line_break_marker'):invoke()
    assert len(calls)==2 and list(tmp_path.glob('translation_*.json'))


@pytest.mark.parametrize('source,target',[
    ('変数 n の値','변수n값'),('English word','connection 확인'),
    ('natural English','known number'),('n をそのまま','문자n그대로'),
    ('原文','확인\n다음'),('原文','x^n을 계산'),('原文','n차 함수')])
def test_actual_letters_variables_and_real_newlines_survive(source,target):
    assert N.text_contract.translation_text(source,target)==(target,0)


def test_authored_text_is_never_rewritten_by_bare_n_guard():
    assert N.text_contract.translation_text('原文','확인n다음',False)==('확인n다음',0)
