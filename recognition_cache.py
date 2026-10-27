"""Per-crop persistence also serves OCR preview branches without repeating inference."""
import base64
import io
import json
import numpy as np
from PIL import Image
from .models import MangaOCRAdaptive
from . import stage_cache
from .limits import MAX_SOURCE_PIXELS


def restore(value):
    """Validate the nested OCR payload as well as its outer cache checksum."""
    import torch
    data=json.loads(value)
    if (not isinstance(data,dict) or not isinstance(data.get('text'),str)
            or not isinstance(data.get('report'),str) or not isinstance(json.loads(data['report']),dict)
            or not isinstance(data.get('previews'),list) or not data['previews']):
        raise ValueError('Invalid OCR cache payload')
    previews=[];pixels=0
    for encoded in data['previews']:
        if not isinstance(encoded,str):raise ValueError('Invalid OCR preview')
        with Image.open(io.BytesIO(base64.b64decode(encoded,validate=True))) as image:
            pixels+=image.width*image.height
            if pixels>MAX_SOURCE_PIXELS:raise ValueError('OCR preview cache exceeds pixel budget')
            previews.append(torch.from_numpy(np.asarray(image.convert('RGB'),dtype=np.float32)/255)[None])
    return data['text'],data['report'],previews

class MangaOCRAdaptiveCached(MangaOCRAdaptive):
    @classmethod
    def INPUT_TYPES(cls):
        schema=super().INPUT_TYPES();schema['optional']['cache_policy']=(['reuse','refresh','off'],{'default':'reuse'});return schema
    @classmethod
    def IS_CHANGED(cls,cache_policy='reuse',**kwargs):return stage_cache.VERSION if cache_policy=='reuse' else float('nan')
    def read(self,images,model=None,cache_policy='reuse',**options):
        ident=getattr(model,'cache_identity',None)
        key=stage_cache.identity(images,None,None,'ocr-region',json.dumps([ident,options],sort_keys=True)) if ident else None
        cached=stage_cache.read(key,'text') if key and cache_policy=='reuse' else None
        if cached:
            try:result=restore(cached)
            except (ValueError,TypeError,KeyError,OSError,Image.DecompressionBombError):cached=None
        if not cached:
            result=super().read(images,model,**options)
            if key and cache_policy!='off':
                previews=[]
                for value in result[2]:
                    image=Image.fromarray((value[0].detach().cpu().numpy()*255).round().astype('uint8'));buf=io.BytesIO();image.save(buf,format='PNG');previews.append(base64.b64encode(buf.getvalue()).decode())
                try:stage_cache.write(key,'text',json.dumps({'text':result[0],'report':result[1],'previews':previews}))
                except OSError:pass  # Persistence failure must not invalidate a successfully recognized crop.
        return {'ui':{'manga_status':[{'state':'reused' if cached else 'computed','message':'OCR'}]},'result':result}
