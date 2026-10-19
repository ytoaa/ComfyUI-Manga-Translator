"""Bounded, conservative placement inside existing source/bubble permissions.

An early paragraph must not consume a later paragraph's source frame. Where
frames overlap, the nearer source centre owns the pixel; this is a layout
reservation, not a claim about detector or OCR correctness. No glyph is clipped.
"""
import math
import numpy as np
from scipy import ndimage
from .bubble_constraints import largest_rectangle, overlap


def source_contains(region, xx, yy):
    quad=region.get('frame_quad')
    if quad is None:
        x,y,w,h=region['source']
        return (xx>=x)&(xx<x+w)&(yy>=y)&(yy<y+h)
    q=np.asarray(quad,dtype=np.float64)
    u,v=q[1]-q[0],q[3]-q[0]
    dx,dy=xx-q[0,0],yy-q[0,1]
    a=(dx*u[0]+dy*u[1])/float(u@u)
    b=(dx*v[0]+dy*v[1])/float(v@v)
    return (a>=0)&(a<1)&(b>=0)&(b<1)


def competing_regions(region, regions, bounds):
    for other in regions:
        if other is region:
            continue
        left, top, right, bottom = overlap(bounds, other['source'])
        if left < right and top < bottom:
            yield other, (left, top, right, bottom)


def reserve_sources(region, regions, bounds):
    """Return a local permission mask and the IDs whose space was reserved."""
    x, y, w, h = bounds
    sx, sy, sw, sh = region['source']
    cx, cy = sx + sw / 2, sy + sh / 2
    allowed = np.ones((h, w), bool)
    neighbours = []
    for other, (left, top, right, bottom) in competing_regions(region, regions, bounds):
        a, b, c, d = other['source']
        ox, oy = a + c / 2, b + d / 2
        # Coincident source anchors do not establish separate ownership. Keep
        # the old hard collision path rather than inventing two text locations.
        if cx == ox and cy == oy:
            continue
        xx = np.arange(left, right, dtype=np.float64)[None, :] + .5
        yy = np.arange(top, bottom, dtype=np.float64)[:, None] + .5
        inside = source_contains(region,xx,yy)
        # Difference of squared distances avoids large page-sized distance maps.
        difference = 2 * xx * (ox - cx) + 2 * yy * (oy - cy) + cx*cx + cy*cy - ox*ox - oy*oy
        nearer = difference < 0
        if region['id'] < other['id']:
            nearer |= difference == 0
        owned = ~source_contains(other,xx,yy) | (inside & nearer)
        if not owned.all():
            neighbours.append(other['id'])
            allowed[top-y:bottom-y, left-x:right-x] &= owned
    if neighbours:
        # Match the renderer's two-pixel separation without cutting alpha.
        allowed &= ~ndimage.binary_dilation(~allowed, iterations=2)
    return allowed, neighbours


def free_rectangles(allowed, bounds, source):
    """At most five all-free rectangles; large masks use all-pixel pooling.

    Pooling can miss a narrow valid slot, but can never certify a blocked pixel.
    The final renderer independently checks every positive alpha pixel again.
    """
    if allowed.all() or not allowed.any():
        return []
    x, y, w, h = bounds
    step = max(1, math.ceil(math.sqrt(allowed.size / 65536)))
    rows, cols = math.ceil(h / step), math.ceil(w / step)
    coarse = np.pad(allowed, ((0, rows*step-h), (0, cols*step-w)), constant_values=False)
    coarse = coarse.reshape(rows, step, cols, step).all(axis=(1, 3))
    sx, sy, sw, sh = source
    cx = max(0, min(cols, round((sx + sw/2 - x) / step)))
    cy = max(0, min(rows, round((sy + sh/2 - y) / step)))
    slices = [(0, 0, cols, rows), (0, 0, cx, rows), (cx, 0, cols, rows),
              (0, 0, cols, cy), (0, cy, cols, rows)]
    found = []
    for a, b, c, d in slices:
        if a >= c or b >= d:
            continue
        rect = largest_rectangle(coarse[b:d, a:c])
        if rect is None:
            continue
        u, v, rw, rh = rect
        rect = [x+(a+u)*step, y+(b+v)*step, rw*step, rh*step]
        if min(rect[2:]) >= 8 and rect not in found:
            found.append(rect)
    def rank(rect):
        a, b, c, d = overlap(rect, source)
        area = max(0, c-a) * max(0, d-b)
        rx, ry, rw, rh = rect
        distance = (rx+rw/2-sx-sw/2)**2 + (ry+rh/2-sy-sh/2)**2
        return -area, distance, -rw*rh
    return sorted(found, key=rank)
