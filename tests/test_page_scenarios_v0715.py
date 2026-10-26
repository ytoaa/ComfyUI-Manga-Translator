"""Deterministic rendered pages and adversarial detector observations, no model claims."""
import json
from copy import deepcopy
import numpy as np
from PIL import Image,ImageDraw,ImageFont
import pytest
from tests.test_source_ownership import R,S,P,mask
from tests.test_hybrid_lettering import core,hybrid,fixture,run


def page(style='plain'):
    clean=np.full((500,640,3),1. if style!='gray' else .7,np.float32)
    picture=Image.fromarray((clean*255).astype('uint8'));draw=ImageDraw.Draw(picture)
    font=ImageFont.truetype(core.font_path('NanumGothic-Bold.ttf','TEST'),24)
    # Staggered rows are intentional: their y projections partly overlap.
    for i,text in enumerate(['COMPLETE SOURCE','KEEP THE END.','NEXT MESSAGE','DO NOT IDENTIFY.']):
        draw.text((30,30+i*85),text,font=font,fill='black')
    original=np.asarray(picture,np.float32)/255
    ink=np.max(np.abs(original-clean),axis=2)>.07
    if style=='rotated':
        original=original.transpose(1,0,2).copy();clean=clean.transpose(1,0,2).copy();ink=ink.T.copy()
    return original,clean,ink


def observation(box,ink,score=.9):
    x,y,z,t=box
    return {'label':'text','bbox':box,'score':score,'mask':mask(ink[y:t,x:z],x,y)}


def resolve(rows,owners=(),size=(640,500)):
    w,h=size
    return json.loads(R.MangaDetectionRegionsResolved().convert({'protocol':1,
        'image_width':w,'image_height':h,'detections':[*rows,*owners,{'label':'bubble','bbox':[0,0,w,h],'score':.99,'mask':mask(np.ones((h,w),bool),0,0)}]})[0])


def cases():
    result=[]
    for style in ['plain','gray','rotated']:
        original,clean,ink=page(style);h,w=ink.shape
        large=[20,20,400,400];small=[20,20,400,150]
        owners=[{'label':'bubble','bbox':[0,0,420,160],'score':.9},
                {'label':'bubble','bbox':[0,180,420,480],'score':.9}]
        if style=='rotated':
            large=[large[1],large[0],large[3],large[2]];small=[small[1],small[0],small[3],small[2]]
            for row in owners:row['bbox']=[row['bbox'][1],row['bbox'][0],row['bbox'][3],row['bbox'][2]]
        # Keep a continuous source pixel across the alleged owner gap: the
        # detector's false boundary must not justify splitting real source.
        if style=='rotated':ink[40,145:195]=True;original[40,145:195]=0
        else:ink[145:195,40]=True;original[145:195,40]=0
        rows=[observation(large,ink),observation(small,ink,.8)]
        result.append((style+'-nested',original,clean,ink,rows,owners,1,False))
    original,clean,ink=page()
    for name,a,b,expected,review in [
        ('mixed-crops',[20,20,400,240],[20,100,400,400],2,True),
        ('independent',[20,20,400,90],[20,190,400,270],2,False),
        ('full-duplicate',[20,20,400,400],[20,20,400,400],1,False),
        ('partial-ending',[20,20,400,400],[20,20,400,270],1,False)]:
        result.append((name,original,clean,ink,[observation(a,ink),observation(b,ink,.8)],[],expected,review))
    return result


@pytest.mark.parametrize('case',cases(),ids=lambda v:v[0])
def test_rendered_source_scenarios(case):
    name,original,clean,ink,rows,owners,count,review=case;h,w=ink.shape
    doc=resolve(rows,owners,(w,h));assert len(doc['regions'])==count,name
    for r in doc['regions']:r.update(source='Complete synthetic source.',target='완전한 시험 번역문.')
    reasons=[S.review_reason(r,w,h) for r in doc['regions']]
    assert any(x=='ambiguous_source_overlap' for x in reasons)==review
    plan=P.build(doc,w,h)['page_edit_plan']
    assert all(r['action']==('preserve' if review else 'replace') for r in plan['regions'])
    # Duplicate resolution keeps the complete detected extent, including the
    # final line beyond the smaller crop. It never fabricates an OCR suffix.
    if count==1:
        box=doc['regions'][0]['bbox'];raw=rows[0]['bbox']
        assert np.allclose(box,np.asarray(raw)/[w,h,w,h]*1000)


def test_cross_boundary_disjoint_ink_cannot_bypass_separator():
    from source_ownership_tests.region_boundaries import separators
    _,_,ink=page();a=observation([20,20,400,400],ink)
    b=observation([20,20,400,90],np.zeros_like(ink));b['mask']=mask(np.ones((10,10),bool),370,70)
    barriers=separators([{'label':'panel','bbox':[0,0,420,100]}, {'label':'panel','bbox':[0,200,420,480]}])
    assert len(R.merge_detector_regions([a,b],.75,barriers=barriers,width=640,height=500))==2


def giant_projection():
    clean=np.ones((360,360,3),np.float32);original=clean.copy();ink=np.zeros((360,360),np.float32)
    for y in range(20,325,20):
        x=20+((y//20)%3)*90;ink[y:y+24,x:x+16]=1
    original[ink>0]=0
    doc=json.dumps({'schema':1,'coordinate_format':'xywh','page_size':[360,360],
                    'regions':[{'id':'r1','bbox':[10,10,340,340],'text':'시험 번역문'}]})
    return original,clean,ink,doc


def test_collapsed_projection_is_reviewed_before_expensive_fit():
    v=giant_projection();profile,_=hybrid.profile(*v[:3],'NanumGothic-Bold.ttf')
    assert profile['measurement_warning']=='inconsistent_source_typography'
    plan,out,alpha,report,_,_=run(v,fit_failure_policy='preserve_review')
    assert not plan['regions'] and not alpha.any() and np.array_equal(out,v[0])
    assert report['lettering_review'][0]['reason']=='inconsistent_source_typography'
    with pytest.raises(ValueError,match='inconsistent source typography'):run(v,fit_failure_policy='stop')


def test_explicit_typography_override_allows_reviewed_source():
    plan,_,alpha,_,_,_=run(giant_projection(),fit_failure_policy='preserve_review',
                          region_options_json='{"r1":{"font_cap":24}}')
    assert plan['regions'] and alpha.any()


def test_readability_fallback_has_an_explicit_warning():
    _,_,_,report,_,_=run(fixture('시험 문장 '*15,width=320,height=120,font_size=42),
                        fit_policy='readable',fit_failure_policy='preserve_review')
    assert report['regions'] and any(r['source_ratio_relaxed'] for r in report['regions'])
    for row in report['regions']:
        if row['source_ratio_relaxed']:
            assert row['warning']=='source_ratio_relaxed' and report['needs_review']


def test_image_simulator_checks_and_writes_all_eight_scenarios(tmp_path):
    from tools.simulate_source_scenarios import simulate
    simulate(tmp_path/'scenarios')
    summary=json.loads((tmp_path/'scenarios'/'summary.json').read_text())
    assert len(summary['cases'])==8
    assert len(list((tmp_path/'scenarios').glob('*/source.png')))==8
    assert len(list((tmp_path/'scenarios').glob('*/result.png')))==8
    assert (tmp_path/'source-scenarios-v0.7.15.zip').is_file()
