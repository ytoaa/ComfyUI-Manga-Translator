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
