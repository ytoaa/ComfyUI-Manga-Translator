"""Source-capped lettering plans. CPU only; no image model rewrites characters."""
import json
import math
import re
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from . import core
from . import bubble_constraints
from . import placement
from .. import boundary_review

MODES = ('source', 'bubble', 'strict')
DIRECTIONS = ('auto', 'horizontal', 'vertical_rtl', 'vertical_ltr')
LINE_BREAKS = ('preserve','reflow')
FIT_POLICIES = ('source_ratio','readable')


def review_skip_reason(rows):
    return ('bubble_regions_preserved' if all(r['reason']=='unverified_bubble_ownership' for r in rows)
            else 'lettering_regions_preserved')


def reflow_text(text):
    """Treat single newlines as physical wraps; retain blank-line paragraphs."""
    def separator(match):
        left,right=match.string[:match.start()].rstrip(),match.string[match.end():].lstrip()
        if not left or not right:
            return ''
        # Japanese/CJK source-like runs need no extra word separator. Korean
        # and Latin translated prose retain a word boundary across soft wraps.
        cjk=lambda c: '\u3040' <= c <= '\u30ff' or '\u3400' <= c <= '\u9fff'
        return '' if cjk(left[-1]) and cjk(right[0]) else ' '
    return '\n\n'.join(re.sub(r'[ \t]*\n[ \t]*',separator,paragraph).strip()
                        for paragraph in re.split(r'\n[ \t]*\n+',text.strip()))


def bands(values):
    labels, count = ndimage.label(values)
    return [(int(np.where(labels==i)[0][0]),int(np.where(labels==i)[0][-1])+1)
            for i in range(1,count+1)]


def component_size(ink):
    """Recover collapsed projections only from repeated, glyph-like components.

    Filled boxes, rules, isolated dots and widely mixed font sizes provide no
    certificate. This estimates geometry, not the identity of any character.
    """
    labels,count=ndimage.label(ink,np.ones((3,3),bool))
    if not 8<=count<=8192:return None
    areas=np.bincount(labels.ravel(),minlength=count+1)
    rows=[]
    for index,sl in enumerate(ndimage.find_objects(labels),1):
        if sl is None:continue
        h,w=sl[0].stop-sl[0].start,sl[1].stop-sl[1].start
        if min(h,w)>=5 and .4<=w/h<=2.5 and .08<=areas[index]/(h*w)<=.85:
            rows.append((max(h,w),int(areas[index])))
    if len(rows)<8:return None
    median=float(np.median([v[0] for v in rows]))
    cohort=[v for v in rows if .65*median<=v[0]<=1.5*median]
    if len(cohort)<8 or sum(v[1] for v in cohort)<.7*int(ink.sum()):return None
    sizes=[v[0] for v in cohort]
    if np.percentile(sizes,90)>np.percentile(sizes,25)*1.6:return None
    return {'visible_height':float(np.percentile(sizes,80)), 'components':len(cohort),
            'ink_coverage':round(sum(v[1] for v in cohort)/int(ink.sum()),4)}


def column_size(ink,cols,extent):
    if extent is None or ink.shape[0]<4*extent:return None
    widths=[b-a for a,b in cols if b-a>=max(5,extent*.5)]
    if not 1<=len(widths)<=8 or max(widths)>2*extent or max(widths)>1.8*min(widths):return None
    labels,count=ndimage.label(ink,np.ones((3,3),bool))
    if not 8<=count<=8192:return None
    areas=np.bincount(labels.ravel(),minlength=count+1);eligible=[]
    for i,sl in enumerate(ndimage.find_objects(labels),1):
        if sl is None:continue
        h,w=sl[0].stop-sl[0].start,sl[1].stop-sl[1].start
        if min(h,w)>=3 and .08<=areas[i]/(h*w)<=.85:eligible.append(int(areas[i]))
    if len(eligible)<8 or sum(eligible)<.6*int(ink.sum()):return None
    return {'visible_height':extent,'columns':len(widths),
            'ink_coverage':round(sum(eligible)/int(ink.sum()),4)}


def source_style(reference, cleaned, support, readable):
    """Faint pigment requires localized evidence on an unchanged uniform background."""
    try:
        return core.analyze_style(reference, cleaned, support)
    except ValueError as exc:
        if not readable or not str(exc).startswith('Too few text pixels'): raise
        original_error = exc
    owned = support > .1
    delta = np.max(np.abs(reference-cleaned), axis=2)
    outside = ~ndimage.binary_dilation(owned, iterations=2)
    if (owned.sum() < 32 or owned.mean() > .65 or outside.sum() < 16
            or np.quantile(delta[outside], .95) > 2/255): raise original_error
    background = np.median(cleaned.reshape(-1, 3), axis=0)
    if np.quantile(np.max(np.abs(cleaned-background), axis=2), .95) > 2/255: raise original_error
    contrast = float(np.quantile(delta[owned], .9))
    if not 4/255 <= contrast < .07: raise original_error
    threshold = max(3/255, contrast*.5)
    ink = owned & (delta >= threshold)
    if ink.sum() < 32: raise original_error
    signed = np.mean(reference-cleaned, axis=2)[ink]
    if max(np.mean(signed>0), np.mean(signed<0)) < .95: raise original_error
    style, raw = core.analyze_style(reference, cleaned, support, difference_threshold=threshold)
    analysis = json.loads(raw)
    analysis.update(low_contrast_source=True, difference_threshold=threshold,
                    evidence='localized consistent pigment on unchanged uniform background')
    return style, json.dumps(analysis, ensure_ascii=False)


def profile(reference, cleaned, support, font_name, foreground=None, difference_threshold=.07):
    ink = (support>.1) & (np.max(np.abs(reference-cleaned),axis=2) >= difference_threshold)
    if foreground is not None:
        pigment=ink & (np.max(np.abs(reference-np.asarray(foreground)),axis=2)<.2)
        if pigment.sum()>=8: ink=pigment
    if ink.sum()<8:
        raise ValueError('Too few source ink pixels to estimate typography')
    ys,xs = np.where(ink)
    rows = bands(ndimage.binary_closing(ink.sum(axis=1) >= max(1,ink.shape[1]*.002),structure=np.ones(3),border_value=0))
    cols = bands(ndimage.binary_closing(ink.sum(axis=0) >= max(1,ink.shape[0]*.002),structure=np.ones(3),border_value=0))
    width,height = int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1)
    vertical = height>width*1.8 and len(rows)>=2 and len(cols)<len(rows)
    direction = 'vertical_rtl' if vertical else 'horizontal'
    runs = cols if vertical else rows
    lengths = [b-a for a,b in runs if b-a>=3]
    # A disconnected period/antialias fragment is source ink, but must not
    # become another text row or halve the estimated glyph height.
    significant = [(a,b) for a,b in runs if b-a >= max(3,max(lengths,default=3)*.45)]
    lengths = [b-a for a,b in significant]
    visible = float(np.median(lengths)) if lengths else float(min(width,height))
    # Projection bands can collapse many staggered glyphs into one huge row.
    # Do not silently treat that connected extent as one font size.
    labels,count=ndimage.label(ink)
    extents=[max(sl[0].stop-sl[0].start,sl[1].stop-sl[1].start)
             for sl in ndimage.find_objects(labels,max_label=min(count,8192)) if sl is not None and
             min(sl[0].stop-sl[0].start,sl[1].stop-sl[1].start)>=3]
    component_extent=float(np.percentile(extents,90)) if len(extents)>=8 else None
    measurement_warning=('inconsistent_source_typography' if component_extent and visible>4*component_extent else None)
    columns=column_size(ink,cols,component_extent) if measurement_warning else None
    recovery=columns or (component_size(ink) if measurement_warning else None)
    if recovery:
        visible=recovery['visible_height'];measurement_warning=None
        if columns:
            direction='vertical_rtl';significant=cols
    path=core.font_path(font_name,'')
    from pathlib import Path
    stat=Path(path).stat();coverage=core._font_coverage(path,stat.st_mtime_ns,stat.st_size)
    # A font covering Latin/other target text need not contain Korean. Keep
    # the old Korean probe where supported, otherwise use a real covered glyph.
    probe=next((c for c in ('가','M','国') if ord(c) in coverage),None)
    if probe is None:
        probe=next((chr(c) for c in sorted(coverage) if chr(c).isprintable() and not chr(c).isspace()),None)
    if probe is None:raise ValueError('Selected font has no measurable glyph')
    sample = ImageFont.truetype(path,100)
    box = sample.getbbox(probe)
    em = max(4,min(512,round(visible*100/max(1,box[3]-box[1]))))
    alignment = 'center'
    if not vertical and len(rows)>1:
        starts,ends,centers = [],[],[]
        for a,b in rows:
            xx=np.where(ink[a:b].any(axis=0))[0]
            if len(xx):
                starts.append(xx.min());ends.append(xx.max());centers.append((xx.min()+xx.max())/2)
        variation = [float(np.std(v)) for v in (starts,centers,ends)]
        alignment = ('left','center','right')[int(np.argmin(variation))]
    return {'measurement_warning':measurement_warning,'measurement_method':'vertical_columns' if columns else 'component_consensus' if recovery else 'projection_bands',
            **({'component_recovery':recovery} if recovery else {}),
            'component_extent_p90':component_extent,'font_cap':em,'visible_height':round(visible,2),'direction':direction,
            'alignment':alignment,'line_count':max(1,len(significant)),
            'confidence':'heuristic; override ambiguous or rotated source',
            'ink_bbox':[int(xs.min()),int(ys.min()),width,height]}, ink


def scaled_style(style, scale, size):
    result=dict(style)
    result['size']=list(size)
    for key in ('outline_width','weight_px','shadow_x','shadow_y','shadow_blur'):
        result[key]=style[key]*scale
    return result


def validate_options(item,opts):
    """Invalid authored settings stay errors even if source quality is poor."""
    layout=item.get('layout',{})
    allowed={'direction','alignment','min_font','max_font','padding','line_spacing','tracking',
             'rotation','shear','supersample','max_lines','vertical_policy','wrap_policy'}
    if set(layout)-allowed:raise ValueError(f"{item['id']}: unknown layout option")
    values={**layout,**opts}
    choices={'mode':MODES,'direction':DIRECTIONS,'fit_policy':FIT_POLICIES,'line_breaks':LINE_BREAKS,
             'alignment':('left','center','right'),'vertical_policy':('simple','typographic'),
             'wrap_policy':('greedy','balanced')}
    for key,valid in choices.items():
        if key in values and values[key] not in valid:raise ValueError(f"{item['id']}: invalid {key}")
    for key,lo,hi in [('font_cap',4,512),('max_font',4,512),('min_font',4,512),
                      ('padding',0,32),('max_lines',0,64),('supersample',1,4)]:
        if key in values:core.integer(values[key],lo,hi,key)
    for key,lo,hi in [('min_scale',.2,1),('rotation',-180,180),('shear',-.6,.6),
                      ('bend',-256,256),('line_spacing',.5,3),('tracking',-4,32)]:
        if key in values:core.finite(values[key],lo,hi,key)
    for key in ('respect_bubbles','require_bubble'):
        if key in values and type(values[key]) is not bool:raise ValueError(f"{item['id']}: invalid {key}")


def bubble_rect(mask, source, shape, padding):
    """Largest sampled centred rectangle fully inside one supplied bubble component."""
    x,y,w,h=source
    selected=mask>.5
    labels,_=ndimage.label(selected)
    cx,cy=x+w//2,y+h//2
    label=int(labels[cy,cx])
    if not label:
        return None
    component=labels==label
    # A neighbour's bubble may never be selected from centre alone.
    if component[y:y+h,x:x+w].mean()<.95:
        return None
    safe=ndimage.binary_erosion(component,iterations=max(1,padding),border_value=0)
    maxw,minx=min(shape[1],w*3),max(0,cx-w*3//2)
    maxx=min(shape[1],cx+w*3//2+1)
    maxhalf=min(cy,shape[0]-1-cy,max(h,h*3//2))
    common=np.ones(maxx-minx,bool);best=None;area=0
    # Intersection by row pair avoids materializing a 3-D candidate array.
    for half in range(maxhalf+1):
        common &= safe[cy-half,minx:maxx] & safe[cy+half,minx:maxx]
        center=cx-minx
        if not common[center]:
            break
        lo=center
        while lo>0 and common[lo-1]: lo-=1
        hi=center+1
        while hi<len(common) and common[hi]: hi+=1
        left,right=minx+lo,minx+hi
        top,bottom=cy-half,cy+half+1
        if left<=x and right>=x+w and top<=y and bottom>=y+h:
            current=(right-left)*(bottom-top)
            if current>area and current<=core.MAX_REGION_PIXELS:
                best=[left,top,right-left,bottom-top];area=current
    return best


def detected_bubble_rect(result, source, shape, padding):
    """Use a single actual RF-DETR bubble mask; never a box or union of neighbours."""
    from ..mask_nodes import _decode_mask
    x,y,w,h=source
    candidates=[]
    for item in result['detections']:
        if item.get('label')!='bubble' or not isinstance(item.get('mask'),dict): continue
        raw=item['mask']
        a,b,c,d=(raw.get(k) for k in ('x','y','width','height'))
        if any(type(v) is not int for v in (a,b,c,d)): raise ValueError('Invalid detected bubble bounds')
        if a<=x and b<=y and a+c>=x+w and b+d>=y+h:
            candidates.append(raw)
    if len(candidates)>64: raise ValueError('Too many enclosing bubble masks')
    for raw in sorted(candidates,key=lambda m:m['width']*m['height']):
        local,(a,b,c,d)=_decode_mask(raw,shape[1],shape[0])
        page=np.zeros(shape[:2],np.float32)
        page[b:b+d,a:a+c]=local
        rect=bubble_rect(page,source,shape,padding)
        if rect is not None: return rect
    return None


def _curve(layer,alpha,bend):
    if not bend:
        return layer,alpha
    h,w=alpha.shape
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    offset=bend*(1-((xx-(w-1)/2)/max(1,(w-1)/2))**2)
    coordinates=np.array([yy-offset,xx])
    premult=layer*alpha[...,None]
    warped_a=ndimage.map_coordinates(alpha,coordinates,order=1,mode='constant')
    warped=np.stack([ndimage.map_coordinates(premult[...,c],coordinates,order=1,mode='constant') for c in range(3)],axis=-1)
    output=np.divide(warped,warped_a[...,None],out=np.zeros_like(warped),where=warped_a[...,None]>1e-6)
    return output,warped_a


def build_plan(original,cleaned,source_mask,document,default_font='NanumGothic-Bold.ttf',
               mode='source',direction='auto',min_font=10,min_scale=.55,padding=2,
               region_options_json='{}',bubble_mask=None,detection_result=None,line_breaks='preserve',
               fit_policy='source_ratio',respect_bubbles=False,page_direction=None,oriented_fit=False,bubble_failure_policy='stop',
               fit_failure_policy='stop'):
    original,cleaned=core.rgb(original),core.rgb(cleaned)
    if original.shape!=cleaned.shape: raise ValueError('Original and cleaned dimensions differ')
    support=core.mask_array(source_mask,original.shape[:2])
    data=core.parse_regions(document,original.shape)
    if mode not in MODES or direction not in DIRECTIONS: raise ValueError('Invalid lettering mode/direction')
    if bubble_failure_policy not in ('stop','preserve_review'):raise ValueError('Invalid bubble failure policy')
    if fit_failure_policy not in ('stop','preserve_review'):raise ValueError('Invalid lettering fit failure policy')
    if page_direction is not None and page_direction not in DIRECTIONS:
        raise ValueError('Invalid page lettering direction')
    forced_direction=page_direction if page_direction not in (None,'auto') else None
    if line_breaks not in LINE_BREAKS: raise ValueError('Invalid line break policy')
    if fit_policy not in FIT_POLICIES: raise ValueError('Invalid lettering fit policy')
    if type(respect_bubbles) is not bool:raise ValueError('Invalid bubble containment switch')
    core.integer(min_font,4,128,'min_font');core.finite(min_scale,.2,1,'min_scale')
    core.integer(padding,0,32,'padding')
    if not isinstance(region_options_json,str) or len(region_options_json.encode('utf-8'))>262144:
        raise ValueError('Region overrides exceed 256 KiB')
    overrides=json.loads(region_options_json)
    ids={r['id'] for r in data['regions']}
    orientations=data.get('source_orientation',{})
    if not isinstance(orientations,dict) or set(orientations)-ids:raise ValueError('Invalid source orientation IDs')
    if not isinstance(overrides,dict) or set(overrides)-ids: raise ValueError('Overrides need existing region IDs')
    if bubble_mask is not None: bubble_mask=core.mask_array(bubble_mask,original.shape[:2])
    if detection_result is not None:
        if not isinstance(detection_result,dict) or detection_result.get('protocol')!=1 or not isinstance(detection_result.get('detections'),list):
            raise ValueError('Invalid bubble detection response')
        if (detection_result.get('image_width'),detection_result.get('image_height'))!=(original.shape[1],original.shape[0]):
            raise ValueError('Bubble detections belong to a different page size')
    plan={'version':1,'cleaned':cleaned.copy(),'regions':[], 'fit_failure_policy':fit_failure_policy,
          'page_direction':page_direction,'needs_review':bool(data.get('needs_review'))}
    if fit_failure_policy == 'preserve_review':
        plan['original'] = original.copy()
    protected=boundary_review.boxes(data,original.shape[1],original.shape[0])
    if detection_result is not None:
        detected=boundary_review.boxes(detection_result,original.shape[1],original.shape[0])
        # OCR geometry/quality review may add protection after detection.
        # Every original detector guard must survive; extra guards only remove
        # edit permissions and are valid downstream evidence.
        if any(box not in protected for box in detected):
            raise ValueError('Boundary protection missing or changed in lettering document')
    boundary_review.restore(plan['cleaned'],original,protected)
    preserved=core.source_preservation_boxes(data,original.shape)
    boundary_review.restore(plan['cleaned'],original,preserved)
    plan['boundary_review_required']=bool(protected)
    plan['protected_boxes_pixels']=protected+preserved
    plan['preserved_punctuation']=data.get('preserved_punctuation',[])
    plan['source_preservation']=data.get('source_preservation',[])
    plan['lettering_review']=[]
    def preserve_item(item,diagnostic,reason='unverified_bubble_ownership'):
        x,y,w,h=core.bbox(item.get('source_edit_bbox',item.get('restore_bounds',item.get('bbox',item.get('source')))),original.shape)
        box=[x,y,x+w,y+h]
        boundary_review.restore(plan['cleaned'],original,[box])
        plan['protected_boxes_pixels'].append(box)
        plan['needs_review']=True
        plan['lettering_review'].append({'id':item['id'],'parent_id':item.get('parent_id',item['id']),
            'bbox_pixels':box,'reason':reason,'diagnostic':diagnostic})
    # Validate the page index once; decode only candidate interiors belonging
    # to active text owners. Unrelated tiled bubbles do not spend a fit budget.
    bubble_index=(bubble_constraints.RegionCandidates(bubble_mask,detection_result,original.shape)
                  if respect_bubbles or mode=='bubble' or any(v.get('respect_bubbles') or v.get('require_bubble') or v.get('mode')=='bubble'
                                            for v in overrides.values() if isinstance(v,dict)) else [])
    reports=[]
    preview=Image.fromarray((original*255).round().astype('uint8'))
    draw=ImageDraw.Draw(preview)
    total_area=0
    for item in data['regions']:
        ident=item['id'];opts=overrides.get(ident,{})
        allowed={'font','mode','direction','font_cap','min_font','min_scale','alignment','rotation','shear','bend','padding','max_lines','line_spacing','tracking','line_breaks','fit_policy','respect_bubbles','require_bubble'}
        if not isinstance(opts,dict) or set(opts)-allowed: raise ValueError(f'{ident}: unknown typography override')
        validate_options(item,opts)
        selected_mode=opts.get('mode',mode)
        if selected_mode not in MODES:raise ValueError(f'{ident}: invalid mode')
        font=opts.get('font',item.get('font',default_font))
        try:
            font,font_fallback=core.resolve_font(font,item['text'])
        except core.FontCoverageError as exc:
            if fit_failure_policy=='stop' or opts.get('mode',mode)=='strict':
                raise ValueError(f'{ident}: {exc}') from None
            preserve_item(item,exc.diagnostic,'unsupported_translation_glyphs')
            continue
        ref,clean,mask,_=core.crop_region(original,cleaned,support,item['bbox'])
        if ident in data.get('source_owners',{}):
            from ..source_partition import _local
            mask=mask*_local(data['source_owners'][ident],item['bbox'],original.shape[1],original.shape[0])
        if item.get('frame_quad'):
            owned=Image.new('L',(ref.shape[1],ref.shape[0]));x,y,_,_=item['bbox']
            ImageDraw.Draw(owned).polygon([(a-x,b-y) for a,b in item['frame_quad']],fill=255)
            mask=mask*(np.asarray(owned)>0)
        policy=opts.get('fit_policy',fit_policy)
        if policy not in FIT_POLICIES: raise ValueError(f'{ident}: invalid fit policy')
        try:
            style,analysis=source_style(ref,clean,mask,policy=='readable' and selected_mode!='strict')
            difference_threshold=json.loads(analysis).get('difference_threshold',.07)
            measured,ink=profile(ref,clean,mask,font,style['foreground'],difference_threshold)
        except ValueError as exc:
            if (fit_failure_policy != 'preserve_review' or opts.get('mode',mode) == 'strict' or
                    not str(exc).startswith(('Too few text pixels', 'Too few source ink pixels'))):
                raise
            preserve_item(item,{'code':'insufficient_source_style_pixels'},'insufficient_source_style_pixels')
            continue
        source_angle=0
        if ident in orientations:
            entry=orientations[ident]
            if not isinstance(entry,dict):raise ValueError('Invalid source orientation')
            source_angle=entry.get('source_angle')
            core.finite(source_angle,-25,25,'source_angle')
            from ..text_geometry import rotation_pixels
            if rotation_pixels((ref.shape[1],ref.shape[0]),source_angle)>8*1024*1024:
                raise ValueError('Rectified typography reference exceeds 8 Mi pixels')
            # Typography measurement shares OCR's rectified frame. Bubble
            # ownership and the final glyph alpha still use original pixels.
            def rotated(value,mode):
                raster=Image.fromarray((value*255).round().astype('uint8'),mode)
                return np.asarray(raster.rotate(-source_angle,Image.Resampling.NEAREST if mode=='L' else Image.Resampling.BICUBIC,
                                               expand=True),np.float32)/255
            try:
                rectified,_=profile(rotated(ref,'RGB'),rotated(clean,'RGB'),rotated(mask,'L'),font,style['foreground'],difference_threshold)
            except ValueError as exc:
                if (fit_failure_policy!='preserve_review' or selected_mode=='strict' or
                        not str(exc).startswith(('Too few text pixels','Too few source ink pixels'))):raise
                preserve_item(item,{'code':'insufficient_rectified_style_pixels'},'insufficient_source_style_pixels')
                continue
            measured=rectified
        if measured.get('measurement_warning') and 'font_cap' not in opts and 'max_font' not in item.get('layout',{}):
            if fit_failure_policy=='stop' or selected_mode=='strict':
                raise ValueError(f'{ident}: inconsistent source typography; review crop and mask')
            preserve_item(item,{'code':'inconsistent_source_typography','measured_font_cap':measured['font_cap'],
                'component_extent_p90':measured['component_extent_p90']},'inconsistent_source_typography')
            continue
        style=core.adjust_style(style,**item.get('style',{}))
        layout=dict(item.get('layout',{}))
        # Old JSON controls remain usable; all values are validated by the renderer.
        supplied_direction=opts.get('direction',layout.pop('direction',page_direction or direction))
        if supplied_direction not in DIRECTIONS: raise ValueError(f'{ident}: invalid direction')
        actual_direction=(forced_direction or
                          (measured['direction'] if supplied_direction=='auto' else supplied_direction))
        if source_angle and actual_direction=='horizontal' and 'rotation' not in opts:
            layout.setdefault('rotation',source_angle)
        cap=opts.get('font_cap',layout.pop('max_font',measured['font_cap']))
        core.integer(cap,4,512,'font_cap')
        ratio=opts.get('min_scale',min_scale);core.finite(ratio,.2,1,'min_scale')
        floor=opts.get('min_font',layout.pop('min_font',min_font));core.integer(floor,4,512,'min_font')
        absolute_floor=floor
        source_enlarged=False
        if (floor>cap and policy=='readable' and selected_mode!='strict'
                and 'font_cap' not in opts and 'max_font' not in item.get('layout',{})):
            cap=floor
            source_enlarged=True
        adjustments={'source_enlarged':source_enlarged,
                     'low_contrast_source':bool(json.loads(analysis).get('low_contrast_source'))}
        if any(adjustments.values()): plan['needs_review']=True
        floor=max(floor,math.ceil(cap*ratio))
        if floor>cap:
            if fit_failure_policy=='stop' or selected_mode=='strict':
                raise ValueError(f'{ident}: source size {cap}px is below readability minimum {floor}px; review typography')
            preserve_item(item,{'code':'source_below_readability_minimum','source_cap':cap,
                'minimum_font':floor,'measured_font_cap':measured['font_cap'],
                'cap_origin':'override' if 'font_cap' in opts or 'max_font' in item.get('layout',{}) else 'source_measurement',
                'text_preserved':True},'source_below_readability_minimum')
            continue
        policy=opts.get('fit_policy',fit_policy)
        if policy not in FIT_POLICIES: raise ValueError(f'{ident}: invalid fit policy')
        # Explicit per-region scaling constraints and strict layouts stay hard.
        fallback_floor=(absolute_floor if policy=='readable' and selected_mode!='strict'
                        and 'min_scale' not in opts else floor)
        breaks=opts.get('line_breaks',line_breaks)
        if breaks not in LINE_BREAKS: raise ValueError(f'{ident}: invalid line break policy')
        flow=breaks=='reflow' and actual_direction=='horizontal' and selected_mode!='strict'
        # Model-generated source line breaks must not become short columns when
        # the user asks for uniform vertical output. Explicit preserve stays hard.
        reflow=flow or (forced_direction is not None and breaks=='reflow' and selected_mode!='strict')
        rendered_text=reflow_text(item['text']) if reflow else item['text']
        source=list(item['bbox'])
        bounds=source
        pad=opts.get('padding',layout.pop('padding',padding));core.integer(pad,0,32,'padding')
        respect=opts.get('respect_bubbles',respect_bubbles)
        require=opts.get('require_bubble',False)
        if type(respect) is not bool or type(require) is not bool:raise ValueError(f'{ident}: invalid bubble controls')
        guard=None;guard_report={'status':'disabled'}
        if respect or require or selected_mode=='bubble':
            try:
                bubble_items=bubble_index.for_region(source,ink)
                guard,guard_report=bubble_constraints.constrain(ink,source,bubble_items,original.shape,pad,
                                                               selected_mode=='bubble')
            except bubble_constraints.BubbleContainmentError as exc:
                if bubble_failure_policy=='stop' or require:raise ValueError(f'{ident}: {exc}') from None
                preserve_item(item,exc.diagnostic)
                continue
            if require and guard is None:raise ValueError(f'{ident}: no verified enclosing bubble; require_bubble is enabled')
        bubble=None
        if selected_mode=='bubble' and guard is not None:
            bubble=guard['rectangle']
        warning=None
        if selected_mode=='bubble' and bubble is None: warning='No enclosing bubble mask; source frame retained'
        curve=opts.get('bend',0.);core.finite(curve,-256,256,'bend')
        render_options={'direction':actual_direction,
                        'alignment':opts.get('alignment',layout.pop('alignment',measured['alignment'])),
                        'padding':pad,'supersample':2,'vertical_policy':'typographic',
                        'wrap_policy':'greedy' if flow else 'balanced',**layout}
        for key in ('rotation','shear','line_spacing','tracking'):
            if key in opts: render_options[key]=opts[key]
        original_lines=min(64,measured['line_count'])
        forced_lines=opts.get('max_lines',render_options.pop('max_lines',0))
        core.integer(forced_lines,0,64,'max_lines')
        phases=[(source,forced_lines or (0 if reflow else original_lines),'source-flow' if reflow else 'source-lines')]
        if selected_mode!='strict' and not forced_lines and not reflow: phases.append((source,0,'reflow'))
        if bubble and bubble!=source: phases.append((bubble,forced_lines,'bubble'))
        if guard and guard['rectangle']!=source:
            phases.append((guard['rectangle'],forced_lines or (original_lines if selected_mode=='strict' else 0),
                           'bubble-interior'))
        if (selected_mode=='bubble' and flow and bubble and bubble[2]>=source[2]*1.5
                and source[3]>source[2]*1.8 and not forced_lines):
            # Explicit bubble mode plus horizontal reflow: use verified width
            # before accepting a stack of one-character lines in a source column.
            phases.sort(key=lambda phase:0 if phase[2]=='bubble' else 1)
        prepared={'id':ident,'parent_id':item.get('parent_id',ident),
                  'restore_bounds':list(core.bbox(item.get('source_edit_bbox',source), original.shape)),
                  'text':rendered_text,'original_text':item['text'],'line_breaks':breaks,
                  'font':font,'font_fallback':font_fallback,'style':style,'source':source,
                  'phases':phases,'cap':cap,'floor':floor,'fallback_floor':fallback_floor,
                  'style_cap':measured['font_cap'] if source_enlarged else cap,
                  'readability_adjustments':adjustments,
                  'fit_policy':policy,'mode':selected_mode,'options':render_options,'bend':curve,
                  'bubble_guard':guard,'bubble_containment':guard_report,
                  'profile':measured,'analysis':json.loads(analysis),'warning':warning}
        if oriented_fit and (item.get('frame_quad') or render_options.get('rotation')):
            from . import frame
            quad=item.get('frame_quad') or frame.rectangle(ink,source,render_options.get('rotation',0),pad+2)
            if item.get('frame_quad') and 'rotation' in opts:
                q=np.asarray(quad);center=q.mean(axis=0)
                current=math.degrees(math.atan2(-(q[1,1]-q[0,1]),q[1,0]-q[0,0]))
                angle=math.radians(opts['rotation']-current)
                q=(q-center)@np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])+center
                quad=q.tolist()
            frame.geometry(quad);prepared['frame_quad']=quad
            draw.line([tuple(p) for p in quad]+[tuple(quad[0])],fill=(70,140,255),width=3)
        # Bound repeated search work and plan memory, including optional expanded rectangles.
        total_area+=max(max(b[2]*b[3] for b,_,_ in phases),guard['mask'].size if guard else 0)
        if total_area>core.MAX_TYPOGRAPHY_PIXELS: raise ValueError('Total typography area exceeds 32 Mi pixels')
        plan['regions'].append(prepared)
        x,y,w,h=source
        draw.rectangle((x,y,x+w-1,y+h-1),outline=(255,180,0),width=2)
        if bubble:
            x,y,w,h=bubble
            draw.rectangle((x,y,x+w-1,y+h-1),outline=(0,200,220),width=2)
        if guard:
            x,y,w,h=guard['rectangle']
            draw.rectangle((x,y,x+w-1,y+h-1),outline=(40,220,80),width=2)
        reports.append({'id':ident,'source':source,'source_profile':measured,'font':font,
                        'font_cap':cap,'min_font':floor,'mode':selected_mode,'font_fallback':font_fallback,
                        'fallback_min_font':fallback_floor,'fit_policy':policy,
                        'readability_adjustments':adjustments,
                        'bubble_containment':guard_report,
                        'direction':actual_direction,'line_breaks':breaks,'soft_wraps_reflowed':reflow,
                        'style_analysis':json.loads(analysis),
                        'transform':{key:render_options.get(key,0) for key in ('rotation','shear')},
                        'bend':curve,
                        'warning':warning})
    # A restored region also protects its overlapping neighbours. Otherwise a
    # later translation could cover the restored source, or fail on a new mask.
    pending=True
    while pending and plan['lettering_review']:
        pending=False
        for region in list(plan['regions']):
            x,y,w,h=region['restore_bounds'];box=[x,y,x+w,y+h]
            if any(boundary_review.intersects(box,r['bbox_pixels']) for r in plan['lettering_review']):
                nonbubble=any(r['reason']!='unverified_bubble_ownership' and boundary_review.intersects(box,r['bbox_pixels'])
                              for r in plan['lettering_review'])
                if nonbubble and region['mode']=='strict':
                    raise ValueError(f"{region['id']}: strict lettering overlaps a preserved edit frame")
                preserve_item(region,{'code':'overlaps_preserved_lettering_region' if nonbubble else 'overlaps_preserved_bubble_region'},
                              'overlaps_preserved_lettering_region' if nonbubble else 'unverified_bubble_ownership')
                plan['regions'].remove(region);reports=[r for r in reports if r['id']!=region['id']];pending=True
    for item in plan['lettering_review']:
        a,b,c,d=item['bbox_pixels'];draw.rectangle((a,b,c-1,d-1),outline=(255,60,80),width=3)
    for a,b,c,d in preserved:
        draw.rectangle((a,b,c-1,d-1),outline=(80,160,255),width=2)
    for a,b,c,d in protected:
        draw.rectangle((a,b,c-1,d-1),outline=(255,60,80),width=3)
    report={'schema':1,'regions':reports,'preview':'orange=source frame; cyan=expanded bubble frame; green=safe bubble interior; red=preserved boundary review; blue=preserved source',
            'protected_boxes_pixels':plan['protected_boxes_pixels'],'needs_review':bool(protected) or plan['needs_review'],
            'lettering_review':plan['lettering_review'],
            'page_direction':page_direction,
            'preserved_punctuation':plan['preserved_punctuation'],
            'source_preservation':plan['source_preservation'],
            **({'page_status':'no_text_detected','lettering_skipped':True} if not reports and not preserved and not plan['lettering_review'] else {}),
            **({'lettering_skipped':True,'skip_reason':review_skip_reason(plan['lettering_review'])} if not reports and plan['lettering_review'] else {}),
            **({'lettering_skipped':True,'skip_reason':'source_preserved'} if not reports and preserved else {}),
            'font_identity':'selected font; source size/direction/alignment are measured estimates',
            'curves':'manual bend only; no automatic curve reconstruction'}
    return plan,np.asarray(preview,np.float32)/255,json.dumps(report,ensure_ascii=False,indent=2)


def _placement_permissions(region, regions, bounds, shape, protected):
    x,y,w,h=core.bbox(bounds,shape)
    guard=region.get('bubble_guard')
    allowed=bubble_constraints.canvas_mask(guard,bounds) if guard else np.ones((h,w),bool)
    for a,b,c,d in protected:
        left,top,right,bottom=max(x,a),max(y,b),min(x+w,c),min(y+h,d)
        if left<right and top<bottom:allowed[top-y:bottom-y,left-x:right-x]=False
    owned,neighbours=placement.reserve_sources(region,regions,bounds)
    return allowed & owned,neighbours


class LetteringFitError(ValueError):
    def __init__(self,message,diagnostic):
        super().__init__(message)
        self.diagnostic=diagnostic


def _render_plan_once(plan):
    if not isinstance(plan,dict) or plan.get('version')!=1 or not isinstance(plan.get('regions'),list):
        raise ValueError('Expected MangaLetterPlan output')
    if len(plan['regions'])>core.MAX_LETTERING_REGIONS:
        raise ValueError('Too many active lettering regions')
    result=core.rgb(plan['cleaned']).copy()
    page_alpha=np.zeros(result.shape[:2],np.float32)
    # A byte per page pixel also identifies the actual colliding paragraph.
    occupied=np.zeros(result.shape[:2],np.uint8)
    reports=[]
    staged=[]
    staged_pixels=0
    protected=plan.get('protected_boxes_pixels',[])
    for index,region in enumerate(plan['regions']):
        chosen=None;reason='no candidate'
        reserved_ids=set();collision_ids=set();attempts=0
        sx,sy,sw,sh=region['source']
        coincident=any(other is not region and
            (other['source'][0]+other['source'][2]/2,other['source'][1]+other['source'][3]/2)==(sx+sw/2,sy+sh/2)
            for other in plan['regions'])
        phases=[(bounds,lines,phase,region['cap'],region['floor']) for bounds,lines,phase in region['phases']]
        fallback_floor=region.get('fallback_floor',region['floor'])
        if fallback_floor<region['floor']:
            phases.extend((bounds,lines,phase+'-readable',region['floor']-1,fallback_floor)
                          for bounds,lines,phase in region['phases'])
        for bounds,lines,phase,ceiling,floor in phases:
            bx,by,bw,bh=core.bbox(bounds,result.shape)
            permission,neighbours=_placement_permissions(region,plan['regions'],bounds,result.shape,protected)
            reserved_ids.update(neighbours)
            free=permission & (occupied[by:by+bh,bx:bx+bw]==0)
            variants=[(bounds,phase)]
            # Keep explicit strict composition and unresolved coincident source
            # anchors on the hard failure path. A rotated local frame requires
            # its own local-space layout; do not replace it with an axis box.
            if region.get('mode')!='strict' and not region.get('frame_quad') and not coincident:
                variants.extend((rect,phase+'-free-space') for rect in placement.free_rectangles(free,bounds,region['source']) if rect!=bounds)
            options=dict(region['options'])
            # Reserve vertical clearance before bending, never crop the warped glyph.
            options['padding']=options['padding']+math.ceil(abs(region['bend']))
            for size in range(ceiling,floor-1,-1):
                scale=size/region.get('style_cap',region['cap'])
                for candidate,candidate_phase in variants:
                    x,y,w,h=core.bbox(candidate,result.shape)
                    style=scaled_style(region['style'],scale,(w,h))
                    attempts+=1
                    try:
                        if region.get('frame_quad') and phase.startswith(('source','reflow')):
                            from . import frame
                            actual_bounds,layer,alpha,render=frame.render(region['text'],style,region['font'],region['frame_quad'],result.shape,
                                min_font=size,max_font=size,max_lines=lines,**options)
                        else:
                            actual_bounds=candidate
                            layer,alpha,render=core.render_text(region['text'],style,font_name=region['font'],
                                min_font=size,max_font=size,max_lines=lines,**options)
                            render=json.loads(render)
                    except ValueError as exc:
                        if any(s in str(exc) for s in ('does not fit','leave no space','glyph leaves page boundary',
                                                       'Weight erosion removed all glyphs','Empty oriented glyph')):
                            reason=str(exc);continue
                        raise
                    x,y,w,h=core.bbox(actual_bounds,result.shape)
                    if not region.get('frame_quad'):
                        allowed=permission[y-by:y-by+h,x-bx:x-bx+w]
                    else:
                        allowed,neighbours=_placement_permissions(region,plan['regions'],actual_bounds,result.shape,protected)
                        reserved_ids.update(neighbours)
                    layer,alpha=_curve(layer,alpha,region['bend'])
                    active=alpha>.01
                    if not active.any(): reason='empty glyph';continue
                    if active[0].any() or active[-1].any() or active[:,0].any() or active[:,-1].any():
                        reason='transformed glyph touches canvas boundary';continue
                    if np.any((alpha>0)&~allowed):
                        reason='lettering would leave the verified bubble mask or enter preserved boundary pixels / neighbouring source reservation';continue
                    conflicts=np.unique(occupied[y:y+h,x:x+w][active])
                    if conflicts.any():
                        collision_ids.update(plan['regions'][int(value)-1]['id'] for value in conflicts if value)
                        reason='neighbouring translation collision';continue
                    chosen=(actual_bounds,layer,alpha,render,style,scale,candidate_phase)
                    break
                if chosen is not None:break
            if chosen is not None: break
        if chosen is None:
            conflicts=sorted(reserved_ids|collision_ids)
            diagnostic={'region_id':region['id'],'reason':reason,'source_bounds_xywh':region['source'],
                'conflicting_region_ids':conflicts,'collision_region_ids':sorted(collision_ids),
                'reserved_source_region_ids':sorted(reserved_ids),'placement_attempts':attempts,
                'coincident_source_anchors':coincident,'minimum_font':fallback_floor}
            raise LetteringFitError(f"{region['id']}: no safe lettering fit above {fallback_floor}px ({reason}); "
                             f"source_cap={region['cap']}px, source_floor={region['floor']}px, "
                             f"direction={region['options']['direction']}, bounds_xywh={region['source']}; "
                             f"conflicting_region_ids={conflicts}, placement_attempts={attempts}; "
                             'review text, direction or region options',diagnostic)
        bounds,layer,alpha,render,style,scale,phase=chosen
        place={'version':1,'bbox_xywh':bounds,'page_size':[result.shape[1],result.shape[0]]}
        staged_pixels+=alpha.size
        if staged_pixels>core.MAX_TYPOGRAPHY_PIXELS:raise ValueError('Staged lettering exceeds typography pixel budget')
        staged.append((layer,alpha,place))
        x,y,w,h=core.bbox(bounds,result.shape)
        active=np.zeros(result.shape[:2],bool);active[y:y+h,x:x+w]=alpha>.01
        occupied[ndimage.binary_dilation(active,iterations=2)]=index+1
        reports.append({'id':region['id'],'source_profile':region['profile'],'bbox':bounds,
                        'font_fallback':region.get('font_fallback'),
                        'readability_adjustments':region.get('readability_adjustments',{}),
                        'fit_phase':phase,'scale':round(scale,4),'render':render,
                        'fit_policy':region.get('fit_policy','source_ratio'),
                        'source_floor':region['floor'],'minimum_font':fallback_floor,
                        'placement':{'policy':'reserve_neighbour_source_frames',
                            'reserved_source_region_ids':sorted(reserved_ids),'attempts':attempts,
                            'repositioned':phase.endswith('-free-space')},
                        'source_ratio_relaxed':render['font_size']<region['floor'],
                        'bubble_containment':region.get('bubble_containment',{'status':'disabled'}),
                        'original_text':region['original_text'],'line_breaks':region['line_breaks'],
                        'outline_width':style['outline_width'],'bend':region['bend'],'warning':('source_ratio_relaxed' if render['font_size']<region['floor'] else region['warning'])})
    # All source ownership and actual glyph alpha checks finish before the
    # first composite. A rejected attempt cannot leak partially placed layers.
    for layer,alpha,place in staged:
        result,changed=core.composite(result,layer,alpha,place)
        page_alpha=changed+page_alpha*(1-changed)
    return result,page_alpha,json.dumps({'schema':1,'regions':reports,
        'protected_boxes_pixels':protected,'needs_review':plan.get('boundary_review_required',bool(protected)) or plan.get('needs_review',False) or any(r['source_ratio_relaxed'] for r in reports),
        'page_direction':plan.get('page_direction'),
        'preserved_punctuation':plan.get('preserved_punctuation',[]),
        'source_preservation':plan.get('source_preservation',[]),
        'lettering_review':plan.get('lettering_review',[]),
        **({'page_status':'no_text_detected','lettering_skipped':True} if not reports and not (plan.get('source_preservation') or plan.get('preserved_punctuation') or plan.get('lettering_review')) else {}),
        **({'lettering_skipped':True,'skip_reason':review_skip_reason(plan['lettering_review'])} if not reports and plan.get('lettering_review') else {}),
        **({'lettering_skipped':True,'skip_reason':'source_preserved'} if not reports and (plan.get('source_preservation') or plan.get('preserved_punctuation')) else {}),
        'quality_scope':'geometry/style approximation; OCR, translation and GPU cleanup require separate review'},
        ensure_ascii=False,indent=2)


def render_plan(plan):
    """Fit on a working copy; restore failed ownership groups before retrying.

    Actual style still uses the cleaned background. Failed fits never publish
    that erased source: restore the original edit frame and close all source
    overlaps, discard prior glyphs, and fit independent regions again.
    """
    policy = plan.get('fit_failure_policy', 'stop')
    if policy not in ('stop', 'preserve_review'):
        raise ValueError('Invalid lettering fit failure policy')
    if policy == 'stop':
        return _render_plan_once(plan)
    original = core.rgb(plan.get('original'))
    if original.shape != plan['cleaned'].shape:
        raise ValueError('Lettering recovery needs the same original page')
    working = {**plan, 'cleaned':plan['cleaned'].copy(), 'regions':list(plan['regions']),
               'protected_boxes_pixels':list(plan.get('protected_boxes_pixels', [])),
               'lettering_review':list(plan.get('lettering_review', []))}
    for _ in range(len(working['regions'])+1):
        try:
            return _render_plan_once(working)
        except LetteringFitError as exc:
            failed = next((r for r in working['regions'] if r['id'] == exc.diagnostic['region_id']), None)
            if failed is None or failed.get('mode') == 'strict':
                raise
            parents = {failed.get('parent_id', failed['id'])}
            blocked = set()
            boxes = []
            changed = True
            while changed:
                changed = False
                for region in working['regions']:
                    if region['id'] in blocked:
                        continue
                    x,y,w,h = region.get('restore_bounds', region['source'])
                    box = [x,y,x+w,y+h]
                    if region.get('parent_id', region['id']) in parents or any(boundary_review.intersects(box, b) for b in boxes):
                        blocked.add(region['id']);parents.add(region.get('parent_id', region['id']))
                        boxes.append(box);changed = True
            if any(r['id'] in blocked and r.get('mode') == 'strict' for r in working['regions']):
                raise
            boundary_review.restore(working['cleaned'], original, boxes)
            working['protected_boxes_pixels'].extend(box for box in boxes if box not in working['protected_boxes_pixels'])
            for region in working['regions']:
                if region['id'] in blocked:
                    x,y,w,h = region.get('restore_bounds', region['source'])
                    working['lettering_review'].append({'id':region['id'], 'parent_id':region.get('parent_id', region['id']),
                        'bbox_pixels':[x,y,x+w,y+h], 'reason':'unfit_lettering_preserved',
                        'diagnostic':exc.diagnostic})
            working['regions'] = [r for r in working['regions'] if r['id'] not in blocked]
            working['needs_review'] = True
    raise ValueError('Lettering recovery did not converge')
