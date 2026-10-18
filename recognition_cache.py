"""Per-crop persistence also serves OCR preview branches without repeating inference."""
import base64
import io
import json
import numpy as np
from PIL import Image
from .models import MangaOCRAdaptive
from . import stage_cache

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
            import torch
            data=json.loads(cached)
            result=(data['text'],data['report'],[torch.from_numpy(np.asarray(Image.open(io.BytesIO(base64.b64decode(p))).convert('RGB'),dtype=np.float32)/255)[None] for p in data['previews']])
        else:
            result=super().read(images,model,**options)
            if key and cache_policy!='off':
                previews=[]
                for value in result[2]:
                    image=Image.fromarray((value[0].detach().cpu().numpy()*255).round().astype('uint8'));buf=io.BytesIO();image.save(buf,format='PNG');previews.append(base64.b64encode(buf.getvalue()).decode())
                try:stage_cache.write(key,'text',json.dumps({'text':result[0],'report':result[1],'previews':previews}))
                except OSError:pass  # Persistence failure must not invalidate a successfully recognized crop.
        return {'ui':{'manga_status':[{'state':'reused' if cached else 'computed','message':'OCR'}]},'result':result}
