"""Opt-in CPU model nodes; immutable pinned downloads and existing mask assembly."""
import errno
import json
from pathlib import Path
import shutil
import threading
from urllib.request import urlopen
import uuid
from .adapters.alternative_files import SPECS

PADDLE_ENGINE='PP-OCRv6 · multilingual (CPU)'
DETECTORS={'CTD ONNX · raw blocks':'ctd','PP-OCRv6 + CTD ink':'pp-det'}
INPAINTERS={'LaMa':'lama','Anime LaMa':'anime-lama'}
_LOCK=threading.RLock();_CACHE={}


def generation(folder,key):
    from .stage_cache import file_identity
    return {name:file_identity(folder/name) for name in SPECS[key]['files']}


def ensure(key,download=True,progress=lambda *a:None):
    import folder_paths
    if key not in SPECS:raise ValueError('Unknown optional model')
    spec=SPECS[key];destination=Path(folder_paths.models_dir)/'manga_translator'/'alternatives'/key
    def valid(folder):return all((folder/n).is_file() for n in spec['files']) and generation(folder,key)==spec['files']
    with _LOCK:
        if destination.is_dir() and valid(destination):return destination
        if destination.exists():raise ValueError('Alternative model bundle is incomplete or modified; preserve/rename it: '+str(destination))
        if not download:raise ValueError('Optional model is missing; enable download_missing or install its pinned files')
        destination.parent.mkdir(parents=True,exist_ok=True);temporary=destination.parent/('.download-'+uuid.uuid4().hex);temporary.mkdir()
        try:
            for i,(name,url) in enumerate(spec['urls'].items()):
                count=0
                with urlopen(url,timeout=60) as response,(temporary/name).open('wb') as output:
                    while chunk:=response.read(1024*1024):
                        try:
                            import comfy.model_management
                            comfy.model_management.throw_exception_if_processing_interrupted()
                        except ImportError:pass
                        count+=len(chunk)
                        if count>2*1024**3:raise ValueError('Alternative model download exceeds file budget')
                        output.write(chunk);progress(i,len(spec['files']),name,count)
            if not valid(temporary):raise ValueError('Downloaded alternative model SHA256 mismatch')
            (temporary/'model-files.json').write_text(json.dumps(spec,sort_keys=True))
            try:temporary.rename(destination)
            except OSError as exc:
                if exc.errno not in (errno.EEXIST,errno.ENOTEMPTY) or not valid(destination):raise
        finally:
            if temporary.exists():shutil.rmtree(temporary)
    return destination


class Model:
    def __init__(self,key,folder,dependencies=None):
        if key not in SPECS:raise ValueError('Invalid alternative model')
        self.key,self.folder=key,Path(folder);self.files=generation(self.folder,key)
        if self.files!=SPECS[key]['files']:raise ValueError('Alternative model SHA256 mismatch')
        self.dependencies=dependencies or {}
        self.cache_identity={'engine':key,'repository':SPECS[key]['repository'],'revision':SPECS[key]['revision'],'files':self.files,
            'device':'cpu','runtime':'opencv_dnn' if key=='ctd' else 'pytorch','dependencies':{k:v.cache_identity for k,v in self.dependencies.items()}}
    def _verify(self):
        if generation(self.folder,self.key)!=self.files:raise ValueError('Alternative model bundle changed; reload before inference')
        for model in self.dependencies.values():model._verify()
    def _backend(self):
        from .adapters import alternative_runtime as R
        self._verify();key=(self.key,str(self.folder.resolve()),json.dumps(self.cache_identity,sort_keys=True))
        with _LOCK:
            if key not in _CACHE:
                if self.key=='ctd':value=R.ComicDetector(self.folder)
                elif self.key=='pp-det':value=R.PaddleDetector(self.folder,self.dependencies['ctd']._backend())
                elif self.key=='pp-rec':value=R.PaddleRecognition(self.folder)
                else:value=R.Lama(self.folder/next(iter(SPECS[self.key]['files'])))
                self._verify()
                for old in list(_CACHE):
                    if old[:2]==key[:2]:del _CACHE[old]
                _CACHE[key]=value
        return _CACHE[key]
    def _call(self,name,*args,**kwargs):
        self._verify();result=getattr(self._backend(),name)(*args,**kwargs);self._verify();return result
    def detect(self,image,thresholds):return self._call('detect',image,thresholds)
    def ocr(self,image,options,max_patches=256):return self._call('ocr',image,options,max_patches=max_patches)
    def inpaint(self,image,mask):return self._call('inpaint',image,mask)
    def input_size(self,size,patches):
        from .adapters.alternative_runtime import rec_size
        return rec_size(size)


def load(key,download=True):
    dependencies={'ctd':load('ctd',download)} if key=='pp-det' else {}
    return Model(key,ensure(key,download),dependencies)


class MangaAlternativeDetectorModel:
    CATEGORY='Manga Translator/Models';FUNCTION='load'
    DESCRIPTION='CPU 검출 선택. CTD raw blocks 또는 PP-OCRv6+CTD 획. 말풍선·컷·효과음 분류 없음. 임계값 CTD .4 / PP .45부터 검수하세요.'
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'engine':(list(DETECTORS),),'download_missing':('BOOLEAN',{'default':True})}}
    RETURN_TYPES=('MANGA_DETECTOR_MODEL','STRING');RETURN_NAMES=('검출_모델','모델_상태')
    def load(self,engine,download_missing=True):
        if engine not in DETECTORS:raise ValueError('Unknown detector choice')
        model=load(DETECTORS[engine],download_missing)
        return model,json.dumps({'engine':engine,'device':'cpu','identity':model.cache_identity},ensure_ascii=False)


class MangaLocalInpaintModel:
    CATEGORY='Manga Translator/Models';FUNCTION='load'
    DESCRIPTION='고정 SHA256의 LaMa / Anime LaMa. CPU 검증 경로. 실제 추론은 남은 제거 타일이 있을 때 수행합니다.'
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'engine':(list(INPAINTERS),),'download_missing':('BOOLEAN',{'default':True})}}
    RETURN_TYPES=('MANGA_LOCAL_INPAINT_MODEL','STRING');RETURN_NAMES=('제거_모델','모델_상태')
    def load(self,engine='Anime LaMa',download_missing=True):
        if engine not in INPAINTERS:raise ValueError('Unknown inpaint choice')
        model=load(INPAINTERS[engine],download_missing)
        return model,json.dumps({'engine':engine,'device':'cpu','identity':model.cache_identity},ensure_ascii=False)


class MangaLocalInpaint:
    CATEGORY='Manga Translator/Cleanup';FUNCTION='finish'
    DESCRIPTION='실제 LaMa 타일을 기존 mask·보호 영역 검증으로 합칩니다. 빈 계획은 모델을 생략합니다. 무늬 복원은 검수하세요.'
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'plan':('MANGA_INPAINT_PLAN',),'model':('MANGA_LOCAL_INPAINT_MODEL',{'lazy':True}),
        'strict_cleanup':('BOOLEAN',{'default':True}),'blend_width':('INT',{'default':8,'min':0,'max':32})}}
    RETURN_TYPES=('IMAGE','STRING');RETURN_NAMES=('cleaned_page','cleanup_report')
    def check_lazy_status(self,plan,strict_cleanup=True,blend_width=8,model=None):return ['model'] if plan.get('tiles') and model is None else []
    def finish(self,plan,model=None,strict_cleanup=True,blend_width=8):
        from . import inpaint_tiles as I
        from .lettering.nodes import tensor
        if not isinstance(plan,dict) or plan.get('version')!=1 or not isinstance(plan.get('tiles'),list) or len(plan['tiles'])>256:raise ValueError('Expected a bounded inpaint tile plan')
        if type(strict_cleanup) is not bool:raise ValueError('strict_cleanup must be boolean')
        if plan['tiles'] and model is None:raise ValueError('Connect a local inpaint model for pending tiles')
        generated=[]
        for tile in plan['tiles']:
            x,y,r,b=tile['crop'];crop=plan['base'][y:b,x:r]
            if crop.shape[:2]!=tile['mask'].shape:raise ValueError('Inpaint tile/mask dimensions differ')
            generated.append(model.inpaint(crop,tile['mask']))
        output,raw=I.assemble(plan,generated,strict_cleanup,blend_width);report=json.loads(raw)
        report.update(tile_backend=model.key if generated else 'uniform_or_empty',local_model_tiles=len(generated),model_identity=model.cache_identity if generated else None,qwen_generated=False,
            quality_scope='actual local tiles; source-change heuristic and outside-mask preservation, not semantic quality certification')
        return tensor(output),json.dumps(report,ensure_ascii=False,indent=2)


NODE_CLASS_MAPPINGS={c.__name__:c for c in (MangaAlternativeDetectorModel,MangaLocalInpaintModel,MangaLocalInpaint)}
NODE_DISPLAY_NAME_MAPPINGS={'MangaAlternativeDetectorModel':'대체 검출 모델 · CPU','MangaLocalInpaintModel':'대체 제거 모델 · LaMa / Anime LaMa','MangaLocalInpaint':'대체 타일 제거 · 보호 영역 유지'}
