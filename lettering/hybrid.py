"""Source-capped lettering plans. CPU only; no image model rewrites characters."""
import json
import math
import re
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from . import core
from . import bubble_constraints
from .. import boundary_review

MODES = ('source', 'bubble', 'strict')
DIRECTIONS = ('auto', 'horizontal', 'vertical_rtl', 'vertical_ltr')
LINE_BREAKS = ('preserve','reflow')
FIT_POLICIES = ('source_ratio','readable')


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


def profile(reference, cleaned, support, font_name, foreground=None):
    ink = (support>.1) & (np.max(np.abs(reference-cleaned),axis=2) >= .07)
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
    sample = ImageFont.truetype(core.font_path(font_name,'가'),100)
    box = sample.getbbox('가')
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
    return {'font_cap':em,'visible_height':round(visible,2),'direction':direction,
            'alignment':alignment,'line_count':max(1,len(significant)),
            'confidence':'heuristic; override ambiguous or rotated source',
            'ink_bbox':[int(xs.min()),int(ys.min()),width,height]}, ink


def scaled_style(style, scale, size):
    result=dict(style)
    result['size']=list(size)
    for key in ('outline_width','weight_px','shadow_x','shadow_y','shadow_blur'):
        result[key]=style[key]*scale
    return result


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
               fit_policy='source_ratio',respect_bubbles=False):
    original,cleaned=core.rgb(original),core.rgb(cleaned)
    if original.shape!=cleaned.shape: raise ValueError('Original and cleaned dimensions differ')
    support=core.mask_array(source_mask,original.shape[:2])
    data=core.parse_regions(document,original.shape)
    if mode not in MODES or direction not in DIRECTIONS: raise ValueError('Invalid lettering mode/direction')
    if line_breaks not in LINE_BREAKS: raise ValueError('Invalid line break policy')
    if fit_policy not in FIT_POLICIES: raise ValueError('Invalid lettering fit policy')
    if type(respect_bubbles) is not bool:raise ValueError('Invalid bubble containment switch')
    core.integer(min_font,4,128,'min_font');core.finite(min_scale,.2,1,'min_scale')
    core.integer(padding,0,32,'padding')
    if not isinstance(region_options_json,str) or len(region_options_json.encode('utf-8'))>262144:
        raise ValueError('Region overrides exceed 256 KiB')
    overrides=json.loads(region_options_json)
    ids={r['id'] for r in data['regions']}
    if not isinstance(overrides,dict) or set(overrides)-ids: raise ValueError('Overrides need existing region IDs')
    if bubble_mask is not None: bubble_mask=core.mask_array(bubble_mask,original.shape[:2])
    if detection_result is not None:
        if not isinstance(detection_result,dict) or detection_result.get('protocol')!=1 or not isinstance(detection_result.get('detections'),list):
            raise ValueError('Invalid bubble detection response')
        if (detection_result.get('image_width'),detection_result.get('image_height'))!=(original.shape[1],original.shape[0]):
            raise ValueError('Bubble detections belong to a different page size')
    plan={'version':1,'cleaned':cleaned.copy(),'regions':[]}
    protected=boundary_review.boxes(data,original.shape[1],original.shape[0])
    if detection_result is not None:
        detected=boundary_review.boxes(detection_result,original.shape[1],original.shape[0])
        if detected and protected != detected:
            raise ValueError('Boundary protection missing or changed in lettering document')
    boundary_review.restore(plan['cleaned'],original,protected)
    punctuation=core.preserved_punctuation_boxes(data,original.shape)
    boundary_review.restore(plan['cleaned'],original,punctuation)
    plan['boundary_review_required']=bool(protected)
    plan['protected_boxes_pixels']=protected+punctuation
    plan['preserved_punctuation']=data.get('preserved_punctuation',[])
    # Prepare masks once, rather than decoding every detection for every text.
    bubble_items=(bubble_constraints.candidates(bubble_mask,detection_result,original.shape)
                  if respect_bubbles or any(v.get('respect_bubbles') or v.get('require_bubble')
                                            for v in overrides.values() if isinstance(v,dict)) else [])
    reports=[]
    preview=Image.fromarray((original*255).round().astype('uint8'))
    draw=ImageDraw.Draw(preview)
    total_area=0
    for item in data['regions']:
        ident=item['id'];opts=overrides.get(ident,{})
        allowed={'font','mode','direction','font_cap','min_font','min_scale','alignment','rotation','shear','bend','padding','max_lines','line_spacing','tracking','line_breaks','fit_policy','respect_bubbles','require_bubble'}
        if not isinstance(opts,dict) or set(opts)-allowed: raise ValueError(f'{ident}: unknown typography override')
        font=opts.get('font',item.get('font',default_font))
        font,font_fallback=core.resolve_font(font,item['text'])
        ref,clean,mask,_=core.crop_region(original,cleaned,support,item['bbox'])
        style,analysis=core.analyze_style(ref,clean,mask)
        measured,ink=profile(ref,clean,mask,font,style['foreground'])
        style=core.adjust_style(style,**item.get('style',{}))
        layout=dict(item.get('layout',{}))
        # Old JSON controls remain usable; all values are validated by the renderer.
        supplied_direction=opts.get('direction',layout.pop('direction',direction))
        if supplied_direction not in DIRECTIONS: raise ValueError(f'{ident}: invalid direction')
        actual_direction=measured['direction'] if supplied_direction=='auto' else supplied_direction
        cap=opts.get('font_cap',layout.pop('max_font',measured['font_cap']))
        core.integer(cap,4,512,'font_cap')
        ratio=opts.get('min_scale',min_scale);core.finite(ratio,.2,1,'min_scale')
        floor=opts.get('min_font',layout.pop('min_font',min_font));core.integer(floor,4,512,'min_font')
        absolute_floor=floor
        floor=max(floor,math.ceil(cap*ratio))
        if floor>cap: raise ValueError(f'{ident}: source size {cap}px is below readability minimum {floor}px; review typography')
        selected_mode=opts.get('mode',mode)
        if selected_mode not in MODES: raise ValueError(f'{ident}: invalid mode')
        policy=opts.get('fit_policy',fit_policy)
        if policy not in FIT_POLICIES: raise ValueError(f'{ident}: invalid fit policy')
        # Explicit per-region scaling constraints and strict layouts stay hard.
        fallback_floor=(absolute_floor if policy=='readable' and selected_mode!='strict'
                        and 'min_scale' not in opts else floor)
        breaks=opts.get('line_breaks',line_breaks)
        if breaks not in LINE_BREAKS: raise ValueError(f'{ident}: invalid line break policy')
        flow=breaks=='reflow' and actual_direction=='horizontal' and selected_mode!='strict'
        rendered_text=reflow_text(item['text']) if flow else item['text']
        source=list(item['bbox'])
        bounds=source
        pad=opts.get('padding',layout.pop('padding',padding));core.integer(pad,0,32,'padding')
        respect=opts.get('respect_bubbles',respect_bubbles)
        require=opts.get('require_bubble',False)
        if type(respect) is not bool or type(require) is not bool:raise ValueError(f'{ident}: invalid bubble controls')
        guard=None;guard_report={'status':'disabled'}
        if respect or require:
            try:
                guard,guard_report=bubble_constraints.constrain(ink,source,bubble_items,original.shape,pad,
                                                               selected_mode=='bubble')
            except ValueError as exc:raise ValueError(f'{ident}: {exc}') from None
            if require and guard is None:raise ValueError(f'{ident}: no verified enclosing bubble; require_bubble is enabled')
        bubble=None
        if selected_mode=='bubble' and bubble_mask is not None:
            bubble=bubble_rect(bubble_mask,source,original.shape,pad)
        if selected_mode=='bubble' and bubble_mask is None and detection_result is not None:
            bubble=detected_bubble_rect(detection_result,source,original.shape,pad)
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
        phases=[(source,forced_lines or (0 if flow else original_lines),'source-flow' if flow else 'source-lines')]
        if selected_mode!='strict' and not forced_lines and not flow: phases.append((source,0,'reflow'))
        if bubble and bubble!=source: phases.append((bubble,forced_lines,'bubble'))
        if guard and guard['rectangle']!=source:
            phases.append((guard['rectangle'],forced_lines or (original_lines if selected_mode=='strict' else 0),
                           'bubble-interior'))
        prepared={'id':ident,'text':rendered_text,'original_text':item['text'],'line_breaks':breaks,
                  'font':font,'font_fallback':font_fallback,'style':style,'source':source,
                  'phases':phases,'cap':cap,'floor':floor,'fallback_floor':fallback_floor,
                  'fit_policy':policy,'options':render_options,'bend':curve,
                  'bubble_guard':guard,'bubble_containment':guard_report,
                  'profile':measured,'analysis':json.loads(analysis),'warning':warning}
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
                        'bubble_containment':guard_report,
                        'direction':actual_direction,'line_breaks':breaks,'soft_wraps_reflowed':flow,
                        'warning':warning})
    for a,b,c,d in punctuation:
        draw.rectangle((a,b,c-1,d-1),outline=(80,160,255),width=2)
    for a,b,c,d in protected:
        draw.rectangle((a,b,c-1,d-1),outline=(255,60,80),width=3)
    report={'schema':1,'regions':reports,'preview':'orange=source frame; cyan=expanded bubble frame; green=safe bubble interior; red=preserved boundary review; blue=original dot punctuation',
            'protected_boxes_pixels':protected,'needs_review':bool(protected),
            'preserved_punctuation':plan['preserved_punctuation'],
            **({'page_status':'no_text_detected','lettering_skipped':True} if not reports and not punctuation else {}),
            **({'lettering_skipped':True,'skip_reason':'source_punctuation_preserved'} if not reports and punctuation else {}),
            'font_identity':'selected font; source size/direction/alignment are measured estimates',
            'curves':'manual bend only; no automatic curve reconstruction'}
    return plan,np.asarray(preview,np.float32)/255,json.dumps(report,ensure_ascii=False,indent=2)


def render_plan(plan):
    if not isinstance(plan,dict) or plan.get('version')!=1 or not isinstance(plan.get('regions'),list):
        raise ValueError('Expected MangaLetterPlan output')
    result=core.rgb(plan['cleaned']).copy()
    page_alpha=np.zeros(result.shape[:2],np.float32)
    occupied=np.zeros(result.shape[:2],bool)
    reports=[]
    protected=plan.get('protected_boxes_pixels',[])
    for region in plan['regions']:
        chosen=None;reason='no candidate'
        phases=[(bounds,lines,phase,region['cap'],region['floor']) for bounds,lines,phase in region['phases']]
        fallback_floor=region.get('fallback_floor',region['floor'])
        if fallback_floor<region['floor']:
            phases.extend((bounds,lines,phase+'-readable',region['floor']-1,fallback_floor)
                          for bounds,lines,phase in region['phases'])
        for bounds,lines,phase,ceiling,floor in phases:
            x,y,w,h=core.bbox(bounds,result.shape)
            guard=region.get('bubble_guard')
            allowed=bubble_constraints.canvas_mask(guard,[x,y,w,h]) if guard else None
            if protected:
                permitted=np.ones((h,w),bool)
                for a,b,c,d in protected:
                    left,top,right,bottom=max(x,a),max(y,b),min(x+w,c),min(y+h,d)
                    if left<right and top<bottom: permitted[top-y:bottom-y,left-x:right-x]=False
                allowed=permitted if allowed is None else allowed & permitted
            options=dict(region['options'])
            # Reserve vertical clearance before bending, never crop the warped glyph.
            options['padding']=options['padding']+math.ceil(abs(region['bend']))
            for size in range(ceiling,floor-1,-1):
                scale=size/region['cap']
                style=scaled_style(region['style'],scale,(w,h))
                try:
                    layer,alpha,render=core.render_text(region['text'],style,font_name=region['font'],
                        min_font=size,max_font=size,max_lines=lines,**options)
                except ValueError as exc:
                    if any(s in str(exc) for s in ('does not fit','leave no space')):
                        reason=str(exc);continue
                    raise
                layer,alpha=_curve(layer,alpha,region['bend'])
                active=alpha>.01
                if not active.any(): reason='empty glyph';continue
                if active[0].any() or active[-1].any() or active[:,0].any() or active[:,-1].any():
                    reason='transformed glyph touches canvas boundary';continue
                if allowed is not None and np.any((alpha>0)&~allowed):
                    reason='lettering would leave the verified bubble mask or enter preserved boundary pixels';continue
                if np.any(active & occupied[y:y+h,x:x+w]):
                    reason='neighbouring translation collision';continue
                chosen=(bounds,layer,alpha,json.loads(render),style,scale,phase)
                break
            if chosen is not None: break
        if chosen is None:
            raise ValueError(f"{region['id']}: no safe lettering fit above {fallback_floor}px ({reason}); "
                             f"source_cap={region['cap']}px, source_floor={region['floor']}px, "
                             f"direction={region['options']['direction']}, bounds_xywh={region['source']}; "
                             'review text, direction or region options')
        bounds,layer,alpha,render,style,scale,phase=chosen
        place={'version':1,'bbox_xywh':bounds,'page_size':[result.shape[1],result.shape[0]]}
        result,changed=core.composite(result,layer,alpha,place)
        page_alpha=changed+page_alpha*(1-changed)
        occupied |= ndimage.binary_dilation(changed>.01,iterations=2)
        reports.append({'id':region['id'],'source_profile':region['profile'],'bbox':bounds,
                        'font_fallback':region.get('font_fallback'),
                        'fit_phase':phase,'scale':round(scale,4),'render':render,
                        'fit_policy':region.get('fit_policy','source_ratio'),
                        'source_floor':region['floor'],'minimum_font':fallback_floor,
                        'source_ratio_relaxed':render['font_size']<region['floor'],
                        'bubble_containment':region.get('bubble_containment',{'status':'disabled'}),
                        'original_text':region['original_text'],'line_breaks':region['line_breaks'],
                        'outline_width':style['outline_width'],'bend':region['bend'],'warning':region['warning']})
    return result,page_alpha,json.dumps({'schema':1,'regions':reports,
        'protected_boxes_pixels':protected,'needs_review':plan.get('boundary_review_required',bool(protected)),
        'preserved_punctuation':plan.get('preserved_punctuation',[]),
        **({'page_status':'no_text_detected','lettering_skipped':True} if not reports and not plan.get('preserved_punctuation') else {}),
        **({'lettering_skipped':True,'skip_reason':'source_punctuation_preserved'} if not reports and plan.get('preserved_punctuation') else {}),
        'quality_scope':'geometry/style approximation; OCR, translation and GPU cleanup require separate review'},
        ensure_ascii=False,indent=2)
