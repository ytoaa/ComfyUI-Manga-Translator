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


def _verified_rows(image,support,valid,include_glyphs=False):
    """Find repeated glyph baselines, not peaks made by paper texture.

    Projections can split a glyph's top and bottom into different 'lines'.
    Components vote with their whole height; cuts must lie between cohorts.
    The rotated source footprint also exposes characters already cut by the
    original rectangular crop. Context outside that footprint is not invented.
    """
    stride=max(1,math.ceil(max(image.size)/1024))
    pixels=np.asarray(image,np.float32)[::stride,::stride]
    gray=pixels@np.array([.299,.587,.114],np.float32)
    detail=gray-ndimage.uniform_filter(gray,31,mode='reflect')
    support=support[::stride,::stride]>.5
    valid=valid[::stride,::stride]
    edge=valid & ~ndimage.binary_erosion(valid,iterations=2)
    choices=[]
    for polarity in (-1,1):
        ink=(detail*polarity>24) & valid
        labels,count=ndimage.label(ink,structure=np.ones((3,3),bool))
        if count>32768:continue
        areas=np.bincount(labels.ravel(),minlength=count+1)
        seeded=np.bincount(labels[support].ravel(),minlength=count+1)
        edge_pixels=np.bincount(labels[edge].ravel(),minlength=count+1)
        objects=ndimage.find_objects(labels)
        components=[]
        small=[]
        for index,slices in enumerate(objects,1):
            if slices is None:continue
            y,x=slices;h,w=y.stop-y.start,x.stop-x.start
            box=[x.start,y.start,x.stop,y.stop]
            if areas[index]>=12 and 3<=h<=gray.shape[0]*.45 and 2<=w<=gray.shape[1]*.5:
                small.append((box,int(edge_pixels[index])))
            if (areas[index]>=20 and max(4,round(gray.shape[0]*.02))<=h<=gray.shape[0]*.45
                    and 3<=w<=gray.shape[1]*.5 and w/h<3):
                components.append([*box,int(areas[index]),int(seeded[index]),index])
        if len(components)<6:continue
        comp=np.asarray(components)
        cohorts=[]
        for baseline in np.unique(comp[:,3]):
            group=comp[np.abs(comp[:,3]-baseline)<=3]
            if len(group)<3:continue
            height=float(np.median(group[:,3]-group[:,1]))
            group=group[((group[:,3]-group[:,1])>=height*.65)&((group[:,3]-group[:,1])<=height*1.5)]
            if (len(group)<3 or baseline!=round(float(np.median(group[:,3])))
                    or np.ptp(np.r_[group[:,0],group[:,2]])<height*3):continue
            cohorts.append({'top':int(group[:,1].min()),'bottom':int(group[:,3].max()),
                            'ids':set(group[:,6].tolist()),'height':height})
        cohorts.sort(key=lambda c:c['top'])
        merged=[]
        for row in cohorts:
            if merged and row['top']<=merged[-1]['bottom']:
                merged[-1]['bottom']=max(merged[-1]['bottom'],row['bottom'])
                merged[-1]['ids']|=row['ids']
            else:merged.append(row)
        if not 2<=len(merged)<=32:continue
        clipped=[]
        for index,row in enumerate(merged):
            hits=[]
            for box,amount in small:
                if (amount<2 or box[3]<=row['top'] or box[1]>=row['bottom']
                        or box[3]-box[1]>row['height']*1.8
                        or box[2]-box[0]>row['height']*3):continue
                # A ring/heart can have nested components. Count independently
                # cut objects, not a hollow shape and its interior twice.
                overlaps=[i for i,b in enumerate(hits) if max(b[0],box[0])<min(b[2],box[2])
                          and max(b[1],box[1])<min(b[3],box[3])]
                for i in reversed(overlaps):
                    old=hits.pop(i);box=[min(old[0],box[0]),min(old[1],box[1]),max(old[2],box[2]),max(old[3],box[3])]
                hits.append(box)
            if len(hits)>=2:
                clipped.append({'row':index,'component_groups':len(hits),
                                'boxes':[[v*stride for v in box] for box in hits]})
        ids=set().union(*(row['ids'] for row in merged))
        mass=int(sum(seeded[i] for i in ids))
        unassigned=[i for i,row in enumerate(merged) if sum(seeded[j]>=3 for j in row['ids'])<3]
        choices.append((mass,merged,clipped,polarity,unassigned,components))
    if not choices:return [],{'method':'component_baselines','reason':'unverified_glyph_rows','needs_review':True}
    _,bands,clipped,polarity,unassigned,components=max(choices,key=lambda c:c[0])
    # Whole component boxes also let context recovery match the same baselines.
    glyph_groups=[]
    for row in bands:
        boxes=[[int(v)*stride for v in c[:4]] for c in components if c[6] in row['ids']]
        glyph_groups.append(boxes)
    cuts=[0]+[round((a['bottom']+b['top'])*stride/2) for a,b in zip(bands,bands[1:])]+[image.height]
    rows=[[0,a,image.width,b] for a,b in zip(cuts,cuts[1:])]
    return rows,{'method':'component_baselines','coordinate_frame':'rectified_crop_pixels','analysis_stride':stride,'polarity':polarity,
                 'bands_pixels':[[r['top']*stride,r['bottom']*stride] for r in bands],
                 **({'glyph_groups_pixels':glyph_groups} if include_glyphs else {}),
                 'clipped_source_rows':clipped,'unassigned_rows':unassigned,
                 'needs_review':bool(clipped or unassigned),
                 'reason':'source_crop_cuts_glyphs' if clipped else 'unassigned_glyph_rows' if unassigned else 'verified_glyph_rows'}


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
    if rotation_pixels(image.size,angle)>8*1024*1024:
        return {},{**evidence,'reason':'rectified_size_limit'}
    rectified=rotate_rgb(image,angle)
    if rectified.width*rectified.height>8*1024*1024:
        return {},{**evidence,'reason':'rectified_size_limit'}
    rotated_support=np.asarray(Image.fromarray((support>.5).astype('uint8')*255).rotate(
        angle,Image.Resampling.NEAREST,expand=True))>0
    valid=np.asarray(Image.new('L',image.size,255).rotate(angle,Image.Resampling.NEAREST,expand=True))>0
    rows,validation=_verified_rows(rectified,rotated_support,valid)
    evidence['row_validation']=validation
    if validation['needs_review']:
        return {},{**evidence,'reason':validation['reason'],'needs_review':True}
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
    evidence=value.get('evidence',{})
    if (isinstance(evidence,dict) and isinstance(evidence.get('row_validation'),dict)
            and evidence['row_validation'].get('needs_review')):
        raise ValueError('Unverified source crop must be reviewed before OCR')
    if value.get('rectified_size')!=list(rotated.size):raise ValueError('Invalid rectified source size')
    rows=value.get('rows')
    if not isinstance(rows,list) or not 2<=len(rows)<=32:raise ValueError('Invalid deskew rows')
    if value.get('row_mode')=='context_glyph_bounds':
        from .source_recovery import verify_context
        verify_context(image,value)
        previous=0;output=[]
        for row in rows:
            if (not isinstance(row,list) or len(row)!=4 or any(type(v) is not int for v in row)
                    or not 0<=row[0]<row[2]<=rotated.width or not previous<=row[1]<row[3]<=rotated.height):
                raise ValueError('Invalid recovered glyph row bounds')
            output.append(rotated.crop(tuple(row)));previous=row[3]
        return output
    previous=0;output=[]
    for row in rows:
        if (not isinstance(row,list) or len(row)!=4 or any(type(v) is not int for v in row)
                or row[0]!=0 or row[2]!=rotated.width or row[1]!=previous
                or not row[1]<row[3]<=rotated.height):raise ValueError('Deskew rows must partition rectified input')
        output.append(rotated.crop(tuple(row)));previous=row[3]
    if previous!=rotated.height:raise ValueError('Incomplete deskew row partition')
    return output
