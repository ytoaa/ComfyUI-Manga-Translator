"""Read-only stage inspection; no model calls, pixel replacement or quality verdicts."""
import json
import math
import numpy as np
from PIL import Image, ImageDraw

from .nodes import encode, layout
from .lettering.nodes import image, mask, tensor

STAGES = ['detection', 'ocr', 'cleanup_plan', 'cleanup', 'letter_plan', 'letter_render']


def document(value):
    if not isinstance(value,str) or len(value)>2_000_000:
        raise ValueError('Debug report must be JSON text at most 2,000,000 characters')
    result=json.loads(value,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite debug report')))
    if not isinstance(result,dict):raise ValueError('Debug report must be an object')
    return result


def detection_report(result,regions,original):
    if not isinstance(result,dict) or result.get('protocol')!=1:
        raise ValueError('Connect a detector result to detection debug')
    height,width=original.shape[:2]
    if (result.get('image_width'),result.get('image_height'))!=(width,height):
        raise ValueError('Detection debug image dimensions differ from detector result')
    data=layout(regions)
    if (data.get('image_width'),data.get('image_height'))!=(width,height):
        raise ValueError('Detection debug regions belong to another page size')
    audit=result.get('detection_audit',{})
    excluded=audit.get('excluded_candidates',[])
    if not isinstance(excluded,list) or len(excluded)>256:raise ValueError('Invalid excluded candidate report')
    stride=max(1,math.ceil(max(width,height)/2048))
    canvas=Image.fromarray((original[::stride,::stride]*255).round().astype('uint8'))
    draw=ImageDraw.Draw(canvas)
    for row in excluded:
        box=row.get('bbox_pixels') if isinstance(row,dict) else None
        if (not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box)):
            raise ValueError('Invalid excluded candidate box')
        a,b,c,d=box
        a,b,c,d=max(0,a),max(0,b),min(width-1,c),min(height-1,d)
        if c>a and d>b:draw.rectangle((a/stride,b/stride,c/stride,d/stride),outline=(255,160,30),width=2)
    rows=[]
    for row in data['regions']:
        a,b,c,d=[v*s/1000 for v,s in zip(row['bbox'],(width,height,width,height))]
        draw.rectangle((a/stride,b/stride,max(a,c-1)/stride,max(b,d-1)/stride),outline=(30,220,100),width=2)
        draw.text((a/stride,max(0,b/stride-13)),row['id'],fill=(10,90,30),stroke_width=1,stroke_fill='white')
        rows.append({'id':row['id'],'bbox_pixels':[a,b,c,d],'kind':row.get('kind','text')})
    report={'image_width':width,'image_height':height,'selected_regions':rows,
            'preview_size':list(canvas.size),'preview_stride':stride,
            'excluded_locations_available':bool(excluded) or audit.get('excluded_onomatopoeia_detections',0)==0,
            'detection_audit':audit,'region_resolution':data.get('region_resolution',{}),
            'legend':'green=selected logical region; orange=excluded onomatopoeia candidate',
            'notes':['Excluded candidates are raw overlapping inference observations, not unique text instances.',
                     'A detector class does not prove the semantic role of the lettering.',
                     'Older detector reports contain counts only; excluded locations require a new detection run.']}
    return report,np.asarray(canvas,np.float32)/255


class MangaDebugInspect:
    CATEGORY='Manga Translator/디버깅'
    DESCRIPTION='읽기 전용 단계 보고서와 검수 이미지. 보고서→미리보기 아무거나, 검수 이미지→이미지 미리보기. 성공 판정이나 처리 설정을 바꾸지 않습니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'stage':(STAGES,{'default':'detection'})},'optional':{
            'report_json':('STRING',{'forceInput':True,'tooltip':'단계의 보고서 STRING 출력. detection에서는 정리된 영역 JSON.'}),
            'preview_image':('IMAGE',{'tooltip':'원본 또는 단계 이미지. detection은 원본 페이지를 연결.'}),
            'preview_mask':('MASK',{'tooltip':'선택: 원문 스타일 마스크 또는 새 글자 알파. 이미지보다 우선하여 흑백으로 표시.'}),
            'detection_result':('MANGA_DETECTION',{'tooltip':'detection 단계에만 필요한 검출 결과.'})}}
    RETURN_TYPES=('STRING','IMAGE')
    RETURN_NAMES=('단계_디버그_JSON','단계_검수_이미지')
    FUNCTION='inspect'

    def inspect(self,stage,report_json=None,preview_image=None,preview_mask=None,detection_result=None):
        if stage not in STAGES:raise ValueError('Invalid debug stage')
        if stage=='detection':
            if preview_image is None:raise ValueError('Connect original page to detection debug')
            report,preview=detection_report(detection_result,report_json,image(preview_image))
            output=tensor(preview)
        else:
            report=document(report_json)
            if preview_mask is not None:
                selected=mask(preview_mask)
                if not np.isfinite(selected).all():raise ValueError('Invalid debug mask values')
                stride=max(1,math.ceil(max(selected.shape)/2048))
                selected=selected[::stride,::stride]
                output=tensor(np.repeat(np.clip(selected,0,1)[...,None],3,axis=-1))
            elif preview_image is not None:
                output=preview_image
            else:
                canvas=Image.new('RGB',(320,48),'#303030')
                ImageDraw.Draw(canvas).text((10,16),'No preview image/mask connected',fill='white')
                output=tensor(np.asarray(canvas,np.float32)/255)
        scope={'detection':'class_selection_not_text_completeness',
               'ocr':'heuristic_checks_not_recognition_accuracy',
               'cleanup_plan':'mask_and_tile_plan_not_background_quality',
               'cleanup':'pixel_checks_not_semantic_restoration_quality',
               'letter_plan':'measured_style_and_geometry_estimates',
               'letter_render':'render_geometry_not_translation_accuracy'}[stage]
        return encode({'schema':1,'stage':stage,'quality_scope':scope,'report':report}),output
