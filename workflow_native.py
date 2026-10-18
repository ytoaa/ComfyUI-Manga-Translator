"""One folder page per normal canvas prompt; never dispatches GPU work or starts a worker."""
from copy import deepcopy
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid

from .tools.run_project import (Project, ProjectError, Paused, InputError, ACTIVE, FINISHED,
    atomic_write, json_bytes, read_json, project_lock, normalise_image, digest, workflow_bindings)

VERSION = '0.6.0'


def _write_run(folder, run):
    run['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    atomic_write(folder/'canvas_run.json', json_bytes(run))


def _read_run(folder):
    path = folder/'canvas_run.json'
    if not path.exists(): return None
    run = read_json(path)
    if (not isinstance(run,dict) or run.get('schema') != 1
            or not re.fullmatch(r'[a-f0-9]{32}',str(run.get('run_id','')))
            or not isinstance(run.get('visited'),list) or not isinstance(run.get('page_ids'),list)):
        raise ProjectError('Invalid canvas project run; preserve its records')
    return run


def prefix_bindings(graph):
    bind = workflow_bindings(graph)
    for key,slot in (('final',3),('source',4),('target',5)):
        if graph[bind[key]]['inputs'].get('filename_prefix') != [bind['load'],slot]:
            raise ProjectError('폴더의 캔버스 실행에는 새 통합 08의 저장 경로 연결이 필요합니다. 새 JSON을 가져오세요.')
    return bind


class CanvasExecution:
    def _project(self, inputs, folder, graph, client, cached=False):
        project = Project(inputs,folder,graph,client)
        inventory = read_json(folder/'project.json')['pages'] if cached else None
        project._prepare_project(inventory=inventory)
        return project

    def _eligible(self, project, page, retry):
        state = project.state(page)
        if not state or state.get('input_sha256') != page['input_sha256']: return True
        if state['status'] in FINISHED:
            for name,sha in state.get('artifacts',{}).items():
                path = project._attempt_dir(state)/name
                if not path.exists() or digest(path.read_bytes()) != sha:
                    state.update(status='needs_review',reason='project_artifact_missing_or_modified')
                    project._save(state)
                    break
            return False
        if state['status'] == 'failed':
            if retry: return True
            if state.get('reason') == 'execution_failed' and not state.get('failure_message'):
                raise Paused('이전 실패의 상세가 없습니다. 실패 재시도로 실제 페이지 오류를 확인하세요.')
            return False
        return True

    def _reconcile(self, project, state, retry, current_prompt_id):
        history = project.client.history(state['prompt_id'])
        if history:
            status = history.get('status') or {}
            if status.get('status_str') not in ('success','error'):
                raise Paused('이전 페이지의 완료 여부를 확인 중입니다. 큐에서 같은 작업을 다시 제출하지 않습니다.')
            try: project._collect(state,history)
            except Paused:
                if not (retry and state.get('status') == 'failed'): raise
            return
        if project._queue_identity(state):
            raise Paused('이전 페이지 작업이 현재 큐에 있습니다. 기존 작업이 끝난 뒤 재개하세요.')
        evidence = project.client.restart_evidence(state) if retry and hasattr(project.client,'restart_evidence') else None
        if not evidence and retry and hasattr(project.client,'orphan_evidence'):
            evidence=project.client.orphan_evidence(state,current_prompt_id)
        if evidence:
            # A normal canvas node must never wait for another queued prompt:
            # the native executor is occupied by this very prompt.
            for _ in range(2):
                history = project.client.history(state['prompt_id'])
                if history:
                    project._collect(state,history); return
                if project._queue_identity(state):
                    raise Paused('기존 작업이 큐에 나타났습니다. 중복 실행하지 않고 중단합니다.')
            state.update(status='failed',reason='server_restarted_outcome_lost' if evidence['kind']=='native_process_restart' else 'native_queue_outcome_lost',
                restart_recovery=evidence,
                failure_message='현재 네이티브 실행에서 이전 작업의 큐·이력 부재를 재확인했습니다. 이전 결과는 미확정으로 보존하고 명시적 재시도를 허용합니다.')
            project._save(state)
            return
        error=Paused('이전 페이지가 큐·이력에 없습니다. 같은 입력 노드에서 실패 재시도를 선택하세요.' if not retry else
                     '이전 페이지의 결과가 없고 현재 네이티브 실행 소유권도 확인하지 못했습니다. recovery_check를 확인하세요.')
        error.recovery_check={'code':'explicit_retry_required' if not retry else 'native_ownership_or_restart_unverified',
            'retry_requested':retry,'previous_prompt_id':state['prompt_id'],'current_prompt_id':current_prompt_id,
            'relative_path':state['relative_path'],'previous_created_at':state.get('created_at'),
            'previous_updated_at':state.get('updated_at'),'current_process':getattr(project.client,'execution_context',None)}
        raise error

    def report(self, project, run, message=None):
        report = project._summary(run.get('message') if run['status']=='paused' else None)
        return {**report,'execution_mode':'canvas_native','runtime_version':VERSION,
            'run_id':run['run_id'],'status':run['status'],'phase':run['phase'],
            'message':message or run.get('message',''),'requested_action':run['requested_action'],
            'running':run['phase']=='processing','current_page':run.get('current_page'),
            'pages_visited':len(run['visited']),'pages_selected':len(run['page_ids']),
            'project_folder':str(project.destination),
            **({'recovery_check':run['recovery_check']} if 'recovery_check' in run else {}), **({'export':run['export']} if 'export' in run else {})}

    def _finish(self, project, run):
        report = project._summary()
        if any(report['counts'].get(status,0) for status in ACTIVE | {'preparing'}):
            raise Paused('완료되지 않은 페이지 기록이 있습니다. 실제 큐·이력을 확인한 뒤 재개하세요.')
        partial = any(n and key not in ('completed','unchanged_blank') for key,n in report['counts'].items())
        run.update(status='needs_review' if partial else 'completed',phase='finished',active_prompt=None,
                   message='폴더 처리 완료. 페이지별 결과와 오류를 검수하세요.')
        report['export'] = project._export(report) if any(report['counts'].get(k) for k in ('completed','unchanged_blank')) else None
        run['export']=report['export']
        _write_run(project.destination,run)
        result={**self.report(project,run),'export':report['export']}
        atomic_write(project.destination/'summary.json',json_bytes(result))
        return result

    def begin(self, inputs, folder, graph, client, prompt_id, source_id, action, continuation=None):
        prefix_bindings(graph)
        with project_lock(folder):
            run = _read_run(folder)
            if continuation is not None:
                if (not run or continuation.get('run_id') != run['run_id']
                        or continuation.get('source_node') != str(source_id)):
                    raise Paused('연속 실행 정보가 현재 프로젝트와 다릅니다. 자동 제출을 멈췄습니다.')
                if run['status'] not in ('running','awaiting_canvas') or run.get('stop_requested'):
                    return {'report':self.snapshot(folder),'ticket':None}
            project = self._project(inputs,folder,graph,client,cached=continuation is not None)
            retry = run['requested_action']=='실패 재시도' if continuation is not None else action=='실패 재시도'
            if run and run.get('active_prompt') == prompt_id:
                state = project.state(next(p for p in project.pages if p['id']==run['active_page']))
                return self._page_result(project,run,state,source_id)
            try:
                if continuation is None:
                    # Record this actual invocation before reconciliation can
                    # pause. An older run's action must never label this Run.
                    run = {'schema':1,'run_id':uuid.uuid4().hex,'project_id':project.project_id,
                           'source_node':str(source_id),'source_folder':str(inputs.resolve()),
                           'requested_action':action,'invocation_prompt_id':prompt_id,
                           'status':'running','phase':'selecting','visited':[],'page_ids':[],
                           'active_prompt':None,'stop_requested':False}
                    _write_run(folder,run)
                for page in project.recovery_pages:
                    state = project.state(page)
                    if state and state['status'] in ACTIVE:
                        self._reconcile(project,state,retry,prompt_id)
                        if run and run.get('active_prompt') == state['prompt_id'] and state['status'] not in ACTIVE:
                            run.update(active_prompt=None,last_resolved_prompt=state['prompt_id'])
                if continuation is None:
                    run['page_ids']=[p['id'] for p in project.pages if self._eligible(project,p,retry)]
                    # The live graph remains authoritative; processing changes are
                    # rejected by the same fingerprint, while prefix links may migrate.
                    atomic_write(folder/'workflow.api.json',json_bytes(graph))
                pending = [p for p in project.pages if p['id'] in run['page_ids'] and p['id'] not in run['visited']]
                if not pending: return {'report':self._finish(project,run),'ticket':None}
                page = pending[0]
                state = project._new(page)
                state.update(status='running',prompt_id=prompt_id,
                    submission_token={'project':project.project_id,'page':page['id'],'attempt':state['attempt']},
                    output_prefix=f'manga_translator/projects/{project.project_id}/{page["id"]}/a{state["attempt"]:06d}')
                context = getattr(client,'execution_context',None)
                if isinstance(context,dict): state['execution_context']=deepcopy(context)
                run.update(status='running',phase='processing',active_page=page['id'],active_prompt=prompt_id,
                           current_page=page['relative_path'],message=f'{page["relative_path"]} · 현재 워크플로우에서 실행 중')
                run['visited'].append(page['id'])
                project._save(state); _write_run(folder,run)
                try:
                    if page['scan_issue']: raise InputError(page['scan_issue'])
                    encoded,size,uniform = normalise_image(inputs/page['relative_path'],page['input_sha256'],project.max_pixels)
                    state.update(image_size=size,uniform_rgb=uniform)
                    project._artifact(state,'input.png',encoded)
                    uploaded = client.upload(encoded,page['id']+'_'+uuid.uuid4().hex+'.png','manga_translator/'+project.project_id)
                    state['uploaded_reference']={'filename':uploaded['name'],'subfolder':uploaded['subfolder'],'type':'input'}
                    project._save(state)
                except InputError as exc:
                    state.update(status='failed',reason='invalid_input',failure_message=str(exc)); project._save(state)
                    result = self._page_result(project,run,state,source_id)
                    result['image_reference']=None
                    return result
                return self._page_result(project,run,state,source_id)
            except (ProjectError,OSError) as exc:
                if not run:
                    run={'schema':1,'run_id':uuid.uuid4().hex,'project_id':project.project_id,'source_node':str(source_id),
                         'source_folder':str(inputs.resolve()),'requested_action':action,'visited':[],'page_ids':[]}
                run.update(status='paused',phase='paused',message=str(exc),stop_requested=True)
                if hasattr(exc,'recovery_check'): run['recovery_check']=exc.recovery_check
                _write_run(folder,run)
                return {'report':self.report(project,run),'ticket':None}

    def _page_result(self, project, run, state, source_id):
        prefix=state['output_prefix']
        return {'report':self.report(project,run),'image_reference':state.get('uploaded_reference'),
            'prefixes':(prefix+'/result',prefix+'/ocr',prefix+'/translation'),
            'ticket':{'project_name':project.destination.name,'run_id':run['run_id'],
                      'source_node':str(source_id),'prompt_id':state['prompt_id'],
                      'relative_path':state['relative_path'],'index':len(run['visited']),
                      'total':len(run['page_ids'])}}

    def snapshot(self, folder):
        run=_read_run(folder)
        report=read_json(folder/'summary.json') if (folder/'summary.json').exists() else {'counts':{},'pages':[]}
        if not run: return {**report,'status':'ready','phase':'ready','running':False,'runtime_version':VERSION}
        return {**report,'execution_mode':'canvas_native','runtime_version':VERSION,
                'run_id':run['run_id'],'status':run['status'],'phase':run['phase'],
                'halted':run.get('message') if run['status']=='paused' else None,
                'message':run.get('message',''),'running':run['phase']=='processing',
                'current_page':run.get('current_page'),'requested_action':run['requested_action'],
                **({'recovery_check':run['recovery_check']} if 'recovery_check' in run else {})}

    def refresh(self, folder, client):
        run=_read_run(folder)
        if not run or not run.get('active_prompt'): return self.snapshot(folder)
        ident=run['active_prompt']
        history=client.history(ident)
        if history and (history.get('status') or {}).get('status_str') in ('success','error'):
            return self.resolve(folder,run['run_id'],ident,client)['report']
        queue=client.queue()
        if any(row[1]==ident for key in ('queue_running','queue_pending') for row in queue.get(key,[])):
            return self.snapshot(folder)
        # Completion can land between the two core reads.
        history=client.history(ident)
        if history and (history.get('status') or {}).get('status_str') in ('success','error'):
            return self.resolve(folder,run['run_id'],ident,client)['report']
        with project_lock(folder):
            current=_read_run(folder)
            if current and current.get('active_prompt')==ident:
                current.update(status='paused',phase='paused',stop_requested=True,
                    message='저장된 페이지가 현재 큐·이력에 없습니다. 서버 재시작 후 실패 재시도로 복구하세요.')
                _write_run(folder,current)
            return self.snapshot(folder)

    def pause(self, folder, run_id=None):
        with project_lock(folder):
            run=_read_run(folder)
            if run and (run_id is None or run['run_id']==run_id):
                run.update(stop_requested=True,status='stopping' if run.get('active_prompt') else 'paused',
                    phase='processing' if run.get('active_prompt') else 'paused',
                    message='연속 실행 중지 요청. 현재 페이지 이후 추가 제출하지 않습니다.')
                _write_run(folder,run)
            return self.snapshot(folder)

    def resolve(self, folder, run_id, prompt_id, client):
        with project_lock(folder):
            run=_read_run(folder)
            if not run or run['run_id'] != run_id: raise Paused('이전 연속 실행의 응답입니다. 다음 페이지를 제출하지 않습니다.')
            graph=read_json(folder/'workflow.api.json')
            project=self._project(Path(run['source_folder']),folder,graph,client,cached=True)
            if run.get('last_resolved_prompt') == prompt_id:
                return {'pending':False,'continue':False,'report':self.report(project,run)}
            if run.get('active_prompt') != prompt_id: raise Paused('현재 페이지의 작업 ID와 다릅니다.')
            history=client.history(prompt_id)
            if not history: return {'pending':True,'continue':False,'report':self.report(project,run)}
            status=history.get('status') or {}
            if status.get('status_str') not in ('success','error'): return {'pending':True,'continue':False,'report':self.report(project,run)}
            state=project.state(next(p for p in project.pages if p['id']==run['active_page']))
            if state.get('prompt_id') != prompt_id:
                raise Paused('완료 이력과 페이지 시도의 작업 ID가 다릅니다. 기록을 보존하고 중단합니다.')
            try:
                if state['status'] in ACTIVE: project._collect(state,history)
                if state['status']=='failed' and state.get('reason') in ('TypeError','SyntaxError','IndentationError','NameError','AttributeError','KeyError','AssertionError'):
                    raise Paused('페이지 처리 중 구현/구성 오류가 발생했습니다. 실패 노드와 서버 로그를 확인한 뒤 재시도하세요.')
                run.update(active_prompt=None,last_resolved_prompt=prompt_id)
                if run.get('stop_requested'):
                    run.update(status='paused',phase='paused',message='연속 실행 중지. 현재 페이지 결과를 저장했습니다.')
                elif len(run['visited']) >= len(run['page_ids']):
                    return {'pending':False,'continue':False,'report':self._finish(project,run)}
                else:
                    run.update(status='awaiting_canvas',phase='awaiting_canvas',message='현재 페이지 완료. 캔버스에서 다음 페이지를 실행합니다.')
            except (ProjectError,OSError) as exc:
                run.update(status='paused',phase='paused',message=str(exc),last_resolved_prompt=prompt_id)
            _write_run(folder,run)
            return {'pending':False,'continue':run['status']=='awaiting_canvas','report':self.report(project,run)}


CANVAS = CanvasExecution()


def register_routes():
    try:
        from server import PromptServer
        from aiohttp import web
    except ImportError: return
    server=getattr(PromptServer,'instance',None)
    if server is None or not hasattr(server,'routes') or getattr(server,'_manga_canvas_routes',False): return
    from .workflow_project import NativeComfyClient, WorkflowProjects
    def target(body):
        if not isinstance(body,dict): raise ProjectError('Invalid canvas request')
        import folder_paths
        folder=WorkflowProjects.destination(folder_paths.get_output_directory(),body.get('project_name'))
        run=_read_run(folder)
        if not run or body.get('run_id') != run['run_id']: raise Paused('프로젝트 실행 정보가 다릅니다.')
        client=NativeComfyClient(server,folder_paths.get_input_directory(),folder_paths.get_output_directory(),run['source_node'])
        if not Path(run['source_folder']).resolve().is_relative_to(client.input_root):
            raise ProjectError('Saved project input leaves the ComfyUI input directory')
        return folder,client
    @server.routes.post('/manga_translator/workflow/resolve')
    async def resolve(request):
        try:
            body=await request.json(); folder,client=target(body)
            result=await asyncio.to_thread(CANVAS.resolve,folder,body['run_id'],body['prompt_id'],client)
            return web.json_response(result)
        except (ProjectError,OSError,KeyError,ValueError) as exc:
            return web.json_response({'error':str(exc)},status=400)
    @server.routes.post('/manga_translator/workflow/pause')
    async def pause(request):
        try:
            body=await request.json(); folder,_=target(body)
            return web.json_response(CANVAS.pause(folder,body['run_id']))
        except (ProjectError,OSError,KeyError,ValueError) as exc:
            return web.json_response({'error':str(exc)},status=400)
    server._manga_canvas_routes=True
