"""Render reproducible hybrid examples; synthetic typography, not GPU outputs."""
from argparse import ArgumentParser
import base64
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hybrid_demo',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
from hybrid_demo.lettering import core,hybrid


def demo(destination,preview_log=False):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    fontpath=core.font_path('NanumGothic-Bold.ttf','한국어')
    examples=[
      ('짧은 번역 · 원문 크기 상한','SOURCE','가',400,140,42,{}),
      ('긴 번역 · 행 수 유지하며 축소','SOURCE','원본보다 아주 긴 한국어 문장입니다',400,140,42,{'min_scale':.3}),
      ('최소 크기 도달 후 재배치','SOURCE','이 문장은 여러 줄로 재배치해야 읽을 수 있는 번역문입니다',210,180,32,{'min_scale':.65}),
      ('영역별 세로쓰기 · 숫자·라틴','SOURCE','가나다 12 TEST!',200,320,32,{'direction':'vertical_rtl','min_scale':.3}),
      ('말풍선 마스크 안에서 확장','TEST','원본보다 긴 번역문을 말풍선 안에 다시 배치합니다',400,240,26,{'mode':'bubble','min_scale':.8}),
      ('수동 회전·기울기·곡선','SOURCE','효과음',400,180,48,{'region_options_json':json.dumps({'r1':{'rotation':12,'shear':.1,'bend':8}}),'min_scale':.3})]
    sheet=Image.new('RGB',(960,1800),'#eeeeee');d=ImageDraw.Draw(sheet)
    label=ImageFont.truetype(fontpath,20);small=ImageFont.truetype(fontpath,15)
    d.text((20,10),'합성 입력 · 실제 폰트 렌더링 / GPU 모델 추론 결과 아님',font=label,fill='black')
    reports={}
    for index,(name,source,target,w,h,size,options) in enumerate(examples):
        clean=Image.new('RGB',(w,h),'#a6a6a6')
        bounds=[10,10,w-20,h-20]
        if options.get('mode')=='bubble':
            clean=Image.new('RGB',(w,h),'#777777');cd=ImageDraw.Draw(clean)
            cd.ellipse((30,20,370,220),fill='#eeeeee')
            yy,xx=np.mgrid[:h,:w]
            options['bubble_mask']=(((xx-200)/168)**2+((yy-120)/98)**2<1).astype(np.float32)
            bounds=[140,85,120,70]
        original=clean.copy()
        ImageDraw.Draw(original).text((w//2,h//2),source,font=ImageFont.truetype(fontpath,size),anchor='mm',fill='black')
        orig=np.asarray(original,np.float32)/255;bg=np.asarray(clean,np.float32)/255
        mask=(np.max(np.abs(orig-bg),axis=2)>.03).astype(np.float32)
        doc=json.dumps({'schema':1,'coordinate_format':'xywh','page_size':[w,h],
                        'regions':[{'id':'r1','bbox':bounds,'text':target,'source_text':source}]})
        plan,preview,planning=hybrid.build_plan(orig,bg,mask,doc,**options)
        result,alpha,report=hybrid.render_plan(plan);report=json.loads(report);reports[str(index+1)]=report
        for filename,array in [('original',orig),('result',result),('plan',preview),('alpha',alpha)]:
            Image.fromarray((array*255).round().astype('uint8')).save(destination/f'{index+1}-{filename}.png')
        top=55+index*285
        d.text((20,top),name,font=label,fill='black')
        row=report['regions'][0]
        d.text((20,top+29),f"상한 {plan['regions'][0]['cap']}px → {row['render']['font_size']}px / {row['fit_phase']}",font=small,fill='#333333')
        for col,picture in enumerate([original,Image.fromarray((result*255).round().astype('uint8'))]):
            picture=picture.copy();picture.thumbnail((440,205),Image.Resampling.LANCZOS)
            sheet.paste(picture,(20+col*480,top+58))
    sheet.save(destination/'comparison.png')
    (destination/'reports.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    if preview_log:
        print('HYBRID_PREVIEW_BASE64='+base64.b64encode((destination/'comparison.png').read_bytes()).decode('ascii'))
    print(json.dumps({k:{'size':v['regions'][0]['render']['font_size'],'phase':v['regions'][0]['fit_phase']} for k,v in reports.items()}))
    return reports


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__);parser.add_argument('--destination',required=True)
    parser.add_argument('--preview-log',action='store_true')
    args=parser.parse_args();demo(args.destination,args.preview_log)
