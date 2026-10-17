"""Bounded OCR input planning and conservative output checks; no model calls."""
import math
import numpy as np
from scipy import ndimage


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


def text_problem(text, image):
    if not isinstance(text,str) or not text.strip():
        return 'empty'
    compact = ''.join(text.split())
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
    columns = foreground.any(axis=0)
    bands = int(np.count_nonzero(columns & ~np.r_[False,columns[:-1]]))
    if image.width >= image.height*3 and bands >= 12 and len(compact) < math.ceil(bands/4):
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
    candidates=[]
    for threshold in (16,8):
        if max(positive,negative)<threshold:
            continue
        foreground=(detail>threshold if positive>negative*1.2 else detail < -threshold
                    if negative>positive*1.2 else np.abs(detail)>threshold)
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
            candidates.append((separation,horizontal,boxes,threshold,removed))
        if candidates:break
    if candidates:
        candidates.sort(key=lambda row:row[0],reverse=True)
        best=candidates[0]
        other=next((v for v in candidates[1:] if v[1]!=best[1]),None)
        if other and (best[0]<other[0]*1.5 or best[0]-other[0]<.05):
            return [],{'strategy':'ambiguous_rows_and_columns'}
        _,horizontal,boxes,threshold,removed=best
        return [(image.crop(box),box) for box in boxes],{
            'strategy':'verified_rows' if horizontal else 'verified_columns',
            'separator':'\n','contrast':threshold,'ruling_strips_ignored_in_analysis':removed}
    if direction in ('auto','horizontal'):
        parts=plan_line(image,max_aspect=6.)
        if len(parts)>1:return parts,{'strategy':'shorter_horizontal_chunks','separator':''}
    return [],{'strategy':'no_verified_alternative'}
