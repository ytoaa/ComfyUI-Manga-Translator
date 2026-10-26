"""Render deterministic adversarial pages; simulate geometry and real CPU lettering.

Detection observations and translation strings are controlled inputs. This is
not an OCR/translation/model accuracy benchmark. No private pages are loaded.
"""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys
import zipfile
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.test_page_scenarios_v0715 import cases,resolve,P,giant_projection,run


def save(path,array):
    Image.fromarray((np.clip(array,0,1)*255).round().astype('uint8')).save(path)


def simulate(destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    summaries=[]
    for case in cases():
        name,original,clean,ink,rows,owners,count,review=case;h,w=ink.shape
        folder=destination/name;folder.mkdir(exist_ok=True)
        doc=resolve(rows,owners,(w,h))
        for row in doc['regions']:row.update(source='Complete synthetic source.',target='완전한 시험 번역문.')
        edited=P.build(doc,w,h)['page_edit_plan'];assert len(doc['regions'])==count
        allowed=np.zeros((h,w),bool);prepared=[]
        for row in edited['regions']:
            x,y,z,t=row['bbox_pixels']
            if row['action']=='replace':
                allowed[y:t,x:z]=True
                prepared.append({'id':row['id'],'bbox':[x,y,z-x,t-y],'text':'완전한 시험 번역문.'})
        assert bool(prepared)!=review
        cleaned=original.copy();cleaned[allowed]=clean[allowed]
        raw=json.dumps({'schema':1,'coordinate_format':'xywh','page_size':[w,h],'regions':prepared})
        if prepared:
            _,output,alpha,report,_,_=run((original,cleaned,ink.astype(np.float32),raw),
                fit_policy='readable',fit_failure_policy='preserve_review')
            if name=='rotated-nested':
                assert not report['regions'] and report['lettering_review'][0]['reason']=='inconsistent_source_typography'
                assert np.array_equal(output,original)
            else:assert len(report['regions'])==len(prepared),name
            assert all(r['render']['text']=='완전한 시험 번역문.' for r in report['regions'])
        else:output=original.copy();report={'regions':[],'simulation_preserved':True}
        assert np.array_equal(output[~allowed],original[~allowed]),name
        save(folder/'source.png',original);save(folder/'result.png',output)
        overlay=Image.fromarray((original*255).round().astype('uint8'));draw=ImageDraw.Draw(overlay)
        for row in rows:draw.rectangle(row['bbox'],outline='orange',width=2)
        for row in edited['regions']:draw.rectangle(row['bbox_pixels'],outline='red' if row['action']=='preserve' else 'green',width=2)
        overlay.save(folder/'regions.png')
        (folder/'report.json').write_text(json.dumps({'edit_plan':edited,'lettering':report},ensure_ascii=False,indent=2))
        summaries.append({'scenario':name,'raw_observations':len(rows),'resolved':count,'preserve':review,'outside_unchanged':True})
    values=giant_projection();_,out,alpha,report,_,_=run(values,fit_failure_policy='preserve_review')
    assert not alpha.any() and np.array_equal(out,values[0])
    folder=destination/'collapsed-projection';folder.mkdir(exist_ok=True)
    save(folder/'source.png',values[0]);save(folder/'result.png',out)
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    summaries.append({'scenario':'collapsed-projection','preserve':True,'outside_unchanged':True})
    (destination/'summary.json').write_text(json.dumps({'scope':'controlled_detector_and_translation_inputs_real_CPU_lettering',
        'cases':summaries},ensure_ascii=False,indent=2))
    archive=destination.parent/'source-scenarios-v0.7.15.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destination.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(destination))
    print(json.dumps({'scenarios':len(summaries),'archive':str(archive),'checks':'PASS'}))


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__);parser.add_argument('--destination',required=True)
    simulate(parser.parse_args().destination)
