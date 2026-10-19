"""Manga fixture oracle controls; procedural proxy art only, no private images."""
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw,ImageFilter
import pytest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import manga_image_scenarios as F


@pytest.fixture(scope='module')
def fixtures(tmp_path_factory):
    base=tmp_path_factory.mktemp('manga-fixtures');assets=base/'assets';assets.mkdir();inventory={}
    for i,name in enumerate(('rain','temple')):
        image=Image.new('RGB',(192,288),(70+i*40,85,95));d=ImageDraw.Draw(image)
        for x in range(0,192,9):d.line((x,0,x+25,288),fill=(185,175,165),width=2)
        image.save(assets/(name+'.png'));inventory[name]={'sha256':F.digest(assets/(name+'.png'))}
    shutil.copyfile(ROOT/'lettering/fonts/MangaSansKR-Fallback.ttf',assets/'NotoSerifJP.ttf')
    inventory['font']={'sha256':F.digest(assets/'NotoSerifJP.ttf'),'source':'test proxy font; no downloaded font in Git'}
    (assets/'assets.json').write_text(json.dumps(inventory));folder=base/'fixtures'
    # The bundled fallback deliberately lacks 戻. This procedural oracle test
    # substitutes a supported literal; the actual private model audit uses the
    # complete, SHA-verified Noto Serif JP face and the original literal.
    add=F.Scene.add
    def proxy_literal(self,ident,text,*args,**kwargs):
        return add(self,ident,text.replace('戻','駅'),*args,**kwargs)
    with patch.object(F.Scene,'add',proxy_literal):refs=F.generate(folder,assets)
    return assets,folder,refs


def test_private_manga_suite_has_declared_independent_references(fixtures):
    _,folder,refs=fixtures
    assert len(refs['pages'])==32 and len({r['id'] for r in refs['pages']})==32
    assert len(refs['ocr'])==40
    assert sum(len(p['regions']) for p in refs['pages'])==42
    F.verify(refs,folder)


def test_clean_retains_balloon_alpha_and_background_detail(fixtures):
    _,folder,refs=fixtures;pages={p['id']:p for p in refs['pages']}
    images=[np.asarray(Image.open(folder/pages['rain-'+v]['clean'])) for v in ('opaque','alpha192','alpha128','alpha064','alpha000')]
    # The same location is the balloon interior, away from glyphs/border/tail.
    samples=[a[165:240,100:140].astype(float) for a in images]
    assert np.ptp(samples[0])==0
    assert all(np.ptp(a)>0 for a in samples[1:])
    assert all(np.mean(a)>np.mean(b) for a,b in zip(samples,samples[1:]))
    assert not np.array_equal(images[2],images[0])


def test_only_glyphs_differ_from_clean_reference_before_jpeg(fixtures):
    _,folder,refs=fixtures
    for p in refs['pages']:
        image=np.asarray(Image.open(folder/p['image']));clean=np.asarray(Image.open(folder/p['clean']))
        with np.load(folder/p['truth']) as source:
            masks=[source[r['id']] for r in p['regions']]
            support=np.logical_or.reduce(masks) if masks else np.zeros(image.shape[:2],bool)
            for r,m in zip(p['regions'],masks):
                assert m.any()
                a,b,c,d=r['frame_pixels'];outside=m.copy();outside[b:d,a:c]=False
                assert not outside.any(),(p['id'],r['id'])
            if p['variant']!='jpeg-blur':assert np.array_equal(image[~support],clean[~support]),p['id']
        if p['negative']:assert not p['regions'] and np.array_equal(image,clean)


def test_ruby_keeps_separate_truth_and_clipped_text_has_no_full_ocr_oracle(fixtures):
    _,folder,refs=fixtures
    for p in refs['pages']:
        if p['variant']=='vertical-ruby':
            rows={r['id']:r for r in p['regions']};assert rows['ruby']['ruby_of']=='body'
            assert rows['ruby']['source_size']==12 and rows['body']['vertical']
            with np.load(folder/p['truth']) as masks:assert not (masks['ruby']&masks['body']).any()
        for r in p['regions']:
            if r['clipped']:assert not any(o['id']==p['id']+'-'+r['id'] for o in refs['ocr'])


def test_changed_source_or_truth_fails_before_model_execution(fixtures,tmp_path):
    assets,folder,refs=fixtures
    copied=tmp_path/'fixtures';shutil.copytree(folder,copied)
    row=refs['pages'][0];(copied/row['truth']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='Fixture changed'):F.verify(refs,copied)
    copied_assets=tmp_path/'assets';shutil.copytree(assets,copied_assets)
    (copied_assets/'NotoSerifJP.ttf').write_bytes(b'changed font')
    with pytest.raises(ValueError,match='Font changed'):F.generate(tmp_path/'bad',copied_assets)


def test_codec_artifacts_are_not_extra_reference_glyphs(fixtures):
    _,folder,refs=fixtures
    for family in ('rain','temple'):
        with np.load(folder/(family+'-opaque-truth.npz')) as f:geometric=f['dialogue']
        blurred=np.asarray(Image.fromarray(geometric.astype('uint8')*255).filter(ImageFilter.GaussianBlur(.55)))>1
        with np.load(folder/(family+'-jpeg-blur-truth.npz')) as f:
            assert np.array_equal(f['dialogue'],blurred)
            assert 'codec_artifact_support' in f
            assert (f['codec_artifact_support']&~blurred).any()
