"""Bounded glossary and artifact-verified, human-approved preceding-page context."""
import hashlib
import json
from pathlib import Path
from .document import digest


def glossary(value):
    if len(value.encode())>262144:raise ValueError('Glossary exceeds 256 KiB')
    entries=json.loads(value)
    if not isinstance(entries,list) or len(entries)>2048:raise ValueError('Glossary needs at most 2048 entries')
    found={}
    for e in entries:
        if not isinstance(e,dict) or set(e)-{'source','target','note'} or any(not isinstance(e.get(k),str) or not e[k].strip() or len(e[k])>512 for k in ('source','target')) or not isinstance(e.get('note',''),str) or len(e.get('note',''))>1024:raise ValueError('Invalid glossary entry')
        key=e['source'].casefold()
        if key in found and found[key]['target']!=e['target']:raise ValueError('Conflicting glossary targets')
        found[key]=e
    return list(found.values())


def history(report,language,budget):
    if not report or not report.get('project_folder') or not budget:return []
    import folder_paths
    root=(Path(folder_paths.get_output_directory())/'manga_translator'/'workflow_projects').resolve()
    folder=Path(report['project_folder']).resolve()
    if folder==root or not folder.is_relative_to(root):raise ValueError('Context project lies outside workflow projects')
    pages=[]
    for page in report.get('pages',[]):
        if page.get('relative_path')==report.get('current_page'):break
        if page.get('status')!='completed':continue
        try:
            state_path=(folder/page['state_file']).resolve()
            if not state_path.is_relative_to(folder) or state_path.name!='state.json':continue
            state=json.loads(state_path.read_text());path=state_path.parent/'target.json'
            if path.stat().st_size>4*1024*1024:continue
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=state['artifacts']['target.json']:continue
            data=json.loads(raw);rows=data.get('regions',[])
            if data.get('translation_metadata',{}).get('target_language')!=language or not rows or any(r.get('authored',{}).get('target',{}).get('origin')!='human' for r in rows):continue
            pages.append({'page':page['relative_path'],'regions':[{'source':r['source'],'target':r['target']} for r in rows]})
        except (OSError,ValueError,KeyError,TypeError):continue
    chosen=[];used=0
    for p in reversed(pages):
        size=len(json.dumps(p,ensure_ascii=False).encode())
        if used+size>budget:break
        chosen.insert(0,p);used+=size
    return chosen


class MangaTranslationContext:
    CATEGORY='Manga Translator/Translation';FUNCTION='build'
    DESCRIPTION='용어집과 사람이 확정한 이전 페이지 번역만 문맥으로 사용합니다. 자동 요약을 만들지 않습니다.'
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'ocr_json':('STRING',{'forceInput':True}),
        'glossary_json':('STRING',{'default':'[]','multiline':True}),'target_language':('STRING',{'default':'Korean'}),
        'style_instructions':('STRING',{'default':'','multiline':True}),'history_bytes':('INT',{'default':12000,'min':0,'max':128000})},
        'optional':{'project_report':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('STRING','STRING','STRING');RETURN_NAMES=('번역_문맥','문맥_보고서','번역_언어')
    def build(self,ocr_json,glossary_json='[]',target_language='Korean',style_instructions='',history_bytes=12000,project_report=None):
        if type(history_bytes) is not int or not 0<=history_bytes<=128000 or len(style_instructions)>8192:raise ValueError('Invalid context budget')
        source=json.loads(ocr_json);text='\n'.join(r.get('source','') for r in source['regions']).casefold()
        selected=[e for e in glossary(glossary_json) if e['source'].casefold() in text]
        previous=history(json.loads(project_report) if project_report else None,target_language,history_bytes)
        context={'schema':1,'source_revision':digest(source),'target_language':target_language,
                 'glossary':selected,'reviewed_history':previous,'style_instructions':style_instructions}
        report=json.dumps({'matched_terms':len(selected),'history_pages':len(previous),'history_budget_bytes':history_bytes,'scope':'human_approved_preceding_pages_only'})
        return json.dumps(context,ensure_ascii=False),report,target_language
