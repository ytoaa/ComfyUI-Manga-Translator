"""Bounded line breaking: fewest lines, then balanced widths and word boundaries."""
from .core import _word_units, _advance


def balanced(paragraph, font, width, tracking):
    units=_word_units(paragraph.strip())
    n=len(units)
    if not n: return [[]]
    # Negative tracking can make prefix lengths non-monotone; preserve legacy layout.
    if tracking<0: return None
    advances=[_advance(font,u,tracking) for u in units]
    prefix=[0.]
    counts=[0]
    for unit,value in zip(units,advances):
        prefix.append(prefix[-1]+value+tracking)
        counts.append(counts[-1]+len(unit))
    if prefix[-1]-tracking<=width:
        return [[c for unit in units for c in unit]]
    best={0:(0,0.,[])}
    for start in range(n):
        if start not in best: continue
        lines,cost,path=best[start]
        for end in range(start+1,n+1):
            trimmed=end
            while trimmed>start and all(c.isspace() for c in units[trimmed-1]): trimmed-=1
            if trimmed==start: continue
            extent=prefix[trimmed]-prefix[start]-tracking
            if extent>width:
                # A single Latin word must be shrunk, never silently split or clipped.
                break
            following=end
            while following<n and all(c.isspace() for c in units[following]): following+=1
            word_break=(trimmed<n and not all(c.isspace() for c in units[trimmed]) and
                        not all(c.isspace() for c in units[trimmed-1]))
            count=counts[trimmed]-counts[start]
            penalty=((width-extent)/max(1,width))**2
            if word_break: penalty+=.35
            if following==n and count<3 and start>0: penalty+=1.5
            candidate=(lines+1,cost+penalty,path+[(start,trimmed)])
            old=best.get(following)
            if old is None or candidate[:2]<old[:2]: best[following]=candidate
    if n not in best:
        # Return an oversized atomic word so the font-size search rejects this size.
        return [[c for unit in units for c in unit]]
    return [[c for unit in units[a:b] for c in unit] for a,b in best[n][2]]
