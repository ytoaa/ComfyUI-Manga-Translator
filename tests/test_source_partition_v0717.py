"""Independent source layers: compare pixels, never assume successful return."""
from copy import deepcopy
import io
import json
import hashlib
import zipfile
import numpy as np
import pytest
import torch
from PIL import Image,ImageDraw,ImageFont
from tools.simulate_ownership_scenarios import cases,scenario,execute,module,C,H,R,N,encode_mask

S=module('source_partition')


@pytest.mark.parametrize('case',cases(),ids=lambda c:c['name'])
def test_overlapping_observations_produce_two_complete_unique_ocr_sources_and_two_translations(case):
    before=case['original'].copy();raw=deepcopy(case['raw'])
    report,crops,result=execute(case)
    assert np.array_equal(case['original'],before) and case['raw']==raw
    assert all(c['foreign_pixels']==0 for c in report['crop_checks'])
    assert len(report['lettering']['regions'])==2 and not report['lettering'].get('lettering_review')
    if case['name']=='staggered-columns':
        assert all(24<=r['source_profile']['font_cap']<=36 for r in report['lettering']['regions'])
    if case['name']=='diagonal-overlap':
        assert all(r['fit_phase'].startswith('bubble') for r in report['lettering']['regions'])


def test_partition_does_not_drop_or_duplicate_positive_input_pixels():
    c=scenario('ink-conservation');raw=c['raw'];w,h=raw['image_width'],raw['image_height']
    rows=[{**r,'source_detector_ids':[str(i)]} for i,r in enumerate(raw['detections']) if r['label']=='text']
    bubbles=[r for r in raw['detections'] if r['label']=='bubble']
    parts,audit=S.partition_by_bubbles(rows,bubbles,w,h)
    merged=R.merge_detector_regions(parts,.75,width=w,height=h)
    assert len(merged)==2 and all(a['parts']==2 for a in audit)
    source=np.zeros((h,w),np.int32)
    for row in merged:
        m,(x,y,s,t)=S._decode_mask(row['mask'],w,h);source[y:y+t,x:x+s]+=m.astype(np.int32)
    assert source.max()==1
    assert np.array_equal(source>0,c['truth'][0]|c['truth'][1])


def test_missing_interiors_do_not_turn_overlaps_into_verified_owners():
    c=scenario('missing-interiors')
    for r in c['raw']['detections']:
        if r['label']=='bubble':r.pop('mask')
    d=json.loads(R.MangaDetectionRegionsResolved().convert(c['raw'])[0])
    assert d['needs_review']
    assert all('ocr_owner_mask' not in r['source_ownership'] for r in d['regions'])
    assert any(r['source_ownership'].get('review_reason')=='ambiguous_source_overlap' for r in d['regions'])


def test_boundary_through_one_connected_glyph_cannot_partition_that_observation():
    pixels=np.zeros((80,100),bool);pixels[20:40,40:60]=True
    raw,box=encode_mask(pixels,0,0)
    item={'label':'text','bbox':box,'score':.9,'mask':raw}
    bubbles=[]
    for x,z in [(0,50),(50,100)]:
        mask=np.ones((80,z-x),bool);m,b=encode_mask(mask,x,0)
        bubbles.append({'label':'bubble','bbox':b,'score':.9,'mask':m})
    result,audit=S.partition_by_bubbles([item],bubbles,100,80)
    assert result==[item] and not audit


def test_non_nested_rival_interiors_never_choose_a_shared_glyph_arbitrarily():
    pixels=np.zeros((100,100),bool);pixels[35:65,40:60]=True
    m,b=encode_mask(pixels,0,0);row={'label':'text','bbox':b,'score':.9,'mask':m}
    bubbles=[]
    for x in (10,30):
        raw,box=encode_mask(np.ones((60,60),bool),x,20)
        bubbles.append({'label':'bubble','bbox':box,'mask':raw,'score':.9})
    result,audit=S.partition_by_bubbles([row],bubbles,100,100)
    assert result==[row] and not audit


def test_reference_isolation_keeps_original_and_does_not_read_foreign_pixels():
    crop=torch.ones((1,80,100,3));crop[:,20:40,20:30]=0;crop[:,20:40,70:80]=0
    before=crop.clone();raw,_=encode_mask(np.ones((80,50),bool),0,0)
    isolated,allowed=S.isolate_crop(crop,raw,[0,0,100,80],100,80)
    assert torch.equal(crop,before) and not isolated[:,20:40,20:30].any()
    assert isolated[:,20:40,70:80].eq(1).all()


def test_unverified_spanning_observation_cannot_rejoin_two_verified_owners():
    c=scenario('unverified-bridge');raw=c['raw'];w,h=raw['image_width'],raw['image_height']
    pixels=c['truth'][0]|c['truth'][1];pixels=pixels.copy();pixels[100:105,100:105]=True
    mask,box=encode_mask(pixels,0,0)
    raw['detections'].append({'label':'text','bbox':box,'score':.99,'mask':mask})
    items=[r for r in raw['detections'] if r['label']=='text'];bubbles=[r for r in raw['detections'] if r['label']=='bubble']
    parts,_=S.partition_by_bubbles(items,bubbles,w,h)
    selected=R.merge_detector_regions(parts,.75,width=w,height=h)
    assert len(selected)==3 and len({r['bubble_owner'] for r in selected if r.get('bubble_owner')})==2


@pytest.mark.parametrize('partial',[False,True])
def test_text_effect_alias_identity_survives_tightening_to_owned_ink(partial):
    c=scenario('label-alias',box_only_overlap=True)
    other=deepcopy(c['raw']['detections'][0]);other['label']='onomatopoeia'
    if partial:
        pixels=c['truth'][0].copy();pixels[:85]=False
        other['mask'],_=encode_mask(pixels,0,0)
    c['raw']['detections'].append(other)
    d=json.loads(R.MangaDetectionRegionsResolved().convert(c['raw'],include_sfx=True)[0])
    assert len(d['regions'])==2
    assert sum(r['source_ownership']['cross_label_alias'] for r in d['regions'])==1
    assert next(r for r in d['regions'] if r['source_ownership']['cross_label_alias'])['source_ownership']['labels']==['onomatopoeia','text']


def test_disjoint_sources_in_one_bubble_keep_two_owners_and_crop_margins_do_not_duplicate_ink():
    page=torch.ones((1,100,120,3));detections=[]
    for x in (30,45):
        page[:,20:40,x:x+10]=0;mask,box=encode_mask(np.ones((20,10),bool),x,20)
        detections.append({'label':'text','bbox':[20,15,65,45],'score':.9,'mask':mask})
    mask,box=encode_mask(np.ones((65,65),bool),10,5)
    detections.append({'label':'bubble','bbox':box,'score':.9,'mask':mask})
    raw={'protocol':1,'image_width':120,'image_height':100,'detections':detections}
    resolved=R.MangaDetectionRegionsResolved().convert(raw)[0]
    assert len(json.loads(resolved)['regions'])==2
    crops,manifest,_,_=N.MangaRegionCrops().crop(page,resolved,ocr_padding=12)
    assert len(crops)==2 and all(int((c[0,...,0]==0).sum())==200 for c in crops)


def test_repeated_glyph_geometry_recovers_size_but_filled_noise_does_not():
    picture=Image.new('RGB',(360,360),'white');draw=ImageDraw.Draw(picture)
    font=ImageFont.truetype(C.font_path('NanumGothic-Bold.ttf',''),28)
    for i in range(17):draw.text((20+(i%3)*90,10+i*18),'B',font=font,fill='black')
    original=np.asarray(picture,np.float32)/255;clean=np.ones_like(original)
    ink=np.max(abs(original-clean),axis=2)>.07
    p,_=H.profile(original,clean,ink,'NanumGothic-Bold.ttf')
    assert p['measurement_method'] in ('component_consensus','vertical_columns') and 18<=p['font_cap']<=32
    from tests.test_page_scenarios_v0715 import giant_projection
    p,_=H.profile(*giant_projection()[:3],'NanumGothic-Bold.ttf')
    assert p['measurement_warning']=='inconsistent_source_typography'


def test_reproduction_export_roundtrips_exact_pixels_masks_and_hashes(tmp_path):
    c=scenario('bundle');raw={**c['raw'],'api_key':'must-not-be-saved','base_url':'must-not-be-saved'}
    regions=R.MangaDetectionRegionsResolved().convert(c['raw'])[0]
    result=module('reproduction').save(c['original'],raw,regions,tmp_path)
    with zipfile.ZipFile(result['path']) as z:
        manifest=json.loads(z.read('manifest.json'))
        for name,digest in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
        assert np.array_equal(np.load(io.BytesIO(z.read('original.npy')),allow_pickle=False),c['original'])
        restored=json.loads(z.read('detection.json'))
        assert restored==c['raw'] and 'api_key' not in restored and 'base_url' not in restored
        assert z.read('regions.json').decode()==regions
    assert not list(tmp_path.rglob('*.tmp')) and result['automatic_upload'] is False


def test_export_is_opt_in_and_failures_are_not_reported_as_saved(monkeypatch,tmp_path):
    import types,sys
    D=module('debug_nodes');c=scenario('debug');page=torch.from_numpy(c['original'])[None]
    regions=R.MangaDetectionRegionsResolved().convert(c['raw'])[0]
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    args=('detection',regions,page,None,c['raw'])
    report,_=D.MangaDebugInspect().inspect(*args)
    assert 'reproduction' not in json.loads(report)['report'] and not list(tmp_path.iterdir())
    report,_=D.MangaDebugInspect().inspect(*args,save_reproduction=True)
    assert json.loads(report)['report']['reproduction']['path'].endswith('.zip')
    with pytest.raises(ValueError,match='requires the detection'):D.MangaDebugInspect().inspect('ocr','{}',save_reproduction=True)


def test_partition_and_typography_reject_bad_masks_before_allocation():
    c=scenario('bad-mask');c['raw']['detections'][2]['mask']['runs']=[10]
    with pytest.raises(ValueError,match='RLE length'):R.MangaDetectionRegionsResolved().convert(c['raw'])
    doc={'schema':1,'coordinate_format':'xywh','page_size':[100,100],'regions':[],
         'source_owners':{'unknown':{'x':0,'y':0,'width':100,'height':100,'runs':[0,10000]}}}
    with pytest.raises(ValueError,match='source owner IDs'):C.parse_regions(json.dumps(doc),(100,100,3))


@pytest.mark.parametrize('target',['문장n 다음','문장 n다음','문장 n 다음','문장\u200an\u200a다음'])
def test_spaced_phantom_line_breaks_do_not_bypass_translation_contract(target):
    T=module('text_contract')
    with pytest.raises(ValueError,match='translation_line_break_marker'):T.translation_text('原文',target)
    assert T.translation_text('変数 n',target)==(target,0)
    assert T.translation_text('原文',target,False)==(target,0)


def test_single_region_translation_uses_the_same_marker_guard(monkeypatch):
    T=module('lettering.translate')
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'확인 n다음'}}]}).encode()
    monkeypatch.setattr(T,'urlopen',lambda *a,**k:Response())
    with pytest.raises(ValueError,match='translation_line_break_marker'):T.translate('原文',model='simulation')


def test_source_overlap_preservation_sets_review_without_an_upstream_flag():
    P=module('page_edit')
    doc={'image_width':100,'image_height':100,'regions':[{'id':'r1','bbox':[100,100,800,800],
         'source':'unresolved source','target':'번역문','source_ownership':{'schema':1,'review_reason':'ambiguous_source_overlap'}}]}
    result=P.build(doc,100,100)
    assert result['page_edit_plan']['regions'][0]['action']=='preserve'
    assert result['needs_review'] is True and result['page_edit_plan']['needs_review'] is True
