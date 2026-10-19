"""Pixel containment in an explicitly supplied or detected speech-bubble mask."""
import numpy as np
from scipy import ndimage
from . import core


class BubbleContainmentError(ValueError):
    """Insufficient ownership evidence, distinct from invalid inputs/budgets."""
    def __init__(self,message,code,evidence=None):
        super().__init__(message)
        self.diagnostic={'code':code,**(evidence or {})}


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
    x,y,w,h=source;count=int(ink.sum());matched=[];crossing=False;evidence=[]
    for item in items:
        a,b,c,d=item['bounds'];left,top,right,bottom=overlap(source,item['bounds'])
        if left>=right or top>=bottom:continue
        covered=np.count_nonzero(ink[top-y:bottom-y,left-x:right-x] &
                                  item['mask'][top-b:bottom-b,left-a:right-a])
        coverage=covered/max(1,count)
        evidence.append({'bubble_index':item['index'],'mask_source':item['source'],
                         'source_ink_coverage':round(coverage,4),'bounds_xywh':item['bounds']})
        if coverage>=.95:matched.append((item,coverage))
        elif coverage>=.5:crossing=True
    if not matched:
        if crossing:raise BubbleContainmentError('Source ink crosses a known bubble mask; review region ownership or bubble segmentation',
            'bubble_source_crossing',{'source_ink_pixels':count,'required_coverage':.95,'candidates':evidence})
        return None,{'status':'unavailable','reason':'no_bubble_covers_source_ink'}
    matched.sort(key=lambda pair:pair[0]['pixels']);chosen,coverage=matched[0]
    ambiguous=False
    for other,_ in matched[1:]:
        left,top,right,bottom=overlap(chosen['bounds'],other['bounds'])
        a,b,_,_=chosen['bounds'];u,v,_,_=other['bounds']
        common=np.count_nonzero(chosen['mask'][top-b:bottom-b,left-a:right-a] &
                                 other['mask'][top-v:bottom-v,left-u:right-u]) if left<right and top<bottom else 0
        if common/max(1,min(chosen['pixels'],other['pixels']))<.9:
            ambiguous=True
    resolution=None
    if ambiguous:
        # Every candidate covers the source ink. Their intersection is a
        # containment certificate common to all candidates, never a union or
        # an arbitrary guess about which bubble owns the paragraph.
        left=max(item['bounds'][0] for item,_ in matched)
        top=max(item['bounds'][1] for item,_ in matched)
        right=min(item['bounds'][0]+item['bounds'][2] for item,_ in matched)
        bottom=min(item['bounds'][1]+item['bounds'][3] for item,_ in matched)
        if left>=right or top>=bottom or (right-left)*(bottom-top)>core.MAX_REGION_PIXELS:
            raise BubbleContainmentError('Ambiguous overlapping bubble masks; no bounded common interior','bubble_ambiguous_interior',{'candidates':evidence})
        common=np.ones((bottom-top,right-left),bool)
        for item,_ in matched:
            a,b,_,_=item['bounds']
            common &= item['mask'][top-b:bottom-b,left-a:right-a]
        # Reject overlaps that lose actual source ink, including disconnected
        # intersections whose largest rectangle belongs to another component.
        labels,_=ndimage.label(common)
        ix0,iy0,ix1,iy1=overlap(source,[left,top,right-left,bottom-top])
        source_labels=labels[iy0-top:iy1-top,ix0-left:ix1-left]
        source_ink=ink[iy0-y:iy1-y,ix0-x:ix1-x]
        weights=np.bincount(source_labels[source_ink].ravel(),minlength=1)
        weights[0]=0
        label=int(weights.argmax())
        coverage=float(weights[label]/max(1,count))
        if not label or coverage<.95:
            raise BubbleContainmentError('Ambiguous overlapping bubble masks; common interior does not cover source ink','bubble_ambiguous_ownership',{'source_ink_coverage':coverage,'candidates':evidence})
        chosen={'bounds':[left,top,right-left,bottom-top],'mask':labels==label,
                'safe':{},'index':chosen['index'],'source':'detector_intersection'}
        resolution={'strategy':'common_mask_intersection','bubble_indices':[item['index'] for item,_ in matched]}
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
    if rect is None:raise BubbleContainmentError('Verified bubble has no safe text interior after clearance','bubble_empty_safe_interior',{'candidates':evidence,'clearance':clearance})
    rect[0]+=left;rect[1]+=top
    report={'status':'verified','mask_source':chosen['source'],'bubble_index':chosen['index'],
            'source_ink_coverage':round(coverage,4),'clearance':clearance,'safe_rectangle':rect,
            **({'overlap_resolution':resolution} if resolution else {})}
    return {'bounds':[left,top,right-left,bottom-top],'mask':safe,'rectangle':rect},report


def canvas_mask(guard,bounds):
    x,y,w,h=bounds;allowed=np.zeros((h,w),bool)
    left,top,right,bottom=overlap(bounds,guard['bounds'])
    if left<right and top<bottom:
        a,b,_,_=guard['bounds']
        allowed[top-y:bottom-y,left-x:right-x]=guard['mask'][top-b:bottom-b,left-a:right-a]
    return allowed
