"""Adversarial OCR plans and failures with explicit model doubles, not accuracy tests."""
import importlib.util
import json
from pathlib import Path
import sys
import types

import numpy as np
from PIL import Image, ImageDraw, ImageFont
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


@pytest.mark.parametrize('text', ['<UNK><UNK>大白白あ', '<unk>', '[UNK]', '<UNK_SPAN>'])
def test_explicit_unreadable_markers_are_not_recognized_text(text):
    assert P.text_problem(text, long_line()) == 'ocr_unrecognized_span'


def test_layout_recovery_cannot_accept_a_different_unknown_marker(monkeypatch):
    source = Image.new('RGB', (120, 70), 'white')
    monkeypatch.setattr(M, 'pil_image', lambda _: source)
    monkeypatch.setattr(M, '_ocr_line_images', lambda _: [source])
    monkeypatch.setattr(P, 'recovery_parts', lambda *a: (
        [(source.crop((0, 0, 60, 70)), [0, 0, 60, 70]),
         (source.crop((60, 0, 120, 70)), [60, 0, 120, 70])],
        {'strategy': 'shorter_horizontal_chunks', 'separator': ''}))
    saved = []
    monkeypatch.setattr(M, '_save_ocr_failure', lambda src, crop, diagnostic: saved.append(diagnostic) or 'fixture.json')
    class Model:
        calls = 0
        def ocr(self, image, options, max_patches):
            self.calls += 1
            return {'text': '<UNK_SPAN>' if self.calls <= 2 else '<UNK><UNK>'}
    model = Model()
    with pytest.raises(ValueError, match='ocr_unrecognized_span'):
        M.MangaOCRAdaptive().read(object(), model, quality_guard=True, retry_on_layout_failure=True)
    assert model.calls == 4
    assert saved[0]['rejected_text'] == '<UNK><UNK>'


def test_short_correct_name_and_manga_elongation_remain_valid():
    source = Image.new('RGB',(100,60),'white')
    assert P.text_problem('先生',source) is None
    assert P.text_problem('どぅぅぅ！',source) is None


@pytest.mark.parametrize('guard', [False, True])
@pytest.mark.parametrize('recovered', [False, True])
def test_unknown_span_has_bounded_retry_and_never_silently_loses_text(monkeypatch, guard, recovered):
    source = Image.new('RGB', (120, 70), 'white')
    monkeypatch.setattr(M, 'pil_image', lambda _: source)
    saved = []
    monkeypatch.setattr(M, '_save_ocr_failure', lambda src, crop, diagnostic: saved.append(diagnostic) or 'fixture.json')
    class Model:
        calls = 0
        def ocr(self, image, options, max_patches):
            self.calls += 1
            return {'text': '読めた文字' if recovered and self.calls == 2 else '読めた<UNK_SPAN>文字'}
    model = Model()
    def invoke():
        return M.MangaOCRAdaptive().read(object(), model, line_split=False, quality_guard=guard,
                                       base_patches=256, small_text_patches=512)
    if recovered:
        text, report, _ = invoke()
        assert text == '読めた文字' and not saved
        attempts = json.loads(report)['chunks'][0]['attempts']
        assert [a['issue'] for a in attempts] == ['ocr_unrecognized_span', None]
    else:
        with pytest.raises(ValueError, match='ocr_unrecognized_span'):
            invoke()
        assert saved[0]['rejected_text'] == '読めた<UNK_SPAN>文字'
        assert saved[0]['code'] == 'ocr_unrecognized_span'
    assert model.calls == 2


def test_visible_long_line_with_reported_four_character_ocr_triggers_omission_alarm():
    assert P.text_problem('面文字読',long_line()) == 'possible_omission'
    assert P.text_problem('画像の文字を読み取り、自然な韓国語に翻訳します。',long_line()) is None


def short_line_on_speckled_paper(bright=False):
    image=Image.new('RGB',(280,51),'#d7c7a5');draw=ImageDraw.Draw(image)
    for x in range(19,124,15):
        draw.rectangle((x,6,x+10,19),outline='#202020',width=2)
        draw.line((x+5,6,x+5,19),fill='#202020',width=1)
    draw.rectangle((130,17,131,18),fill='#202020')
    for x in range(140,278,4):draw.point((x,35+(x%3)),fill='#202020')
    if bright:image=Image.fromarray(255-np.asarray(image))
    return image


@pytest.mark.parametrize('bright',[False,True])
def test_short_sentence_on_speckled_paper_does_not_trigger_false_omission(bright):
    image=short_line_on_speckled_paper(bright);original=image.tobytes();evidence={}
    assert P.text_problem('房间找到莱斯里。',image,evidence) is None
    check=evidence['omission']
    assert check['raw_projection_bands']>=32
    assert check['supported_projection_bands']<12
    assert image.tobytes()==original
    assert P.text_problem('内内内内内内内内内内',image)=='short_repetition'


def test_small_disconnected_glyphs_still_support_a_real_omission_alarm():
    image=Image.new('RGB',(280,20),'white');draw=ImageDraw.Draw(image)
    for x in range(2,278,6):draw.rectangle((x,8,x+1,9),fill='black')
    assert P.text_problem('字',image)=='possible_omission'


def test_page_number_on_paper_with_larger_speckles_is_not_an_omission():
    image=Image.new('RGB',(305,39),'#d7c7a5');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Regular.ttf'),24)
    draw.text((0,16),'32',font=font,fill='#202020',anchor='lt')
    for i,x in enumerate(range(60,294,12)):
        y=4+(i%2)*15
        draw.rectangle((x,y,x+2,y+2),fill='#606050')
    evidence={}
    assert P.text_problem('32',image,evidence) is None
    assert evidence['omission']['analysis_min_component_pixels']>4


def test_false_omission_does_not_overwrite_first_result_with_unneeded_retry(monkeypatch):
    source=short_line_on_speckled_paper();monkeypatch.setattr(M,'pil_image',lambda _:source)
    class Model:
        calls=0
        def ocr(self,image,options,max_patches):
            self.calls+=1
            assert image.tobytes()==source.tobytes()
            return {'text':'房间找到莱斯里。' if self.calls==1 else '房间找到薪里。'}
    model=Model()
    text,raw,previews=M.MangaOCRAdaptive().read(object(),model,line_split=False,quality_guard=True,
        base_patches=256,small_text_patches=512)
    assert model.calls==1 and text=='房间找到莱斯里。' and len(previews)==1
    attempts=json.loads(raw)['chunks'][0]['attempts']
    assert len(attempts)==1 and attempts[0]['issue'] is None
    assert attempts[0]['quality_evidence']['omission']['raw_projection_bands']>=32


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


def test_tall_horizontal_paragraph_uses_rows_instead_of_assuming_vertical_script():
    source=Image.new('RGB',(278,446),'#d7c7a5')
    draw=ImageDraw.Draw(source)
    for y in range(8,430,22):
        for x in range(10,263,16):
            draw.rectangle((x,y,x+12,y+13),outline='#202020',width=2)
            draw.line((x+6,y,x+6,y+13),fill='#202020',width=1)
    lines=M._ocr_line_images(source)
    assert len(lines) == 20
    assert all(line.width == 278 and line.height < 40 for line in lines)
    assert sum(line.height for line in lines) >= source.height


def test_single_horizontal_row_is_not_split_into_vertical_letter_columns():
    source=long_line()
    lines=M._ocr_line_images(source)
    assert len(lines) == 1 and lines[0].size == source.size


def test_explicit_vertical_direction_controls_column_reading_order():
    source=Image.new('RGB',(140,310),'white');draw=ImageDraw.Draw(source)
    for x in (15,60,105):
        for y in range(10,280,24):draw.rectangle((x,y,x+15,y+15),fill='black')
    rtl=M._ocr_line_images(source,'vertical_rtl')
    ltr=M._ocr_line_images(source,'vertical_ltr')
    assert len(rtl) == len(ltr) == 3
    assert [p.tobytes() for p in rtl] == [p.tobytes() for p in reversed(ltr)]
    assert len(M._ocr_line_images(source)) == 3


def test_token_limit_retries_once_with_double_budget_and_records_actual_attempts(monkeypatch):
    from ocr_quality_tests.adapters.hayai import HayaiOutputError
    monkeypatch.setattr(M,'pil_image',lambda _:Image.new('RGB',(278,446),'white'))
    calls=[]
    class Model:
        def ocr(self,image,options,max_patches):
            calls.append(options.max_new_tokens)
            if len(calls)==1:raise HayaiOutputError('ocr_token_limit')
            return {'text':'完整正文'}
    text,raw,_=M.MangaOCRAdaptive().read(object(),Model(),line_split=False,retry_on_token_limit=True)
    assert text == '完整正文' and calls == [256,512]
    generations=json.loads(raw)['chunks'][0]['attempts'][0]['generation_attempts']
    assert [g['status'] for g in generations] == ['ocr_token_limit','accepted']
    assert [g['max_new_tokens'] for g in generations] == calls


@pytest.mark.parametrize('budget,enabled,expected',[(256,True,[256,512]),(1536,True,[1536,2048]),
                                                  (2048,True,[2048]),(256,False,[256])])
def test_persistent_token_limit_stops_without_accepting_partial_text(monkeypatch,budget,enabled,expected):
    from ocr_quality_tests.adapters.hayai import HayaiOutputError
    monkeypatch.setattr(M,'pil_image',lambda _:Image.new('RGB',(278,446),'white'))
    calls=[]
    class Model:
        def ocr(self,image,options,max_patches):
            calls.append(options.max_new_tokens)
            raise HayaiOutputError('ocr_token_limit')
    with pytest.raises(HayaiOutputError,match='ocr_token_limit'):
        M.MangaOCRAdaptive().read(object(),Model(),max_new_tokens=budget,line_split=False,retry_on_token_limit=enabled)
    assert calls == expected


def test_token_and_repetition_retries_share_a_three_generation_bound(monkeypatch):
    from ocr_quality_tests.adapters.hayai import HayaiOutputError
    monkeypatch.setattr(M,'pil_image',lambda _:Image.new('RGB',(278,446),'white'))
    calls=[]
    class Model:
        def ocr(self,image,options,max_patches):
            calls.append((options.max_new_tokens,options.repetition_penalty))
            if len(calls)==1:raise HayaiOutputError('ocr_token_limit')
            if len(calls)==2:raise HayaiOutputError('ocr_repetition_loop')
            return {'text':'完整正文'}
    result=M.MangaOCRAdaptive().read(object(),Model(),line_split=False,retry_on_token_limit=True)
    assert result[0] == '完整正文' and calls == [(256,1.),(512,1.),(512,1.1)]
