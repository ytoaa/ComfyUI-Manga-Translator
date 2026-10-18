"""Bounded OCR input planning and conservative output checks; no model calls."""
import math
import numpy as np
from scipy import ndimage
from .text_contract import ocr_problem


def dot_punctuation(image):
    """Recognize only 3..24 isolated, filled, evenly spaced round dots.

    This bounded geometry reader does not accept model output or infer words.
    A mixed, cropped, hollow, textured or ambiguous input keeps normal OCR.
    """
    width,height=image.size
    if width*height>262144 or min(width,height)<8 or max(width,height)<3*min(width,height):
        return None
    pixels=np.asarray(image.convert('RGB'),np.float32)
    background=np.median(pixels.reshape(-1,3),axis=0)
    delta=np.max(np.abs(pixels-background),axis=2)
    if np.mean(delta<=12)<.70: return None
    foreground=delta>=64
    labels,count=ndimage.label(foreground,structure=np.ones((3,3),bool))
    if not 3<=count<=24: return None
    boxes=[];sizes=[];areas=[];centers=[]
    for i,slices in enumerate(ndimage.find_objects(labels),1):
        y,x=slices;w,h=x.stop-x.start,y.stop-y.start
        local=labels[slices]==i
        if (min(w,h)<3 or not .75<=w/h<=1.33 or not .60<=local.mean()<=.91 or
                not np.array_equal(ndimage.binary_fill_holes(local),local)):
            return None
        margin=max(2,round(min(w,h)*.12))
        if min(x.start,y.start,width-x.stop,height-y.stop)<margin: return None
        boxes.append([x.start,y.start,x.stop,y.stop]);sizes.append((w+h)/2);areas.append(int(local.sum()))
        yy,xx=np.where(local)
        centers.append([float(xx.mean()+x.start),float(yy.mean()+y.start)])
    if min(sizes)/max(sizes)<.70 or min(areas)/max(areas)<.60: return None
    axis=1 if height>width else 0
    centers=np.asarray(centers);diameter=float(np.median(sizes))
    if np.ptp(centers[:,1-axis])>max(1,diameter*.20): return None
    order=np.argsort(centers[:,axis]);gaps=np.diff(centers[order,axis]);spacing=float(np.median(gaps))
    if not 1.8*diameter<=spacing<=6*diameter or np.ptp(gaps)>spacing*.25: return None
    return {'strategy':'source_dot_punctuation','text':'・'*count,'count':count,
            'axis':'vertical' if axis else 'horizontal','component_boxes':[boxes[i] for i in order],
            'scope':'geometric_dot_count_only_not_general_OCR'}


def ink(image):
    pixels = np.asarray(image.convert('RGB'), dtype=np.float32)
    gray = pixels @ np.array([.299, .587, .114], dtype=np.float32)
    detail = gray-ndimage.uniform_filter(gray, size=31, mode='reflect')
    positive, negative = float(np.percentile(detail,99)), -float(np.percentile(detail,1))
    if positive > negative*1.2:
        return detail > 16
    if negative > positive*1.2:
        return detail < -16
    return np.abs(detail) > 16


def plan_line(image, max_aspect=12.):
    """Split a long horizontal line only at two clear foreground-free columns.

    No overlapping recognition chunks, substring de-duplication, or lost source
    pixels. Ambiguous gaps keep the original input intact. Vertical text is
    intentionally unchanged. A bounded plan never exceeds 16 chunks per row.
    """
    width,height = image.size
    if width <= height*max_aspect:
        return [(image, [0,0,width,height])]
    foreground = ink(image)
    occupied = foreground.any(axis=0)
    target = max(32, round(height*max_aspect))
    active = np.flatnonzero(occupied)
    if not len(active) or active[-1]-active[0]+1 <= target:
        return [(image,[0,0,width,height])]
    ys = np.flatnonzero(foreground.any(axis=1))
    min_gap = max(2, math.ceil((ys[-1]-ys[0]+1)*.12))
    empty = np.flatnonzero(~occupied)
    gaps = np.split(empty, np.flatnonzero(np.diff(empty)>1)+1)
    clear = np.array([(group[0]+group[-1]+1)//2 for group in gaps if len(group)>=min_gap],dtype=int)
    cuts = [0]
    while active[-1]+1-max(cuts[-1],active[0]) > target*1.35:
        start = max(cuts[-1],int(active[0]))
        low,high = start+target*.65, min(active[-1]-target*.35, start+target*1.35)
        choices = clear[(clear >= low) & (clear <= high)]
        if not len(choices) or len(cuts) >= 16:
            return [(image, [0,0,width,height])]
        desired = start+target
        cuts.append(int(choices[np.argmin(np.abs(choices-desired))]))
    cuts.append(width)
    return [(image.crop((a,0,b,height)), [a,0,b,height]) for a,b in zip(cuts,cuts[1:])]


def text_problem(text, image, evidence=None):
    if not isinstance(text,str) or not text.strip():
        return 'empty'
    if issue := ocr_problem(text):
        return issue
    compact = ''.join(text.split())
    if compact and set(compact)=={'・'}:
        dots=dot_punctuation(image)
        if dots and compact==dots['text']:
            if evidence is not None:evidence['verified_punctuation']=dots
            return None
    # Short pathological loops from the actual report used to evade the
    # adapter's 32-character loop check. Keep ordinary manga elongations.
    for period in range(1,9):
        repeats = max(4, math.ceil(8/period))
        for start in range(len(compact)):
            block = compact[start:start+period]
            count = repeats
            if (period == 1 and len(compact) >= 8 and '\u4e00' <= block <= '\u9fff'
                    and block not in '笑哈呵啊嗚嗷哇嘻嘿喔哦嗯哼唉呜噗'):
                count = 4
            if block and compact.startswith(block*count,start):
                return 'short_repetition'
    # This is a weak omission alarm, NOT confidence or character recognition.
    # Connected script/stylized graphics may evade it. No rejection for a few
    # punctuation components or a short name with several kanji radicals.
    foreground = ink(image)
    raw_columns=foreground.any(axis=0)
    raw_bands=int(np.count_nonzero(raw_columns & ~np.r_[False,raw_columns[:-1]]))
    # A paper speck used to count as a whole glyph-sized band regardless of
    # area. Exclude only tiny disconnected components from this weak estimate;
    # do not alter the recognition image, masks, splitting or returned text.
    labels,count=ndimage.label(foreground,structure=np.ones((3,3),bool))
    areas=np.bincount(labels.ravel(),minlength=count+1)
    # Scale the speck threshold to observed foreground components, with a
    # low cap so ordinary small print still contributes to the estimate.
    minimum_area=max(4,min(16,math.ceil(areas[1:].max(initial=0)*.2)))
    supported=areas>=minimum_area
    supported[0]=False
    columns=supported[labels].any(axis=0)
    bands=int(np.count_nonzero(columns & ~np.r_[False,columns[:-1]]))
    eligible=image.width>=image.height*3 and bands>=12
    minimum=math.ceil(bands/4) if eligible else 0
    if evidence is not None:
        evidence['omission']={'raw_projection_bands':raw_bands,'supported_projection_bands':bands,
                              'analysis_min_component_pixels':minimum_area,'minimum_characters':minimum,
                              'scope':'weak_omission_estimate_not_recognition_confidence'}
    if eligible and len(compact)<minimum:
        return 'possible_omission'
    return None


def join_chunks(texts):
    """Retain English word boundaries; adjacent CJK chunks need no new space."""
    output = ''
    for text in texts:
        text = text.strip()
        if output and text and output[-1].isascii() and text[0].isascii() and output[-1].isalnum() and text[0].isalnum():
            output += ' '
        output += text
    return output


def _runs(active, min_gap=4):
    indices=np.flatnonzero(active)
    runs=[]
    for group in np.split(indices,np.flatnonzero(np.diff(indices)>1)+1):
        if not len(group):continue
        a,b=int(group[0]),int(group[-1])+1
        if runs and a-runs[-1][1]<min_gap:runs[-1][1]=b
        else:runs.append([a,b])
    return runs


def _multicolumn_parts(image,detail,positive,negative):
    """Verify horizontal text columns before making any row cuts.

    Paper specks and narrow scanner-edge strips are ignored only in analysis.
    A gutter needs actual empty columns between repeated, elongated text rows.
    Auxiliary gutter content stays with the following text column. Its number
    boxes can merge adjacent rows so that a section marker is never cut in two.
    Recognition inputs partition all original pixels in column reading order.
    """
    width,height=image.size
    if max(positive,negative)<24 or width<128 or height<48:
        return [],None
    foreground=(detail>24 if positive>negative*1.2 else detail < -24
                if negative>positive*1.2 else np.abs(detail)>24)
    labels,count=ndimage.label(foreground,structure=np.ones((3,3),bool))
    if count>65536:
        return [],None
    sizes=np.bincount(labels.ravel(),minlength=count+1)
    keep=sizes>=8;keep[0]=False
    edge_candidates=[[],[]]
    for index,slices in enumerate(ndimage.find_objects(labels),1):
        y,x=slices
        w,h=x.stop-x.start,y.stop-y.start
        if (x.start==0 or x.stop==width) and w<=max(3,round(width*.01)) and h>=max(16,4*w):
            edge_candidates[0 if x.start==0 else 1].append((index,y))
            if h>=height*.25 and h>=10*w:
                keep[index]=False
    for candidates in edge_candidates:
        support=np.zeros(height,bool)
        for index,y in candidates:support[y]=True
        if np.count_nonzero(support)>=height*.5:
            for index,y in candidates:keep[index]=False
    work=keep[labels]
    gutters=[]
    for a,b in _runs(work.sum(axis=0)<=2):
        if b-a<max(8,round(height*.035)) or a<32 or b>width-32:
            continue
        clear=~work[:,a:b].any(axis=0)
        safe=np.flatnonzero(clear & np.r_[clear[1:],False])
        if len(safe):
            gutters.append(a+int(safe[np.argmin(np.abs(safe-(b-a)/2))]))
    if not 1<=len(gutters)<=7:
        return [],None
    edges=[0,*gutters,width]

    def rows(a,b,verify=False):
        region=work[:,a:b]
        found=[(top,bottom) for top,bottom in _runs(region.any(axis=1)) if bottom-top>=8]
        if not verify:return found
        if b-a<64 or len(found)<3:return []
        good=0
        for top,bottom in found:
            band=region[top:bottom]
            if np.count_nonzero(band.any(axis=0))<3*(bottom-top):continue
            values,n=ndimage.label(band,structure=np.ones((3,3),bool))
            if np.count_nonzero(np.bincount(values.ravel(),minlength=n+1)[1:]>=4)>=3:good+=1
        return found if good>=math.ceil(len(found)*.75) else []

    bodies=[i for i,(a,b) in enumerate(zip(edges,edges[1:])) if rows(a,b,True)]
    if len(bodies)<2 or sum(edges[i+1]-edges[i] for i in bodies)<width*.6:
        return [],None
    # Attach narrow auxiliary strips to the next body, preserving all their
    # pixels. Use that full pane for row gaps: a marker crossing two physical
    # lines prevents the cut and both lines are recognized together.
    cuts=[0,*[edges[i+1] for i in bodies[:-1]],width]
    boxes=[];columns=[]
    for a,b in zip(cuts,cuts[1:]):
        found=rows(a,b)
        if not 2<=len(found)<=16:return [],None
        active=work[:,a:b].any(axis=1)
        row_cuts=[0]
        for left,right in zip(found,found[1:]):
            gap=np.arange(left[1],right[0])
            clear=gap[~active[gap]]
            if len(clear)<4:return [],None
            row_cuts.append(int(clear[np.argmin(np.abs(clear-(left[1]+right[0])/2))]))
        row_cuts.append(height)
        boxes.extend([[a,top,b,bottom] for top,bottom in zip(row_cuts,row_cuts[1:])])
        columns.append({'bbox':[a,0,b,height],'rows':len(found)})
    if len(boxes)>16:return [],None
    return [(image.crop(box),box) for box in boxes],{
        'strategy':'verified_multicolumn_rows','separator':'\n',
        'reading_order':'columns_left_to_right_then_rows_top_to_bottom',
        'columns':columns,'contrast':24,'analysis_only_min_component_pixels':8}


def recovery_parts(image, direction='auto'):
    """One alternative reading plan after output rejection, never a blind cut.

    Thin persistent ruling lines may inform segmentation without being erased
    from recognition crops. Every cut needs a clear gap in the remaining ink;
    crops partition the complete input, including punctuation and margins.
    """
    if direction not in ('auto','horizontal','vertical_rtl','vertical_ltr'):
        raise ValueError('Invalid recovery direction')
    pixels=np.asarray(image.convert('RGB'),np.float32)
    gray=pixels @ np.array([.299,.587,.114],np.float32)
    detail=gray-ndimage.uniform_filter(gray,size=31,mode='reflect')
    positive,negative=float(np.percentile(detail,99)),-float(np.percentile(detail,1))
    if direction in ('auto','horizontal'):
        parts,report=_multicolumn_parts(image,detail,positive,negative)
        if parts:return parts,report
    candidates=[]
    for threshold in (16,8):
        if max(positive,negative)<threshold:
            continue
        foreground=(detail>threshold if positive>negative*1.2 else detail < -threshold
                    if negative>positive*1.2 else np.abs(detail)>threshold)
        # Texture specks and dotted gutter marks can fill every row gap.
        # This is analysis only: recognition crops retain all source pixels.
        labels,count=ndimage.label(foreground,structure=np.ones((3,3),bool))
        supported=np.bincount(labels.ravel(),minlength=count+1)>=8
        supported[0]=False
        clean=supported[labels]
        speckles=int(np.count_nonzero(foreground & ~clean))
        foreground=clean
        for horizontal in (True,False):
            name='horizontal' if horizontal else 'vertical_rtl'
            if direction!='auto' and horizontal!=(direction=='horizontal'):
                continue
            work=foreground.copy() if horizontal else foreground.T.copy()
            # A thin panel edge can bridge every gap between text rows. Remove
            # only narrow, nearly continuous cross-axis strips from analysis.
            persistent=work.mean(axis=0)>=.8
            groups=np.split(np.flatnonzero(persistent),np.flatnonzero(np.diff(np.flatnonzero(persistent))>1)+1)
            removed=0
            for group in groups:
                if len(group) and len(group)<=max(2,round(work.shape[1]*.005)):
                    work[:,group]=False
                    removed+=len(group)
            active=work.any(axis=1)
            indices=np.flatnonzero(active)
            if not len(indices):continue
            runs=[]
            for group in np.split(indices,np.flatnonzero(np.diff(indices)>1)+1):
                a,b=int(group[0]),int(group[-1])+1
                if runs and a-runs[-1][1]<4:runs[-1][1]=b
                else:runs.append([a,b])
            runs=[(a,b) for a,b in runs if b-a>=8]
            if not 2<=len(runs)<=16:continue
            elongated=0
            for a,b in runs:
                if np.count_nonzero(work[a:b].any(axis=0))<3*(b-a):continue
                labels,count=ndimage.label(work[a:b],structure=np.ones((3,3),bool))
                # A large connected glyph or drawn frame must not become
                # several "text rows" just because its strokes have gaps.
                if np.count_nonzero(np.bincount(labels.ravel(),minlength=count+1)[1:]>=4)>=3:
                    elongated+=1
            if elongated<math.ceil(len(runs)*.75):continue
            cuts=[0];valid=True
            for left,right in zip(runs,runs[1:]):
                gap=np.arange(left[1],right[0])
                clear=gap[~active[gap]]
                if len(clear)<4:
                    valid=False;break
                midpoint=(left[1]+right[0])//2
                cuts.append(int(clear[np.argmin(np.abs(clear-midpoint))]))
            if not valid:continue
            cuts.append(work.shape[0])
            boxes=[([0,a,image.width,b] if horizontal else [a,0,b,image.height])
                   for a,b in zip(cuts,cuts[1:])]
            if not horizontal and direction!='vertical_ltr':boxes.reverse()
            separation=sum(b[0]-a[1] for a,b in zip(runs,runs[1:]))/(runs[-1][1]-runs[0][0])
            candidates.append((separation,horizontal,boxes,threshold,removed,speckles))
        if candidates:break
    if candidates:
        candidates.sort(key=lambda row:row[0],reverse=True)
        best=candidates[0]
        other=next((v for v in candidates[1:] if v[1]!=best[1]),None)
        if other and (best[0]<other[0]*1.5 or best[0]-other[0]<.05):
            return [],{'strategy':'ambiguous_rows_and_columns'}
        _,horizontal,boxes,threshold,removed,speckles=best
        return [(image.crop(box),box) for box in boxes],{
            'strategy':'verified_rows' if horizontal else 'verified_columns',
            'separator':'\n','contrast':threshold,'ruling_strips_ignored_in_analysis':removed,
            'analysis_min_component_pixels':8,'speckle_pixels_ignored_in_analysis':speckles}
    if direction in ('auto','horizontal'):
        parts=plan_line(image,max_aspect=6.)
        if len(parts)>1:return parts,{'strategy':'shorter_horizontal_chunks','separator':''}
    return [],{'strategy':'no_verified_alternative'}
