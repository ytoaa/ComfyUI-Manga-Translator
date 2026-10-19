"""Independent reference and scoring controls; no model inference or art assets."""
from argparse import Namespace
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image,ImageDraw
import pytest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import hard_image_scenarios as F
import stress_ambiguous_pages as H


@pytest.fixture(scope='module')
def fixtures(tmp_path_factory):
    base=tmp_path_factory.mktemp('hard-fixtures');assets=base/'assets';assets.mkdir();inventory={}
    for i,name in enumerate(F.NAMES):
        image=Image.new('RGB',(170,170),(140+i*30,160,180));draw=ImageDraw.Draw(image)
        for x in range(0,170,9):draw.line((x,0,x+30,170),fill=(190,140,100),width=2)
        path=assets/(name+'.png');image.save(path);inventory[name]={'sha256':F.digest(path),'source':'test-only procedural blank art'}
    (assets/'assets.json').write_text(json.dumps(inventory))
    folder=base/'fixtures';refs=F.generate(folder,assets)
    return base,assets,folder,refs


def test_hard_suite_contains_36_private_pages_and_independent_reference_assets(fixtures):
    _,_,folder,refs=fixtures
    assert len(refs['pages'])==36 and len({p['id'] for p in refs['pages']})==36
    assert len(refs['ocr'])==45
    assert set(refs['backgrounds'])==set(F.NAMES)
    assert all(p['sha256'] and p['clean_sha256'] and p['truth_sha256'] for p in refs['pages'])
    F.verify(refs,folder)


def test_exact_annotation_twins_are_diagnostic_and_never_accuracy_examples(fixtures):
    _,_,folder,refs=fixtures
    twins=[p for p in refs['pages'] if p.get('semantic_ambiguity')]
    assert len(twins)==2 and all(p['exclude_accuracy'] for p in twins)
    assert twins[0]['sha256']==twins[1]['sha256']
    assert (folder/twins[0]['image']).read_bytes()==(folder/twins[1]['image']).read_bytes()
    assert len(twins[0]['regions'])==1 and twins[1]['regions']==[]
    assert twins[0]['intended_meaning']!=twins[1]['intended_meaning']


def test_invisible_literal_has_no_visible_glyph_or_ocr_oracle(fixtures):
    _,_,_,refs=fixtures;row=next(p for p in refs['pages'] if p['id']=='contrast-000')
    assert row['negative'] and not row['regions'] and row['sha256']==row['clean_sha256']
    assert not any(r['page_id']==row['id'] for r in refs['ocr'])
    assert [p['contrast_delta'] for p in refs['pages'] if p['family']=='contrast']==[0,2,4,8,16,32,64,128]


def test_glyphs_do_not_occlude_each_other_and_have_bounded_frames(fixtures):
    _,_,folder,refs=fixtures
    for p in refs['pages']:
        image=np.asarray(Image.open(folder/p['image']));clean=np.asarray(Image.open(folder/p['clean']))
        support=np.zeros(image.shape[:2],bool)
        with np.load(folder/p['truth']) as masks:
            for r in p['regions']:
                mask=masks[r['id']];assert mask.any()
                assert not (support&mask).any(),p['id']
                support|=mask
                a,b,c,d=r['frame_pixels'];outside=mask.copy();outside[b:d,a:c]=False
                assert not outside.any(),(p['id'],r['id'])
                assert 0<=a<c<=p['size'][0] and 0<=b<d<=p['size'][1]
        if not p.get('degradation'):assert np.array_equal(image[~support],clean[~support]),p['id']
        if p.get('degradation')=='low-res':assert p['size']==[384,384]


def test_clipped_literals_are_not_compared_against_invisible_full_text(fixtures):
    _,_,_,refs=fixtures
    clipped=[(p,r) for p in refs['pages'] for r in p['regions'] if r['clipped']]
    assert len(clipped)==6
    assert not any(o['id']==p['id']+'-'+r['id'] for o in refs['ocr'] for p,r in clipped)


def test_changed_truth_masks_and_backgrounds_fail_preflight(fixtures,tmp_path):
    _,assets,folder,refs=fixtures
    import shutil
    copied=tmp_path/'fixtures';shutil.copytree(folder,copied)
    row=refs['pages'][0];(copied/row['truth']).write_bytes(b'changed truth')
    with pytest.raises(ValueError,match='Fixture changed'):F.verify(refs,copied)
    copied_assets=tmp_path/'assets';shutil.copytree(assets,copied_assets)
    Image.new('RGB',(170,170),'white').save(copied_assets/(F.NAMES[0]+'.png'))
    with pytest.raises(ValueError,match='Background differs'):F.generate(tmp_path/'bad',copied_assets)


def test_partial_or_mixed_or_clipped_crop_is_not_a_unique_full_text_oracle():
    a=np.zeros((40,80),bool);a[10:20,10:30]=True
    b=np.zeros_like(a);b[10:20,50:70]=True
    page={'regions':[{'id':'a','text':'WAIT','clipped':False},{'id':'b','text':'HERE','clipped':False}]}
    assert H.match_crop(page,[a,b],[5,5,35,25])['unique_full_reference']['id']=='a'
    assert H.match_crop(page,[a,b],[15,5,35,25])['unique_full_reference'] is None
    assert H.match_crop(page,[a,b],[5,5,75,25])['unique_full_reference'] is None
    page['regions'][0]['clipped']=True
    assert H.match_crop(page,[a,b],[5,5,35,25])['unique_full_reference'] is None
    assert H.match_crop(page,[a,b],[5,5,35,25])['touches_clipped_source']


def test_new_artwork_damage_is_distinguished_from_preexisting_degradation():
    clean=np.full((20,20,3),.8,np.float32);original=clean.copy();original[5:8,5:8]=0
    mask=np.zeros((20,20),bool);mask[5:8,5:8]=True
    good={'base':clean.copy(),'cleanup_mask':np.ones_like(mask)}
    assert H.cleanup_evidence(original,clean,good,mask)['new_artwork_damage_pixels_outside_reference_glyphs']==0
    bad={'base':clean.copy(),'cleanup_mask':np.ones_like(mask)};bad['base'][12:15,12:15]=.1
    assert H.cleanup_evidence(original,clean,bad,mask)['new_artwork_damage_pixels_outside_reference_glyphs']==9


def test_annotation_observations_never_inflate_pass_or_gap_counts(fixtures,tmp_path):
    _,_,folder,refs=fixtures
    (tmp_path/'fixtures').mkdir();(tmp_path/'fixtures/references.json').write_bytes((folder/'references.json').read_bytes())
    audit=H.Audit(tmp_path,'unit',refs)
    audit.case('chain-ambiguous-latin-intent','diagnostic','cannot determine intent from pixels',lambda:(False,{'answer':'I'}))
    audit.case('letter-ambiguous-lines-intent-1','diagnostic','not an accuracy oracle',lambda:(True,{}))
    assert audit.report['counts']=={'OBSERVATION':2}
