"""Recover the same clipped glyph rows from bounded source-page context.

No OCR guesses, new text rows, or rectangular cleanup permission. A recovery
must match every old baseline, finish its glyphs, and avoid other owners.
"""
import hashlib
import json
import math
import numpy as np
from PIL import Image
from scipy import ndimage
from . import text_geometry as G


def digest(image):
    return hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()


def _transform(size,rotated_size,angle):
    radians=math.radians(angle);c,s=math.cos(radians),math.sin(radians)
    w,h=size;rw,rh=rotated_size
    return c,s,rw/2-c*w/2-s*h/2,-s,c,rh/2+s*w/2-c*h/2


def _rows_digest(rows):
    return hashlib.sha256(json.dumps(rows,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def verify_context(image,plan):
    record=plan.get('context_recovery',{})
    if (record.get('schema')!=1 or record.get('source_rgb_sha256')!=digest(image)
            or record.get('rows_sha256')!=_rows_digest(plan.get('rows'))
            or record.get('polarity') not in (-1,1)
            or record.get('status')!='recovered' or not plan.get('evidence',{}).get('accepted')):
        raise ValueError('Recovered OCR source context is stale or unverified')


def recover(page,box,support,ident,analysis,obstacles=(),edit_margin=12):
    """Return a new crop/plan/edit bounds only when all old rows are recovered."""
    audit={'strategy':'source_context_glyph_continuation','status':'preserved'}
    old=analysis.get('row_validation',{})
    bands=old.get('bands_pixels',[]);angle=analysis.get('correction_degrees')
    if analysis.get('reason')!='source_crop_cuts_glyphs' or not 2<=len(bands)<=32:
        return None,{**audit,'reason':'no_clipped_baseline_evidence'}
    if type(angle) not in (float,int) or not 2.5<=abs(angle)<25:
        return None,{**audit,'reason':'invalid_source_angle'}
    margin=min(192,max(32,math.ceil(max(b-a for a,b in bands)*4)))
    a,b,c,d=box
    bounds=[max(0,a-margin),max(0,b-margin),min(page.width,c+margin),min(page.height,d+margin)]
    audit.update(original_crop_bbox_pixels=list(box),context_bbox_pixels=bounds)
    context=page.crop(tuple(bounds))
    if context.width*context.height>4*1024*1024 or G.rotation_pixels(context.size,angle)>8*1024*1024:
        return None,{**audit,'reason':'context_size_limit'}
    rotated=G.rotate_rgb(context,angle)
    footprint=Image.new('L',context.size,0)
    from PIL import ImageDraw
    ImageDraw.Draw(footprint).rectangle((a-bounds[0],b-bounds[1],c-bounds[0]-1,d-bounds[1]-1),fill=255)
    footprint=np.asarray(footprint.rotate(angle,Image.Resampling.NEAREST,expand=True))>0
    context_support=np.asarray(Image.fromarray((support[bounds[1]:bounds[3],bounds[0]:bounds[2]]>.5).astype('uint8')*255).rotate(
        angle,Image.Resampling.NEAREST,expand=True))>0
    valid=np.asarray(Image.new('L',context.size,255).rotate(angle,Image.Resampling.NEAREST,expand=True))>0
    _,rows=G._verified_rows(rotated,footprint,valid,include_glyphs=True)
    if 'glyph_groups_pixels' not in rows:
        return None,{**audit,'reason':'no_context_baselines'}
    old_size=(c-a,d-b);old_rot=G.rotate_rgb(page.crop(tuple(box)),angle)
    t=_transform(context.size,rotated.size,angle);o=_transform(old_size,old_rot.size,angle)
    shift_y=t[3]*(a-bounds[0])+t[4]*(b-bounds[1])+t[5]-o[5]
    gray=np.asarray(rotated,np.float32)@np.array([.299,.587,.114],np.float32)
    ink=((gray-ndimage.uniform_filter(gray,31,mode='reflect'))*rows['polarity']>24)&valid
    labels,count=ndimage.label(ink,np.ones((3,3),bool))
    if count>32768:return None,{**audit,'reason':'context_component_limit'}
    areas=np.bincount(labels.ravel(),minlength=count+1)
    objects=ndimage.find_objects(labels)
    clipped={q['row'] for q in old.get('clipped_source_rows',[])}
    selected=[];selected_members=[];used=set()
    for top,bottom in bands:
        top+=shift_y;bottom+=shift_y
        matches=[]
        for index,(start,end) in enumerate(rows['bands_pixels']):
            overlap=min(bottom,end)-max(top,start)
            if overlap>=min(bottom-top,end-start)*.55 and end-start<=(bottom-top)*2.5:
                matches.append(index)
        if len(matches)!=1 or matches[0] in used:
            return None,{**audit,'reason':'ambiguous_baseline_match'}
        index=matches[0];used.add(index)
        components=sorted(rows['glyph_groups_pixels'][index])
        height=float(np.median([q[3]-q[1] for q in components]))
        groups=[]
        for q in components:
            if not groups or q[0]-max(v[2] for v in groups[-1])>height*4:groups.append([])
            groups[-1].append(q)
        def seed(group):
            trusted=sum(int(context_support[q[1]:q[3],q[0]:q[2]].sum()) for q in group)
            # Baselines with no detector support can still finish previously
            # observed partial glyphs, but do not acquire another text owner.
            return trusted+sum(int(footprint[q[1]:q[3],q[0]:q[2]].sum()) for q in group)*.1
        ranked=sorted(((seed(group),group) for group in groups),key=lambda v:v[0],reverse=True)
        if not ranked or len(ranked[0][1])<3 or ranked[0][0]<height*height*.1:
            return None,{**audit,'reason':'unsupported_context_row'}
        group=ranked[0][1]
        for amount,other in ranked[1:]:
            other_height=float(np.median([q[3]-q[1] for q in other]))
            if len(other)<3 or not height*.65<=other_height<=height*1.5:continue
            gap=max(min(q[0] for q in other)-max(q[2] for q in group),
                    min(q[0] for q in group)-max(q[2] for q in other),0)
            if gap<=height*6:
                # The point of recovery is to finish glyphs outside detector
                # support. A lower mask score must not drop half this line.
                group=group+other
            elif amount>ranked[0][0]*.35:
                return None,{**audit,'reason':'multiple_row_owners'}
        if len(selected) not in clipped:
            group=[q for q in group if footprint[q[1]:q[3],q[0]:q[2]].mean()>.5]
        if len(group)<3:return None,{**audit,'reason':'insufficient_original_glyphs'}
        # Cohorts omit punctuation and short letter fragments. Include nearby
        # whole components on this same baseline before choosing OCR bounds.
        candidates=[]
        row_top=min(q[1] for q in group)-height*.3
        row_bottom=max(q[3] for q in group)+height*.5
        for label,slices in enumerate(objects,1):
            if slices is None or areas[label]<3:continue
            y,x=slices;h,w=y.stop-y.start,x.stop-x.start
            if (row_top<=y.start<y.stop<=row_bottom and h<=height*1.8 and w<=height*3
                    and (len(selected) in clipped or footprint[y,x].mean()>.5)):
                candidates.append([x.start,y.start,x.stop,y.stop])
        if len(candidates)>2048:return None,{**audit,'reason':'row_component_limit'}
        left=min(q[0] for q in group);right=max(q[2] for q in group)
        included={tuple(q) for q in group}
        # Reach left once, then right once; no unbounded retry/chain loop.
        for ordered in (sorted(candidates,reverse=True),sorted(candidates)):
            for q in ordered:
                if tuple(q) not in included and max(q[0]-right,left-q[2],0)<=height*2:
                    group.append(q);included.add(tuple(q));left=min(left,q[0]);right=max(right,q[2])
        # Recovered characters must be complete inside this real page context.
        edge=valid & ~ndimage.binary_erosion(valid,iterations=3)
        if any(edge[q[1]:q[3],q[0]:q[2]].any() for q in group):
            return None,{**audit,'reason':'context_still_cuts_glyphs'}
        pad=max(3,round(height*.4))
        selected.append([max(0,min(q[0] for q in group)-pad),max(0,min(q[1] for q in group)-pad),
                         min(rotated.width,max(q[2] for q in group)+pad),min(rotated.height,max(q[3] for q in group)+pad)])
        selected_members.append(group)
    for left,right in zip(selected,selected[1:]):
        if left[3]>right[1]:
            middle=round((left[3]+right[1])/2);left[3]=middle;right[1]=middle
    if any(not (row[0]<=q[0]<q[2]<=row[2] and row[1]<=q[1]<q[3]<=row[3])
           for row,group in zip(selected,selected_members) for q in group):
        return None,{**audit,'reason':'row_partition_cuts_glyphs'}
    local=_whole_row_mask(labels,areas,objects,selected,context.size,rotated.size,angle)
    yy,xx=np.nonzero(local)
    if not len(xx):return None,{**audit,'reason':'empty_recovered_ink'}
    ink_box=[int(xx.min())+bounds[0],int(yy.min())+bounds[1],int(xx.max())+1+bounds[0],int(yy.max())+1+bounds[1]]
    edit=[max(0,ink_box[0]-edit_margin),max(0,ink_box[1]-edit_margin),
          min(page.width,ink_box[2]+edit_margin),min(page.height,ink_box[3]+edit_margin)]
    if any(max(edit[0],q[0])<min(edit[2],q[2]) and max(edit[1],q[1])<min(edit[3],q[3]) for q in obstacles):
        return None,{**audit,'reason':'neighbour_ownership_conflict'}
    extra=local.copy();extra[max(0,b-bounds[1]):d-bounds[1],max(0,a-bounds[0]):c-bounds[0]]=False
    if extra.sum()<12:return None,{**audit,'reason':'no_source_continuation'}
    audit.update(status='recovered',reason='complete_source_baseline_continuation',source_rgb_sha256=digest(context),
                 rows_sha256=_rows_digest(selected),polarity=rows['polarity'],
                 schema=1,ink_bbox_pixels=ink_box,added_ink_pixels=int(extra.sum()),rows=len(selected))
    evidence={**analysis,'accepted':True,'needs_review':False,'reason':'source_context_recovered',
              'row_validation':{'method':'context_component_baselines','needs_review':False,
                                'coordinate_frame':'rectified_crop_pixels','bands_pixels':[[q[1],q[3]] for q in selected]}}
    plan={'strategy':G.STRATEGY,'region_id':ident,'source_size':list(context.size),'correction_degrees':angle,
          'source_angle':-angle,'rectified_size':list(rotated.size),'coordinate_frame':'rectified_crop_pixels',
          'row_mode':'context_glyph_bounds','rows':selected,'evidence':evidence,'context_recovery':audit}
    c0,s0=math.cos(math.radians(angle)),math.sin(math.radians(angle))
    line_boxes=[]
    for x0,y0,x1,y1 in selected:
        points=[(c0*(x-t[2])-s0*(y-t[5])+bounds[0],s0*(x-t[2])+c0*(y-t[5])+bounds[1])
                for x,y in ((x0,y0),(x0,y1),(x1,y0),(x1,y1))]
        line_boxes.append([max(0,math.floor(min(p[0] for p in points))),max(0,math.floor(min(p[1] for p in points))),
                           min(page.width,math.ceil(max(p[0] for p in points))),min(page.height,math.ceil(max(p[1] for p in points)))])
    return {'crop_bbox_pixels':bounds,'edit_bbox_pixels':edit,'bbox_pixels':ink_box,
            'line_bboxes_pixels':line_boxes,'plan':plan},audit


def recover_masks(original,data,source,cleanup):
    """Use the same verified source ink in cleanup; reject changed page pixels."""
    source=source.copy();cleanup=cleanup.copy();height,width=source.shape
    for row in data['regions']:
        plan=row.get('ocr_region_plan',{})
        if plan.get('row_mode')!='context_glyph_bounds':continue
        record=plan.get('context_recovery',{})
        bounds=record.get('context_bbox_pixels')
        if (not isinstance(bounds,list) or len(bounds)!=4 or any(type(v) is not int for v in bounds)
                or not 0<=bounds[0]<bounds[2]<=width or not 0<=bounds[1]<bounds[3]<=height
                or (bounds[2]-bounds[0])*(bounds[3]-bounds[1])>4*1024*1024):
            raise ValueError('Invalid recovered source context bounds')
        context=original.crop(tuple(bounds));verify_context(context,plan)
        # Also validate the exact OCR row partitions, before destructive work.
        G.planned_inputs(context,plan)
        # Recompute pixels from original RGB and the verified row geometry.
        # The JSON never carries an arbitrary erase bitmap.
        local=_context_ink(context,plan)
        x,y=bounds[:2];w,h=context.size
        yy,xx=np.nonzero(local)
        if not len(xx):raise ValueError('Empty recovered source mask')
        ink_bounds=[int(xx.min())+x,int(yy.min())+y,int(xx.max())+1+x,int(yy.max())+1+y]
        if record.get('ink_bbox_pixels')!=ink_bounds:
            raise ValueError('Recovered source mask bounds differ')
        edit=row.get('edit_bbox_pixels',[])
        if len(edit)!=4 or not (edit[0]<=ink_bounds[0] and edit[1]<=ink_bounds[1]
                               and edit[2]>=ink_bounds[2] and edit[3]>=ink_bounds[3]):
            raise ValueError('Recovered source ink exceeds edit owner')
        source[y:y+h,x:x+w]=np.maximum(source[y:y+h,x:x+w],local)
        grown=ndimage.binary_dilation(local>.5,iterations=8)
        cleanup[y:y+h,x:x+w]=np.maximum(cleanup[y:y+h,x:x+w],grown)
    return source,cleanup


def _context_ink(context,plan):
    angle=plan['correction_degrees'];rotated=G.rotate_rgb(context,angle)
    gray=np.asarray(rotated,np.float32)@np.array([.299,.587,.114],np.float32)
    valid=np.asarray(Image.new('L',context.size,255).rotate(angle,Image.Resampling.NEAREST,expand=True))>0
    ink=((gray-ndimage.uniform_filter(gray,31,mode='reflect'))*plan['context_recovery']['polarity']>24)&valid
    labels,count=ndimage.label(ink,np.ones((3,3),bool))
    if count>32768:raise ValueError('Recovered source component budget exceeded')
    areas=np.bincount(labels.ravel(),minlength=count+1)
    return _whole_row_mask(labels,areas,ndimage.find_objects(labels),plan['rows'],context.size,rotated.size,angle)


def _whole_row_mask(labels,areas,objects,rows,source_size,rotated_size,angle):
    # Only whole small components, never a rectangular erase mask. Used both
    # when planning and when recomputing cleanup from the original page.
    keep=np.zeros(len(areas),bool)
    for index,slices in enumerate(objects,1):
        if slices is None:continue
        y,x=slices;h,w=y.stop-y.start,x.stop-x.start
        for q in rows:
            if (q[0]<=x.start<x.stop<=q[2] and q[1]<=y.start<y.stop<=q[3]
                    and 3<=areas[index] and h<=q[3]-q[1] and w<=max(6,(q[3]-q[1])*3)):
                keep[index]=True;break
    transform=_transform(source_size,rotated_size,angle)
    return np.asarray(Image.fromarray(keep[labels].astype('uint8')*255).transform(source_size,Image.Transform.AFFINE,
                      transform,Image.Resampling.NEAREST))>0
