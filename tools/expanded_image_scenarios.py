"""Independent generated stress images; no user assets or model-made answers."""
from pathlib import Path
import hashlib
import json

import numpy as np
from PIL import Image, ImageDraw

if __package__:
    from . import image_scenarios as S
else:
    import image_scenarios as S


class Scene:
    def __init__(self, ident, size=(800, 640), background='white', cleanup='flat'):
        self.ident, self.cleanup = ident, cleanup
        self.clean = Image.new('RGB', size, background)
        self.image = None
        self.rows, self.masks = [], []

    def add(self, ident, text, xy, size=28, color='black', angle=0, vertical=False,
            outline=0, frame=None, clipped=False, stroke_color=None, fixed_target=None, kind='text'):
        if self.image is None:self.image = self.clean.copy()
        # Check the complete literal, including characters not visible after a cut.
        face = S.font(size, text)
        if vertical:
            alpha = Image.new('L', (size*2+20, (size+6)*len(text)+20))
            draw = ImageDraw.Draw(alpha)
            for i, char in enumerate(text):draw.text((10, 5+i*(size+6)), char, font=face, fill=255)
        else:
            box = ImageDraw.Draw(Image.new('L', (1, 1))).multiline_textbbox((0, 0), text, font=face, spacing=8, stroke_width=outline)
            alpha = Image.new('L', (box[2]-box[0]+16, box[3]-box[1]+16))
            ImageDraw.Draw(alpha).multiline_text((8-box[0], 8-box[1]), text, font=face, fill=255, spacing=8, stroke_width=outline)
        inner=None
        if stroke_color is not None and outline:
            inner=Image.new('L',alpha.size)
            ImageDraw.Draw(inner).multiline_text((8-box[0],8-box[1]),text,font=face,fill=255,spacing=8)
        if angle:
            alpha = alpha.rotate(angle, Image.Resampling.BICUBIC, expand=True)
            if inner is not None:inner=inner.rotate(angle,Image.Resampling.BICUBIC,expand=True)
        full = Image.new('L', self.clean.size);full.paste(alpha, xy)
        mask = np.asarray(full)>0
        self.image.paste(stroke_color if inner is not None else color, mask=full)
        if inner is not None:
            pigment=Image.new('L',self.clean.size);pigment.paste(inner,xy)
            self.image.paste(color,mask=pigment)
            # Independently resampled fill/outline can have different 1px
            # bicubic fringes. Truth must cover both painted alpha layers.
            mask |= np.asarray(pigment)>0
        yy, xx = np.where(mask)
        if not len(xx):raise ValueError('Invisible generated reference: '+ident)
        box = [int(xx.min()), int(yy.min()), int(xx.max()+1), int(yy.max()+1)]
        if frame is None:
            frame = [max(0, box[0]-12), max(0, box[1]-12), min(self.clean.width, box[2]+12), min(self.clean.height, box[3]+12)]
        self.rows.append({'id': ident, 'text': text, 'kind': kind, 'bbox_pixels': box,
                          'frame_pixels': frame, 'source_size': size, 'source_angle': angle,
                          'vertical': vertical, 'clipped': clipped,
                          **({'fixed_target':fixed_target} if fixed_target else {})})
        self.masks.append(mask)


def scenes():
    p=Scene('tiny-bubbles')
    draw=ImageDraw.Draw(p.clean)
    for x, size in ((25,10),(275,14),(525,20)):
        draw.ellipse((x,60,x+235,200),fill='#ffffff',outline='#222222',width=3)
    for x, size in ((25,10),(275,14),(525,20)):
        p.add('s'+str(size),'先生は話します。',(x+20,105),size=size)
    # Decorations precede the first glyph, so every source uses this same clean page.
    yield p
    p=Scene('mixed-directions', (800,760), '#eeeeee')
    p.add('horizontal','春の公園を歩きます。',(40,60),size=28)
    p.add('vertical','先生は静かに話します。',(610,100),size=26,vertical=True)
    p.add('latin','TRAIN C7',(60,400),size=32)
    yield p
    p=Scene('bright-and-colored')
    draw=ImageDraw.Draw(p.clean);draw.rectangle((30,40,770,210),fill='#222222');draw.rectangle((30,340,770,540),fill='#365d83')
    p.add('white','KEEP THE DOOR OPEN',(60,90),color='white',size=34)
    p.add('cream','春の公園は静かです。',(70,400),color='#fff1cf',size=32)
    yield p
    p=Scene('low-contrast',background='#e6e6e6')
    p.add('faint','先生は静かに話します。',(60,200),size=30,color='#dcdcdc')
    yield p
    p=Scene('outlined-effect',background='#7192a9',cleanup='model')
    draw=ImageDraw.Draw(p.clean)
    for x in range(0,800,22):draw.line((x,0,x+130,640),fill='#93adbf',width=3)
    p.add('effect','WHOOSH!',(70,180),size=76,color='white',outline=3,stroke_color='#161d29',angle=10,kind='sfx')
    yield p
    p=Scene('mixed-punctuation')
    p.add('mixed','先生 C7 12:30!?',(90,200),size=34,fixed_target='확인 C7 12:30!? 「봄」')
    yield p
    p=Scene('high-dpi',size=(2400,1800))
    p.add('heading','KEEP THE GATE OPEN',(350,650),size=96)
    yield p
    p=Scene('gradient-caption',cleanup='model')
    x=np.linspace(90,225,800,dtype=np.uint8)
    p.clean=Image.fromarray(np.broadcast_to(x[None,:,None],(640,800,3)).copy())
    p.add('caption','NEXT MORNING\nKEEP WALKING',(90,200),size=34,color='#10243a')
    yield p
    p=Scene('screentone',cleanup='model')
    draw=ImageDraw.Draw(p.clean)
    for y in range(0,640,6):
        for x in range(0,800,6):draw.rectangle((x,y,x+1,y+1),fill='#777777')
    p.add('tone','春の公園を友達と歩きます。',(65,200),size=32)
    yield p
    p=Scene('slanted-labels',size=(900,760))
    for i,angle in enumerate((-23,12,24)):
        p.add('angle'+str(i),'LIBRARY NOTES',(80,40+i*230),size=28,angle=angle)
    yield p
    p=Scene('narrow-vertical',size=(640,760))
    p.add('narrow','先生は静かに話します。',(280,70),size=28,vertical=True)
    yield p
    p=Scene('overlap-paragraphs',size=(640,480))
    p.add('upper','春の公園',(350,115),size=26,frame=[170,80,510,280])
    p.add('lower','明日は学校へ',(250,245),size=26,frame=[230,180,440,350])
    yield p
    p=Scene('dense-footnotes',size=(900,700))
    for i in range(12):p.add('note'+str(i),f'Ref {i+1:02d}',(35+(i%4)*225,60+(i//4)*210),size=12)
    yield p
    p=Scene('edge-clipped')
    p.add('cut','KEEP THE GATE OPEN',(-35,150),size=38,clipped=True)
    yield p
    p=Scene('nontext-art')
    draw=ImageDraw.Draw(p.clean)
    draw.ellipse((70,50,350,330),fill='#dddddd',outline='black',width=7)
    for k in range(8):draw.line((420+k*25,100,420+k*25,420),fill='#777777',width=3)
    draw.polygon([(110,480),(280,380),(350,560)],fill='#444444')
    p.image=p.clean.copy()
    yield p


def generate(destination):
    dest=Path(destination);dest.mkdir(parents=True,exist_ok=True)
    refs={'schema':1,'source':'new generated shapes/text only; no user assets',
          'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'base_generator_sha256':hashlib.sha256(Path(S.__file__).read_bytes()).hexdigest(),
          'font_sha256':hashlib.sha256(S.FONT.read_bytes()).hexdigest(),'pages':[],'ocr':[]}
    for p in scenes():
        if p.image is None:p.image=p.clean.copy()
        p.image.save(dest/(p.ident+'.png'));p.clean.save(dest/(p.ident+'-clean.png'))
        np.savez_compressed(dest/(p.ident+'-truth.npz'),**{r['id']:m for r,m in zip(p.rows,p.masks)})
        refs['pages'].append({'id':p.ident,'image':p.ident+'.png','clean':p.ident+'-clean.png',
            'sha256':hashlib.sha256((dest/(p.ident+'.png')).read_bytes()).hexdigest(),
            'clean_sha256':hashlib.sha256((dest/(p.ident+'-clean.png')).read_bytes()).hexdigest(),
            'size':list(p.image.size),'cleanup':p.cleanup,'regions':p.rows})
        # Representative known crops; a clipped original has no full-text oracle.
        chosen=p.rows if p.ident in ('mixed-directions','slanted-labels') else p.rows[:1]
        for r in chosen:
            if r['clipped']:continue
            box=r['bbox_pixels'];box=[max(0,box[0]-6),max(0,box[1]-6),min(p.image.width,box[2]+6),min(p.image.height,box[3]+6)]
            filename='ocr-'+p.ident+'-'+r['id']+'.png';p.image.crop(box).save(dest/filename)
            refs['ocr'].append({'id':p.ident+'-'+r['id'],'image':filename,'sha256':hashlib.sha256((dest/filename).read_bytes()).hexdigest(),
                               'expected':r['text'],'direction':'vertical_rtl' if r['vertical'] else 'auto'})
    (dest/'references.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2),encoding='utf-8')
    return refs
