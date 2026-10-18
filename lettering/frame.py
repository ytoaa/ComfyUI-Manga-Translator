"""Fit in a rotated local rectangle, then map premultiplied glyphs to page pixels."""
import json
import math
import numpy as np
from PIL import Image
from . import core


def geometry(quad):
    q=np.asarray(quad,dtype=float)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Expected four finite frame corners')
    a,b=q[1]-q[0],q[3]-q[0];w,h=np.linalg.norm(a),np.linalg.norm(b)
    if min(w,h)<4 or abs(np.dot(a,b)/(w*h))>.02 or np.linalg.norm(q[2]-q[0]-a-b)>1:raise ValueError('Frame must be a rotated rectangle')
    return q[0],a/w,b/h,math.ceil(w),math.ceil(h)


def rectangle(ink,bounds,angle,padding):
    x,y,w,h=bounds;yy,xx=np.where(ink)
    if not len(xx):raise ValueError('Oriented frame requires source ink')
    theta=math.radians(angle);u=np.array([math.cos(theta),-math.sin(theta)]);v=np.array([math.sin(theta),math.cos(theta)])
    points=np.column_stack((xx+x,yy+y));local=np.column_stack((points@u,points@v))
    lo=local.min(axis=0)-padding;hi=local.max(axis=0)+padding+1
    return [(u*a+v*b).tolist() for a,b in ((lo[0],lo[1]),(hi[0],lo[1]),(hi[0],hi[1]),(lo[0],hi[1]))]


def block_quad(row,block):
    x,y,z,t=row['crop_bbox_pixels'];a,b,c,d=block['bbox_local']
    points=np.array([[a,b],[c,b],[c,d],[a,d]],float)
    if block['coordinate_frame']=='rectified_crop_pixels':
        plan=row.get('ocr_region_plan',{})
        if plan.get('source_size')!=[z-x,t-y]:raise ValueError('Paragraph source frame differs from crop')
        rw,rh=plan['rectified_size'];angle=math.radians(plan['source_angle'])
        # OCR rotates source by -source_angle; invert that transform here.
        rotation=np.array([[math.cos(angle),math.sin(angle)],[-math.sin(angle),math.cos(angle)]])
        points=(points-np.array([rw/2,rh/2]))@rotation.T+np.array([(z-x)/2,(t-y)/2])
    return (points+np.array([x,y])).tolist()


def render(text,style,font,quad,page_shape,**options):
    p,u,v,w,h=geometry(quad)
    if w*h>16*1024*1024:raise ValueError('Local frame exceeds raster budget')
    local=dict(style);local['size']=[w,h];options={**options,'rotation':0}
    layer,alpha,report=core.render_text(text,local,font_name=font,**options)
    yy,xx=np.where(alpha>0)
    if not len(xx):raise ValueError('Empty oriented glyph')
    points=p+xx[:,None]*u+yy[:,None]*v
    height,width=page_shape[:2]
    if np.any(points[:,0]<1) or np.any(points[:,0]>width-2) or np.any(points[:,1]<1) or np.any(points[:,1]>height-2):raise ValueError('Transformed glyph leaves page boundary')
    q=np.asarray(quad);left=max(0,math.floor(q[:,0].min())-3);top=max(0,math.floor(q[:,1].min())-3)
    right=min(width,math.ceil(q[:,0].max())+3);bottom=min(height,math.ceil(q[:,1].max())+3)
    if (right-left)*(bottom-top)>32*1024*1024:raise ValueError('Page frame exceeds raster budget')
    offset=np.array([left,top])-p
    transform=(u[0],u[1],float(offset@u),v[0],v[1],float(offset@v))
    def warp(a):return np.asarray(Image.fromarray(a.astype('float32'),'F').transform((right-left,bottom-top),Image.Transform.AFFINE,transform,Image.Resampling.BICUBIC),np.float32)
    warped_alpha=np.clip(warp(alpha),0,1)
    premult=np.stack([warp(layer[:,:,c]*alpha) for c in range(3)],axis=-1)
    rgb=np.clip(np.divide(premult,warped_alpha[:,:,None],out=np.zeros_like(premult),where=warped_alpha[:,:,None]>1e-6),0,1)
    result=json.loads(report);result.update(local_size=[w,h],frame_quad=quad,coordinate_frame='oriented_local_pixels')
    return [left,top,right-left,bottom-top],rgb,warped_alpha,result
