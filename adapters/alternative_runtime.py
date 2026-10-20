"""Optional CPU inference; no GPL CTD application code or ONNX Runtime.

CTD uses raw YOLO blocks and UNet probabilities, not upstream grouping.
Paddle DB line areas are not glyph masks: CTD supplies their ink support.
"""
import math
import threading
import numpy as np
from PIL import Image
from .alternative_files import SPECS


def rgb(image):
    if not isinstance(image,Image.Image) or min(image.size)<1 or image.width*image.height>64*1024*1024:
        raise ValueError('Expected a PIL page within the 64 Mi-pixel limit')
    return np.asarray(image.convert('RGB'))


def ctc_decode(probabilities,characters):
    p=np.asarray(probabilities)
    if p.ndim!=3 or p.shape[0]!=1 or p.shape[-1]!=len(characters) or not np.isfinite(p).all():
        raise ValueError('Unexpected CTC probabilities/vocabulary')
    indices=p[0].argmax(axis=1);selected=(indices!=0)&np.r_[True,indices[1:]!=indices[:-1]]
    text=''.join(characters[i] for i in indices[selected])
    confidence=float(p[0,np.arange(len(indices))[selected],indices[selected]].mean()) if selected.any() else 0.
    return text,confidence


def rec_size(size):
    w,h=size
    if min(w,h)<=0:raise ValueError('Empty OCR crop')
    if h/w>=1.5:w,h=h,w
    return min(3200,max(320,int(48*w/h))),48


def recognition_input(image):
    import cv2
    data=rgb(image)
    if data.shape[0]/data.shape[1]>=1.5:data=np.rot90(data)
    h,w=data.shape[:2];width=min(3200,max(320,int(48*w/h)));resized=min(width,math.ceil(48*w/h))
    pixels=cv2.resize(data[:,:,::-1],(resized,48)).astype(np.float32)/127.5-1
    result=np.zeros((1,3,48,width),np.float32);result[0,:,:,:resized]=pixels.transpose(2,0,1)
    return result


class PaddleRecognition:
    def __init__(self,folder):
        import yaml
        config=yaml.safe_load((folder/'inference.yml').read_text())['PostProcess']
        self.characters=['']+config['character_dict']
        if config.get('use_space_char',True):self.characters.append(' ')
        from transformers import AutoModelForTextRecognition
        self.net=AutoModelForTextRecognition.from_pretrained(str(folder),local_files_only=True,trust_remote_code=False).eval()
    input_size=staticmethod(rec_size)
    def ocr(self,image,options,max_patches=256):
        from .hayai import HayaiOutputError
        import torch
        with torch.inference_mode():values=self.net(pixel_values=torch.from_numpy(recognition_input(image))).last_hidden_state.detach().float().cpu().numpy()
        text,score=ctc_decode(values,self.characters)
        if len(text)>options.max_new_tokens:raise HayaiOutputError('ocr_token_limit')
        return {'protocol':1,'text':text,'model':SPECS['pp-rec']['repository'],'revision':SPECS['pp-rec']['revision'],
            'confidence':score,'preprocess':'BGR / 48px / tall crops rotated CCW / greedy CTC','patch_budget_applicable':False}


def encode_detection(box,score,ink):
    from .model import rle
    h,w=ink.shape
    a,b,c,d=[int(v) for v in (max(0,math.floor(box[0])),max(0,math.floor(box[1])),min(w,math.ceil(box[2])),min(h,math.ceil(box[3])))]
    if a>=c or b>=d:return None
    local=ink[b:d,a:c]
    if local.sum()<8:return None
    return {'label':'text','score':float(score),'bbox':[a,b,c,d],'mask':{'x':a,'y':b,'width':c-a,'height':d-b,'runs':rle(local)}}


def detection_result(key,image,boxes,scores,ink,method):
    found=[];protected=[]
    for box,score in zip(boxes,scores):
        item=encode_detection(box,score,ink)
        if item is not None:found.append(item)
        else:
            a,b,c,d=[int(v) for v in (max(0,math.floor(box[0])),max(0,math.floor(box[1])),min(image.width,math.ceil(box[2])),min(image.height,math.ceil(box[3])))]
            if a<c and b<d:protected.append([a,b,c,d])
    result={'protocol':1,'image_width':image.width,'image_height':image.height,'model':SPECS[key]['repository'],
        'revision':SPECS[key]['revision'],'detections':found,'postprocessing':method,
        'capabilities':{'bubble':False,'panel':False,'sfx_classification':False,'ink_support':'CTD UNet > .3'}}
    if protected:result.update(needs_review=True,boundary_review={'schema':1,'reason':'alternative_candidate_without_ink_support','protected_boxes_pixels':protected})
    return result


class ComicDetector:
    def __init__(self,folder):
        import cv2
        self.net=cv2.dnn.readNetFromONNX(str(folder/'comic-text-detector.onnx'));self.lock=threading.Lock()
    def maps(self,image):
        import cv2
        data=rgb(image);h,w=data.shape[:2];scale=min(1024/w,1024/h);rw,rh=round(w*scale),round(h*scale)
        canvas=np.zeros((1024,1024,3),np.uint8);canvas[:rh,:rw]=cv2.resize(data,(rw,rh))
        x=np.ascontiguousarray(canvas.transpose(2,0,1)[None],dtype=np.float32)/255
        with self.lock:
            self.net.setInput(x);names=self.net.getUnconnectedOutLayersNames();values=dict(zip(names,self.net.forward(names)))
        ink=cv2.resize(values['seg'][0,0,:rh,:rw],(w,h),interpolation=cv2.INTER_LINEAR)>.3
        return values['blk'][0],ink,(rw/w,rh/h)
    def detect(self,image,thresholds):
        import cv2
        proposals,ink,(sx,sy)=self.maps(image);scores=proposals[:,4]*proposals[:,5:].max(axis=1)
        indices=np.flatnonzero(scores>=thresholds.get('text',.4));p=proposals[indices,:4].copy();p[:,:2]-=p[:,2:]/2
        chosen=np.asarray(cv2.dnn.NMSBoxes(p.tolist(),scores[indices].tolist(),float(thresholds.get('text',.4)),.35),dtype=int).reshape(-1)
        p=p[chosen];p[:,2:]+=p[:,:2];p/=np.array([sx,sy,sx,sy])
        return detection_result('ctd',image,p,scores[indices[chosen]],ink,'raw YOLO blocks + NMS .35; no upstream grouping/refinement')


def db_boxes(probabilities,width,height,box_threshold=.45):
    import cv2,pyclipper
    p=np.asarray(probabilities)
    if p.ndim!=2 or not np.isfinite(p).all():raise ValueError('Invalid DB detection map')
    contours,_=cv2.findContours((p>.2).astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE);boxes=[];scores=[]
    for contour in contours[:3000]:
        if len(contour)<3:continue
        rect=cv2.minAreaRect(contour);points=cv2.boxPoints(rect)
        if min(rect[1])<3:continue
        x,y,w,h=cv2.boundingRect(contour);support=np.zeros((h,w),np.uint8);cv2.fillPoly(support,[np.round(points-[x,y]).astype(np.int32)],1)
        selected=p[y:y+h,x:x+w][support>0];score=float(selected.mean()) if selected.size else 0.
        if score<box_threshold:continue
        area=abs(cv2.contourArea(points));length=cv2.arcLength(points,True)
        if length<=0:continue
        offset=pyclipper.PyclipperOffset();offset.AddPath(np.round(points*16).astype(int).tolist(),pyclipper.JT_ROUND,pyclipper.ET_CLOSEDPOLYGON);expanded=offset.Execute(area*1.4/length*16)
        if len(expanded)!=1:continue
        pts=np.asarray(expanded[0],np.float32)/16;pts[:,0]*=width/p.shape[1];pts[:,1]*=height/p.shape[0]
        boxes.append([float(pts[:,0].min()),float(pts[:,1].min()),float(pts[:,0].max()),float(pts[:,1].max())]);scores.append(score)
    return boxes,scores


class PaddleDetector:
    def __init__(self,folder,ctd):
        from transformers import AutoModelForObjectDetection
        self.net=AutoModelForObjectDetection.from_pretrained(str(folder),local_files_only=True,trust_remote_code=False).eval();self.ctd=ctd
    def detect(self,image,thresholds):
        import cv2,torch
        data=rgb(image);h,w=data.shape[:2];ratio=min(max(1.,736/min(h,w)),4000/max(h,w));rh=max(32,round(h*ratio/32)*32);rw=max(32,round(w*ratio/32)*32)
        x=cv2.resize(data[:,:,::-1],(rw,rh)).astype(np.float32)/255;x=(x-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
        with torch.inference_mode():values=self.net(pixel_values=torch.from_numpy(np.ascontiguousarray(x.transpose(2,0,1)[None]))).last_hidden_state.detach().float().cpu().numpy()[0,0]
        boxes,scores=db_boxes(values,w,h,thresholds.get('text',.45));_,ink,_=self.ctd.maps(image)
        return detection_result('pp-det',image,boxes,scores,ink,'PP-OCRv6 DB .2 / unclip1.4 + CTD ink; unsupported candidates protected')


class Lama:
    def __init__(self,path):
        import torch
        self.model=torch.jit.load(str(path),map_location='cpu').eval()
    def inpaint(self,image,mask):
        import torch
        image=np.asarray(image,np.float32);mask=np.asarray(mask)
        if image.ndim!=3 or image.shape[-1]!=3 or image.shape[:2]!=mask.shape or not image.size or not np.isfinite(image).all() or image.min()<0 or image.max()>1 or not np.isfinite(mask).all():raise ValueError('Expected finite RGB [0,1] tile and matching mask')
        h,w=image.shape[:2]
        if max(h,w)>1024:raise ValueError('Local inpaint tile exceeds 1024px')
        if not (mask>.5).any():return image.copy()
        ph=max(32,math.ceil(h/8)*8)-h;pw=max(32,math.ceil(w/8)*8)-w
        padded=np.pad(image,((0,ph),(0,pw),(0,0)),mode='reflect' if min(h,w)>1 else 'edge');support=np.pad(mask>.5,((0,ph),(0,pw)))
        x=torch.from_numpy(padded.transpose(2,0,1).copy())[None];m=torch.from_numpy(support.astype(np.float32))[None,None]
        with torch.inference_mode():value=self.model(x,m)
        result=value[0].permute(1,2,0).detach().float().cpu().numpy()[:h,:w]
        if result.shape!=image.shape or not np.isfinite(result).all():raise ValueError('Invalid local inpaint output')
        return np.clip(result,0,1)
