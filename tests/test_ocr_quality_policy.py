"""Adversarial OCR plans and failures with explicit model doubles, not accuracy tests."""
import importlib.util
import json
from pathlib import Path
import sys
import types

import numpy as np
from PIL import Image, ImageDraw
import pytest

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('ocr_quality_tests'); pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg
def module(name):
    spec = importlib.util.spec_from_file_location(pkg.__name__+'.'+name, ROOT/(name+'.py'))
    result = importlib.util.module_from_spec(spec); sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result
P = module('ocr_policy'); M = module('models'); N = module('nodes')


def long_line(bright=False):
    image = Image.new('RGB',(1035,38), '#777777' if bright else 'white')
    draw = ImageDraw.Draw(image)
    for x in range(8,1020,25):
        draw.rectangle((x,9,x+14,28),fill='white' if bright else 'black')
    draw.rectangle((1029,24,1031,26),fill='white' if bright else 'black')
    return image


@pytest.mark.parametrize('bright',[False,True])
def test_long_line_chunks_reassemble_every_pixel_without_overlap_or_lost_punctuation(bright):
    source = long_line(bright)
    parts = P.plan_line(source)
    assert 1 < len(parts) <= 16
    assert np.array_equal(np.concatenate([np.asarray(part) for part,box in parts],axis=1),np.asarray(source))
    for _,box in parts[1:]:
        assert not P.ink(source)[:,box[0]-1:box[0]+1].any()


def test_unknown_gap_and_vertical_input_are_never_arbitrarily_cut():
    source = Image.new('RGB',(1035,38),'white')
    ImageDraw.Draw(source).rectangle((0,9,1034,28),fill='black')
    assert len(P.plan_line(source)) == 1
    assert len(P.plan_line(source.rotate(90,expand=True))) == 1


def test_short_text_in_long_box_does_not_create_empty_ocr_chunks():
    source=Image.new('RGB',(1200,40),'white')
    draw=ImageDraw.Draw(source)
    for x in range(8,200,20):draw.rectangle((x,9,x+10,28),fill='black')
    assert len(P.plan_line(source)) == 1


@pytest.mark.parametrize('text',['顔の集の集の集の集の集落し渡し渡し、','清イストを数数数数と数と遊え、'])
def test_reported_short_ocr_loops_are_suspect(text):
    assert P.text_problem(text,long_line()) == 'short_repetition'


def test_short_correct_name_and_manga_elongation_remain_valid():
    source = Image.new('RGB',(100,60),'white')
    assert P.text_problem('先生',source) is None
    assert P.text_problem('どぅぅぅ！',source) is None


def test_visible_long_line_with_reported_four_character_ocr_triggers_omission_alarm():
    assert P.text_problem('面文字読',long_line()) == 'possible_omission'
    assert P.text_problem('画像の文字を読み取り、自然な韓国語に翻訳します。',long_line()) is None


def test_chunk_join_retains_english_word_spaces_without_cjk_overlap_deletion():
    assert P.join_chunks(['THE RAIN','IS GETTING','WORSE.']) == 'THE RAIN IS GETTING WORSE.'
    assert P.join_chunks(['原文を','確認します。']) == '原文を確認します。'
    assert P.join_chunks(['同じ','同じ']) == '同じ同じ'


def test_suspicious_ocr_retries_once_with_other_budget_and_saves_diagnostics(monkeypatch):
    monkeypatch.setattr(M,'pil_image',lambda _:long_line())
    calls=[]
    class Model:
        def ocr(self,image,options,max_patches):
            calls.append(max_patches)
            return {'text':'面文字読' if len(calls)==1 else '画像の文字を読み取り、自然な韓国語に翻訳します。'}
    text,report,previews = M.MangaOCRAdaptive().read(object(),Model(),quality_guard=True)
    assert calls == [1024,256]
    report = json.loads(report)
    assert report['chunks'][0]['attempts'][0]['issue'] == 'possible_omission'
    assert report['chunks'][0]['attempts'][1]['issue'] is None
    assert len(previews) == 1 and previews[0].shape == (1,38,1035,3)
    assert text.startswith('画像')


def test_continuing_short_loop_stops_before_ocr_collection(monkeypatch):
    monkeypatch.setattr(M,'pil_image',lambda _:long_line())
    calls=[]
    class Model:
        def ocr(self,image,options,max_patches):
            calls.append(max_patches)
            return {'text':'顔の集の集の集の集の集落'}
    with pytest.raises(ValueError,match='short_repetition'):
        M.MangaOCRAdaptive().read(object(),Model(),quality_guard=True)
    assert calls == [1024,256]


def test_diagnostics_keep_region_identity_and_translation_does_not_receive_them():
    source={'regions':[{'id':'a','bbox':[0,0,100,100]},{'id':'b','bbox':[0,200,100,300]}]}
    reports=[json.dumps({'source_size':[10,10]}),json.dumps({'source_size':[20,20]})]
    data=json.loads(N.MangaCollectOCR().collect(['先生','TEST'],[json.dumps(source)],reports)[0])
    assert [(row['id'],row['source'],row['ocr_diagnostics']['source_size']) for row in data['regions']] == [
        ('a','先生',[10,10]),('b','TEST',[20,20])]
    with pytest.raises(ValueError,match='diagnostic count'):
        N.MangaCollectOCR().collect(['先生','TEST'],[json.dumps(source)],reports[:1])
