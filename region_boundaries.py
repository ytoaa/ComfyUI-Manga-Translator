"""Detector-frame separators corroborated by intact source segmentation ink.

No RGB invention or OCR slicing: a split needs a real gap between detected
owners and a completely empty segmentation strip. Every positive input pixel
must survive. The same separators forbid subsequent transitive rejoining.
"""
import math
import numpy as np
from .mask_nodes import _decode_mask
from .limits import MAX_REGION_PIXELS
from .adapters.model import rle


def area(b):return (b[2]-b[0])*(b[3]-b[1])


def intersection(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def separators(owners):
    # Tile crops cannot establish a true panel edge. Compact near-identical
    # complete observations so their IDs do not create artificial owners.
    groups=[]
    for row in owners:
        if row.get('tile_provenance',{}).get('clipped_edges'):continue
        b=row['bbox'];kind=row['label']
        for old in groups:
            common=intersection(b,old['bbox'])
            if kind==old['label'] and common/(area(b)+area(old['bbox'])-common)>=.85:
                old['bbox']=[min(b[0],old['bbox'][0]),min(b[1],old['bbox'][1]),
                             max(b[2],old['bbox'][2]),max(b[3],old['bbox'][3])]
                break
        else:groups.append({'label':kind,'bbox':list(b)})
    found=set()
    for i,left in enumerate(groups):
        for right in groups[i+1:]:
            if left['label']!=right['label']:continue
            for axis in (0,1):
                a,b=sorted((left['bbox'],right['bbox']),key=lambda q:q[axis])
                start,end=math.ceil(a[axis+2]),math.floor(b[axis])
                cross=1-axis;lo=max(a[cross],b[cross]);hi=min(a[cross+2],b[cross+2])
                if end-start<2 or hi-lo<.8*min(a[cross+2]-a[cross],b[cross+2]-b[cross]):continue
                found.add((axis,start,end,lo,hi,left['label']))
    if len(found)>4096:raise ValueError('Region boundary separator budget exceeds 4096')
    return sorted(found)


def relevant(box,barrier):
    axis,start,end,lo,hi,_=barrier;cross=1-axis
    return min(box[cross+2],hi)-max(box[cross],lo)>=(box[cross+2]-box[cross])*.95


def compatible(a,b,barriers):
    a=a.get('_ink_bbox',a['bbox']);b=b.get('_ink_bbox',b['bbox'])
    union=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
    for barrier in barriers:
        if not relevant(union,barrier):continue
        axis,start,end,*_=barrier
        # A non-adjacent owner pair can bracket another complete panel. Text
        # inside that interval is neutral, not arbitrarily divided at its mid.
        def side(box):return -1 if box[axis+2]<=start else 1 if box[axis]>=end else 0
        if side(a)!=side(b):return False
    return True


def encode_mask(pixels,x,y):
    yy,xx=np.nonzero(pixels)
    if not len(xx):return None,None
    a,b,c,d=int(xx.min()),int(yy.min()),int(xx.max())+1,int(yy.max())+1
    return {'x':x+a,'y':y+b,'width':c-a,'height':d-b,'runs':rle(pixels[b:d,a:c])},[x+a,y+b,x+c,y+d]


def partition(items,barriers,width,height):
    result=[];audit=[]
    for item in items:
        box=item['bbox'];possible=[q for q in barriers if relevant(box,q) and box[q[0]]<q[1] and box[q[0]+2]>q[2]]
        if not possible or not isinstance(item.get('mask'),dict):result.append(item);continue
        raw=item['mask']
        if raw['width']*raw['height']>MAX_REGION_PIXELS:raise ValueError('Region boundary mask exceeds 16 Mi pixels')
        pixels,(x,y,w,h)=_decode_mask(raw,width,height);pixels=pixels>.5
        cuts={0:set(),1:set()};evidence=[]
        for axis,start,end,lo,hi,kind in possible:
            offset=x if axis==0 else y;size=w if axis==0 else h
            a,b=max(0,start-offset),min(size,end-offset)
            if a>=b:continue
            strip=pixels[:,a:b] if axis==0 else pixels[a:b,:]
            before=pixels[:,:a] if axis==0 else pixels[:a,:]
            after=pixels[:,b:] if axis==0 else pixels[b:,:]
            if strip.any() or not before.any() or not after.any():continue
            cut=(start+end)//2
            cuts[axis].add(cut);evidence.append({'axis':'x' if axis==0 else 'y','gap_pixels':[start,end],'cut_pixel':cut,'owner_kind':kind})
        if not evidence:result.append(item);continue
        xs=[x]+sorted(cuts[0])+[x+w];ys=[y]+sorted(cuts[1])+[y+h]
        if (len(xs)-1)*(len(ys)-1)>32:raise ValueError('Region boundary split exceeds 32 parts')
        parts=[];count=0
        for top,bottom in zip(ys,ys[1:]):
            for left,right in zip(xs,xs[1:]):
                local=pixels[top-y:bottom-y,left-x:right-x]
                encoded,ink=encode_mask(local,left,top)
                if encoded is None:continue
                count+=int(local.sum())
                # Retain source bbox margins inside this verified blank cut.
                bounds=[max(box[0],left),max(box[1],top),min(box[2],right),min(box[3],bottom)]
                bounds=[min(bounds[0],ink[0]),min(bounds[1],ink[1]),max(bounds[2],ink[2]),max(bounds[3],ink[3])]
                parts.append({**item,'bbox':bounds,'mask':encoded,'_ink_bbox':ink,
                              'boundary_partition':{'schema':1,'original_bbox_pixels':box,'part':len(parts)+1}})
        if count!=int(pixels.sum()):raise ValueError('Region boundary split changed source ink')
        result.extend(parts)
        audit.append({'detector_ids':item.get('source_detector_ids',[]),'original_bbox_pixels':box,
                      'parts':len(parts),'source_ink_pixels':count,'cuts':evidence})
        if len(result)>512:raise ValueError('Partitioned detector candidate budget exceeds 512')
    if len(result)>512:raise ValueError('Partitioned detector candidate budget exceeds 512')
    return result,audit


def union_masks(a,b,width,height):
    if not isinstance(a.get('mask'),dict) or not isinstance(b.get('mask'),dict):return None
    masks=[]
    for item in (a,b):
        raw=item['mask']
        if raw['width']*raw['height']>MAX_REGION_PIXELS:raise ValueError('Merged source mask exceeds 16 Mi pixels')
        mask,bounds=_decode_mask(raw,width,height);masks.append((mask>.5,bounds))
    x=min(q[1][0] for q in masks);y=min(q[1][1] for q in masks)
    right=max(q[1][0]+q[1][2] for q in masks);bottom=max(q[1][1]+q[1][3] for q in masks)
    if (right-x)*(bottom-y)>MAX_REGION_PIXELS:raise ValueError('Merged source mask exceeds 16 Mi pixels')
    pixels=np.zeros((bottom-y,right-x),bool)
    for mask,(a,b,w,h) in masks:pixels[b-y:b-y+h,a-x:a-x+w]|=mask
    return encode_mask(pixels,x,y)[0]
