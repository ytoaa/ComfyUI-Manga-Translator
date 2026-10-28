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


def _read_json_bytes(path, limit):
    if not path.is_file():raise ValueError('Context artifact must be a regular file')
    with path.open('rb') as stream:
        raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Context artifact exceeds size limit')
    return raw


def history(report,language,budget):
    if not report or not budget:return []
    if not isinstance(report,dict):raise ValueError('Context report must be an object')
    if not report.get('project_folder'):return []
    import folder_paths
    output=Path(folder_paths.get_output_directory()).resolve()
    root=(output/'manga_translator'/'workflow_projects').resolve()
    folder=Path(report['project_folder']).resolve()
    if not root.is_relative_to(output) or folder==root or not folder.is_relative_to(root):
        raise ValueError('Context project lies outside workflow projects')
    pages=report.get('pages',[]);current=report.get('current_page')
    if not isinstance(pages,list) or not isinstance(current,str) or not current:return []
    positions=[i for i,p in enumerate(pages) if isinstance(p,dict) and p.get('relative_path')==current]
    if len(positions)!=1:return []
    chosen=[];used=0
    for page in reversed(pages[:positions[0]]):
        if used>=budget:break
        if not isinstance(page,dict) or page.get('status')!='completed' or not isinstance(page.get('relative_path'),str):continue
        try:
            state_path=(folder/page['state_file']).resolve()
            if not state_path.is_relative_to(folder) or state_path.name!='state.json':continue
            state=json.loads(_read_json_bytes(state_path,2*1024*1024))
            if not isinstance(state,dict) or not isinstance(state.get('artifacts'),dict):continue
            path=(state_path.parent/'target.json').resolve()
            if path.parent!=state_path.parent:continue
            raw=_read_json_bytes(path,4*1024*1024)
            if hashlib.sha256(raw).hexdigest()!=state['artifacts'].get('target.json'):continue
            data=json.loads(raw)
            if not isinstance(data,dict):continue
            metadata=data.get('translation_metadata');rows=data.get('regions')
            if not isinstance(metadata,dict) or metadata.get('target_language')!=language or not isinstance(rows,list) or not rows:continue
            valid=True
            for row in rows:
                if not isinstance(row,dict) or any(not isinstance(row.get(k),str) for k in ('source','target')):
                    valid=False;break
                authored=row.get('authored')
                target=authored.get('target') if isinstance(authored,dict) else None
                if not isinstance(target,dict) or target.get('origin')!='human':
                    valid=False;break
            if not valid:continue
            item={'page':page['relative_path'],'regions':[{'source':r['source'],'target':r['target']} for r in rows]}
            size=len(json.dumps(item,ensure_ascii=False).encode())
            if used+size>budget:break
            chosen.append(item);used+=size
        except (OSError,ValueError,KeyError,TypeError,RecursionError):continue
    return list(reversed(chosen))


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
