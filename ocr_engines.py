"""Selectable pinned OCR bundles with atomic, hash-verified first-use acquisition."""
import errno
import hashlib
import json
from pathlib import Path
import shutil
import threading
from urllib.request import urlopen
import uuid
from .adapters import hayai_files

ENGINES=('Hayai v2','Manga OCR · Japanese','PP-OCRv6 · multilingual (CPU)')
MANGA_REPO='kha-white/manga-ocr-base'
MANGA_REV='aa6573bd10b0d446cbf622e29c3e084914df9741'
MANGA_FILES={
 'config.json':'8c0e395de8fa699daaac21aee33a4ba9bd1309cfbff03147813d2a025f39f349',
 'preprocessor_config.json':'af4eb4d79cf61b47010fc0bc9352ee967579c417423b4917188d809b7e048948',
 'special_tokens_map.json':'303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3',
 'tokenizer_config.json':'d775ad1deac162dc56b84e9b8638f95ed8a1f263d0f56f4f40834e26e205e266',
 'vocab.txt':'344fbb6b8bf18c57839e924e2c9365434697e0227fac00b88bb4899b78aa594d',
 'pytorch_model.bin':'c63e0bb5b3ff798c5991de18a8e0956c7ee6d1563aca6729029815eda6f5c2eb'}
_LOCK=threading.RLock();_RESIDENT={}


def spec(engine):
    if engine==ENGINES[2]:
        from .adapters.alternative_files import SPECS
        s=SPECS['pp-rec'];return s['repository'],s['revision'],s['files'],s['urls'],'pp-ocrv6-medium-rec'
    if engine==ENGINES[0]:return hayai_files.REPO,hayai_files.REV,hayai_files.FILES,hayai_files.URLS,'hayai-ocr-v2'
    if engine==ENGINES[1]:return MANGA_REPO,MANGA_REV,MANGA_FILES,{n:f'https://huggingface.co/{MANGA_REPO}/resolve/{MANGA_REV}/{n}' for n in MANGA_FILES},'manga-ocr-base'
    raise ValueError('Unknown OCR engine')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def ensure(engine,download=True,progress=lambda *a:None):
    if engine==ENGINES[2]:
        from .alternative_models import ensure as ensure_alternative
        return ensure_alternative('pp-rec',download,progress)
    import folder_paths
    repo,rev,files,urls,name=spec(engine)
    destination=Path(folder_paths.models_dir)/'manga_translator'/'ocr'/name
    def valid(folder):return all((folder/n).is_file() and sha(folder/n)==s for n,s in files.items())
    with _LOCK:
        if engine==ENGINES[0]:
            from .models import catalog
            for folder in catalog('ocr').values():
                if valid(folder):return folder
        if destination.is_dir() and valid(destination):return destination
        if destination.exists():raise ValueError('OCR bundle is incomplete or modified; preserve/rename it before downloading: '+str(destination))
        if not download:raise ValueError('OCR model is missing. Enable download_missing or install the pinned model bundle')
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.parent/('.download-'+uuid.uuid4().hex);temporary.mkdir()
        try:
            for i,(name,expected) in enumerate(files.items()):
                h=hashlib.sha256();count=0
                with urlopen(urls[name],timeout=60) as response,(temporary/name).open('wb') as output:
                    while chunk:=response.read(1024*1024):
                        try:
                            import comfy.model_management
                            comfy.model_management.throw_exception_if_processing_interrupted()
                        except ImportError:pass
                        count+=len(chunk)
                        if count>2*1024**3:raise ValueError('OCR download exceeds file budget')
                        output.write(chunk);h.update(chunk);progress(i,len(files),name,count)
                if h.hexdigest()!=expected:raise ValueError('Downloaded OCR SHA256 mismatch: '+name)
            (temporary/'model-files.json').write_text(json.dumps({'repository':repo,'revision':rev,'files':files}))
            try:temporary.rename(destination)
            except OSError as exc:
                # Concurrent processes may have completed the exact pinned bundle.
                # Never overwrite an incomplete or modified existing directory.
                if exc.errno not in (errno.EEXIST,errno.ENOTEMPTY) or not valid(destination):raise
        finally:
            if temporary.exists():shutil.rmtree(temporary)
    return destination


class MangaBackend:
    def __init__(self,folder,device):
        import torch
        if tuple(int(n) for n in torch.__version__.split('+')[0].split('.')[:2])<(2,6):raise ValueError('Manga OCR requires torch >= 2.6 for weights_only checkpoint loading')
        from transformers import ViTImageProcessor,VisionEncoderDecoderModel
        self.processor=ViTImageProcessor.from_pretrained(str(folder),local_files_only=True)
        self.model=VisionEncoderDecoderModel.from_pretrained(str(folder),local_files_only=True,use_safetensors=False).to(device).eval()
        self.vocab=(folder/'vocab.txt').read_text().splitlines();self.device=device
    def ocr(self,image,options,max_patches=256):
        import torch
        from .adapters.hayai import validate_result
        pixels=self.processor(images=image.convert('RGB'),return_tensors='pt').pixel_values.to(self.device)
        with torch.inference_mode():
            ids=self.model.generate(pixels,max_new_tokens=options.max_new_tokens,repetition_penalty=options.repetition_penalty,num_beams=1,do_sample=False)[0].tolist()[1:]
        end={self.model.config.eos_token_id,self.model.config.pad_token_id};tokens=[];count=len(ids)
        for index,ident in enumerate(ids):
            if ident in end:count=index;break
            value=self.vocab[ident] if 0<=ident<len(self.vocab) else '[UNK]'
            if value not in ('[CLS]','[SEP]','[PAD]'):tokens.append(value.removeprefix('##'))
        text=validate_result(''.join(tokens),count,options.max_new_tokens)
        return {'protocol':1,'text':text,'model':MANGA_REPO,'revision':MANGA_REV}


class LazyOCR:
    def __init__(self,engine,folder,device):
        self.engine,self.folder,self.device=engine,Path(folder).resolve(),device
        repo,rev,files,_,_=spec(engine)
        self.files=dict(files)
        if self._generation()!=self.files:raise ValueError('OCR model SHA256 mismatch; reload a verified bundle')
        self.cache_identity={'engine':engine,'repository':repo,'revision':rev,'files':dict(self.files),'device':device}
    def _generation(self):
        from .stage_cache import file_identity
        return {name:file_identity(self.folder/name) for name in self.files}
    def _verify(self):
        try:
            if self._generation()==self.files:return
        except OSError:
            pass
        raise ValueError('OCR model bundle changed; reload the model before inference')
    def input_size(self,size,patches):
        if self.engine==ENGINES[1]:return 224,224
        from .adapters.hayai import preprocess_size
        return preprocess_size(size,patches)
    def ocr(self,image,options,max_patches=256):
        key=(self.engine,str(self.folder),self.device,tuple(sorted(self.files.items())))
        with _LOCK:
            self._verify()
            if key not in _RESIDENT:
                if self.engine==ENGINES[1]:backend=MangaBackend(self.folder,self.device)
                else:
                    from .adapters.hayai import Backend,load_model
                    from tokenizers import Tokenizer
                    if self.device=='cuda':backend=Backend(self.folder)
                    else:
                        backend=object.__new__(Backend);backend.model=load_model(self.folder,'cpu')
                        backend.tokenizer=Tokenizer.from_file(str(self.folder/'tokenizer.json'))
                        backend.model_name=hayai_files.REPO;backend.revision=hayai_files.REV;backend.device='cpu'
                self._verify()
                for old in list(_RESIDENT):
                    if old[:3]==key[:3]:del _RESIDENT[old]
                _RESIDENT[key]=backend
            backend=_RESIDENT[key]
        self._verify()
        result=backend.ocr(image,options,max_patches=max_patches)
        self._verify()
        return result


class MangaOCRModel:
    CATEGORY='Manga Translator/Models';FUNCTION='load'
    DESCRIPTION='OCR 엔진 선택. 누락 모델은 고정 revision과 SHA256을 확인하여 내려받습니다. 추론은 OCR 노드가 실행할 때 시작합니다.'
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'engine':(list(ENGINES),),'download_missing':('BOOLEAN',{'default':True}),
        'device':(['auto','cuda','cpu'],{'default':'auto'})},'hidden':{'unique_id':'UNIQUE_ID'}}
    RETURN_TYPES=('MANGA_OCR_MODEL','STRING');RETURN_NAMES=('OCR_모델','모델_상태')
    def load(self,engine=ENGINES[0],download_missing=True,device='auto',unique_id=None):
        import torch
        if device not in ('auto','cuda','cpu'):raise ValueError('Invalid OCR device')
        if engine==ENGINES[2]:
            if device=='cuda':raise ValueError('PP-OCRv6 adapter is CPU only; select cpu or auto')
            device='cpu'
        if device=='auto':device='cuda' if torch.cuda.is_available() else 'cpu'
        if device=='cuda' and not torch.cuda.is_available():raise ValueError('CUDA is unavailable; select cpu or auto')
        def progress(i,total,name,count):
            try:
                from server import PromptServer
                PromptServer.instance.send_sync('manga_model_progress',{'node':unique_id,'file':name,'bytes':count,'index':i,'total':total})
            except ImportError:pass
        folder=ensure(engine,download_missing,progress)
        status={'state':'ready','engine':engine,'device':device,'folder':str(folder),'revision':spec(engine)[1],
                'language_scope':'Japanese' if engine==ENGINES[1] else 'Japanese/Chinese/English/declared Latin scripts; verify recognition' if engine==ENGINES[2] else 'model-supported scripts; verify recognition'}
        if engine==ENGINES[2]:
            from .alternative_models import Model
            backend=Model('pp-rec',folder)
        else:backend=LazyOCR(engine,folder,device)
        return {'ui':{'manga_status':[status]},'result':(backend,json.dumps(status,ensure_ascii=False))}
