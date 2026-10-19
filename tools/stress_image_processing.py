"""Additional generated-image CPU checks, with translation deliberately excluded.

Controlled cleanup has exact generator masks, not detector predictions. Isolated
lettering receives a declared known clean input, never alleged Qwen output.
Real-model modes use pinned weights and independent literal references.
"""
from argparse import ArgumentParser
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import hashlib
import json
import math
import os
import sys

import numpy as np
from PIL import Image

if __package__:
    from . import expanded_image_scenarios as F, simulate_page_failures as A
else:
    import expanded_image_scenarios as F
    import simulate_page_failures as A
S=F.S


def read_case(args,row):
    folder=args.destination/'fixtures'
    for name,key in (('image','sha256'),('clean','clean_sha256')):
        if hashlib.sha256((folder/row[name]).read_bytes()).hexdigest()!=row[key]:raise ValueError('Fixture bytes changed')
    original=np.asarray(Image.open(folder/row['image']).convert('RGB'),np.float32)/255
    clean=np.asarray(Image.open(folder/row['clean']).convert('RGB'),np.float32)/255
    with np.load(folder/(row['id']+'-truth.npz')) as source:
        masks=[source[r['id']] for r in row['regions']]
    return original,clean,masks


def document(row,multiplier=1):
    w,h=row['size'];regions=[];protected=[]
    for r in row['regions']:
        a,b,c,d=r['frame_pixels']
        phrase='다음 역에서 만나 함께 길을 확인합니다. '
        n=max(2,math.ceil(len(r['text'].replace('\n',''))*multiplier*.8))
        target=(phrase*math.ceil(n/len(phrase)))[:n].strip()
        if r.get('fixed_target'):target=r['fixed_target']*(2 if multiplier>1 else 1)
        regions.append({'id':r['id'],'kind':r['kind'],'source':r['text'],'target':target,
                        'bbox':[a*1000/w,b*1000/h,c*1000/w,d*1000/h],
                        'edit_bbox_pixels':[a,b,c,d]})
        if r['clipped']:protected.append([a,b,c,d])
    data={'image_width':w,'image_height':h,'regions':regions}
    if protected:data.update(needs_review=True,boundary_review={'schema':1,'reason':'known_clipped_test_source','protected_boxes_pixels':protected})
    return data


def cleanup_case(args,row,get):
    from scipy import ndimage
    import torch
    E,I=get('page_edit'),get('inpaint_tiles')
    original,reference,masks=read_case(args,row)
    ink=np.logical_or.reduce(masks) if masks else np.zeros(original.shape[:2],bool)
    data=E.build(document(row),*row['size'],source_mask=ink)
    source,grown=E.masks(data,ink,ndimage.binary_dilation(ink,iterations=8) if ink.any() else ink)
    plan=I.make_plan(original,source,grown,regions_json=json.dumps(data),recover_uniform_ink=True)
    evidence={'declared_input':'exact generated source masks, not real detection','model_generated':False,
              'report':plan['report'],'reference_background_used_only_for_grading':True}
    if plan['tiles']:
        try:I.assemble(plan,[])
        except ValueError as exc:evidence['missing_tiles_refused']=str(exc)
        else:return False,{**evidence,'missing_tiles_refused':False}
        return row['cleanup']=='model',{**evidence,'whole_page_cleanup_completed':False}
    result,report=I.assemble(plan,[],blend_width=8)
    protected=plan['report'].get('protected_boxes_pixels',[])
    wanted=reference.copy()
    for a,b,c,d in protected:wanted[b:d,a:c]=original[b:d,a:c]
    delta=np.max(np.abs(result-wanted),axis=2)
    residual=float((delta[ink]>.035).mean()) if ink.any() else 0
    art_error=int(((delta>.035)&~ink).sum())
    outside=bool(np.array_equal(result[~plan['cleanup_mask']],original[~plan['cleanup_mask']]))
    met=residual<=.01 and art_error==0 and outside
    path=args.destination/'cleanup-artifacts'/(row['id']+'.png');path.parent.mkdir(exist_ok=True)
    Image.fromarray((result*255).round().astype('uint8')).save(path)
    return met,{**evidence,'whole_page_cleanup_completed':not bool(protected),'empty_no_op':not bool(masks),
                'preservation_is_not_removal_success':bool(protected),'residual_reference_ink_fraction':residual,
                'background_error_pixels':art_error,'outside_cleanup_unchanged':outside,'assembly':json.loads(report),'image':str(path)}


def lettering_case(args,row,get,direction,multiplier,oversized=False):
    import torch
    E,L,H=[get(n) for n in ('page_edit','lettering.nodes','lettering.hybrid')]
    original,clean,masks=read_case(args,row)
    ink=np.logical_or.reduce(masks) if masks else np.zeros(original.shape[:2],bool)
    doc=document(row,multiplier)
    if oversized:
        for r in doc['regions']:r['target']='아주 긴 시험 문장을 여기에 계속 배치합니다. '*25
    data=E.build(doc,*row['size'],source_mask=ink)
    prepared,support=L.MangaLetterPrepare().prepare(torch.from_numpy(original)[None],json.dumps(data),
                                                  text_pixel_mask=torch.from_numpy(ink.astype(np.float32))[None])
    options={r['id']:{'rotation':r['source_angle']} for r in row['regions'] if r['source_angle']}
    scope={'declared_input':'isolated lettering with exact generated clean reference; no cleanup model called',
           'direction':direction,'target_multiplier':multiplier,'oversized_control':oversized}
    try:
        plan,_,build=H.build_plan(original,clean,support[0].numpy(),prepared,page_direction=direction,
            fit_policy='readable',line_breaks='reflow',oriented_fit=True,region_options_json=json.dumps(options))
        composites=[];method=H.core.composite
        def observe(*a,**k):
            result,alpha=method(*a,**k);composites.append(alpha>0);return result,alpha
        H.core.composite=observe
        try:result,alpha,raw=H.render_plan(plan)
        finally:H.core.composite=method
    except ValueError as exc:
        recognized=isinstance(exc,H.LetteringFitError)
        return oversized and recognized,{**scope,'refused':str(exc),'diagnostic':getattr(exc,'diagnostic',None),
             'policy_or_evidence_abstention':not recognized}
    report=json.loads(raw);union=np.zeros(alpha.shape,bool);collision=0
    for pixels in composites:collision+=int((union&pixels).sum());union|=pixels
    protected=plan['protected_boxes_pixels']
    kept=all(not alpha[b:d,a:c].any() and np.array_equal(result[b:d,a:c],original[b:d,a:c]) for a,b,c,d in protected)
    outside=np.array_equal(result[alpha==0],plan['cleaned'][alpha==0])
    expected={r['id']:r['text'] for r in plan['regions']}
    complete={r['id']:r['render']['text'] for r in report['regions']}==expected
    should_render=sum(not r['clipped'] for r in row['regions'])
    count_ok=len(report['regions'])==should_render
    met=not oversized and collision==0 and kept and outside and complete and count_ok
    path=args.destination/'lettering-artifacts'/(row['id']+'-'+direction+'-'+str(multiplier)+'.png');path.parent.mkdir(exist_ok=True)
    Image.fromarray((result*255).round().astype('uint8')).save(path)
    return met,{**scope,'glyph_collision_pixels':collision,'protected_pixels_exact':kept,'outside_alpha_exact':bool(outside),
                'all_strings_retained':complete,'requested_regions':len(row['regions']),'expected_rendered_regions':should_render,
                'actual_rendered_regions':len(report['regions']),'preservation_is_not_translated_success':bool(protected),
                'build_report':json.loads(build),'render_report':report,'image':str(path)}


def pixel_cases(audit,args,get,refs):
    for row in refs['pages']:
        def clean(row=row):
            try:return cleanup_case(args,row,get)
            except ValueError as exc:return False,{'refused':str(exc),'scope':'actual cleanup on exact generated geometry'}
        audit.case('cleanup-'+row['id'],'controlled-cleanup',
                   'remove known flat-background glyphs without artwork loss, or require missing model output on nonuniform background',clean)
        for direction,multiplier in (('horizontal',1),('horizontal',1.6),('vertical_rtl',1)):
            audit.case('letter-'+row['id']+'-'+direction+'-'+str(multiplier),'isolated-lettering',
                'retain complete fixed strings and separate positive alpha; preserve clipped source and artwork outside alpha',
                lambda r=row,d=direction,m=multiplier:lettering_case(args,r,get,d,m))
    small=next(r for r in refs['pages'] if r['id']=='mixed-punctuation')
    audit.case('letter-impossible-length','lettering-refusal','reject an oversized target without clipping',
               lambda:lettering_case(args,small,get,'horizontal',1,True))


def input_cases(audit,args,get):
    P=get('tools.run_project');folder=args.destination/'input-artifacts';folder.mkdir(exist_ok=True)
    def normalize(path):
        data=path.read_bytes();value,size,blank=P.normalise_image(path,hashlib.sha256(data).hexdigest(),64*1024*1024)
        return Image.open(BytesIO(value)).convert('RGB'),size,blank
    for kind in ('rgba','palette-alpha','exif-rotation','high-bit-depth','animation','corrupt','changed-after-scan'):
        def case(kind=kind):
            path=folder/(kind+'.png');expected_error=kind in ('high-bit-depth','animation','corrupt','changed-after-scan')
            expected=None
            if kind=='rgba':
                original=Image.new('RGBA',(91,67),(0,0,0,0));original.putpixel((25,24),(100,20,40,128));original.save(path)
                expected=Image.alpha_composite(Image.new('RGBA',original.size,'white'),original).convert('RGB')
            elif kind=='palette-alpha':
                original=Image.new('P',(91,67),0);original.putpalette([0,0,0,255,0,0]+[0]*762);original.putpixel((25,24),1)
                original.save(path,transparency=0)
                expected=Image.new('RGB',original.size,'white');expected.putpixel((25,24),(255,0,0))
            elif kind=='exif-rotation':
                original=Image.new('RGB',(91,67),'white');original.putpixel((7,11),(0,0,0))
                exif=original.getexif();exif[274]=6;original.save(path,exif=exif)
                expected=original.transpose(Image.Transpose.ROTATE_270)
            elif kind=='high-bit-depth':Image.new('I;16',(91,67),1024).save(path)
            elif kind=='animation':
                path=folder/'animation.gif';Image.new('RGB',(91,67),'white').save(path,save_all=True,append_images=[Image.new('RGB',(91,67),'black')])
            elif kind=='corrupt':path.write_bytes(b'broken image')
            else:Image.new('RGB',(91,67),'white').save(path)
            try:
                if kind=='changed-after-scan':P.normalise_image(path,'0'*64,64*1024*1024);raise AssertionError('Changed source accepted')
                picture,size,blank=normalize(path)
            except P.InputError as exc:return expected_error,{'kind':kind,'refused':str(exc)}
            return not expected_error and np.array_equal(np.asarray(picture),np.asarray(expected)),{'kind':kind,'size':size,'blank':blank,'white_alpha_composite_exact':kind!='exif-rotation'}
        audit.case('input-'+kind,'input-normalization','canonicalize alpha/EXIF, reject unsupported or changed inputs before inference',case)


def tile_cases(audit,args,get,refs):
    from scipy import ndimage
    I=get('inpaint_tiles');row=next(r for r in refs['pages'] if r['id']=='gradient-caption')
    original,reference,masks=read_case(args,row);ink=np.logical_or.reduce(masks)
    for kind in ('known-clean','unchanged','partial-source','wrong-color','missing','extra','wrong-size','nan','nonowned-corruption'):
        def case(kind=kind):
            plan=I.make_plan(original,ink,ndimage.binary_dilation(ink,iterations=8),uniform_fill=False)
            values=[]
            for t in plan['tiles']:
                a,b,c,d=t['crop'];value=reference[b:d,a:c].copy()
                if kind=='unchanged':value=original[b:d,a:c].copy()
                elif kind=='partial-source':value[:,:value.shape[1]//2]=original[b:d,a:c][:,:value.shape[1]//2]
                elif kind=='wrong-color':value[:]=[.9,.1,.4]
                elif kind=='wrong-size':value=value[:-1]
                elif kind=='nan':value[0,0,0]=np.nan
                elif kind=='nonowned-corruption':value[~t['mask']]=[1,0,0]
                values.append(value)
            if kind=='missing':values=[]
            elif kind=='extra':values.append(values[0].copy())
            should_accept=kind in ('known-clean','nonowned-corruption')
            try:result,raw=I.assemble(plan,values,strict_cleanup=True,blend_width=8)
            except ValueError as exc:return not should_accept,{'scripted_model_output':True,'actual_qwen':False,'kind':kind,'refused':str(exc)}
            delta=np.max(np.abs(result-reference),axis=2)
            good=not np.any(delta>.035)
            outside=np.array_equal(result[~plan['cleanup_mask']],original[~plan['cleanup_mask']])
            return should_accept and good and outside,{'scripted_model_output':True,'actual_qwen':False,'kind':kind,
                'accepted_by_runtime':True,'independent_reference_error_pixels':int((delta>.035).sum()),
                'outside_mask_exact':bool(outside),'runtime_guard_scope':'unchanged-ink heuristic; cannot certify clean background','report':json.loads(raw)}
        audit.case('tile-'+kind,'model-output-injection','accept correct owned pixels; reject invalid, residual-text or corrupt-background candidates',case)


def real_detector(audit,args,get,refs):
    # Reuse the exact same pinned loader and production postprocessing as the
    # previous audit, with these newly generated independent references.
    A.real_detector(audit,get,args,refs)


def real_ocr(audit,args,get,refs):
    from tokenizers import Tokenizer
    import torch
    H,M=get('adapters.hayai'),get('models');folder=H.validate(args.models/'hayai')
    calls=[]
    class Measured(H.Backend):
        def _generate(self,image,options=None,max_patches=256):
            text,tokens=super()._generate(image,options,max_patches)
            calls.append({'rgb_sha256':hashlib.sha256(image.tobytes()).hexdigest(),'size':list(image.size),'text':text,'tokens':tokens,'patches':max_patches})
            return text,tokens
    backend=object.__new__(Measured);backend.model=H.load_model(folder,'cpu');backend.tokenizer=Tokenizer.from_file(str(folder/'tokenizer.json'))
    backend.model_name,backend.revision,backend.device=H.REPO,H.REV,'cpu';backend.input_size=H.preprocess_size
    audit.report.update(model=H.REPO,revision=H.REV,bundle_sha256_verified=True)
    for row in refs['ocr']:
        def case(row=row):
            path=args.destination/'fixtures'/row['image'];assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
            image=Image.open(path).convert('RGB');before=len(calls)
            try:
                text,raw,_=M.MangaOCRAdaptive().read(torch.from_numpy(np.asarray(image,np.float32).copy()/255)[None],backend,
                    quality_guard=True,retry_on_layout_failure=True,text_direction=row['direction'])
                score=S.text_score(row['expected'],text)
                return score['exact'],{'reference':row,'actual':text,'score':score,'diagnostic':json.loads(raw),'calls':calls[before:]}
            except ValueError as exc:return False,{'reference':row,'refused':str(exc),'calls':calls[before:]}
        audit.case('ocr-'+row['id'],'real-ocr','exact generated reference, not mere heuristic acceptance',case,True)


def main():
    p=ArgumentParser(description=__doc__);p.add_argument('--mode',required=True,choices=('generate','contracts','detector','ocr'))
    p.add_argument('--destination',required=True,type=Path);p.add_argument('--models',type=Path)
    p.add_argument('--threads',type=int,choices=range(1,9),default=4);p.add_argument('--include-sfx',action='store_true')
    args=p.parse_args();args.destination=args.destination.resolve()
    if args.destination==S.ROOT or S.ROOT in args.destination.parents:p.error('Keep generated evidence outside Git')
    if args.mode in ('detector','ocr') and args.models is None:p.error('--models required')
    args.destination.mkdir(parents=True,exist_ok=True);reference_path=args.destination/'fixtures/references.json'
    if args.mode=='generate' or not reference_path.exists():refs=F.generate(args.destination/'fixtures')
    else:refs=json.loads(reference_path.read_text())
    if (refs['generator_sha256']!=hashlib.sha256(Path(F.__file__).read_bytes()).hexdigest() or
        refs['base_generator_sha256']!=hashlib.sha256(Path(S.__file__).read_bytes()).hexdigest()):raise ValueError('Generator changed; regenerate references')
    if args.mode=='generate':print(reference_path);return 0
    os.environ.update(CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    import torch
    torch.set_num_threads(args.threads);torch.set_num_interop_threads(1)
    get=A.modules(args.destination);audit=A.Audit(args.destination,args.mode)
    for path in (Path(__file__),Path(F.__file__)):
        audit.report['source_sha256'][path.relative_to(S.ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    audit.report.update(threads=args.threads,scope='additional generated fixtures; translation excluded; no real Qwen generation',fixture_generator=refs['generator_sha256'])
    if args.mode=='contracts':pixel_cases(audit,args,get,refs);input_cases(audit,args,get);tile_cases(audit,args,get,refs)
    elif args.mode=='detector':real_detector(audit,args,get,refs)
    else:real_ocr(audit,args,get,refs)
    audit.report['completed']=True;audit.flush();return audit.exit_code()


if __name__=='__main__':raise SystemExit(main())
