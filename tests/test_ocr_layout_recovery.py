"""Reading-plan recovery with pixel fixtures and explicit OCR test doubles."""
import importlib.util
import json
from pathlib import Path
import sys
import types

import numpy as np
from PIL import Image,ImageDraw,ImageFont
import pytest

ROOT=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('layout_recovery_tests');pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
def module(name):
    spec=importlib.util.spec_from_file_location(pkg.__name__+'.'+name,ROOT/(name+'.py'))
    result=importlib.util.module_from_spec(spec);sys.modules[spec.name]=result;spec.loader.exec_module(result)
    return result
M=module('models');P=module('ocr_policy')


def framed_paragraph(bright=False,step=28):
    image=Image.new('RGB',(580,203),'#777777' if bright else 'white')
    draw=ImageDraw.Draw(image);color='white' if bright else 'black'
    draw.line((1,0,1,202),fill=color,width=2)
    draw.line((578,0,578,202),fill=color,width=2)
    for row,y in enumerate((12,58,104,150)):
        for x in range(22+5*row,545,step):
            draw.rectangle((x,y,x+17,y+21),outline=color,width=2)
            draw.line((x+8,y,x+8,y+21),fill=color,width=2)
    return image


@pytest.mark.parametrize('bright',[False,True])
def test_thin_frame_may_be_ignored_for_cuts_but_every_source_pixel_is_kept(bright):
    image=framed_paragraph(bright)
    assert len(M._ocr_line_images(image))==1
    parts,report=P.recovery_parts(image)
    assert len(parts)==4 and report['strategy']=='verified_rows'
    rebuilt=np.concatenate([np.asarray(part) for part,box in parts],axis=0)
    assert np.array_equal(rebuilt,np.asarray(image))
    assert report['ruling_strips_ignored_in_analysis']>0


def test_failed_block_is_replaced_only_by_validated_rows_and_saved_in_diagnostics(monkeypatch):
    source=framed_paragraph()
    monkeypatch.setattr(M,'pil_image',lambda _:source)
    calls=[]
    expected=('这是第一行的完整正文内容','这是第二行的完整文字内容',
              '这是第三行的完整段落内容','这是第四行的完整結尾内容')
    class Model:
        def ocr(self,image,options,max_patches):
            calls.append((image.size,max_patches))
            return {'text':'顔の集の集の集の集の集落' if image.size==source.size else
                    expected[len(calls)-3]}
    text,raw,previews=M.MangaOCRAdaptive().read(object(),Model(),max_new_tokens=512,
        base_patches=256,small_text_patches=512,quality_guard=True,retry_on_layout_failure=True)
    report=json.loads(raw)
    assert text=='\n'.join(expected)
    assert [budget for size,budget in calls[:2]]==[256,512]
    assert len(calls)==6 and len(previews)==4
    recovery=report['chunks'][0]['layout_recovery']
    assert len(recovery['chunks'])==4
    assert report['recognition_work_items']==5
    assert report['chunk_count']==4 and report['line_count']==4
    assert all(child['attempts'][-1]['issue'] is None for child in recovery['chunks'])


def test_persistent_bad_rows_stop_without_recursing_and_save_actual_failed_input(monkeypatch,tmp_path):
    source=framed_paragraph()
    monkeypatch.setattr(M,'pil_image',lambda _:source)
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    class Model:
        calls=0
        def ocr(self,*a,**kw):
            self.calls+=1
            return {'text':'顔の集の集の集の集の集落'}
    model=Model()
    with pytest.raises(ValueError,match='short_repetition'):
        M.MangaOCRAdaptive().read(object(),model,quality_guard=True,retry_on_layout_failure=True)
    assert model.calls==4
    report_path=next((tmp_path/'manga_translator/ocr_failures').glob('*.json'))
    report=json.loads(report_path.read_text())
    assert report['input_size'][1]<203 and report['source_size']==[580,203]
    assert np.array_equal(np.asarray(Image.open(report['source_image'])),np.asarray(source))
    assert Image.open(report['failed_input_image']).size==tuple(report['input_size'])
    assert report['runtime_settings']['retry_on_layout_failure'] is True


def test_no_evidence_means_no_arbitrary_slices_and_diagnostic_failure_does_not_hide_error(monkeypatch):
    source=Image.new('RGB',(580,203),'white')
    assert not P.recovery_parts(source)[0]
    monkeypatch.setattr(M,'pil_image',lambda _:source)
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda: (_ for _ in ()).throw(OSError())))
    class Model:
        calls=0
        def ocr(self,*a,**kw):
            self.calls+=1
            return {'text':'顔の集の集の集の集の集落'}
    model=Model()
    with pytest.raises(ValueError,match='short_repetition'):
        M.MangaOCRAdaptive().read(object(),model,quality_guard=True,retry_on_layout_failure=True)
    assert model.calls==2


def test_vertical_recovery_keeps_full_column_pixels_and_reading_order():
    source=framed_paragraph().rotate(90,expand=True)
    ltr,report=P.recovery_parts(source,'vertical_ltr')
    rtl,_=P.recovery_parts(source,'vertical_rtl')
    assert len(ltr)==4 and report['strategy']=='verified_columns'
    assert [p.tobytes() for p,_ in ltr]==[p.tobytes() for p,_ in reversed(rtl)]
    assert np.array_equal(np.concatenate([np.asarray(p) for p,_ in ltr],axis=1),np.asarray(source))


def test_disabling_line_split_also_disables_automatic_layout_recovery(monkeypatch):
    monkeypatch.setattr(M,'pil_image',lambda _:framed_paragraph())
    class Model:
        calls=0
        def ocr(self,*a,**kw):
            self.calls+=1
            return {'text':'顔の集の集の集の集の集落'}
    model=Model()
    with pytest.raises(ValueError,match='short_repetition'):
        M.MangaOCRAdaptive().read(object(),model,line_split=False,quality_guard=True,retry_on_layout_failure=True)
    assert model.calls==2


def test_recovery_does_not_hide_a_loop_reconstructed_from_identical_child_outputs(monkeypatch):
    source=framed_paragraph(step=50);monkeypatch.setattr(M,'pil_image',lambda _:source)
    class Model:
        calls=0
        def ocr(self,image,*a,**kw):
            self.calls+=1
            return {'text':'顔の集の集の集の集の集落' if image.size==source.size else '同じ本文ですよね'}
    model=Model()
    with pytest.raises(ValueError,match='short_repetition'):
        M.MangaOCRAdaptive().read(object(),model,quality_guard=True,retry_on_layout_failure=True,
                                  text_direction='horizontal')
    assert model.calls==6


def test_layout_recovery_cannot_exceed_region_work_limit(monkeypatch):
    source=framed_paragraph();monkeypatch.setattr(M,'pil_image',lambda _:source)
    monkeypatch.setattr(P,'plan_line',lambda image:[(image,[0,0,*image.size])]*128)
    class Model:
        calls=0
        def ocr(self,*a,**kw):
            self.calls+=1
            return {'text':'顔の集の集の集の集の集落'}
    model=Model()
    with pytest.raises(ValueError,match='short_repetition'):
        M.MangaOCRAdaptive().read(object(),model,split_long_lines=True,quality_guard=True,retry_on_layout_failure=True)
    assert model.calls==2


def test_one_large_connected_glyph_is_not_turned_into_separate_text_rows():
    image=Image.new('RGB',(580,203),'white');draw=ImageDraw.Draw(image)
    draw.line((1,0,1,202),fill='black',width=2)
    for y in (10,90,170):draw.rectangle((1,y,560,y+20),fill='black')
    assert not P.recovery_parts(image)[0]


@pytest.mark.parametrize('enabled,line_split,strategy',[(False,True,'disabled_by_retry_option'),
    (True,False,'disabled_by_line_split'),(True,True,'no_verified_alternative')])
def test_failure_report_distinguishes_disabled_recovery_from_no_safe_split(monkeypatch,tmp_path,enabled,line_split,strategy):
    monkeypatch.setattr(M,'pil_image',lambda _:Image.new('RGB',(580,203),'white'))
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    class Model:
        def ocr(self,*a,**kw):return {'text':'顔の集の集の集の集の集落'}
    with pytest.raises(ValueError,match=strategy):
        M.MangaOCRAdaptive().read(object(),Model(),quality_guard=True,retry_on_layout_failure=enabled,line_split=line_split)
    report=json.loads(next((tmp_path/'manga_translator/ocr_failures').glob('*.json')).read_text())
    assert report['layout_recovery']['strategy']==strategy
    assert report['runtime_settings']['line_split']==line_split


def two_column_guide(bright=False):
    # Structural fixture only: independent horizontal columns, textured paper,
    # a dotted gutter rule and a section marker spanning two right-hand rows.
    rng=np.random.default_rng(14)
    pixels=np.clip(np.array([218,207,179])+rng.integers(-5,6,(203,580,1)),0,255).astype('uint8')
    image=Image.fromarray(pixels);draw=ImageDraw.Draw(image)
    for x0,ys in [(7,range(4,201,23)),(330,[4,27,50,73,96,142,165,188])]:
        for y in ys:
            for x in range(x0,x0+(245 if x0==7 else 235),15):
                draw.rectangle((x,y,x+10,min(202,y+13)),outline=(20,20,20),width=2)
                draw.line((x+5,y,x+5,min(202,y+13)),fill=(20,20,20),width=2)
    for y in range(16,203,4):draw.line((294,y,294,y+1),fill=(90,90,90))
    draw.rectangle((277,6,312,11),fill=(100,100,100))
    draw.rectangle((277,144,311,178),fill=(100,100,100))
    draw.text((288,151),'8',fill='white')
    draw.line((579,0,579,202),fill=(40,40,40),width=1)
    if bright:image=Image.fromarray(255-np.asarray(image))
    return image


@pytest.mark.parametrize('bright',[False,True])
def test_columns_are_read_independently_and_gutter_marker_is_not_sliced(bright):
    source=two_column_guide(bright)
    assert len(M._ocr_line_images(source))==1
    parts,report=P.recovery_parts(source)
    assert report['strategy']=='verified_multicolumn_rows'
    assert report['reading_order']=='columns_left_to_right_then_rows_top_to_bottom'
    assert [c['rows'] for c in report['columns']]==[9,7]
    assert len(parts)==16
    actual=np.zeros_like(np.asarray(source));coverage=np.zeros((203,580),int)
    for part,(a,b,c,d) in parts:
        actual[b:d,a:c]=np.asarray(part);coverage[b:d,a:c]+=1
        # Neither the section box nor an original glyph is intersected by cuts.
        if a<=277<c:assert not 144<b<179 and not 144<d<179
    assert (coverage==1).all() and np.array_equal(actual,np.asarray(source))
    assert not P.recovery_parts(source,'vertical_rtl')[1]['strategy']=='verified_multicolumn_rows'


def test_column_recovery_uses_original_pixels_and_bounded_validated_child_outputs(monkeypatch):
    source=two_column_guide();monkeypatch.setattr(M,'pil_image',lambda _:source)
    parts,expected_plan=P.recovery_parts(source)
    expected=[f'独立正文第{i}行内容' for i in range(1,17)]
    class Model:
        calls=0
        def ocr(self,image,options,max_patches):
            self.calls+=1
            if image.size==source.size:return {'text':'内内内内内内内内内内内内内内内'}
            index=self.calls-3
            assert image.tobytes()==parts[index][0].tobytes()
            return {'text':expected[index]}
    model=Model()
    text,raw,previews=M.MangaOCRAdaptive().read(object(),model,base_patches=256,small_text_patches=512,
        quality_guard=True,retry_on_layout_failure=True)
    report=json.loads(raw)
    assert text=='\n'.join(expected) and model.calls==18
    assert report['line_count']==report['chunk_count']==len(previews)==16
    assert report['recognition_work_items']==17
    recovery=report['chunks'][0]['layout_recovery']
    assert recovery['columns']==expected_plan['columns'] and len(recovery['chunks'])==16


def test_one_column_with_indented_lines_is_not_promoted_to_multicolumn():
    image=framed_paragraph();parts,report=P.recovery_parts(image)
    assert parts and report['strategy']=='verified_rows'


def speckled_single_column(bright=False):
    source=Image.new('RGB',(305,270),'#d7c7a5');draw=ImageDraw.Draw(source)
    for y in range(0,239,4):draw.rectangle((16,y,17,y+1),fill='#303030')
    for row,y in enumerate(range(3,224,23)):
        for x in range(45+(row%3)*4,291,17):
            draw.rectangle((x,y,x+11,y+13),outline='#202020',width=2)
            draw.line((x+5,y,x+5,y+13),fill='#202020',width=1)
    font=ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Regular.ttf'),24)
    draw.text((0,247),'32',font=font,fill='#202020',anchor='lt')
    if bright:source=Image.fromarray(255-np.asarray(source))
    return source


@pytest.mark.parametrize('bright',[False,True])
def test_dotted_rule_does_not_bridge_rows_and_footer_pixels_remain(bright):
    source=speckled_single_column(bright)
    assert len(M._ocr_line_images(source))==1
    parts,report=P.recovery_parts(source)
    assert len(parts)==11 and report['strategy']=='verified_rows'
    assert report['speckle_pixels_ignored_in_analysis']>0
    assert parts[-1][1][1]<247 and parts[-1][1][3]==270
    rebuilt=np.concatenate([np.asarray(part) for part,_ in parts],axis=0)
    assert np.array_equal(rebuilt,np.asarray(source))
    for _,box in parts[:-1]:
        # Body glyphs are left whole; the ruled gutter stays in the input.
        assert not any(y<box[3]<y+14 for y in range(3,224,23))


def test_dotted_paragraph_recovery_retains_validation_and_is_not_recursive(monkeypatch):
    source=speckled_single_column();monkeypatch.setattr(M,'pil_image',lambda _:source)
    class Model:
        calls=0
        def ocr(self,image,*args,**kwargs):
            self.calls+=1
            return {'text':'抗抗抗抗抗抗抗抗抗抗抗抗'}
    model=Model()
    with pytest.raises(ValueError,match='short_repetition'):
        M.MangaOCRAdaptive().read(object(),model,base_patches=256,small_text_patches=512,
            quality_guard=True,retry_on_layout_failure=True)
    assert model.calls==4  # Two parent attempts and two first-child attempts.
