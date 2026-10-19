"""Private manga fixtures from external clean art plates and a Japanese font.

Only this recipe belongs in Git. Artwork, font downloads, masks and predictions
remain outside the repository. Clean references retain translucent balloons,
their borders, panel gutters and artwork; only added lettering is absent.
"""
from pathlib import Path
from io import BytesIO
import hashlib
import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, features
from fontTools.ttLib import TTFont

SIZE=(768,1152)
VARIANTS=('blank','opaque','alpha192','alpha128','alpha064','alpha000',
          'dark128','dark255','borderless','outlined-sfx','vertical-ruby',
          'overlapping','gutter-cross','faint-ink','jpeg-blur','edge-cut')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Scene:
    def __init__(self,ident,background,font):
        self.ident=ident;self.clean=background.copy();self.image=None
        self.font=Path(font);self.rows=[];self.masks=[];self.bubbles=[]
        with TTFont(self.font) as face:self.characters=set(face.getBestCmap())

    def balloon(self,box,alpha=255,dark=False,tail=True):
        if self.image is not None:raise ValueError('Balloon must precede all lettering')
        layer=Image.new('RGBA',SIZE);d=ImageDraw.Draw(layer)
        color=0 if dark else 255;edge=255 if dark else 25
        x,y,r,b=box
        if tail:d.polygon([(x+45,b-30),(x+10,b+34),(x+100,b-35)],fill=(color,)*3+(alpha,),outline=(edge,)*3+(230,))
        d.ellipse(box,fill=(color,)*3+(alpha,),outline=(edge,)*3+(230,),width=2)
        self.clean=Image.alpha_composite(self.clean.convert('RGBA'),layer).convert('RGB')
        mask=Image.new('L',SIZE);ImageDraw.Draw(mask).ellipse(box,fill=255)
        self.bubbles.append(np.asarray(mask)>0)

    def add(self,ident,text,xy,size=30,color='black',vertical=False,angle=0,
            outline=0,stroke_color=None,frame=None,kind='text',clipped=False,opacity=255):
        if any(ord(c) not in self.characters for c in text if not c.isspace()):raise ValueError('Missing Japanese font glyph')
        face=ImageFont.truetype(str(self.font),size)
        if vertical and not features.check_feature('raqm'):raise RuntimeError('Vertical glyph shaping requires RAQM')
        lines=text.split('\n');layers=[]
        def letter(fillstroke):
            if vertical:
                result=Image.new('L',((size+16)*len(lines)+12,max(map(len,lines))*(size+2)+24))
                d=ImageDraw.Draw(result)
                for i,line in enumerate(lines):
                    d.text((8+(len(lines)-i-1)*(size+16),8),line,font=face,fill=255,
                           direction='ttb',stroke_width=fillstroke,features=['vert'])
                return result
            box=ImageDraw.Draw(Image.new('L',(1,1))).multiline_textbbox((0,0),text,font=face,spacing=9,stroke_width=fillstroke)
            result=Image.new('L',(box[2]-box[0]+20,box[3]-box[1]+20))
            ImageDraw.Draw(result).multiline_text((10-box[0],10-box[1]),text,font=face,fill=255,spacing=9,stroke_width=fillstroke)
            return result
        outer=letter(outline);inner=letter(0) if outline and stroke_color else None
        # Match the independently drawn fill origin to the stroked text origin.
        if inner is not None and not vertical:
            box=ImageDraw.Draw(Image.new('L',(1,1))).multiline_textbbox((0,0),text,font=face,spacing=9,stroke_width=outline)
            inner=Image.new('L',outer.size)
            ImageDraw.Draw(inner).multiline_text((10-box[0],10-box[1]),text,font=face,fill=255,spacing=9)
        if self.image is None:self.image=self.clean.copy()
        union=np.zeros(SIZE[::-1],bool)
        for alpha,pigment in ((outer,stroke_color if inner is not None else color),(inner,color)):
            if alpha is None:continue
            if angle:alpha=alpha.rotate(angle,Image.Resampling.BICUBIC,expand=True)
            if opacity<255:alpha=alpha.point(lambda value:round(value*opacity/255))
            full=Image.new('L',SIZE);full.paste(alpha,xy)
            union|=np.asarray(full)>0;self.image.paste(pigment,mask=full)
        ys,xs=np.where(union)
        if not len(xs):raise ValueError('Reference has no pixels')
        bounds=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
        if frame is None:frame=[max(0,bounds[0]-12),max(0,bounds[1]-12),min(SIZE[0],bounds[2]+12),min(SIZE[1],bounds[3]+12)]
        self.rows.append({'id':ident,'text':text,'kind':kind,'bbox_pixels':bounds,'frame_pixels':frame,
                          'source_size':size,'source_angle':angle,'vertical':vertical,'clipped':clipped,
                          'fixed_target':'잠시 기다려 주세요.' if kind!='sfx' else '우르릉',
                          'ink_opacity':opacity})
        self.masks.append(union)


def scenes(backgrounds,font):
    for family,bg in backgrounds.items():
        for variant in VARIANTS:
            p=Scene(family+'-'+variant,bg,font)
            if variant=='blank':p.image=p.clean.copy()
            elif variant in ('opaque','alpha192','alpha128','alpha064','alpha000','dark128','dark255','jpeg-blur','faint-ink'):
                alpha=255 if variant in ('opaque','jpeg-blur','faint-ink') else int(variant[-3:])
                dark=variant.startswith('dark');p.balloon([34,44,354,396],alpha,dark)
                p.add('dialogue','雨が止んだら\n駅で待ちます。',(165,93),size=32,vertical=True,
                      color='white' if dark else 'black',frame=[60,76,330,363],opacity=72 if variant=='faint-ink' else 255)
            elif variant=='borderless':
                p.add('narration','まだ終わりではない。',(64,78),size=33,color='white',outline=1,stroke_color='#181818')
                p.add('whisper','誰もいない。',(626,482),size=26,vertical=True,color='#dddddd')
            elif variant=='outlined-sfx':
                p.add('sfx','ゴゴゴ',(370,420),size=100,color='white',outline=4,stroke_color='#151515',angle=-19,kind='sfx')
                p.add('small-sfx','ザアア',(58,750),size=55,color='#292929',angle=12,kind='sfx')
            elif variant=='vertical-ruby':
                p.balloon([24,42,348,475]);p.balloon([435,625,742,1085],192)
                p.add('body','明日の約束を\n忘れないで。',(144,92),size=34,vertical=True,frame=[55,75,326,442])
                p.add('ruby','あした',(247,103),size=12,vertical=True,frame=[240,92,272,170])
                p.rows[-1]['ruby_of']='body'
                p.add('lower','ここで待つ。',(564,720),size=32,vertical=True,frame=[475,680,706,1035])
            elif variant=='overlapping':
                p.balloon([30,55,362,380],192);p.balloon([230,205,559,520],128)
                p.add('first','本当に？',(128,104),size=32,vertical=True,frame=[65,92,330,350])
                p.add('second','信じてる。',(398,284),size=32,vertical=True,frame=[265,242,525,488])
            elif variant=='gutter-cross':
                # A real panel gutter is part of the known clean artwork.
                ImageDraw.Draw(p.clean).polygon([(0,695),(767,636),(767,650),(0,709)],fill='white')
                p.add('cross','ここから始まる',(135,616),size=47,color='white',outline=3,stroke_color='#111111',angle=7,kind='sfx')
            elif variant=='edge-cut':
                p.add('cut','この先は通行止め',(-48,95),size=48,clipped=True)
                p.add('safe','戻ろう。',(500,825),size=33,color='white',outline=1,stroke_color='#111111')
            if variant=='jpeg-blur':
                def degrade(im):
                    buffer=BytesIO();im.save(buffer,format='JPEG',quality=38)
                    return Image.open(BytesIO(buffer.getvalue())).convert('RGB').filter(ImageFilter.GaussianBlur(.55))
                p.image=degrade(p.image);p.clean=degrade(p.clean)
                # Glyph retention must not be graded against a wide JPEG halo.
                # Keep the independently transformed glyph support separate
                # from the changed codec pixels used for cleanup diagnostics.
                p.masks=[np.asarray(Image.fromarray(m.astype('uint8')*255).filter(ImageFilter.GaussianBlur(.55)))>1 for m in p.masks]
                p.artifact_support=np.any(np.asarray(p.image)!=np.asarray(p.clean),axis=2)
            yield p,family,variant


def generate(destination,assets):
    dest=Path(destination);assets=Path(assets);dest.mkdir(parents=True,exist_ok=True)
    inventory=json.loads((assets/'assets.json').read_text());backgrounds={}
    for name in ('rain','temple'):
        path=assets/(name+'.png')
        if digest(path)!=inventory[name]['sha256']:raise ValueError('Background changed: '+name)
        backgrounds[name]=Image.open(path).convert('RGB').resize(SIZE,Image.Resampling.LANCZOS)
    font=assets/'NotoSerifJP.ttf'
    if digest(font)!=inventory['font']['sha256']:raise ValueError('Font changed')
    refs={'schema':1,'generator_sha256':digest(__file__),'backgrounds':inventory,'pages':[],'ocr':[],
          'source':'new AI clean art plates; independently rasterized Japanese text and balloon alpha; no user images',
          'reference_scope':'clean includes the same translucent balloons; JPEG transformed independently; no actual Qwen reference injection'}
    for p,family,variant in scenes(backgrounds,font):
        for suffix,im in (('',p.image),('-clean',p.clean)):im.save(dest/(p.ident+suffix+'.png'))
        np.savez_compressed(dest/(p.ident+'-truth.npz'),**{r['id']:m for r,m in zip(p.rows,p.masks)},
                            **{'bubble'+str(i):m for i,m in enumerate(p.bubbles)},
                            **({'codec_artifact_support':p.artifact_support} if hasattr(p,'artifact_support') else {}))
        before=np.asarray(p.image).astype(int);after=np.asarray(p.clean).astype(int)
        for r,m in zip(p.rows,p.masks):r['visible_difference_fraction']=float((np.max(np.abs(before-after),axis=2)[m]>8).mean())
        row={'id':p.ident,'family':family,'variant':variant,'image':p.ident+'.png','clean':p.ident+'-clean.png',
             'truth':p.ident+'-truth.npz','size':list(SIZE),'cleanup':'model','regions':p.rows,'balloon_count':len(p.bubbles),'negative':variant=='blank'}
        for key,sha in (('image','sha256'),('clean','clean_sha256'),('truth','truth_sha256')):row[sha]=digest(dest/row[key])
        refs['pages'].append(row)
        for r in p.rows:
            if r['clipped']:continue
            a,b,c,d=r['bbox_pixels'];box=[max(0,a-8),max(0,b-8),min(SIZE[0],c+8),min(SIZE[1],d+8)]
            filename='ocr-'+p.ident+'-'+r['id']+'.png';p.image.crop(box).save(dest/filename)
            refs['ocr'].append({'id':p.ident+'-'+r['id'],'page_id':p.ident,'image':filename,'sha256':digest(dest/filename),
                                'expected':r['text'],'direction':'vertical_rtl' if r['vertical'] else 'auto','ruby_of':r.get('ruby_of')})
    (dest/'references.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2),encoding='utf-8');return refs


def verify(refs,folder):
    if refs['generator_sha256']!=digest(__file__):raise ValueError('Generator changed')
    for row in refs['pages']:
        for key,sha in (('image','sha256'),('clean','clean_sha256'),('truth','truth_sha256')):
            if digest(Path(folder)/row[key])!=row[sha]:raise ValueError('Fixture changed: '+row[key])
    for row in refs['ocr']:
        if digest(Path(folder)/row['image'])!=row['sha256']:raise ValueError('OCR crop changed')
