"""Reading-plan recovery with pixel fixtures and explicit OCR test doubles."""
import importlib.util
import json
from pathlib import Path
import sys
import types

import numpy as np
from PIL import Image,ImageDraw
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
