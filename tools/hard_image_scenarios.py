"""Hard image fixtures: externally supplied blank art plus independent text.

Background assets are private inputs; this repository stores recipes only.
The two pixel-identical annotation twins are explicitly excluded from accuracy.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import hashlib
import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from fontTools.ttLib import TTFont

if __package__:
    from . import expanded_image_scenarios as F
else:
    import expanded_image_scenarios as F
S=F.S
NAMES=('manga-station','color-market','archive-sheet')
BOLD=S.ROOT/'lettering/fonts/NanumGothic-Bold.ttf'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Scene(F.Scene):
    def __init__(self, ident, background=None, **metadata):
        super().__init__(ident,size=(768,768),cleanup='model')
        if background is not None:self.clean=background.copy()
        self.meta=metadata

    def label(self, ident, text, xy, bold=False, **style):
        if not bold:
            self.add(ident,text,xy,**style)
        else:
            # The alternate face is only used on literals it actually supports.
            with TTFont(BOLD) as face:chars=set(face.getBestCmap())
            if any(ord(c) not in chars for c in text if c!='\n'):raise ValueError('Bold font coverage missing')
            size=style.get('size',24);face=ImageFont.truetype(str(BOLD),size)
            box=ImageDraw.Draw(Image.new('L',(1,1))).multiline_textbbox((0,0),text,font=face,spacing=8)
            layer=Image.new('L',(box[2]-box[0]+16,box[3]-box[1]+16))
            ImageDraw.Draw(layer).multiline_text((8-box[0],8-box[1]),text,font=face,fill=255,spacing=8)
            if self.image is None:self.image=self.clean.copy()
            full=Image.new('L',self.clean.size);full.paste(layer,xy)
            mask=np.asarray(full)>0;ys,xs=np.where(mask)
            bounds=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
            self.image.paste(style.get('color','black'),mask=full)
            frame=style.get('frame',[max(0,bounds[0]-12),max(0,bounds[1]-12),min(768,bounds[2]+12),min(768,bounds[3]+12)])
            self.rows.append({'id':ident,'text':text,'kind':'text','bbox_pixels':bounds,'frame_pixels':frame,'source_size':size,'source_angle':0,'vertical':False,'clipped':False,'source_font':'NanumGothic-Bold.ttf'})
            self.masks.append(mask)
        self.rows[-1]['fixed_target']='다음 역에서 만나 함께 길을 확인합니다.'


def foundation(p):
    d=ImageDraw.Draw(p.clean)
    for box,color in (([25,35,410,175],'#f7f7f7'),([400,270,745,390],'#243746'),([615,460,745,740],'#f7f7f7')):d.rounded_rectangle(box,12,fill=color)
    p.label('jp','明日は駅で\n友達を待ちます。',(55,65),size=26,frame=[25,35,410,175])
    p.label('en','WAIT HERE\nUNTIL NINE.',(425,292),size=25,color='white',bold=True,frame=[400,270,745,390])
    p.label('vertical','先生は話します。',(653,480),size=21,vertical=True,frame=[615,460,745,740])


def transformed(p,kind):
    """Apply the same known nuisance transform to source and clean reference."""
    def run(im):
        if kind=='low-res':return im.resize((384,384),Image.Resampling.LANCZOS)
        buffer=BytesIO();im.save(buffer,format='JPEG',quality=35,subsampling=2)
        return Image.open(BytesIO(buffer.getvalue())).convert('RGB').filter(ImageFilter.GaussianBlur(.65))
    p.image=run(p.image);p.clean=run(p.clean);w,h=p.image.size
    if kind=='low-res':
        p.masks=[np.asarray(Image.fromarray(m.astype('uint8')*255).resize((w,h),Image.Resampling.LANCZOS))>1 for m in p.masks]
        for row,mask in zip(p.rows,p.masks):
            ys,xs=np.where(mask);row['bbox_pixels']=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
            a,b,c,d=row['frame_pixels'];row['frame_pixels']=[math.floor(a/2),math.floor(b/2),math.ceil(c/2),math.ceil(d/2)]
            row['source_size']/=2
    else:
        p.masks=[np.asarray(Image.fromarray(m.astype('uint8')*255).filter(ImageFilter.GaussianBlur(.65)))>1 for m in p.masks]
        for row,mask in zip(p.rows,p.masks):
            ys,xs=np.where(mask);row['bbox_pixels']=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
    p.meta['degradation']=kind
    p.meta['reference_scope']='same known transform independently applied before/after adding glyphs; JPEG differential can extend beyond geometric glyph support'
    return p


def scenes(backgrounds):
    for name,bg in backgrounds.items():
        p=Scene(name+'-blank',bg,family=name,variant='blank',negative=True);p.image=p.clean.copy();yield p
        for variant in ('clear','direct','rotated','low-res','jpeg-blur','crowded','edge-cut'):
            p=Scene(name+'-'+variant,bg,family=name,variant=variant)
            if variant in ('clear','low-res','jpeg-blur','edge-cut'):
                foundation(p)
                if variant=='edge-cut':
                    p.label('cut-left','THE LAST TRAIN',(-35,210),size=34,clipped=True)
                    p.label('cut-right','WAIT HERE',(680,210),size=34,clipped=True)
                elif variant in ('low-res','jpeg-blur'):p=transformed(p,variant)
            elif variant=='direct':
                p.label('effect','WHOOSH!',(60,180),size=70,color='white',outline=3,stroke_color='#161d29',angle=12,kind='sfx')
                p.label('caption','明日は駅で友達を待ちます。',(60,475),size=30,color='#fff1cb',outline=1,stroke_color='black')
                p.label('small','Gate C7 12:30!?',(410,660),size=19,color='white',outline=1,stroke_color='black')
            elif variant=='rotated':
                p.label('a','KEEP THE GATE OPEN',(40,80),size=30,angle=-12,color='white',outline=2,stroke_color='black')
                p.label('b','先生は静かに話します。',(100,330),size=26,angle=18,color='white',outline=1,stroke_color='black')
                p.label('c','WAIT HERE',(620,450),size=28,angle=90,color='white',outline=1,stroke_color='black')
            else:
                draw=ImageDraw.Draw(p.clean)
                for j in range(2):
                    for i in range(4):
                        x,y=10+i*185,100+j*285
                        draw.rectangle([x,y,min(767,x+215),y+115],fill='#f7f7f7',outline='#777777',width=2)
                for j in range(2):
                    for i in range(4):
                        x,y=10+i*185,100+j*285
                        p.label(f'c{i}r{j}','WAIT C7' if j==0 else '先生は話します。',(x+10,y+25),size=20 if j==0 else 16,frame=[x,y,min(768,x+215),y+115],bold=j==0)
                        p.rows[-1]['column']=i+1
            yield p
    bg=backgrounds['archive-sheet']
    for delta in (0,2,4,8,16,32,64,128):
        p=Scene(f'contrast-{delta:03d}',bg,family='contrast',variant=str(delta),contrast_delta=delta,negative=delta==0)
        ImageDraw.Draw(p.clean).rectangle([35,280,730,450],fill=(230,230,230))
        if delta:
            p.label('probe','WAIT HERE',(90,330),size=34,color=(230-delta,)*3,frame=[35,280,730,450])
        else:
            p.image=p.clean.copy();p.meta['hidden_literal']='WAIT HERE';p.meta['invisible_text_is_not_a_visible_reference']=True
        yield p
    base=Image.new('RGB',(768,768),'#eeeeee');draw=ImageDraw.Draw(base)
    for x in range(80,690,24):draw.line((x,90,x,660),fill='#999999',width=2)
    for y in range(90,670,26):draw.line((80,y,680,y),fill='#aaaaaa',width=2)
    p=Scene('grid-negative',base,family='controls',variant='negative',negative=True);p.image=p.clean.copy();yield p
    p=Scene('grid-single-character',base,family='controls',variant='one-character')
    ImageDraw.Draw(p.clean).rectangle([290,290,470,470],fill='white')
    p.label('glyph','あ',(320,320),size=80,frame=[290,290,470,470]);yield p
    p=Scene('ambiguous-latin-intent',Image.new('RGB',(768,768),'#eeeeee'),family='annotation-twins',variant='latin-intent',semantic_ambiguity=True,exclude_accuracy=True)
    p.label('bars','IIIIIII',(180,290),size=90);p.meta['intended_meaning']='seven uppercase I characters';yield p
    q=deepcopy(p);q.ident='ambiguous-lines-intent';q.meta={**p.meta,'variant':'lines-intent','intended_meaning':'seven nonlinguistic vertical strokes','negative':True}
    q.clean=q.image.copy();q.rows=[];q.masks=[];yield q


def generate(destination,assets):
    dest=Path(destination);assets=Path(assets);dest.mkdir(parents=True,exist_ok=True)
    inventory=json.loads((assets/'assets.json').read_text());backgrounds={}
    for name in NAMES:
        path=assets/(name+'.png')
        if digest(path)!=inventory[name]['sha256']:raise ValueError('Background differs from declared asset: '+name)
        backgrounds[name]=Image.open(path).convert('RGB').resize((768,768),Image.Resampling.LANCZOS)
    refs={'schema':1,'source':'three newly generated text-free backgrounds plus deterministic, independent literals; no user assets',
          'generator_sha256':digest(__file__),'base_generator_sha256':digest(F.__file__),'metrics_sha256':digest(S.__file__),
          'font_sha256':{p.name:digest(p) for p in (S.FONT,BOLD)},'backgrounds':inventory,'pages':[],'ocr':[]}
    for p in scenes(backgrounds):
        if p.image is None:p.image=p.clean.copy()
        im=p.ident+'.png';clean=p.ident+'-clean.png';truth=p.ident+'-truth.npz'
        p.image.save(dest/im);p.clean.save(dest/clean);np.savez_compressed(dest/truth,**{r['id']:m for r,m in zip(p.rows,p.masks)})
        refs['pages'].append({'id':p.ident,'image':im,'clean':clean,'sha256':digest(dest/im),'clean_sha256':digest(dest/clean),
            'truth':truth,'truth_sha256':digest(dest/truth),'size':list(p.image.size),'cleanup':'model','regions':p.rows,**p.meta})
        chosen=p.rows if p.meta['variant'] in ('clear','rotated') else p.rows[:2] if p.meta['variant']=='direct' else p.rows[:1]
        for row in chosen:
            if row['clipped']:continue
            a,b,c,d=row['bbox_pixels'];box=[max(0,a-6),max(0,b-6),min(p.image.width,c+6),min(p.image.height,d+6)]
            filename='ocr-'+p.ident+'-'+row['id']+'.png';p.image.crop(box).save(dest/filename)
            refs['ocr'].append({'id':p.ident+'-'+row['id'],'page_id':p.ident,'image':filename,'sha256':digest(dest/filename),'expected':row['text'],
                'direction':'vertical_rtl' if row['vertical'] else 'auto','exclude_accuracy':p.meta.get('exclude_accuracy',False)})
    (dest/'references.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2),encoding='utf-8')
    return refs


def verify(refs,folder):
    if refs['generator_sha256']!=digest(__file__) or refs['base_generator_sha256']!=digest(F.__file__) or refs['metrics_sha256']!=digest(S.__file__):raise ValueError('Fixture generator changed')
    if refs['font_sha256']!={p.name:digest(p) for p in (S.FONT,BOLD)}:raise ValueError('Fixture fonts changed')
    for row in refs['pages']:
        for key,sha in (('image','sha256'),('clean','clean_sha256'),('truth','truth_sha256')):
            if digest(Path(folder)/row[key])!=row[sha]:raise ValueError('Fixture changed: '+row[key])
    for row in refs['ocr']:
        if digest(Path(folder)/row['image'])!=row['sha256']:raise ValueError('OCR fixture changed')
