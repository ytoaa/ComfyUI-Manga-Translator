"""Independent pixel truth for overlapping crops and source-size recovery.

Model observations/OCR/translation are controlled, never called accuracy tests.
The assertions compare crops and rendered pixels against independently painted
source layers; a preserved source is not counted as translated.
"""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
NAME='ownership_image_simulation'
if NAME not in sys.modules:
    spec=importlib.util.spec_from_file_location(NAME,ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
    plugin=importlib.util.module_from_spec(spec);sys.modules[NAME]=plugin;spec.loader.exec_module(plugin)
def module(name):return importlib.import_module(NAME+'.'+name)
N=module('nodes');R=module('region_policy');K=module('mask_nodes')
L=module('lettering.nodes');H=module('lettering.hybrid');C=module('lettering.core')
encode_mask=module('region_boundaries').encode_mask


def scenario(name,scale=1,background='white',jitter=0,rotate=False,duplicate=False,angle=0,low_contrast=False,partial_tail=False,box_only_overlap=False):
    w,h=480,560
    gray={'white':255,'gray':165,'dark':35,'patterned':225}[background]
    clean=Image.new('RGB',(w,h),(gray,)*3)
    if background=='patterned':
        draw=ImageDraw.Draw(clean)
        for x in range(-h,w,18):draw.line((x,0,x+h,h),fill=(110,120,130),width=2)
        draw.rectangle((10,10,w-10,h-10),outline='black',width=4)
    font=ImageFont.truetype(C.font_path('NanumGothic-Bold.ttf',''),30)
    masks=[];owners=[]
    for index,(x,y,bounds) in enumerate([(335,45,[305,15,435,410]),(230,220,[175,180,295,550])]):
        layer=Image.new('L',(w,h));draw=ImageDraw.Draw(layer)
        for i,char in enumerate('하나둘셋넷다섯여덟'):
            draw.text((x+(i%3-1)*jitter,y+31*i),char,font=font,fill=255)
        masks.append(np.asarray(layer)>16)
        owner=Image.new('L',(w,h));ImageDraw.Draw(owner).rounded_rectangle(bounds,radius=25,fill=255)
        owners.append(np.asarray(owner)>0)
    if background=='patterned':
        a=np.asarray(clean).copy()
        for m in owners:a[m]=255
        clean=Image.fromarray(a)
    boxes=[[210,30,410,410],[175,190,375,550]]
    if partial_tail:boxes=[[305,30,410,410],[175,190,343,550]]
    if angle:
        import math
        masks=[np.asarray(Image.fromarray(m).rotate(angle,Image.Resampling.NEAREST)) for m in masks]
        owners=[np.asarray(Image.fromarray(m).rotate(angle,Image.Resampling.NEAREST)) for m in owners]
        clean=clean.rotate(angle,Image.Resampling.BICUBIC,fillcolor=(gray,)*3)
        theta=math.radians(angle);c,s=math.cos(theta),math.sin(theta);transformed=[]
        for x,y,z,t in boxes:
            points=[(w/2+c*(a-w/2)+s*(b-h/2),h/2-s*(a-w/2)+c*(b-h/2)) for a,b in [(x,y),(x,t),(z,y),(z,t)]]
            transformed.append([max(0,math.floor(min(a for a,b in points))),max(0,math.floor(min(b for a,b in points))),
                                min(w,math.ceil(max(a for a,b in points))),min(h,math.ceil(max(b for a,b in points)))])
        boxes=transformed
    if rotate:
        masks=[m.T.copy() for m in masks];owners=[m.T.copy() for m in owners];w,h=h,w
        clean=Image.new('RGB',(w,h),(gray,)*3)
    if scale!=1:
        w,h=round(w*scale),round(h*scale)
        masks=[np.asarray(Image.fromarray(m).resize((w,h),Image.Resampling.NEAREST)) for m in masks]
        owners=[np.asarray(Image.fromarray(m).resize((w,h),Image.Resampling.NEAREST)) for m in owners]
        clean=clean.resize((w,h))
    clean=np.asarray(clean,np.float32)/255;original=clean.copy()
    for m in masks:original[m]=1. if background=='dark' else .45 if low_contrast else 0.
    union=masks[0]|masks[1]
    if rotate:boxes=[[q[1],q[0],q[3],q[2]] for q in boxes]
    boxes=[[round(v*scale) for v in q] for q in boxes]
    detections=[]
    for i,(x,y,z,t) in enumerate(boxes):
        raw,_=encode_mask((masks[i] if box_only_overlap else union)[y:t,x:z],x,y)
        detections.append({'label':'text','bbox':[x,y,z,t],'score':.9-i*.01,'mask':raw})
    for m in owners:
        raw,box=encode_mask(m,0,0)
        detections.append({'label':'bubble','bbox':box,'score':.95,'mask':raw})
    if duplicate:detections.extend([dict(d) for d in detections])
    return {'name':name,'original':original,'clean':clean,'truth':masks,
            'raw':{'protocol':1,'image_width':w,'image_height':h,'detections':detections}}


def cases():
    return [scenario('diagonal-overlap'),scenario('gray-overlap',background='gray'),
            scenario('white-on-dark',background='dark'),scenario('small-source',scale=.6),
            scenario('high-resolution',scale=2),scenario('staggered-columns',jitter=5),
            scenario('horizontal-overlap',rotate=True),scenario('tiled-duplicates',duplicate=True),
            scenario('panel-and-screentone',background='patterned'),scenario('low-contrast',background='gray',low_contrast=True),
            scenario('slanted-plus-eight',angle=8),scenario('slanted-minus-eight',angle=-8),
            scenario('partial-shared-ending',partial_tail=True),scenario('boxes-overlap-ink-disjoint',box_only_overlap=True)]


def execute(case, padding=12):
    import torch
    original,clean=case['original'],case['clean'];h,w=original.shape[:2]
    raw=case['raw'];resolved=R.MangaDetectionRegionsResolved().convert(raw)[0]
    data=json.loads(resolved)
    assert len(data['regions'])==2, (case['name'],len(data['regions']))
    page=torch.from_numpy(original.copy())[None]
    pixel_mask=K.MangaDetectionMask().make(raw)[0]
    crops,manifest,_,plans=N.MangaRegionCrops().crop(page,resolved,ocr_padding=padding,text_pixel_mask=pixel_mask)
    manifest=json.loads(manifest);seen=[];crop_evidence=[]
    for crop,row in zip(crops,manifest['regions']):
        x,y,z,t=row['crop_bbox_pixels'];actual=crop[0].numpy()
        ink=np.max(np.abs(actual-clean[y:t,x:z]),axis=2)>.07
        hits=[int((ink&m[y:t,x:z]).sum()) for m in case['truth']]
        owner=int(np.argmax(hits));other=1-owner
        # No region may share a source letter, or omit any of its own truth.
        assert hits[owner]==int(case['truth'][owner].sum()),(case['name'],hits,'missing source')
        assert hits[other]==0,(case['name'],hits,'foreign source in OCR crop')
        seen.append(owner);crop_evidence.append({'region':row['id'],'truth_owner':owner,'own_pixels':hits[owner],'foreign_pixels':hits[other]})
    assert sorted(seen)==[0,1],(case['name'],'duplicate physical source owner')
    texts=['독립 원문 문장 '+str(i+1) for i in seen]
    collected=json.loads(N.MangaCollectOCR().collect(texts,[json.dumps(manifest)])[0])
    # Equal dialogue in distinct places is intentional: string deduplication
    # would wrongly remove one of these independently printed utterances.
    for row in collected['regions']:row['target']='같은 대사입니다.'
    prepared,support=L.MangaLetterPrepare().prepare(page,json.dumps(collected),text_pixel_mask=pixel_mask)
    plan,_,plan_report=H.build_plan(original,clean,support[0].numpy(),prepared,
        mode='bubble',line_breaks='reflow',page_direction='horizontal',fit_policy='readable',fit_failure_policy='preserve_review',respect_bubbles=True,detection_result=raw)
    output,alpha,report=H.render_plan(plan);report=json.loads(report)
    assert len(report['regions'])==2,(case['name'],report.get('lettering_review'))
    assert not report.get('lettering_review'),case['name']
    assert all(r['render']['text']=='같은 대사입니다.' for r in report['regions'])
    assert all(r['render']['line_count']<=5 for r in report['regions']), 'horizontal text collapsed to single-character lines'
    assert np.array_equal(output[alpha==0],clean[alpha==0]),'outside new text changed'
    return {'resolved':data,'crop_checks':crop_evidence,'plan':json.loads(plan_report),'lettering':report},crops,output


def save(path,pixels):
    Image.fromarray((np.clip(pixels,0,1)*255).round().astype('uint8')).save(path)


def simulate(destination):
    destination=Path(destination).resolve()
    if destination==ROOT or ROOT in destination.parents:raise ValueError('Keep generated images outside the repository')
    destination.mkdir(parents=True,exist_ok=True);summary=[]
    for case in cases():
        folder=destination/case['name'];folder.mkdir(exist_ok=True)
        report,crops,output=execute(case)
        save(folder/'source.png',case['original']);save(folder/'result.png',output)
        save(folder/'expected-clean.png',case['clean'])
        for i,mask in enumerate(case['truth']):save(folder/f'truth-{i+1}.png',mask.astype(np.float32))
        (folder/'detection.json').write_text(json.dumps(case['raw'],ensure_ascii=False,indent=2))
        for i,crop in enumerate(crops):save(folder/f'ocr-{i+1}.png',crop[0].numpy())
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        summary.append({'scenario':case['name'],'processed':len(report['lettering']['regions']),
                        'preserved':len(report['lettering'].get('lettering_review',[])),'crop_checks':report['crop_checks']})
    code_files=['source_partition.py','source_ownership.py','region_policy.py','nodes.py','page_edit.py',
                'lettering/nodes.py','lettering/core.py','lettering/hybrid.py','tools/simulate_ownership_scenarios.py']
    (destination/'summary.json').write_text(json.dumps({'scope':'controlled_model_inputs_real_crop_and_lettering_pixels',
        'version':module('workflow_native').VERSION,'seed':'deterministic_no_random_generator',
        'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in code_files},
        'font_sha256':hashlib.sha256(Path(C.font_path('NanumGothic-Bold.ttf','')).read_bytes()).hexdigest(),
        'cases':summary},ensure_ascii=False,indent=2))
    print(json.dumps({'cases':len(summary),'directory':str(destination)}))


if __name__=='__main__':
    from argparse import ArgumentParser
    parser=ArgumentParser(description=__doc__);parser.add_argument('--destination',required=True)
    simulate(parser.parse_args().destination)
