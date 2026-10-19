"""Real CPU hard tests with independent references and explicit ambiguity.

Generate private fixtures from three externally provided, text-free art assets.
Detector and known-ocr modes execute pinned models. Chain reuses their actual
RF-DETR outputs, recomputes production crops, and executes real adaptive OCR,
collection, edit planning, uniform cleanup and (only if complete) lettering.
No translation or Qwen generation is substituted by reference images.
"""
from argparse import ArgumentParser
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import sys
import time
import traceback

import numpy as np
from PIL import Image

if __package__:
    from . import hard_image_scenarios as F, stress_image_processing as T
else:
    import hard_image_scenarios as F
    import stress_image_processing as T
A,S=T.A,T.S


class Audit(A.Audit):
    def __init__(self,destination,mode,refs):
        if (destination/(mode+'-results.json')).exists():raise ValueError('Use a new destination or archive the previous mode report first')
        super().__init__(destination,mode)
        self.excluded={p['id'] for p in refs['pages'] if p.get('exclude_accuracy')}
        for path in (Path(__file__),Path(F.__file__),Path(T.__file__),Path(F.F.__file__)):
            self.report['source_sha256'][path.relative_to(S.ROOT).as_posix()]=F.digest(path)
        self.report.update(fixture_sha256=F.digest(destination/'fixtures/references.json'),
            scope='generated hard images only; independent visible references; identical annotation twins excluded; translation excluded; no actual Qwen',
            background_sha256={k:v['sha256'] for k,v in refs['backgrounds'].items()},
            accuracy_excluded_page_ids=sorted(self.excluded))
        self.flush()

    def case(self,ident,group,criterion,fn,real_model=False):
        started=time.monotonic();row={'id':ident,'group':group,'criterion':criterion,'real_model':real_model}
        excluded=any(ident.endswith(p) or ('-'+p+'-') in ident for p in self.excluded)
        try:
            met,evidence=fn();row.update(status='OBSERVATION' if excluded else 'PASS' if met else 'GAP',evidence=evidence,accuracy_excluded=excluded)
        except Exception as exc:row.update(status='ERROR',error=str(exc),exception=type(exc).__name__,traceback=traceback.format_exc())
        row['seconds']=round(time.monotonic()-started,3);self.report['results'].append(row);self.flush()
        print(json.dumps({k:row[k] for k in ('id','group','status','seconds')}),flush=True)


def cleanup_evidence(original,clean,plan,ink):
    # Measure new harm relative to the independently transformed clean artwork.
    before=np.max(np.abs(original-clean),axis=2);after=np.max(np.abs(plan['base']-clean),axis=2)
    changed=np.max(np.abs(plan['base']-original),axis=2)>1/255
    damage=int(((after-before>.035)&changed&~ink).sum())
    residual=float((after[ink]>.035).mean()) if ink.any() else 0.
    return {'new_artwork_damage_pixels_outside_reference_glyphs':damage,'residual_reference_fraction_in_partial_base':residual,
            'reference_role':'grading only; never an inpaint candidate','cleanup_mask_pixels':int(plan['cleanup_mask'].sum())}


def known_cleanup(args,row,get):
    import torch
    from scipy import ndimage
    E,I=get('page_edit'),get('inpaint_tiles');original,clean,masks=T.read_case(args,row)
    ink=np.logical_or.reduce(masks) if masks else np.zeros(original.shape[:2],bool)
    doc=E.build(T.document(row),*row['size'],source_mask=ink)
    source,grown=E.masks(doc,ink,ndimage.binary_dilation(ink,iterations=8) if ink.any() else ink)
    try:plan=I.make_plan(original,source,grown,regions_json=json.dumps(doc),recover_uniform_ink=True)
    except ValueError as exc:return False,{'state':'guarded_stop','refused':str(exc),'input_geometry':'exact generated geometry, not actual detector'}
    ev={'input_geometry':'exact generated geometry, not actual detector','qwen_generated':False,'report':plan['report'],**cleanup_evidence(original,clean,plan,ink)}
    if plan['tiles']:
        try:I.assemble(plan,[])
        except ValueError as exc:ev['missing_model_refused']=str(exc)
        else:return False,{**ev,'state':'invalid_missing_output_acceptance','completed':False}
        return ev['new_artwork_damage_pixels_outside_reference_glyphs']==0,{**ev,'state':'waiting_for_qwen','completed':False}
    output,report=I.assemble(plan,[])
    protected=plan['report'].get('protected_boxes_pixels',[])
    wanted=clean.copy()
    for a,b,c,d in protected:wanted[b:d,a:c]=original[b:d,a:c]
    error=np.max(np.abs(output-wanted),axis=2)
    ev.update(state='preserved' if protected else 'empty' if not masks else 'uniform_complete',completed=bool(masks) and not protected,
              final_reference_error_pixels=int((error>.035).sum()),outside_cleanup_exact=bool(np.array_equal(output[~plan['cleanup_mask']],original[~plan['cleanup_mask']])),assembly=json.loads(report))
    path=args.destination/'known-cleanup'/ (row['id']+'.png');path.parent.mkdir(exist_ok=True)
    Image.fromarray((output*255).round().astype('uint8')).save(path);ev['image']=str(path)
    return ev['final_reference_error_pixels']==0 and ev['outside_cleanup_exact'],ev


def contracts(audit,args,get,refs):
    for row in refs['pages']:
        audit.case('cleanup-'+row['id'],'known-geometry-cleanup','no new artwork damage; require missing model output or compare actual uniform result to independent clean reference',lambda r=row:known_cleanup(args,r,get))
        for multiplier in (1,2):
            audit.case('letter-'+row['id']+'-'+str(multiplier),'isolated-lettering',
                'complete fixed strings, zero positive-alpha collision, exact protection and outside-alpha pixels; known clean input explicitly supplied',
                lambda r=row,m=multiplier:T.lettering_case(args,r,get,'horizontal',m))


def detector(audit,args,get,refs):
    scoped=deepcopy(refs)
    for row in scoped['pages']:
        row['clipped_references']=[r for r in row['regions'] if r['clipped']]
        row['regions']=[r for r in row['regions'] if not r['clipped']]
    A.real_detector(audit,get,args,scoped)
    audit.report['criterion_scope']='nonclipped reference glyph retention/duplication and blank false crops; clipped-source edit guards evaluated separately in chain'


def load_hayai(audit,args,get):
    from tokenizers import Tokenizer
    H=get('adapters.hayai');folder=H.validate(args.models/'hayai');calls=[]
    class Measured(H.Backend):
        def _generate(self,image,options=None,max_patches=256):
            text,tokens=super()._generate(image,options,max_patches)
            calls.append({'rgb_sha256':hashlib.sha256(image.tobytes()).hexdigest(),'size':list(image.size),'text':text,'tokens':tokens,'patches':max_patches})
            return text,tokens
    backend=object.__new__(Measured);backend.model=H.load_model(folder,'cpu');backend.tokenizer=Tokenizer.from_file(str(folder/'tokenizer.json'))
    backend.model_name,backend.revision,backend.device=H.REPO,H.REV,'cpu';backend.input_size=H.preprocess_size
    audit.report.update(model=H.REPO,revision=H.REV,bundle_sha256_verified=True)
    return backend,calls


def known_ocr(audit,args,get,refs):
    import torch
    backend,calls=load_hayai(audit,args,get);M=get('models')
    for row in refs['ocr']:
        def case(row=row):
            path=args.destination/'fixtures'/row['image'];image=Image.open(path).convert('RGB');before=len(calls)
            try:
                text,raw,_=M.MangaOCRAdaptive().read(torch.from_numpy(np.asarray(image,np.float32).copy()/255)[None],backend,
                    quality_guard=True,retry_on_layout_failure=True,text_direction=row['direction'],failure_policy='preserve_review')
                score=S.text_score(row['expected'],text)
                return score['exact'],{'reference':row,'actual':text,'score':score,'diagnostic':json.loads(raw),'calls':calls[before:]}
            except ValueError as exc:return False,{'reference':row,'refused':str(exc),'calls':calls[before:]}
        audit.case('ocr-'+row['id'],'real-known-ocr','exact independent literal on a known crop; excludes detector localization',case,True)


def match_crop(page,masks,box):
    values=[{'id':r['id'],'coverage':S.coverage(m,[box]),'text':r['text'],'clipped':r['clipped']} for r,m in zip(page['regions'],masks)]
    touched=[r for r in values if (r['coverage'] or 0)>.05]
    complete=[r for r in touched if r['coverage']>=.98 and not r['clipped']]
    return {'touched':touched,'unique_full_reference':complete[0] if len(touched)==len(complete)==1 else None,
            'no_reference_glyph':not touched,'touches_clipped_source':any(r['clipped'] for r in touched)}


def chain_case(args,page,get,backend,calls):
    import torch
    from scipy import ndimage
    R,N,K,M,C,E,I,L,H=[get(n) for n in ('region_policy','nodes','mask_nodes','models','document','page_edit','inpaint_tiles','lettering.nodes','lettering.hybrid')]
    original,clean,masks=T.read_case(args,page);tensor=torch.from_numpy(original)[None]
    raw_path=args.destination/'detector-artifacts'/(page['id']+'.detections.json')
    found=json.loads(raw_path.read_text());layout=R.MangaDetectionRegionsResolved().convert(found,include_sfx=True)[0]
    mask=K.MangaDetectionMask().make(found,include_sfx=True)[0]
    crops,manifest,_,plans=N.MangaRegionCrops().crop(tensor,layout,allow_empty_page=True,refine_page_columns=True,auto_deskew=True,text_pixel_mask=mask,geometry_policy='preserve_review')
    doc=json.loads(manifest);texts=[];diagnostics=[];records=[];before=len(calls)
    prefix=args.destination/'chain-artifacts'/page['id'];prefix.mkdir(parents=True,exist_ok=True)
    for index,(crop,plan) in enumerate(zip(crops,plans)):
        text,diag,_=M.MangaOCRAdaptive().read(crop,backend,manifest_json=manifest,region_plan_json=plan,
            quality_guard=True,retry_on_layout_failure=True,failure_policy='preserve_review')
        texts.append(text);diagnostics.append(diag)
        if index<len(doc['regions']):
            region=doc['regions'][index];match=match_crop(page,masks,region['crop_bbox_pixels'])
            score=S.text_score(match['unique_full_reference']['text'],text) if match['unique_full_reference'] else None
            records.append({'id':region['id'],'actual':text,'diagnostic':json.loads(diag),'match':match,'score':score})
            Image.fromarray((crop[0].numpy()*255).round().astype('uint8')).save(prefix/(region['id']+'.png'))
    collected=json.loads(N.MangaCollectOCR().collect(texts,[manifest],diagnostics)[0]);A.save(prefix/'collected-ocr.json',collected)
    editable_ids={r['id'] for r in collected['regions']}
    for r in records:r['collected_for_edit']=r['id'] in editable_ids
    active=[r for r in records if r['collected_for_edit'] and r['actual'].strip()]
    false=[r['id'] for r in active if r['match']['no_reference_glyph']]
    clipped=[r['id'] for r in active if r['match']['touches_clipped_source']]
    wrong=[r['id'] for r in active if r['score'] and r['score']['content_cer_without_whitespace']!=0]
    recognized={r['match']['unique_full_reference']['id'] for r in active if r['score'] and r['score']['exact']}
    required={r['id'] for r in page['regions'] if not r['clipped']}
    ev={'scope':'actual RF prediction replay + actual adaptive OCR/collect/edit/cleanup; no reference inpaint injection',
        'raw_prediction_sha256':F.digest(raw_path),'reference':page,'records':records,'model_calls':calls[before:],
        'actual_ocr_crop_count':len(doc['regions']),'collected_regions':len(collected['regions']),
        'false_positive_editable_region_ids':false,'clipped_source_collected_region_ids':clipped,'wrong_source_accepted_region_ids':wrong,
        'strictly_recognized_reference_ids':sorted(recognized),'missing_strict_reference_ids':sorted(required-recognized),
        'needs_review':collected.get('needs_review',False),'actual_qwen_generated':False,'page_completed':False}
    unit,mapping=C.translation_units(collected)
    for row in unit['regions']:row['target']='다음 역에서 만나 함께 길을 확인합니다.'
    translated=C.merge_translations(collected,unit,mapping)
    safety=not false and not clipped and not wrong
    try:
        # Same footprint and 8 iterations as ComfyUI GrowMask(tapered_corners=True).
        grown=mask[0].numpy().copy();kernel=np.array([[0,1,0],[1,1,1],[0,1,0]])
        for _ in range(8):grown=ndimage.grey_dilation(grown,footprint=kernel)
        planned,src,cleanup,_,edit=E.MangaPageEditPlan().plan(tensor,N.encode(translated),mask,torch.from_numpy(grown)[None])
        plan=I.make_plan(original,src[0].numpy(),cleanup[0].numpy(),regions_json=planned,recover_uniform_ink=True)
        ink=np.logical_or.reduce(masks) if masks else np.zeros(original.shape[:2],bool)
        ev.update(edit_report=json.loads(edit),cleanup_report=plan['report'],**cleanup_evidence(original,clean,plan,ink))
        safety=safety and ev['new_artwork_damage_pixels_outside_reference_glyphs']==0
        Image.fromarray((plan['base']*255).round().astype('uint8')).save(prefix/'partial-cleanup-base.png')
        if plan['tiles']:
            try:I.assemble(plan,[])
            except ValueError as exc:ev['missing_qwen_refused']=str(exc)
            else:return False,{**ev,'state':'invalid_missing_qwen_acceptance'}
            return safety,{**ev,'state':'waiting_for_qwen','qwen_tiles':len(plan['tiles'])}
        output,_=I.assemble(plan,[]);ev['qwen_tiles']=0
        protected=plan['report'].get('protected_boxes_pixels',[]);wanted=clean.copy()
        for a,b,c,d in protected:wanted[b:d,a:c]=original[b:d,a:c]
        error=np.max(np.abs(output-wanted),axis=2)
        ev['complete_cleanup_reference_error_pixels']=int((error>.035).sum());safety=safety and ev['complete_cleanup_reference_error_pixels']==0
        prepared,support=L.MangaLetterPrepare().prepare(tensor,planned,text_pixel_mask=torch.from_numpy(plan['source_mask'].astype(np.float32))[None])
        typ,_,build=H.build_plan(original,output,support[0].numpy(),prepared,page_direction='auto',oriented_fit=True,
             bubble_failure_policy='preserve_review',detection_result=found,fit_policy='readable',line_breaks='reflow')
        layers=[];method=H.core.composite
        def observe(*a,**kw):
            result,alpha=method(*a,**kw);layers.append(alpha>0);return result,alpha
        H.core.composite=observe
        try:result,alpha,render=H.render_plan(typ)
        finally:H.core.composite=method
        r=json.loads(render);union=np.zeros(alpha.shape,bool);collisions=0
        for layer in layers:collisions+=int((union&layer).sum());union|=layer
        kept=all(not alpha[b:d,a:c].any() and np.array_equal(result[b:d,a:c],original[b:d,a:c]) for a,b,c,d in typ['protected_boxes_pixels'])
        outside=np.array_equal(result[alpha==0],typ['cleaned'][alpha==0])
        complete={row['id']:row['render']['text'] for row in r['regions']}=={row['id']:row['text'] for row in typ['regions']}
        safety=safety and collisions==0 and kept and outside and complete
        # Confirm known clipped source remained untouched in final real pixels.
        clip_unchanged=all(np.array_equal(result[m],original[m]) for row,m in zip(page['regions'],masks) if row['clipped'])
        safety=safety and clip_unchanged
        ev.update(state='actual_stages_finished',letter_build=json.loads(build),letter_render=r,rendered_regions=len(r['regions']),
            positive_alpha_collision_pixels=collisions,protected_pixels_exact=kept,outside_alpha_exact=bool(outside),
            all_fixed_strings_retained=complete,known_clipped_glyph_pixels_exact=clip_unchanged)
        Image.fromarray((result*255).round().astype('uint8')).save(prefix/'final-test-lettering.png')
        ev['page_completed']=bool(safety and required==recognized and not page.get('exclude_accuracy') and not any(row['clipped'] for row in page['regions'])
             and not collected.get('needs_review') and not r.get('needs_review') and len(r['regions'])==len(collected['regions']))
        return safety,ev
    except ValueError as exc:
        return safety,{**ev,'state':'guarded_stop','refused':str(exc),'diagnostic':getattr(exc,'diagnostic',None)}


def chain(audit,args,get,refs):
    detector_report=json.loads((args.destination/'detector-results.json').read_text())
    if not detector_report['completed'] or detector_report['counts'].get('ERROR'):raise ValueError('Actual detector mode must finish without harness errors first')
    if detector_report['source_sha256']!=audit.report['source_sha256'] or detector_report['fixture_sha256']!=audit.report['fixture_sha256']:raise ValueError('Detector evidence belongs to different source/fixtures')
    audit.report.update(detector_report_sha256=F.digest(args.destination/'detector-results.json'),fresh_detector_inference=False,
        detector_provenance='actual completed inference from detector mode; no scripted predictions')
    backend,calls=load_hayai(audit,args,get)
    for page in refs['pages']:
        audit.case('chain-'+page['id'],'real-detected-chain',
            'no false/incorrect/clipped editable OCR source or new artwork damage; final completion is a separate field; missing Qwen and guarded stops are not completion',
            lambda p=page:chain_case(args,p,get,backend,calls),True)


def main():
    p=ArgumentParser(description=__doc__);p.add_argument('--mode',required=True,choices=('generate','contracts','detector','known-ocr','chain'))
    p.add_argument('--destination',required=True,type=Path);p.add_argument('--assets',type=Path);p.add_argument('--models',type=Path)
    p.add_argument('--threads',type=int,choices=range(1,9),default=4)
    args=p.parse_args();args.destination=args.destination.resolve();args.include_sfx=True
    if args.destination==S.ROOT or S.ROOT in args.destination.parents:p.error('Generated inputs/results must stay outside Git')
    args.destination.mkdir(exist_ok=True,parents=True);path=args.destination/'fixtures/references.json'
    if args.mode=='generate':
        if args.assets is None:p.error('--assets required for generation')
        F.generate(args.destination/'fixtures',args.assets);print(path);return 0
    refs=json.loads(path.read_text());F.verify(refs,args.destination/'fixtures')
    if args.mode in ('detector','known-ocr','chain') and args.models is None:p.error('--models required')
    os.environ.update(CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    import torch
    torch.set_num_threads(args.threads);torch.set_num_interop_threads(1)
    get=A.modules(args.destination);audit=Audit(args.destination,args.mode,refs)
    audit.report['threads']=args.threads
    if args.mode=='contracts':contracts(audit,args,get,refs)
    elif args.mode=='detector':detector(audit,args,get,refs)
    elif args.mode=='known-ocr':known_ocr(audit,args,get,refs)
    else:chain(audit,args,get,refs)
    audit.report['completed']=True;audit.flush();return audit.exit_code()


if __name__=='__main__':raise SystemExit(main())
