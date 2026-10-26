"""Lossless content-addressed native lazy checkpoints; no model execution in a worker."""
import hashlib
import io
import json
import logging
from pathlib import Path
import os
import uuid
import numpy as np

VERSION='0.7.14'
MAX_BYTES=256*1024*1024

def root():
    import folder_paths
    return Path(folder_paths.get_output_directory())/'manga_translator'/'stage_cache'


_FILE_IDENTITIES={}

def file_identity(path):
    path=Path(path);stat=path.stat();key=(str(path.resolve()),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
    if key not in _FILE_IDENTITIES:
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(8*1024*1024),b''):h.update(chunk)
        _FILE_IDENTITIES[key]=h.hexdigest()
    return _FILE_IDENTITIES[key]


def model_identity(kind,inputs):
    """Local weight contents, not just mutable filenames. Hash once per file stat."""
    try:
        import folder_paths
        if kind in ('MangaAlternativeDetectorModel','MangaLocalInpaintModel'):
            from .alternative_models import DETECTORS,INPAINTERS
            from .adapters.alternative_files import SPECS
            key=(DETECTORS if kind=='MangaAlternativeDetectorModel' else INPAINTERS)[inputs['engine']]
            return {k:{n:SPECS[k][n] for n in ('repository','revision','files')} for k in ([key,'ctd'] if key=='pp-det' else [key])}
        if kind=='MangaOCRModel':
            from .ocr_engines import spec
            repo,revision,files,_,_=spec(inputs.get('engine','Hayai v2'))
            return {'repository':repo,'revision':revision,'files':files}
        if kind in ('MangaDetectorLoader','MangaOCRLoader'):
            from .models import catalog
            folder=catalog('detection' if kind=='MangaDetectorLoader' else 'ocr').get(inputs.get('model_name'))
            if folder:return {p.name:file_identity(p) for p in sorted(folder.iterdir()) if p.is_file()}
        names={'UNETLoader':('diffusion_models','unet_name'),'CLIPLoader':('text_encoders','clip_name'),'VAELoader':('vae','vae_name')}
        if kind in names:
            category,field=names[kind];name=inputs.get(field)
            if isinstance(name,str):
                path=folder_paths.get_full_path(category,name)
                if path and Path(path).is_file():return {field:name,'sha256':file_identity(path)}
    except (ImportError,AttributeError,KeyError):pass
    return None


def upstream(graph,ident,seen=None,stage=None,authored_in_extra=False,model_files=True):
    seen=set() if seen is None else set(seen)
    if str(ident) in seen:raise ValueError('Cycle in checkpoint dependencies')
    seen.add(str(ident));node=graph[str(ident)];kind=node['class_type']
    if kind in ('LoadImage','MangaWorkflowInput'):return {'type':'page_pixels'}
    if stage=='image' and kind=='MangaInpaintPlan':return {'type':'effective_cleanup_plan'}
    inputs={}
    for key,value in sorted(node.get('inputs',{}).items()):
        if key in ('filename_prefix','cache_policy'):continue
        if kind=='MangaReviewDocument' and key=='edits_json' and authored_in_extra:continue
        if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and value[0] in graph:
            inputs[key]={'slot':value[1],'node':upstream(graph,value[0],seen,stage,authored_in_extra,model_files)}
        else:inputs[key]=value
    model=model_identity(kind,node.get('inputs',{})) if model_files else None
    return {'type':kind,'inputs':inputs,**({'model_files':model} if model is not None else {})}


def identity(original,prompt,unique_id,stage,extra='',model_files=True):
    array=original.detach().cpu().numpy()
    if array.ndim!=4 or array.shape[0]!=1 or array.shape[-1]!=3 or array.size>64*1024*1024*3 or not np.isfinite(array).all():raise ValueError('Checkpoint needs one finite RGB page')
    config=upstream(prompt,unique_id,stage=stage,authored_in_extra=stage=='text' and bool(extra),model_files=model_files) if prompt and unique_id else {}
    header=json.dumps([VERSION,stage,list(array.shape),str(array.dtype),config,extra],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
    return hashlib.sha256(header+array.tobytes()).hexdigest()


def read_entry(key,kind):
    """Read pixels and diagnostics against one verified manifest snapshot."""
    try:
        folder=root()/key[:2]/key
        if (folder/'manifest.json').stat().st_size>2_100_000:return None
        meta=json.loads((folder/'manifest.json').read_text())
        if not isinstance(meta,dict):return None
        path=folder/'value.bin'
        if meta['key']!=key or meta['kind']!=kind or path.stat().st_size>MAX_BYTES:return None
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=meta['sha256']:return None
        report=meta.get('report_json');details=None
        if 'report_json' in meta:
            if not isinstance(report,str) or hashlib.sha256(report.encode()).hexdigest()!=meta.get('report_sha256'):return None
            details=json.loads(report)
            if not isinstance(details,dict):return None
        if kind=='image':
            import torch
            a=np.load(io.BytesIO(raw),allow_pickle=False)
            if a.dtype!=np.float32 or a.ndim!=4 or a.shape[0]!=1 or a.shape[-1]!=3 or not np.isfinite(a).all():return None
            return torch.from_numpy(a.copy()),details
        value=json.loads(raw)
        if kind=='text' and isinstance(value,str):return value,details
        if kind=='detection' and isinstance(value,dict) and value.get('protocol')==1:return value,details
    except (OSError,ValueError,KeyError,EOFError,TypeError):pass
    return None


def read(key,kind):
    entry=read_entry(key,kind)
    return entry[0] if entry is not None else None


def write(key,kind,value,report_json=None):
    if kind=='image':
        buf=io.BytesIO();np.save(buf,value.detach().cpu().numpy().astype(np.float32),allow_pickle=False);raw=buf.getvalue()
    else:raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
    if len(raw)>MAX_BYTES:logging.warning('Checkpoint exceeds cache budget; continuing without persistence');return
    folder=root()/key[:2]/key;folder.mkdir(parents=True,exist_ok=True)
    def atomic(path,data):
        tmp=folder/(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with tmp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
    atomic(folder/'value.bin',raw)
    meta={'key':key,'kind':kind,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    if isinstance(report_json,str) and len(report_json.encode())<=2_000_000:
        meta.update(report_json=report_json,report_sha256=hashlib.sha256(report_json.encode()).hexdigest())
    atomic(folder/'manifest.json',json.dumps(meta).encode())



def read_report(key):
    entry=read_entry(key,'image')
    return entry[1] if entry is not None else None


def cleanup_identity(extra,plan):
    if plan is None:return extra
    if not isinstance(plan,dict) or plan.get('version')!=1:raise ValueError('Invalid cleanup plan for checkpoint')
    h=hashlib.sha256(str(extra).encode())
    for name in ('original','base','source_mask','cleanup_mask'):
        a=plan.get(name)
        if a is not None:
            if hasattr(a,'detach'):a=a.detach().cpu().numpy()
            a=np.asarray(a);h.update(str((name,a.shape,a.dtype)).encode());h.update(a.tobytes())
    for tile in plan.get('tiles',[]):
        for name in ('crop','mask'):
            a=tile.get(name)
            if a is not None:
                a=np.asarray(a);h.update(str((a.shape,a.dtype)).encode());h.update(a.tobytes())
    return h.hexdigest()


class Checkpoint:
    CATEGORY='Manga Translator/단계 재사용';FUNCTION='checkpoint'
    TYPE='STRING';KIND='text'
    @classmethod
    def INPUT_TYPES(cls):
        optional={'dependency_json':('STRING',{'forceInput':True})}
        if cls.KIND=='image':
            optional['cleanup_plan']=('MANGA_INPAINT_PLAN',)
            optional['report_json']=('STRING',{'forceInput':True,'lazy':True})
        return {'required':{'original':('IMAGE',),'value':(cls.TYPE,{'lazy':True}),
                            'cache_policy':(['reuse','refresh','off'],{'default':'reuse'})},
                'optional':optional,'hidden':{'prompt':'PROMPT','unique_id':'UNIQUE_ID'}}
    @classmethod
    def IS_CHANGED(cls,cache_policy='reuse',prompt=None,unique_id=None,**kwargs):
        if cache_policy!='reuse':return float('nan')
        config=upstream(prompt,unique_id,stage=cls.KIND) if prompt and unique_id is not None else {}
        return hashlib.sha256(json.dumps([VERSION,config],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def _key(self,original,prompt,unique_id,dependency_json,cleanup_plan):
        return identity(original,prompt,unique_id,self.KIND,cleanup_identity(dependency_json,cleanup_plan))
    def _selection(self,original,prompt,unique_id,dependency_json,cleanup_plan):
        # Freeze dependency files selected by a lazy hit, but verify semantic
        # inputs and page pixels again when consuming that selected generation.
        return identity(original,prompt,unique_id,self.KIND,cleanup_identity(dependency_json,cleanup_plan),model_files=False)
    def check_lazy_status(self,original,value=None,cache_policy='reuse',dependency_json='',prompt=None,unique_id=None,cleanup_plan=None,report_json=None):
        self._pinned=None
        if prompt and unique_id is not None and cache_policy=='reuse':
            key=self._key(original,prompt,unique_id,dependency_json,cleanup_plan)
            entry=read_entry(key,self.KIND)
            if entry is not None:
                # A lazy hit suppresses upstream computation. Keep exactly that
                # verified generation alive until execution consumes it, even
                # if eviction removes the on-disk files in between.
                self._pinned=(key,*entry,self._selection(original,prompt,unique_id,dependency_json,cleanup_plan))
                return []
        needed=['value'] if value is None else []
        if (self.KIND=='image' and report_json is None and prompt and unique_id is not None
                and 'report_json' in prompt[str(unique_id)].get('inputs',{})):needed.append('report_json')
        return needed
    def checkpoint(self,original,value=None,cache_policy='reuse',dependency_json='',prompt=None,unique_id=None,cleanup_plan=None,report_json=None):
        bound=bool(prompt) and unique_id is not None
        pin=getattr(self,'_pinned',None);self._pinned=None
        pinned=bool(pin and bound and cache_policy=='reuse' and pin[3]==self._selection(original,prompt,unique_id,dependency_json,cleanup_plan))
        key=pin[0] if pinned else self._key(original,prompt,unique_id,dependency_json,cleanup_plan) if bound else None
        entry=(pin[1],pin[2]) if pinned else read_entry(key,self.KIND) if bound and cache_policy=='reuse' else None
        cached=entry[0] if entry is not None else None
        reused=cached is not None
        if reused:value=cached
        if value is None:raise ValueError('Checkpoint input unavailable')
        if bound and not reused and cache_policy!='off':
            try:write(key,self.KIND,value,report_json)
            except OSError as exc:logging.warning('Checkpoint persistence unavailable: %s',exc)
        details=(entry[1] if reused else json.loads(report_json) if report_json else {}) if self.KIND=='image' else {}
        report=json.dumps({**(details or {}),'stage_cache':{'stage':self.KIND,'state':'reused' if reused else 'computed','key':key,'generation_frozen':pinned}})
        return {'ui':{'text':[report],'manga_status':[{'state':'reused' if reused else 'computed','message':self.KIND}]},'result':(value,report)}

class MangaTextCheckpoint(Checkpoint):RETURN_TYPES=('STRING','STRING');RETURN_NAMES=('문서','재사용_보고서')
class MangaDetectionCheckpoint(Checkpoint):
    TYPE='MANGA_DETECTION';KIND='detection';RETURN_TYPES=('MANGA_DETECTION','STRING');RETURN_NAMES=('검출','재사용_보고서')
class MangaCleanupCheckpoint(Checkpoint):
    TYPE='IMAGE';KIND='image';RETURN_TYPES=('IMAGE','STRING');RETURN_NAMES=('지운_배경','재사용_보고서')
