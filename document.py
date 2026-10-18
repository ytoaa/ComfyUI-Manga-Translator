"""Document snapshots and revision-bound human edits; legacy region fields remain interoperable."""
from copy import deepcopy
import hashlib
import json
import math
import re
import unicodedata


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def review_identity(context):
    """A stable page owner, independent of inference output or attempt number."""
    value=json.loads(context or '{}')
    if not isinstance(value,dict):raise ValueError('Review page context must be an object')
    identity=value.get('review_identity',{})
    if not isinstance(identity,dict):raise ValueError('Invalid review page identity')
    if identity and (set(identity)!={'page_key','input_sha256'} or
            any(not isinstance(identity[k],str) or not identity[k] for k in identity)):
        raise ValueError('Review identity needs page_key and input_sha256')
    return identity


def review_revision(data,identity,stage):
    # Diagnostics, cached document mirrors and machine reports are not authored
    # content. Only fields whose changes can invalidate an edit belong here.
    fields=('id','kind','bbox','crop_bbox_pixels','edit_bbox_pixels','line_bboxes_pixels','source','blocks','presentation')
    rows=[]
    for row in data['regions']:
        item={k:deepcopy(row[k]) for k in fields if k in row}
        if stage=='target' and 'target' in row:item['target']=row['target']
        if 'blocks' in item:
            keep=('id','source','bbox_local','coordinate_frame','role','presentation')+ (('target',) if stage=='target' else ())
            item['blocks']=[{k:b[k] for k in keep if k in b} for b in item['blocks']]
        geometry=row.get('ocr_region_plan',{})
        item['frame']={k:geometry[k] for k in ('strategy','source_angle','correction_degrees','rectified_size','rows','source_quad') if k in geometry}
        rows.append(item)
    return digest({'page':identity,'stage':stage,'size':[data.get('image_width'),data.get('image_height')],'regions':rows})


def review_text(value,source=False):
    if __package__: from .text_contract import ocr_problem
    else: from text_contract import ocr_problem
    if not isinstance(value,str) or not value.strip() or len(value)>(16000 if source else 2048):
        raise ValueError('Review needs nonempty plain text within the text budget')
    if ocr_problem(value) or re.search(r'<br\b',value,re.I) or any(unicodedata.category(c).startswith('C') and c!='\n' for c in value):
        raise ValueError('Review text contains unresolved OCR or markup/control characters')
    return value


def attach(data):
    data=deepcopy(data)
    data['document_version']=2
    data['document']={'schema':2,'coordinate_format':'explicit_per_field','regions':[
        {'id':r['id'],'analysis':{k:v for k,v in {
            'bbox_normalized_1000':r.get('bbox'),'crop_bbox_pixels':r.get('crop_bbox_pixels'),
            'line_bboxes_pixels':r.get('line_bboxes_pixels')}.items() if v is not None},
         'content':{k:r[k] for k in ('source','target','blocks') if k in r},
         'presentation':r.get('presentation',{}),'authored':r.get('authored',{})} for r in data['regions']]}
    return data


def blocks_from_ocr(row,report):
    plan=row.get('ocr_region_plan',{});boxes=plan.get('rows',[]);texts=report.get('line_texts',[])
    bands=plan.get('evidence',{}).get('row_validation',{}).get('bands_pixels',[])
    if not 2<=len(boxes)==len(texts)==len(bands)<=32: return []
    heights=[b[1]-b[0] for b in bands]
    if min(heights)<=0 or max(heights)<min(heights)*1.4:return []
    groups=[]
    for i,h in enumerate(heights):
        if not texts[i].strip():return []
        x,y,z,t=boxes[i];start,end=bands[i]
        bound=[x,max(y,start-3),z,min(t,end+3)]
        if groups and max(h,groups[-1]['height'])/min(h,groups[-1]['height'])<1.35:
            g=groups[-1];g['indices'].append(i);g['source']+='\n'+texts[i]
            a,b,c,d=g['bbox_local'];x,y,z,t=bound;g['bbox_local']=[min(a,x),min(b,y),max(c,z),max(d,t)]
        else:groups.append({'indices':[i],'source':texts[i],'height':h,'bbox_local':bound})
    if len(groups)<2:return []
    ordered=sorted(heights);n=len(ordered)
    median=(ordered[(n-1)//2]+ordered[n//2])/2
    return [{'id':f"{row['id']}__b{i+1}",**g,'role':'heading' if g['height']>median*1.3 else 'body',
             'coordinate_frame':'rectified_crop_pixels','inferred':True} for i,g in enumerate(groups)]


def validate_blocks(row):
    blocks=row.get('blocks',[])
    if not isinstance(blocks,list) or len(blocks)>32:raise ValueError('At most 32 paragraph blocks per region')
    ids=set()
    for b in blocks:
        ident=b.get('id') if isinstance(b,dict) else None
        if not isinstance(ident,str) or not ident or ident in ids:raise ValueError('Unique paragraph IDs required')
        ids.add(ident);review_text(b.get('source'),True)
        if 'target' in b:review_text(b['target'])
        frame=b.get('coordinate_frame');box=b.get('bbox_local')
        if frame not in ('rectified_crop_pixels','source_crop_pixels') or not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):raise ValueError('Invalid paragraph geometry')
        a,c,d,e=box
        if min(a,c)<0 or d<=a or e<=c:raise ValueError('Invalid paragraph rectangle')
        size=row.get('ocr_region_plan',{}).get('rectified_size') if frame=='rectified_crop_pixels' else None
        if frame=='source_crop_pixels' and row.get('crop_bbox_pixels'):
            x,y,z,t=row['crop_bbox_pixels'];size=[z-x,t-y]
        if size and (d>size[0] or e>size[1]):raise ValueError('Paragraph lies outside its source frame')
    return blocks


def validate_target(row):
    from .lettering.core import clean_text
    blocks=validate_blocks(row)
    if not blocks:return clean_text(row.get('target'))
    for block in blocks:clean_text(block.get('target'))
    if row.get('target')!='\n\n'.join(b['target'] for b in blocks):
        raise ValueError('Parent translation must match its paragraph targets')
    return row['target']


def translation_units(data):
    result=deepcopy(data);units=[];mapping={}
    for r in result['regions']:
        blocks=validate_blocks(r)
        if not blocks:units.append(r);continue
        for b in blocks:
            ident='p_'+digest([r['id'],b['id']])[:24]
            units.append({'id':ident,'bbox':r['bbox'],'source':b['source'],'kind':r.get('kind','text')})
            mapping[ident]=(r['id'],b['id'])
    if len(units)>128:raise ValueError('Translation paragraph budget exceeded')
    result['regions']=units
    return result,mapping


def merge_translations(original,translated,mapping):
    result=deepcopy(original);rows={r['id']:r for r in result['regions']}
    for r in rows.values():r.get('authored',{}).pop('target',None)
    for r in translated['regions']:
        if r['id'] in mapping:
            parent,block=mapping[r['id']]
            next(b for b in rows[parent]['blocks'] if b['id']==block).update({k:r[k] for k in ('target','translation_diagnostics') if k in r})
        else:rows[r['id']].update({k:r[k] for k in ('target','translation_diagnostics') if k in r})
    for r in rows.values():
        if r.get('blocks'):r['target']='\n\n'.join(b['target'] for b in r['blocks'])
    return attach(result)


def apply_edits(data,patch,stage):
    result=deepcopy(data);rows={r['id']:r for r in result['regions']}
    if stage not in ('source','target') or not isinstance(patch,dict) or set(patch)-rows.keys():raise ValueError('Review edits must reference current region IDs')
    for ident,edits in patch.items():
        r=rows[ident];allowed={'source','blocks'} if stage=='source' else {'target','blocks','presentation'}
        if not isinstance(edits,dict) or set(edits)-allowed:raise ValueError('Invalid review edit fields')
        if 'presentation' in edits and (not isinstance(edits['presentation'],dict) or set(edits['presentation'])-{'font','layout','style'}):raise ValueError('Presentation accepts font, layout and style')
        if 'blocks' in edits:
            validate_blocks({**r,'blocks':edits['blocks']})
            if stage=='target':
                if any(not isinstance(b.get('target'),str) or not b['target'].strip() for b in edits['blocks']):raise ValueError('Every reviewed paragraph needs target text')
                old={b['id']:b for b in r.get('blocks',[])}
                if set(old)!={b['id'] for b in edits['blocks']}:raise ValueError('Target review cannot change paragraph IDs')
                for b in edits['blocks']:
                    if any(b.get(k)!=old[b['id']].get(k) for k in ('source','bbox_local','coordinate_frame')):raise ValueError('Change paragraph source/geometry in source review')
        for key,value in edits.items():
            if key in ('source','target'):review_text(value,key=='source')
            r[key]=deepcopy(value);r.setdefault('authored',{})[key]={'origin':'human','base_revision':digest(data)}
        if stage=='source' and edits:
            r.pop('target',None)
            r.get('authored',{}).pop('target',None)
            if 'blocks' not in edits:r.pop('blocks',None)
            for b in r.get('blocks',[]):b.pop('target',None)
        elif 'target' in edits and r.get('blocks'):
            parts=r['target'].split('\n\n')
            if len(parts)==len(r['blocks']) and all(p.strip() for p in parts):
                for b,t in zip(r['blocks'],parts):b['target']=t
            else:r.pop('blocks')
        if 'blocks' in edits:
            r['source']='\n'.join(b['source'] for b in r['blocks'])
            if stage=='target':
                r['target']='\n\n'.join(b['target'] for b in r['blocks'])
                r.setdefault('authored',{})['target']={'origin':'human','base_revision':digest(data)}
    if patch:result.pop('page_edit_plan',None)
    return attach(result)


class MangaReviewDocument:
    CATEGORY='Manga Translator/검수'
    DESCRIPTION='이 페이지의 원문/번역을 수정·확정합니다. 수정은 입력 revision에 묶여 다른 페이지에 적용되지 않습니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'document_json':('STRING',{'forceInput':True}),'stage':(['source','target'],),
                            'edits_json':('STRING',{'default':'{}','multiline':True})},
                'optional':{'page_context_json':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('STRING','STRING');RETURN_NAMES=('검수_문서','검수_보고서');FUNCTION='review'
    def review(self,document_json,stage='source',edits_json='{}',page_context_json='{}'):
        if len(edits_json.encode())>1024*1024:raise ValueError('Review edits exceed 1 MiB')
        if __package__:from .nodes import layout
        else:from nodes import layout
        data=layout(document_json);identity=review_identity(page_context_json)
        revision=review_revision(data,identity,stage);edits=json.loads(edits_json)
        if not isinstance(edits,dict) or set(edits)-{'pages','identities'}:raise ValueError('Review edits need pages and optional identities objects')
        pages=edits.get('pages',{})
        if not isinstance(pages,dict) or len(pages)>256:raise ValueError('Review supports at most 256 page revisions')
        owners=edits.get('identities',{})
        if not isinstance(owners,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in owners.items()):
            raise ValueError('Review identities must map revisions to page keys')
        selected=pages.get(revision,{}) if identity and owners.get(revision)==identity['page_key'] else {}
        stale=[key for key in pages if key!=revision and owners.get(key)==identity.get('page_key')]
        legacy=[key for key in pages if key not in owners]
        result=apply_edits(data,selected,stage)
        report=json.dumps({'stage':stage,'input_revision':revision,'edited_regions':len(selected),
            'page_identity':identity.get('page_key'),'identity_verified':bool(identity),
            **({'stale_edits':stale} if stale else {}),
            **({'legacy_edits':legacy,'conflicts':['이전 교정은 페이지 소유권이 없어 자동 적용하지 않았습니다. 새 통합 08에서 확인 후 다시 저장하세요.']} if legacy else {}),
            **({'conflicts':['페이지 식별 정보가 없습니다. 입력의 상태 출력을 page_context_json에 연결하세요.']} if not identity else {})},ensure_ascii=False)
        return {'ui':{'manga_document':[{'stage':stage,'input_revision':revision,'page_identity':identity.get('page_key'),
                                       'identity_verified':bool(identity),'warnings':json.loads(report).get('conflicts',[])+
                                           (['원문 또는 배치가 바뀐 이전 교정이 있습니다. 확인 후 다시 저장하세요.'] if stale else []),
                                       'document':result}],'text':[report]},
                'result':(json.dumps(result,ensure_ascii=False),report)}
