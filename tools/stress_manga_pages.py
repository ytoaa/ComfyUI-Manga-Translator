"""CPU manga audit: external clean art and Japanese font; no private images in Git.

Modes execute actual native nodes. Detector/OCR modes use pinned real weights;
contracts and bubble-lettering use explicitly supplied independent geometry and
clean references. Missing Qwen is a waiting state, never completed inpainting.
The reduced OCR preset is experimental and does not change production defaults.
"""
from pathlib import Path
import argparse,os,sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
if __package__:
    from . import manga_image_scenarios as F, stress_ambiguous_pages as H
else:
    import manga_image_scenarios as F, stress_ambiguous_pages as H
def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['generate','contracts','detector','ocr-default','ocr-reduced','chain-default','bubble-lettering'])
    p.add_argument('--destination',required=True,type=Path);p.add_argument('--models',type=Path);p.add_argument('--assets',type=Path);p.add_argument('--threads',type=int,choices=range(1,9),default=3);a=p.parse_args()
    a.destination=a.destination.resolve();a.include_sfx=True
    if a.destination==ROOT or ROOT in a.destination.parents:p.error('Keep generated inputs/results outside Git')
    a.destination.mkdir(parents=True,exist_ok=True)
    if a.mode=='generate':
        if a.assets is None:p.error('--assets required')
        F.generate(a.destination/'fixtures',a.assets);return 0
    if a.mode in ('detector','ocr-default','ocr-reduced','chain-default') and a.models is None:p.error('--models required')
    refs=json.loads((a.destination/'fixtures/references.json').read_text());F.verify(refs,a.destination/'fixtures')
    os.environ.update(CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='3',MKL_NUM_THREADS='3')
    import torch;torch.set_num_threads(a.threads);torch.set_num_interop_threads(1)
    get=H.A.modules(a.destination);audit=H.Audit(a.destination,a.mode,refs)
    audit.report['source_sha256']['tools/manga_image_scenarios.py']=F.digest(F.__file__)
    audit.report['source_sha256']['tools/stress_manga_pages.py']=F.digest(__file__)
    audit.report.update(manga_harness_sha256=F.digest(__file__),fixture_scope='32 new manga pages; translation excluded; native CPU nodes and real models where marked')
    if a.mode=='contracts':H.contracts(audit,a,get,refs)
    elif a.mode=='detector':H.detector(audit,a,get,refs)
    elif a.mode.startswith('ocr-'):
        if a.mode=='ocr-reduced':
            M=get('models');base=M.MangaOCRAdaptive
            class Small(base):
                def read(self,*args,**kw):
                    kw.update(base_patches=256,small_text_patches=512,small_text_px=8,line_split=True)
                    return super().read(*args,**kw)
            M.MangaOCRAdaptive=Small
        audit.report['ocr_settings']='production defaults' if a.mode=='ocr-default' else {'base_patches':256,'small_text_patches':512,'small_text_px':8,'line_split':True}
        H.known_ocr(audit,a,get,refs)
    elif a.mode=='chain-default':
        variants=('blank','opaque','alpha128','alpha064','dark128','borderless','vertical-ruby','outlined-sfx')
        subset={**refs,'pages':[r for r in refs['pages'] if r['variant'] in variants]}
        audit.report.update(selected_variants=list(variants),selected_pages=len(subset['pages']),ocr_settings='production defaults')
        H.chain(audit,a,get,subset)
    else:bubble_tests(audit,a,get,refs)
    audit.report['completed']=True;audit.flush();return audit.exit_code()

def bubble_tests(audit,a,get,refs):
    import numpy as np,torch
    E,L,B=[get(n) for n in ('page_edit','lettering.nodes','lettering.hybrid')]
    for row in refs['pages']:
        if not row['balloon_count']:continue
        def case(row=row):
            original,clean,masks=H.T.read_case(a,row);ink=np.logical_or.reduce(masks)
            data=E.build(H.T.document(row),*row['size'],source_mask=ink)
            prepared,support=L.MangaLetterPrepare().prepare(torch.from_numpy(original)[None],json.dumps(data),text_pixel_mask=torch.from_numpy(ink.astype(np.float32))[None])
            with np.load(a.destination/'fixtures'/row['truth']) as f:bubbles=np.logical_or.reduce([f['bubble'+str(i)] for i in range(row['balloon_count'])])
            scope={'declared_input':'independent known clean reference and supplied bubble union mask; not actual detection or completed inpainting','completed':False}
            try:
                plan,_,build=B.build_plan(original,clean,support[0].numpy(),prepared,page_direction='horizontal',
                    mode='bubble',respect_bubbles=True,bubble_mask=bubbles.astype(np.float32),bubble_failure_policy='preserve_review',
                    fit_policy='readable',line_breaks='reflow')
                layers=[];method=B.core.composite
                def observe(*args,**kwargs):
                    result,alpha=method(*args,**kwargs);layers.append(alpha>0);return result,alpha
                B.core.composite=observe
                try:result,alpha,raw=B.render_plan(plan)
                finally:B.core.composite=method
            except ValueError as exc:return False,{**scope,'state':'guarded_stop','refused':str(exc),'diagnostic':getattr(exc,'diagnostic',None)}
            union=np.zeros(alpha.shape,bool);collisions=0
            for layer in layers:collisions+=int((union&layer).sum());union|=layer
            protected=plan['protected_boxes_pixels']
            kept=all(not alpha[b:d,x:c].any() and np.array_equal(result[b:d,x:c],original[b:d,x:c]) for x,b,c,d in protected)
            outside=bool(np.array_equal(result[alpha==0],plan['cleaned'][alpha==0]));report=json.loads(raw)
            retained={r['id']:r['render']['text'] for r in report['regions']}=={r['id']:r['text'] for r in plan['regions']}
            spill=int(((alpha>0)&~bubbles).sum())
            path=a.destination/'bubble-lettering-artifacts'/(row['id']+'.png');path.parent.mkdir(exist_ok=True)
            H.Image.fromarray((result*255).round().astype('uint8')).save(path)
            ev={**scope,'state':'rendered','completed':len(report['regions'])==len(row['regions']),
                'glyph_collision_pixels':collisions,'outside_bubble_alpha_pixels':spill,'outside_alpha_exact':outside,
                'protected_pixels_exact':kept,'strings_retained':retained,'render_report':report,'build_report':json.loads(build),'image':str(path)}
            return collisions==0 and spill==0 and outside and kept and retained and ev['completed'],ev
        audit.case('bubble-'+row['id'],'known-mask-bubble-lettering','actual renderer: full fixed strings inside bubble; no collision or changed protected/outside pixels; isolated clean input',case)

if __name__=='__main__':raise SystemExit(main())
