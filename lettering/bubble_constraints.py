"""Pixel containment in an explicitly supplied or detected speech-bubble mask."""
import numpy as np
from scipy import ndimage
from . import core


def candidates(provided, detection, shape):
    from ..mask_nodes import _decode_mask
    found=[]
    if provided is not None:
        labels,count=ndimage.label(provided>.5)
        if count>64:raise ValueError('Too many bubble-mask components')
        for i,slices in enumerate(ndimage.find_objects(labels),1):
            if slices is None:continue
            ys,xs=slices
            found.append({'mask':labels[ys,xs]==i,'bounds':[xs.start,ys.start,xs.stop-xs.start,ys.stop-ys.start],
                          'source':'provided'})
    elif detection is not None:
        for item in detection['detections']:
            if item.get('label')!='bubble' or not isinstance(item.get('mask'),dict):continue
            local,bounds=_decode_mask(item['mask'],shape[1],shape[0])
            found.append({'mask':local>.5,'bounds':list(bounds),'source':'detector'})
            if len(found)>64:raise ValueError('Too many detected bubble masks')
    if sum(item['mask'].size for item in found)>core.MAX_SOURCE_PIXELS:
        raise ValueError('Bubble mask analysis exceeds the 64 Mi-pixel source-page ceiling')
    for i,item in enumerate(found):
        item.update(index=i,pixels=int(item['mask'].sum()),safe={})
    return found


def overlap(a,b):
    x,y,w,h=a;u,v,s,t=b
    return max(x,u),max(y,v),min(x+w,u+s),min(y+h,v+t)


def largest_rectangle(mask):
    """Maximal all-true rectangle, O(height*width), without assuming convexity."""
    if mask.all():return [0,0,mask.shape[1],mask.shape[0]]
    heights=np.zeros(mask.shape[1],np.int32);best=None;area=0
    for y,row in enumerate(mask):
        heights=np.where(row,heights+1,0)
        stack=[]
        for x,height in enumerate(np.r_[heights,0]):
            start=x
            while stack and stack[-1][1]>height:
                left,tall=stack.pop();current=(x-left)*tall
                if current>area:
                    best=[left,y-tall+1,x-left,tall];area=current
                start=left
            if height and (not stack or stack[-1][1]<height):stack.append((start,int(height)))
    return best


def constrain(ink,source,items,shape,padding,expand=False):
    x,y,w,h=source;count=int(ink.sum());matched=[];crossing=False
    for item in items:
        a,b,c,d=item['bounds'];left,top,right,bottom=overlap(source,item['bounds'])
        if left>=right or top>=bottom:continue
        covered=np.count_nonzero(ink[top-y:bottom-y,left-x:right-x] &
                                  item['mask'][top-b:bottom-b,left-a:right-a])
        coverage=covered/max(1,count)
        if coverage>=.95:matched.append((item,coverage))
        elif coverage>=.5:crossing=True
    if not matched:
        if crossing:raise ValueError('Source ink crosses a known bubble mask; review region ownership or bubble segmentation')
        return None,{'status':'unavailable','reason':'no_bubble_covers_source_ink'}
    matched.sort(key=lambda pair:pair[0]['pixels']);chosen,coverage=matched[0]
    for other,_ in matched[1:]:
        left,top,right,bottom=overlap(chosen['bounds'],other['bounds'])
        a,b,_,_=chosen['bounds'];u,v,_,_=other['bounds']
        common=np.count_nonzero(chosen['mask'][top-b:bottom-b,left-a:right-a] &
                                 other['mask'][top-v:bottom-v,left-u:right-u]) if left<right and top<bottom else 0
        if common/max(1,min(chosen['pixels'],other['pixels']))<.9:
            raise ValueError('Ambiguous overlapping bubble masks; cannot certify translation containment')
    a,b,c,d=chosen['bounds']
    window=[max(0,x-w),max(0,y-h),min(shape[1],x+2*w)-max(0,x-w),
            min(shape[0],y+2*h)-max(0,y-h)] if expand else source
    left,top,right,bottom=overlap(window,chosen['bounds'])
    if (right-left)*(bottom-top)>core.MAX_REGION_PIXELS:
        raise ValueError('Bubble fitting window exceeds 16 Mi pixels')
    clearance=max(1,padding)
    if clearance not in chosen['safe']:
        chosen['safe'][clearance]=ndimage.binary_erosion(chosen['mask'],iterations=clearance,border_value=0)
    safe=chosen['safe'][clearance][top-b:bottom-b,left-a:right-a].copy()
    rect=largest_rectangle(safe)
    if rect is None:raise ValueError('Verified bubble has no safe text interior after clearance')
    rect[0]+=left;rect[1]+=top
    report={'status':'verified','mask_source':chosen['source'],'bubble_index':chosen['index'],
            'source_ink_coverage':round(coverage,4),'clearance':clearance,'safe_rectangle':rect}
    return {'bounds':[left,top,right-left,bottom-top],'mask':safe,'rectangle':rect},report


def canvas_mask(guard,bounds):
    x,y,w,h=bounds;allowed=np.zeros((h,w),bool)
    left,top,right,bottom=overlap(bounds,guard['bounds'])
    if left<right and top<bottom:
        a,b,_,_=guard['bounds']
        allowed[top-y:bottom-y,left-x:right-x]=guard['mask'][top-b:bottom-b,left-a:right-a]
    return allowed
