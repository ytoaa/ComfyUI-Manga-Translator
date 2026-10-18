"""Bounded, mask-supported deskew planning; no word guesses or page edits."""
import math
import numpy as np
from PIL import Image
from scipy import ndimage

STRATEGY='mask_supported_deskew_rows'


def rotation_pixels(size,angle):
    width,height=size;radians=math.radians(angle)
    a,b=abs(math.cos(radians)),abs(math.sin(radians))
    return (math.ceil(width*a+height*b)+2)*(math.ceil(height*a+width*b)+2)


def rotate_rgb(image,angle):
    if rotation_pixels(image.size,angle)>8*1024*1024:
        raise ValueError('Rectified OCR raster exceeds 8 Mi pixels')
    pixels=np.asarray(image.convert('RGB'))
    rim=np.concatenate((pixels[0],pixels[-1],pixels[:,0],pixels[:,-1]))
    color=tuple(np.median(rim,axis=0).round().astype('uint8').tolist())
    return image.convert('RGB').rotate(angle,Image.Resampling.BICUBIC,expand=True,fillcolor=color)


def plan(image,support,ident):
    width,height=image.size
    evidence={'strategy':STRATEGY,'accepted':False,'scope':'geometric_evidence_not_recognition_confidence'}
    if support.shape!=(height,width) or not np.isfinite(support).all():
        raise ValueError('Deskew support must match the OCR crop')
    if width*height>4*1024*1024 or min(width,height)<24:
        return {},{**evidence,'reason':'analysis_size_limit'}
    if width<height*1.4:return {},{**evidence,'reason':'nonhorizontal_frame'}
    stride=max(1,math.ceil(max(width,height)/768))
    rgb=np.asarray(image.convert('RGB'),np.float32)[::stride,::stride]
    gray=rgb@np.array([.299,.587,.114],np.float32)
    detail=gray-ndimage.uniform_filter(gray,31,mode='reflect')
    positive,negative=float(np.percentile(detail,99)),-float(np.percentile(detail,1))
    ink=(detail>16 if positive>negative*1.2 else detail < -16 if negative>positive*1.2 else np.abs(detail)>16)
    ink &= support[::stride,::stride]>.5
    labels,count=ndimage.label(ink,structure=np.ones((3,3),bool))
    if count>32768:return {},{**evidence,'reason':'component_limit'}
    areas=np.bincount(labels.ravel(),minlength=count+1)
    keep=np.zeros(count+1,bool)
    for index,slices in enumerate(ndimage.find_objects(labels),1):
        if slices is None:continue
        y,x=slices;h,w=y.stop-y.start,x.stop-x.start
        keep[index]=(3<=h<=gray.shape[0]*.45 and 2<=w<=gray.shape[1]*.5 and areas[index]>=6)
    ink=keep[labels]
    if keep.sum()<8 or ink.sum()<64:return {},{**evidence,'reason':'insufficient_masked_components'}
    binary=Image.fromarray((ink*255).astype('uint8'))
    def score(angle):
        pixels=np.asarray(binary.rotate(float(angle),Image.Resampling.NEAREST,expand=True))>0
        projection=pixels.sum(axis=1).astype(np.float64)
        return float((projection@projection)/max(1,pixels.sum()))
    baseline=score(0)
    scores=[(score(a),a) for a in range(-25,26)]
    _,coarse=max(scores)
    best,angle=max((score(a),float(a)) for a in np.arange(max(-25,coarse-1),min(25,coarse+1)+.01,.25))
    gain=best/max(1,baseline)
    evidence.update(correction_degrees=angle,projection_gain=round(gain,4),analysis_stride=stride,
                    supported_components=int(keep.sum()))
    if not 2.5<=abs(angle)<25 or gain<1.2:
        return {},{**evidence,'reason':'no_supported_skew'}
    rotated=np.asarray(binary.rotate(angle,Image.Resampling.NEAREST,expand=True))>0
    active=rotated.sum(axis=1)>=max(3,round(rotated.shape[1]*.015))
    runs=[]
    labels,n=ndimage.label(active)
    for slices in ndimage.find_objects(labels):
        y=slices[0]
        if y.stop-y.start>=4:runs.append([y.start,y.stop])
    # A gap of at most two analysis pixels can separate a dot/accent from its
    # row. Keep real row gaps; the planner never decides from decoded strings.
    joined=[]
    for a,b in runs:
        if joined and a-joined[-1][1]<=2:joined[-1][1]=b
        else:joined.append([a,b])
    runs=joined
    if not 2<=len(runs)<=32:return {},{**evidence,'reason':'unverified_row_count'}
    covered=np.zeros(rotated.shape[0],bool)
    for a,b in runs:covered[max(0,a-2):min(len(covered),b+2)]=True
    coverage=float(rotated[covered].sum()/max(1,rotated.sum()))
    evidence['supported_ink_coverage']=round(coverage,4)
    if coverage<.85:return {},{**evidence,'reason':'unassigned_masked_components'}
    if rotation_pixels(image.size,angle)>8*1024*1024:
        return {},{**evidence,'reason':'rectified_size_limit'}
    rectified=rotate_rgb(image,angle)
    if rectified.width*rectified.height>8*1024*1024:
        return {},{**evidence,'reason':'rectified_size_limit'}
    # Full-width disjoint row slices retain horizontal source context. Row
    # boundaries lie between supported bands in the rectified coordinate frame.
    cuts=[0]+[round((a[1]+b[0])*stride/2) for a,b in zip(runs,runs[1:])]+[rectified.height]
    rows=[[0,max(0,a),rectified.width,min(rectified.height,b)] for a,b in zip(cuts,cuts[1:])]
    if any(b<=a for _,a,_,b in rows):return {},{**evidence,'reason':'invalid_rectified_rows'}
    evidence.update(accepted=True,reason='supported_rotation_and_rows')
    result={'strategy':STRATEGY,'region_id':ident,'source_size':[width,height],
            'correction_degrees':angle,'source_angle':-angle,'rectified_size':list(rectified.size),
            'coordinate_frame':'rectified_crop_pixels','rows':rows,'evidence':evidence}
    return result,evidence


def planned_inputs(image,value):
    if (not isinstance(value,dict) or value.get('strategy')!=STRATEGY
            or value.get('source_size')!=list(image.size)):
        raise ValueError('Deskew plan belongs to another source crop')
    angle=value.get('correction_degrees')
    if type(angle) not in (int,float) or not math.isfinite(angle) or not 2.5<=abs(angle)<25:
        raise ValueError('Invalid deskew correction angle')
    if value.get('source_angle')!=-angle or value.get('coordinate_frame')!='rectified_crop_pixels':
        raise ValueError('Invalid deskew coordinate frame')
    if image.width*image.height>4*1024*1024:raise ValueError('Deskew source exceeds analysis limit')
    rotated=rotate_rgb(image,angle)
    if value.get('rectified_size')!=list(rotated.size):raise ValueError('Invalid rectified source size')
    rows=value.get('rows')
    if not isinstance(rows,list) or not 2<=len(rows)<=32:raise ValueError('Invalid deskew rows')
    previous=0;output=[]
    for row in rows:
        if (not isinstance(row,list) or len(row)!=4 or any(type(v) is not int for v in row)
                or row[0]!=0 or row[2]!=rotated.width or row[1]!=previous
                or not row[1]<row[3]<=rotated.height):raise ValueError('Deskew rows must partition rectified input')
        output.append(rotated.crop(tuple(row)));previous=row[3]
    if previous!=rotated.height:raise ValueError('Incomplete deskew row partition')
    return output
