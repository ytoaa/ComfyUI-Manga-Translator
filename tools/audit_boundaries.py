"""CPU acceptance probes for workflow boundaries; failures are reported, never patched.

Model/queue doubles test orchestration contracts. --actual-ocr separately runs
pinned local engines; it never treats a model's normal termination as accuracy.
Outputs are disposable validation evidence, not input/output samples for Git.
"""
from argparse import ArgumentParser
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import types
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('boundary_acceptance',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from boundary_acceptance import document as D,stage_cache as K,translation_context as T,ocr_engines as E
from boundary_acceptance.lettering import frame,core
from tests.test_document_stages import row
from tests.test_project_runner import P,FakeComfy,make_page,graph
from tests.test_canvas_execution import C,CanvasClient
import numpy as np
import torch
from PIL import Image


class Failed(AssertionError):
    def __init__(self,message,evidence=None):super().__init__(message);self.evidence=evidence or {}


def require(condition,message,evidence=None):
    if not condition:raise Failed(message,evidence)


def raises(kind,fn):
    try:fn()
    except kind as exc:return {'exception':type(exc).__name__,'message':str(exc)}
    raise Failed('Expected '+str(kind)+' but operation was accepted')


@dataclass
class Audit:
    destination:Path
    def __post_init__(self):
        self.results=[];self.destination.mkdir(parents=True,exist_ok=True)
        self.work=self.destination/('work-'+uuid.uuid4().hex[:12]);self.work.mkdir()
        names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        self.sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names
                      if Path(name).suffix in ('.py','.js','.cjs','.json') and (ROOT/name).is_file()}
        self.sources['tools/audit_boundaries.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.dirty=bool(subprocess.run(['git','diff','--quiet','HEAD'],cwd=ROOT).returncode)
    def case(self,ident,group,expected,fn,classification='contract'):
        start=time.monotonic();entry={'id':ident,'group':group,'expected':expected,'classification':classification}
        try:entry.update(status='OBSERVED' if classification=='actual_model' else 'PASS',evidence=fn() or {})
        except Failed as exc:entry.update(status='FAIL',issue=str(exc),evidence=exc.evidence)
        except Exception as exc:entry.update(status='ERROR',issue=str(exc),exception=type(exc).__name__)
        entry['seconds']=round(time.monotonic()-start,3);self.results.append(entry)
        print(entry['status'],ident,entry.get('issue',''),flush=True)
        self.save()
    def save(self):
        counts={status:sum(r['status']==status for r in self.results) for status in ('PASS','FAIL','ERROR','OBSERVED')}
        report={'schema':1,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'working_tree_modified':self.dirty,'source_sha256':self.sources,'torch_version':torch.__version__,
                'runtime_version':C.VERSION,'counts':counts,'scope':'CPU contracts; synthetic queue/model histories unless marked actual_model',
                'results':self.results}
        (self.destination/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        lines=['# CPU boundary audit','',f"Source: {report['source_commit']}",f'Counts: {counts}',
               '', 'Actual model inference is explicitly distinguished from model/queue doubles.','',
               '| Case | Status | Expected | Observed |','| --- | --- | --- |']
        for r in self.results:lines.append('| '+r['id']+' | '+r['status']+' | '+r['expected'].replace('|','/')+' | '+r.get('issue','Contract met; see JSON evidence').replace('|','/').replace('\n',' ')+' |')
        (self.destination/'report.md').write_text('\n'.join(lines)+'\n')


CONTEXT={'review_identity':{'page_key':'project/a/page/1','input_sha256':'a'*64}}


def review_document(data,edits,context=CONTEXT):
    # Also usable against the v0.7.0 baseline, whose missing owner input is
    # precisely one of the acceptance failures this tool must expose.
    node=D.MangaReviewDocument();args=[json.dumps(data),'target',edits]
    if hasattr(D,'review_revision'):args.append(json.dumps(context))
    return node.review(*args)


def review(data,patch):
    scoped=hasattr(D,'review_revision')
    revision=D.review_revision(data,CONTEXT['review_identity'],'target') if scoped else D.digest(data)
    edits=json.dumps({'pages':{revision:patch},**({'identities':{revision:CONTEXT['review_identity']['page_key']}} if scoped else {})},ensure_ascii=False)
    output=review_document(data,edits)
    return json.loads(output['result'][0]),edits


def basic_cases(a):
    data={'regions':[row()]}
    def duplicate():
        out,edits=review(data,{'r1':{'target':'별도 페이지 교정'}})
        require(out['regions'][0]['target']=='별도 페이지 교정','First page correction was not applied')
        other=review_document(deepcopy(data),edits,{'review_identity':{**CONTEXT['review_identity'],'page_key':'project/a/page/2'}})
        observed=json.loads(other['result'][0])['regions'][0]['target']
        require(observed==row()['target'],'Identical OCR documents share edits without a project/page namespace',{'pageA_target':out['regions'][0]['target'],'pageB_target':observed})
    a.case('review-identical-pages','review','Different pages may reuse inference but must not share human edits implicitly',duplicate)
    def diagnostic():
        base=deepcopy(data);base['regions'][0]['ocr_diagnostics']={'patch_budget':256}
        _,edits=review(base,{'r1':{'target':'교정문'}});changed=deepcopy(base);changed['regions'][0]['ocr_diagnostics']['patch_budget']=512
        out=review_document(changed,edits);doc=json.loads(out['result'][0]);report=json.loads(out['result'][1])
        require(doc['regions'][0]['target']=='교정문' or report.get('stale_edits') or report.get('conflicts'),
                'Diagnostic-only change silently leaves a stored human correction unapplied',{'target':doc['regions'][0]['target'],'report':report})
    a.case('review-diagnostic-only-change','review','Keep correction or explicitly report an edit conflict',diagnostic)
    def changed_content():
        _,edits=review(data,{'r1':{'target':'교정문'}});changed=deepcopy(data);changed['regions'][0]['source']='다른 원문'
        out=json.loads(review_document(changed,edits)['result'][0])
        require(out['regions'][0]['target']==row()['target'],'Old edit applied to different source');return {'old_edit_not_applied':True}
    a.case('review-different-content','review','Do not apply old edits to changed source',changed_content)
    def authored():
        approved=D.apply_edits(data,{'r1':{'target':row()['target']}},'target')
        corrected=D.apply_edits(approved,{'r1':{'source':'訂正'}},'source')
        require('target' not in corrected['regions'][0] and 'target' not in corrected['regions'][0]['authored'],'Approval leaked into corrected source')
        return {'translation_invalidated':True,'approval_invalidated':True}
    a.case('review-source-edit-invalidates-approval','review','Source edits invalidate translation and approval',authored)
    for count in (256,257,300):
        def limit(count=count):
            edits=json.dumps({'pages':{str(i):{} for i in range(count)}})
            if count<=256:
                D.MangaReviewDocument().review(json.dumps(data),'target',edits);return {'accepted_revisions':count}
            return raises(ValueError,lambda:D.MangaReviewDocument().review(json.dumps(data),'target',edits))
        a.case(f'review-revision-limit-{count}','budget','Accept up to 256 revisions; report configured limit above it',limit,'declared_limit')
    def long_blocks():
        source=deepcopy(data);units,mapping=D.translation_units(source)
        for r in units['regions']:r['target']='가'*1100
        translated=D.merge_translations(source,units,mapping)
        # These individual blocks satisfy review_text; they should reach prepare independently.
        from boundary_acceptance.lettering.nodes import MangaLetterPrepare
        image=torch.ones(1,240,320,3)
        try:MangaLetterPrepare().prepare(image,json.dumps(translated))
        except ValueError as exc:raise Failed('Allowed paragraph blocks exceed the parent text limit before paragraph expansion',{'block_characters':[len(b['target']) for b in translated['regions'][0]['blocks']],'parent_characters':len(translated['regions'][0]['target']),'exception':str(exc)})
        return {'parent_characters':len(translated['regions'][0]['target'])}
    a.case('paragraph-total-length','typography','Paragraph-level accepted text has consistent downstream limits',long_blocks)
    for change in ({'source':'different'},{'bbox_local':[0,0,1,1]},{'coordinate_frame':'rectified_crop_pixels'}):
        field=next(iter(change))
        def invalid(change=change):
            blocks=deepcopy(row()['blocks']);blocks[0].update(change)
            return raises(ValueError,lambda:D.apply_edits(data,{'r1':{'blocks':blocks}},'target'))
        a.case('target-cannot-change-'+field,'review','Target review cannot alter source/geometry',invalid)


def cache_cases(a):
    folder=a.work/'cache-probes';image=torch.rand(1,8,12,3)
    g={'1':{'class_type':'MangaCleanupCheckpoint','inputs':{}}};node=K.MangaCleanupCheckpoint()
    with patch.object(K,'root',lambda:folder):
        def corruption():
            key=K.identity(image,None,None,'image');K.write(key,'image',image);require(torch.equal(K.read(key,'image'),image),'Image cache changed pixels')
            (folder/key[:2]/key/'value.bin').write_bytes(b'partial');require(K.read(key,'image') is None,'Corrupt payload accepted');return {'lossless':True,'corrupt_payload_missed':True}
        a.case('cache-lossless-and-corrupt','cache','Preserve float pixels and reject corrupt payload',corruption)
        def vanished():
            node.checkpoint(image,image,prompt=g,unique_id='1');require(node.check_lazy_status(image,prompt=g,unique_id='1')==[],'Cache did not hit')
            key=node._key(image,g,'1','',None);(folder/key[:2]/key/'value.bin').unlink()
            try:node.checkpoint(image,prompt=g,unique_id='1')
            except ValueError as exc:raise Failed('Cache removal between lazy probe and use aborts the checkpoint',{'exception':str(exc)})
        a.case('cache-evicted-after-probe','cache','Recover boundedly if a previously probed cache disappears',vanished)
        def disk_full():
            with patch.object(K,'write',side_effect=OSError(28,'No space left on device')):
                out=node.checkpoint(image,image,prompt=g,unique_id='1',cache_policy='refresh')
            require(torch.equal(out['result'][0],image),'Cache persistence failure changed successful computation');return {'computation_preserved':True}
        a.case('cache-disk-full','cache','Optional persistence failure does not discard a valid computed image',disk_full)
    def changed_weight():
        path=a.work/'mutable-model.bin';path.write_bytes(b'old');folders=types.SimpleNamespace(get_full_path=lambda *args:str(path))
        graph_value={'1':{'class_type':'UNETLoader','inputs':{'unet_name':'same.bin'}},'2':{'class_type':'MangaCleanupCheckpoint','inputs':{'value':['1',0]}}}
        with patch.dict(sys.modules,{'folder_paths':folders}):
            before=K.identity(image,graph_value,'2','image');path.write_bytes(b'new');after=K.identity(image,graph_value,'2','image')
        require(before!=after,'Mutable model filename reused previous cache');return {'key_changed':True}
    a.case('same-model-name-new-weights','cache','Changed local model bytes invalidate reuse',changed_weight)
    def huge():
        virtual=torch.as_strided(torch.ones(3),size=(1,8193,8192,3),stride=(0,0,0,1))
        return raises(ValueError,lambda:K.identity(virtual,None,None,'image'))
    a.case('source-over-64mp','budget','Reject over-budget image before materializing its bytes',huge,'declared_limit')


def seed_book(root,count=3):
    client=CanvasClient(root);inputs=client.input_root/'book';inputs.mkdir()
    for i in range(count):make_page(inputs/f'{i+1}.png')
    folder=client.output_root/'manga_translator/workflow_projects/book';fake=FakeComfy();fake.base=client.base
    project=P.Project(inputs,folder,graph(),fake);report=project.run()
    require(report['counts']=={'completed':count},'Seed project was not completed',report)
    return C.CanvasExecution(),client,inputs,folder


def finish_native(client,pid,result,g):
    binding=P.workflow_bindings(g);ref=result['image_reference'];image=Image.open(client._path(ref)).convert('RGB');w,h=image.size
    source={'image_width':w,'image_height':h,'regions':[{'id':'r1','kind':'text','bbox':[10,10,900,900],'source':'SAMPLE'}]}
    target=deepcopy(source);target['regions'][0]['target']='번역문';outputs={}
    for kind,data,basename in (('source',source,'ocr'),('target',target,'translation')):
        prefix=result['prefixes'][1 if kind=='source' else 2];parent=prefix.rsplit('/',1)[0]
        descriptor={'filename':basename+'_00001.json','subfolder':parent,'type':'output'}
        path=client.output_root/parent/descriptor['filename'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data))
        outputs[binding[kind]]={'text':[json.dumps(data)],'manga_review_files':[descriptor]}
        outputs[binding[kind+'_preview']]={'text':[json.dumps(data)]}
    parent=result['prefixes'][0].rsplit('/',1)[0];descriptor={'filename':'result_00001_.png','subfolder':parent,'type':'output'}
    image.save(client.output_root/parent/descriptor['filename']);outputs[binding['final']]={'images':[descriptor]}
    client.server.prompt_queue.histories[pid]={'outputs':outputs,'status':{'status_str':'success','completed':True,'messages':[]}}


def project_cases(a):
    def resume():
        engine,client,inputs,folder=seed_book(a.work/'resume')
        changed=graph();next(n for n in changed.values() if n['class_type']=='MangaLetterPlan')['inputs']['default_font']='NanumGothic-Regular.ttf'
        source=P.workflow_bindings(changed)['load'];pid=str(uuid.uuid4());first=engine.begin(inputs,folder,changed,client,pid,source,'시작·재개')
        require(first['ticket']['total']==3,'Settings change did not initially select every page')
        finish_native(client,pid,first,changed);engine.pause(folder,first['ticket']['run_id']);engine.resolve(folder,first['ticket']['run_id'],pid,client)
        resumed=engine.begin(inputs,folder,changed,client,str(uuid.uuid4()),source,'시작·재개')
        evidence={'selected_page':(resumed.get('ticket') or {}).get('relative_path'),'counts':resumed['report']['counts'],'pages_selected':resumed['report'].get('pages_selected')}
        require(resumed.get('ticket') and resumed['ticket']['relative_path']=='2.png','Resume skips completed pages still carrying the old workflow revision',evidence)
        return evidence
    a.case('settings-change-pause-resume','project','Resume remaining old-revision pages after partial settings migration',resume)
    def two_tabs():
        root=a.work/'two-tabs';client=CanvasClient(root);inputs=client.input_root/'book';inputs.mkdir();make_page(inputs/'1.png')
        folder=client.output_root/'manga_translator/workflow_projects/book';engine=C.CanvasExecution();g=graph();source=P.workflow_bindings(g)['load'];pid=str(uuid.uuid4())
        first=engine.begin(inputs,folder,g,client,pid,source,'시작·재개');run_id=first['ticket']['run_id']
        state=P.read_json(next(folder.glob('pages/*/attempt-*/state.json')))
        client.server.prompt_queue.running=[[0,pid,g,{'manga_project':state['submission_token']},[]]]
        second=engine.begin(inputs,folder,g,client,str(uuid.uuid4()),source,'시작·재개');saved=P.read_json(folder/'canvas_run.json')
        require(saved['run_id']==run_id,'Blocked second tab replaces the first active run identity',{'first_run_id':run_id,'saved_run_id':saved['run_id'],'second_status':second['report']['status'],'page_attempts':len(list(folder.glob('pages/*/attempt-*/state.json')))})
        return {'original_run_preserved':True}
    a.case('two-tabs-same-project','project','Reject another owner without replacing the active run',two_tabs)
    def inventory():
        folder=a.work/'inventory';folder.mkdir()
        for i in range(300):make_page(folder/f'{i+1}.png',size=(8,8),blank=True)
        for name in ('a/1.png','b/1.png'):make_page(folder/name,size=(8,8),blank=True)
        pages=P.scan_images(folder);paths=[p['relative_path'] for p in pages]
        require(len(pages)==302 and paths.index('2.png')<paths.index('10.png'),'Inventory dropped duplicates or used lexical order')
        return {'pages':len(pages),'unique_page_ids':len({p['id'] for p in pages}),'scope':'inventory, not 302 model executions'}
    a.case('folder-302-pages-duplicate-names','project','Keep duplicate basenames and natural ordering at book scale',inventory)
    def one_edit_scope():
        before=graph();after=deepcopy(before);next(n for n in after.values() if n['class_type']=='MangaReviewDocument' and n['inputs']['stage']=='target')['inputs']['edits_json']='{"pages":{"one-page":{"r1":{"target":"교정"}}}}'
        require(P.workflow_fingerprint(before)==P.workflow_fingerprint(after),'Editing one page changes the whole-project processing fingerprint',{'all_pages_reselected_on_settings_change':True})
    a.case('one-page-edit-project-selection','project','A local human edit should not select every completed page',one_edit_scope)
    def missing_artifact():
        engine,client,inputs,folder=seed_book(a.work/'missing-artifact',1);path=next(folder.glob('pages/*/attempt-*/result.png'));path.unlink()
        g=graph();out=engine.begin(inputs,folder,g,client,str(uuid.uuid4()),P.workflow_bindings(g)['load'],'시작·재개')
        require(out['report']['counts'].get('completed',0)==0,'Missing final artifact stayed completed',out['report']);return {'counts':out['report']['counts']}
    a.case('completed-result-deleted','project','Missing result is not silently counted as completed',missing_artifact)
    for mode in ('oom','disk_full','missing_final','bad_json','interrupted'):
        def failure(mode=mode):
            root=a.work/('failure-'+mode);make_page(root/'input/1.png');p=P.Project(root/'input',root/'project',graph(),FakeComfy([mode]))
            try:report=p.run()
            except P.ProjectError:report=p._summary('paused')
            require(report['counts'].get('completed',0)==0,'Failed/partial output was certified completed',report)
            return {'counts':report['counts'],'halted':report.get('halted')}
        a.case('execution-'+mode,'project','Never certify partial or interrupted execution as completed',failure)


def geometry_cases(a):
    from tests.test_hybrid_lettering import fixture,run
    original=np.ones((100,270,3),np.float32);original[20:50,20:240]=0
    style,_=core.analyze_style(original,np.ones_like(original),(original[:,:,0]==0).astype(float))
    for angle in (-90,-25,-.1,0,.1,25,90):
        def rotated(angle=angle):
            theta=np.radians(angle);u=np.array([np.cos(theta),-np.sin(theta)]);v=np.array([np.sin(theta),np.cos(theta)]);p=np.array([300,300]);quad=[q.tolist() for q in (p,p+u*260,p+u*260+v*90,p+v*90)]
            bounds,rgb,alpha,report=frame.render('가로 ABC 12',style,'NanumGothic-Bold.ttf',quad,(700,700,3),min_font=22,max_font=22,padding=4)
            require(alpha.max()>.9 and report['font_size']==22 and not alpha[0].any() and not alpha[-1].any(),'Glyph disappeared or was clipped')
            return {'angle':angle,'bounds':bounds,'font_size':report['font_size'],'local_size':report['local_size']}
        a.case('local-frame-angle-'+str(angle),'typography','Real font fits in rotated local coordinates without page loss',rotated,'real_font')
    for direction in ('horizontal','vertical_rtl','vertical_ltr'):
        def mixed(direction=direction):
            _,result,alpha,report,_,_=run(fixture('한글 ABC 12!?',width=480,height=360,font_size=40),direction=direction,fit_policy='readable',min_scale=.3,min_font=8)
            require(alpha.max()>.9 and report['regions'][0]['render']['text']=='한글 ABC 12!?','Mixed script lost from report/glyphs')
            return {'direction':direction,'glyph_alpha_pixels':int((alpha>0).sum()),'scope':'render/geometry, not human readability judgment'}
        a.case('mixed-script-'+direction,'typography','Preserve mixed text under each requested direction',mixed,'real_font')
    def impossible():return raises(ValueError,lambda:run(fixture('매우 긴 번역 '*100,width=160,height=80,font_size=20),min_font=20,min_scale=1))
    a.case('impossible-minimum-fit','typography','Reject overflow rather than clipping letters',impossible,'real_font')
    def missing_font():
        font,reason=core.resolve_font('NanumGothic-Bold.ttf','한글 グルンー')
        require(font!='NanumGothic-Bold.ttf' or reason is None,'Unexpected fallback state');return {'font':font,'fallback':reason}
    a.case('mixed-japanese-font-fallback','typography','Resolve supported Japanese characters with real fallback font',missing_font,'real_font')


def download_cases(a):
    payload=b'pinned model bytes';digest=hashlib.sha256(payload).hexdigest()
    def run_case(mode):
        root=a.work/('download-'+mode);folders=types.SimpleNamespace(models_dir=str(root))
        def response(*args,**kwargs):
            if mode=='dns':raise OSError('temporary name resolution failure')
            if mode=='interrupt':
                class Interrupted(BytesIO):
                    def read(self,*args):raise KeyboardInterrupt('cancelled during download')
                return Interrupted(payload)
            return BytesIO(b'corrupt' if mode=='hash' else payload)
        with patch.dict(sys.modules,{'folder_paths':folders}),patch.object(E,'spec',lambda engine:('repo','rev',{'weights.bin':digest},{'weights.bin':'https://example.invalid/model'},'test')),patch.object(E,'urlopen',response):
            if mode in ('dns','hash','interrupt'):
                evidence=raises((OSError,ValueError,KeyboardInterrupt),lambda:E.ensure(E.ENGINES[1]))
                require(not list((root/'manga_translator/ocr').glob('.download-*')),'Failed download left partial installation');return evidence
            folder=E.ensure(E.ENGINES[1]);require(E.ensure(E.ENGINES[1],False)==folder,'Pinned local model was not reused');return {'verified_and_reused':True}
    for mode in ('dns','hash','interrupt','success'):
        a.case('download-'+mode,'download','Verify fixed bytes, clean failed temporary download, preserve usable model',lambda mode=mode:run_case(mode),'fault_injection')


def frontend_cases(a):
    code=r"""
const fs=require('fs'),vm=require('vm');
class Element{constructor(tag){this.tag=tag;this.children=[];this.style={};this.events={};this.value='';}append(...v){this.children.push(...v);}replaceChildren(){this.children=[];}addEventListener(n,f){this.events[n]=f;}}
const document={createElement:t=>new Element(t)},app={registerExtension:e=>app.extension=e},api={addEventListener(){}};
vm.runInNewContext(fs.readFileSync('web/node_ui.js','utf8').replace(/^import .*;$/gm,''),{app,api,document});
class Node{constructor(){this.id=1;this.widgets=[{name:'edits_json',value:'{}'}];}addDOMWidget(n,t,e,o){return{options:o};}setDirtyCanvas(){}}
(async()=>{await app.extension.beforeRegisterNodeDef(Node,{name:'MangaReviewDocument'});const n=new Node;n.onNodeCreated();
const event={manga_document:[{stage:'target',input_revision:'revision-A',document:{regions:[{id:'r1',target:'old translation'}]}}]};
n.onExecuted(event);let box=n.mangaPanelBody.children.find(e=>e.tag==='textarea');box.value='pending human edit';box.events.input();
n.onExecuted(event);box=n.mangaPanelBody.children.find(e=>e.tag==='textarea');
console.log(JSON.stringify({visible_text:box.value,stored_text:JSON.parse(n.widgets[0].value).pages['revision-A'].r1.target,scope:'DOM/event double; not full browser/ComfyUI'}));})();
"""
    def pending():
        completed=subprocess.run(['node','-e',code],cwd=ROOT,text=True,capture_output=True,check=True)
        evidence=json.loads(completed.stdout)
        require(evidence['visible_text']==evidence['stored_text'],'Replayed execution output resets visible pending edits while stored edits differ',evidence)
        return evidence
    a.case('ui-replayed-output-pending-edit','frontend','Retain pending edits consistently when execution output is replayed',pending,'dom_event_double')


def actual_ocr(a,models,inputs):
    from boundary_acceptance.adapters.options import OcrOptions
    from boundary_acceptance.recognition_cache import MangaOCRAdaptiveCached
    output=a.work/'actual-models';output.mkdir(exist_ok=True)
    folders=types.SimpleNamespace(models_dir=str(models),get_output_directory=lambda:str(output))
    input_paths=sorted(inputs.glob('actual-row-*.png'))
    require(len(input_paths)==5,'Need the five previously verified source row crops')
    from PIL import ImageDraw,ImageFont
    for name,text in [('synthetic-korean','선생님, 안녕하세요.'),('synthetic-latin','LEVEL 2 / TEST')]:
        image=Image.new('RGB',(480,80),'white');ImageDraw.Draw(image).text((16,15),text,font=ImageFont.truetype(str(ROOT/'lettering/fonts/NanumGothic-Regular.ttf'),32),fill='black')
        path=output/(name+'.png');image.save(path);input_paths.append(path)
    with patch.dict(sys.modules,{'folder_paths':folders}):
        for engine in E.ENGINES:
            _,_,_,_,name=E.spec(engine);folder=models/'manga_translator/ocr'/name
            # Revalidate fixed bytes before executing either model.
            _,_,files,_,_=E.spec(engine)
            require(all((folder/n).is_file() and E.sha(folder/n)==sha for n,sha in files.items()),'Missing or modified pinned model '+engine)
            model=E.LazyOCR(engine,folder,'cpu')
            for path in input_paths:
                def infer(path=path,model=model):
                    image=Image.open(path).convert('RGB');start=time.monotonic()
                    try:r=model.ocr(image,OcrOptions(max_new_tokens=256),max_patches=256)
                    except ValueError as exc:return {'adapter_rejection':str(exc),'input_size':list(image.size),'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                    return {'text':r['text'],'model':r.get('model'),'revision':r.get('revision'),'input_size':list(image.size),
                            'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'seconds':round(time.monotonic()-start,3),
                            'accuracy':'NOT_ASSERTED; requires reading against source'}
                a.case(name+'-'+path.stem,'actual_ocr','Record bounded actual CPU OCR output; normal termination is not accuracy',infer,'actual_model')
            for kind,image in [('blank',Image.new('RGB',(280,60),'white')),('dots',__import__('tests.test_dot_punctuation',fromlist=['dots']).dots())]:
                def adaptive(image=image,model=model):
                    page=torch.from_numpy(np.asarray(image,np.float32).copy()/255)[None]
                    try:
                        out=MangaOCRAdaptiveCached().read(page,model,line_split=False,quality_guard=True,cache_policy='off')
                        return {'text':out['result'][0],'report':json.loads(out['result'][1]),'scope':'Actual OCR or verified dot bypass; blank crops are not blank-page classification'}
                    except ValueError as exc:return {'rejected':str(exc)[:1200]}
                a.case(name+'-'+kind,'actual_ocr','Record blank-crop rejection/hallucination or verified punctuation bypass',adaptive,'actual_model')
                if kind=='blank':
                    evidence=deepcopy(a.results[-1].get('evidence',{}))
                    def blank_guard(evidence=evidence):
                        require(not evidence.get('text','').strip(),'Uniform blank crop was accepted as recognized source text',{'accepted_text':evidence.get('text'),'quality_guard':True,'pixel_extrema':[[255,255]]*3})
                        return {'blank_rejected_or_empty':True}
                    a.case(name+'-blank-quality-guard','actual_ocr_quality','Do not accept hallucinated text from a uniform empty crop',blank_guard,'actual_quality_guard')


def main():
    parser=ArgumentParser(description=__doc__);parser.add_argument('--destination',type=Path,default=ROOT/'validation/boundary-audit')
    parser.add_argument('--actual-ocr',action='store_true');parser.add_argument('--models',type=Path);parser.add_argument('--row-inputs',type=Path)
    args=parser.parse_args();torch.set_num_threads(4);a=Audit(args.destination.resolve())
    basic_cases(a);cache_cases(a);project_cases(a);geometry_cases(a);download_cases(a);frontend_cases(a)
    if args.actual_ocr:
        if not args.models or not args.row_inputs:parser.error('--actual-ocr needs --models and --row-inputs')
        actual_ocr(a,args.models,args.row_inputs)
    a.save();counts={s:sum(r['status']==s for r in a.results) for s in ('PASS','FAIL','ERROR','OBSERVED')};print(json.dumps(counts),flush=True)
    return 1 if counts['FAIL'] or counts['ERROR'] else 0

if __name__=='__main__':raise SystemExit(main())
