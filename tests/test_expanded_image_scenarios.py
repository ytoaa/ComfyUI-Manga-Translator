"""Generator and negative grading controls; no actual model downloads/inference."""
from pathlib import Path
import json
import sys

import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import expanded_image_scenarios as F
import stress_image_processing as T


def test_reference_background_is_independent_and_artwork_never_changes_outside_glyph_alpha():
    scenes=list(F.scenes())
    assert len(scenes)==15 and len({p.ident for p in scenes})==15
    for p in scenes:
        source=np.asarray(p.image if p.image is not None else p.clean)
        expected=np.asarray(p.clean)
        support=np.logical_or.reduce(p.masks) if p.masks else np.zeros(source.shape[:2],bool)
        assert np.array_equal(source[~support],expected[~support]),p.ident
        for row,mask in zip(p.rows,p.masks):
            a,b,c,d=row['frame_pixels'];outside=mask.copy();outside[b:d,a:c]=False
            assert not outside.any(),row['id']
            assert row['text'] and mask.any()
            assert set(row['text'])-{'\n'} <= F.S.supported_characters()


def test_generator_keeps_clipped_source_out_of_full_text_ocr_ground_truth(tmp_path):
    refs=F.generate(tmp_path)
    assert len(refs['pages'])==15 and len(refs['ocr'])==17
    assert not any(r['id'].startswith('edge-clipped') for r in refs['ocr'])
    assert next(r for r in refs['pages'] if r['id']=='edge-clipped')['regions'][0]['clipped']
    assert next(r for r in refs['pages'] if r['id']=='high-dpi')['size']==[2400,1800]
    assert next(r for r in refs['pages'] if r['id']=='nontext-art')['regions']==[]


def test_new_scenes_are_byte_reproducible_and_never_use_model_or_user_outputs(tmp_path):
    first=tmp_path/'first';second=tmp_path/'second'
    a,b=F.generate(first),F.generate(second)
    assert a==b and 'no user assets' in a['source']
    for row in a['pages']:
        assert (first/row['image']).read_bytes()==(second/row['image']).read_bytes()
        assert (first/row['clean']).read_bytes()==(second/row['clean']).read_bytes()


@pytest.fixture
def context(tmp_path):
    import argparse
    previous=sys.modules.get('folder_paths')
    args=argparse.Namespace(destination=tmp_path,include_sfx=True)
    refs=F.generate(tmp_path/'fixtures');get=T.A.modules(tmp_path)
    yield args,refs,get
    if previous is None:sys.modules.pop('folder_paths',None)
    else:sys.modules['folder_paths']=previous


def test_changed_fixture_is_a_harness_error_never_a_model_quality_result(context):
    args,refs,_=context;row=refs['pages'][0]
    Image.new('RGB',(20,20),'black').save(args.destination/'fixtures'/row['image'])
    with pytest.raises(ValueError,match='Fixture bytes changed'):T.read_case(args,row)


def test_input_normalization_evaluates_actual_alpha_and_exif_pixels_and_rejections(context):
    args,_,get=context;audit=T.A.Audit(args.destination,'normalization-unit')
    T.input_cases(audit,args,get)
    assert len(audit.report['results'])==7 and audit.report['counts']=={'PASS':7}


def test_partial_source_and_wrong_color_candidates_are_rejected(context):
    args,refs,get=context;audit=T.A.Audit(args.destination,'guarded-tiles-unit')
    T.tile_cases(audit,args,get,refs)
    rows={r['id']:r for r in audit.report['results']}
    assert all(row['status']=='PASS' for row in rows.values())
    assert 'source_ink_components_retained' in rows['tile-partial-source']['evidence']['refused']
    assert 'source_free_boundary_color_shift' in rows['tile-wrong-color']['evidence']['refused']
    assert not rows['tile-partial-source']['evidence']['actual_qwen']


def test_bad_model_candidates_remain_quality_gaps_when_runtime_accepts_them(context,monkeypatch):
    args,refs,get=context;audit=T.A.Audit(args.destination,'tiles-unit')
    assembler=get('inpaint_tiles');original=assembler.assemble
    def bypass(plan,values,**kwargs):
        kwargs['strict_cleanup']=False
        return original(plan,values,**kwargs)
    monkeypatch.setattr(assembler,'assemble',bypass)
    T.tile_cases(audit,args,get,refs)
    rows={r['id']:r for r in audit.report['results']}
    assert rows['tile-known-clean']['status']=='PASS'
    assert rows['tile-nonowned-corruption']['status']=='PASS'
    assert rows['tile-partial-source']['status']=='GAP'
    assert rows['tile-wrong-color']['status']=='GAP'
    assert rows['tile-unchanged']['status']=='GAP'
    assert rows['tile-partial-source']['evidence']['accepted_by_runtime']
    assert rows['tile-partial-source']['evidence']['independent_reference_error_pixels']>0
    assert not rows['tile-partial-source']['evidence']['actual_qwen']


def test_complex_background_does_not_get_a_fake_completed_cleanup(context):
    args,refs,get=context;row=next(r for r in refs['pages'] if r['id']=='gradient-caption')
    met,evidence=T.cleanup_case(args,row,get)
    assert met and evidence['report']['tile_count']>0
    assert evidence['missing_tiles_refused'] and not evidence['whole_page_cleanup_completed']
    assert not evidence['model_generated']


def test_preserved_clipped_glyphs_are_not_counted_as_completed_removal(context):
    args,refs,get=context;row=next(r for r in refs['pages'] if r['id']=='edge-clipped')
    met,evidence=T.cleanup_case(args,row,get)
    assert met and evidence['preservation_is_not_removal_success']
    assert not evidence['whole_page_cleanup_completed']


def test_wrong_reason_for_refusal_cannot_pass_the_oversized_control(context,monkeypatch):
    args,refs,get=context;row=next(r for r in refs['pages'] if r['id']=='mixed-punctuation')
    H=get('lettering.hybrid')
    def unrelated(*a,**k):raise ValueError('Font lacks requested characters')
    monkeypatch.setattr(H,'build_plan',unrelated)
    met,evidence=T.lettering_case(args,row,get,'horizontal',1,True)
    assert not met and 'Font lacks' in evidence['refused']
