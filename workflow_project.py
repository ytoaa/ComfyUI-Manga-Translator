"""Workflow-owned page input and serial projects on ComfyUI's native queue."""
import asyncio
from copy import deepcopy
import json
import logging
import re
from pathlib import Path, PurePosixPath
import threading
import types

from .tools.run_project import (Project, ProjectError, Paused, Rejected, ProtocolError,
                               MAX_INPUT_BYTES, atomic_write, json_bytes, read_json,
                               workflow_bindings)


class NativeComfyClient:
    """Use the installed core's actual /prompt handler without HTTP or a second executor."""
    base = 'comfyui://native-queue'

    def __init__(self, server, input_root, output_root, source_id, extra_pnginfo=None, client_id=None):
        self.server = server
        self.input_root, self.output_root = Path(input_root).resolve(), Path(output_root).resolve()
        self.source_id, self.extra_pnginfo, self.client_id = str(source_id), deepcopy(extra_pnginfo or {}), client_id
        self.submit_handler = next((r.handler for r in server.routes if r.method == 'POST' and r.path == '/prompt'),None)
        if self.submit_handler is None: raise ProjectError('ComfyUI 기본 prompt 경로를 찾을 수 없습니다.')

    def object_info(self):
        import nodes
        return {name:{} for name in nodes.NODE_CLASS_MAPPINGS}

    def history(self, ident):
        return self.server.prompt_queue.get_history(ident).get(ident)

    def queue(self):
        running,pending = self.server.prompt_queue.get_current_queue()
        return {'queue_running':[list(row) for row in running], 'queue_pending':[list(row) for row in pending]}

    def upload(self, data, name, subfolder):
        path = self._path({'type':'input','filename':name,'subfolder':subfolder})
        if len(data)>MAX_INPUT_BYTES: raise ProtocolError('정규화 이미지가 파일 예산을 초과했습니다.')
        if path.exists(): raise ProtocolError('기존 입력 파일을 덮어쓸 수 없습니다.')
        atomic_write(path,data)
        return {'name':name,'subfolder':subfolder,'type':'input'}

    def _path(self, descriptor):
        kind = descriptor.get('type')
        if kind not in ('input','output'): raise ProtocolError('잘못된 ComfyUI 파일 종류입니다.')
        name,sub = descriptor.get('filename'),descriptor.get('subfolder','')
        if (not isinstance(name,str) or not name or PurePosixPath(name).name != name or '\\' in name
                or not isinstance(sub,str) or '\\' in sub or PurePosixPath(sub).is_absolute()
                or '..' in PurePosixPath(sub).parts):
            raise ProtocolError('잘못된 ComfyUI 파일 경로입니다.')
        root = self.input_root if kind == 'input' else self.output_root
        path = (root/sub/name).resolve()
        if not path.is_relative_to(root): raise ProtocolError('파일 경로가 ComfyUI 폴더를 벗어났습니다.')
        return path

    def download(self, descriptor):
        path = self._path(descriptor)
        with path.open('rb') as handle: data = handle.read(128*1024*1024+1)
        if len(data)>128*1024*1024: raise ProtocolError('결과 파일이 전송 예산을 초과했습니다.')
        return data

    def submit(self, graph, ident, token):
        # The flag is execution metadata, never a user-editable mode on the canvas.
        metadata = deepcopy(self.extra_pnginfo)
        metadata['manga_project_page'] = {'source_node':self.source_id, **token}
        payload = {'prompt':deepcopy(graph),'prompt_id':ident,
                   'extra_data':{'manga_project':deepcopy(token),'extra_pnginfo':metadata}}
        if self.client_id: payload['client_id'] = self.client_id
        async def submit():
            async def data(): return payload
            response = await self.submit_handler(types.SimpleNamespace(json=data,headers={}))
            try: result = json.loads(response.body)
            except (ValueError,TypeError) as exc: raise ProtocolError('ComfyUI prompt 응답이 올바르지 않습니다.') from exc
            if response.status >= 400:
                raise Rejected('ComfyUI 워크플로우 검사 실패: '+json.dumps(result,ensure_ascii=False)[:3000])
            return result
        # Only the project worker calls this; never wait on the core event-loop thread.
        return asyncio.run_coroutine_threadsafe(submit(),self.server.loop).result(timeout=60)


class WorkflowProjects:
    def __init__(self):
        self.lock = threading.RLock()
        self.active = None
        self.worker = None
        self.stop_event = threading.Event()

    @staticmethod
    def destination(output_root, name):
        if (not isinstance(name,str) or not name.strip() or name != name.strip() or len(name)>80
                or name in ('.','..') or '/' in name or '\\' in name or name.startswith('.')):
            raise ProjectError('프로젝트 이름은 경로 구분자 없이 1~80자로 입력하세요.')
        root = Path(output_root).resolve()/'manga_translator'/'workflow_projects'
        folder = root/name
        if not folder.resolve().is_relative_to(root.resolve()) or folder.is_symlink():
            raise ProjectError('프로젝트 출력 경로가 올바르지 않습니다.')
        return folder

    @staticmethod
    def inputs(input_root, relative):
        if (not isinstance(relative,str) or not relative or '\\' in relative
                or PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts):
            raise ProjectError('ComfyUI input 안의 원본 하위 폴더를 입력하세요.')
        root = Path(input_root).resolve()
        folder = (root/relative).resolve()
        if (folder == root or not folder.is_relative_to(root) or not folder.is_dir()
                or folder.relative_to(root).parts[0] == 'manga_translator'):
            raise ProjectError('원본을 모은 input 하위 폴더가 필요합니다. input 전체와 내부 작업 폴더는 사용할 수 없습니다.')
        return folder

    def snapshot(self, folder):
        with self.lock:
            report = read_json(folder/'summary.json') if (folder/'summary.json').exists() else {'counts':{},'pages':[]}
            control = read_json(folder/'workflow_control.json') if (folder/'workflow_control.json').exists() else {'status':'ready'}
            running = self.active == folder and bool(self.worker and self.worker.is_alive())
            if not running and control['status'] in ('running','stopping'):
                control = {'status':'paused','message':'서버가 재시작되었습니다. 재개 시 기존 작업부터 확인합니다.'}
            return {**report,**control,'running':running,'project_folder':str(folder),
                    'controls':'같은 입력 노드에서 action을 상태 확인 / 일시정지 / 시작·재개 / 실패 재시도로 선택한 뒤 실행하세요.'}

    @staticmethod
    def _control(folder, status, message):
        atomic_write(folder/'workflow_control.json',json_bytes({'status':status,'message':message}))

    def start(self, folder, inputs, graph, client, retry_failed=False, publish=None):
        with self.lock:
            if self.worker and self.worker.is_alive():
                if self.active == folder: return self.snapshot(folder)
                raise ProjectError('다른 폴더 프로젝트가 진행 중입니다. 해당 프로젝트를 일시정지하거나 완료 후 실행하세요.')
            # The saved canvas is authoritative on resume, including model/lettering settings.
            saved = folder/'workflow.api.json'
            configured = read_json(saved) if saved.exists() else graph
            bindings = workflow_bindings(configured)
            if configured[bindings['load']]['class_type'] != 'MangaWorkflowInput':
                raise ProjectError('프로젝트에는 워크플로우 입력 노드가 필요합니다.')
            client.source_id = bindings['load']
            metadata = folder/'workflow.metadata.json'
            if hasattr(client,'extra_pnginfo'):
                if metadata.exists() and saved.exists(): client.extra_pnginfo = read_json(metadata)
                else: atomic_write(metadata,json_bytes(client.extra_pnginfo))
            self.stop_event = threading.Event()
            project = Project(inputs,folder,configured,client,retry_failed=retry_failed,should_stop=self.stop_event.is_set)
            self._control(folder,'running','ComfyUI 큐에서 페이지를 순차 처리합니다.')
            self.active = folder
            self.worker = threading.Thread(target=self._run,args=(folder,project,publish),daemon=True,name='manga-workflow-project')
            self.worker.start()
            logging.info('Manga folder project worker started: %s', folder.name)
        return self.snapshot(folder)

    def _run(self, folder, project, publish):
        def progress(value):
            project._summary()
            logging.info('Manga project page state: %s', value)
            if publish:
                try: publish(self.snapshot(folder))
                except Exception: logging.warning('Manga project preview update failed',exc_info=True)
        project.progress = progress
        status,message = 'paused','작업이 중단되었습니다. 재개 시 기존 작업부터 확인합니다.'
        try:
            # ComfyUI accepts new /prompt requests while the current prompt is running.
            # Queueing the first page immediately is safer than waiting for the parent
            # control prompt to appear in history; execution remains serialized by the
            # native prompt queue and the page cannot run before the current job ends.
            report = project.run(export=True)
            partial = any(n and s not in ('completed','unchanged_blank') for s,n in report['counts'].items())
            status = 'needs_review' if partial else 'completed'
            message = '프로젝트 처리가 끝났습니다. 페이지별 결과를 검수하세요.'
            logging.info('Manga folder project finished: %s (%s)', folder.name, status)
        except (Paused,ProjectError,OSError) as exc:
            status,message = 'paused',str(exc)
            logging.warning('Manga folder project paused: %s', exc)
        except Exception as exc:
            logging.exception('Manga workflow project failed')
            status,message = 'paused',f'{type(exc).__name__}: {exc}'
        finally:
            with self.lock:
                try: self._control(folder,status,message)
                finally: self.active = None
            if publish:
                try: publish(self.snapshot(folder))
                except Exception: logging.warning('Manga final project preview update failed',exc_info=True)

    def stop(self, folder):
        with self.lock:
            if self.active != folder or not self.worker or not self.worker.is_alive():
                return self.snapshot(folder)
            self.stop_event.set()
            self._control(folder,'stopping','현재 페이지를 정리한 뒤 일시정지합니다.')
        return self.snapshot(folder)


PROJECTS = WorkflowProjects()


def _context(server, prompt, unique_id):
    """Resolve the parent prompt from ComfyUI's running queue without whole-graph equality.

    ComfyUI keeps a deep-copied queue item while execution may annotate its working
    prompt (for example with is_changed/cache information). Matching the complete
    dictionaries therefore becomes unstable. Prefer an exact prompt match, then
    identify the running job by this node's UNIQUE_ID, class type and stable user
    inputs. Never silently pick between multiple candidates.
    """
    running,_ = server.prompt_queue.get_current_queue()
    node_id = str(unique_id)
    current = prompt.get(node_id) if isinstance(prompt,dict) else None
    exact, candidates = [], []
    stable = ('input_mode','input_folder','project_name','action')
    for row in running:
        if not isinstance(row,(list,tuple)) or len(row) < 4 or not isinstance(row[2],dict):
            continue
        queued = row[2]
        if queued == prompt:
            exact.append(row)
            continue
        queued_node = queued.get(node_id)
        if (not isinstance(current,dict) or not isinstance(queued_node,dict)
                or current.get('class_type') != 'MangaWorkflowInput'
                or queued_node.get('class_type') != 'MangaWorkflowInput'):
            continue
        current_inputs, queued_inputs = current.get('inputs',{}), queued_node.get('inputs',{})
        if all(current_inputs.get(key) == queued_inputs.get(key) for key in stable):
            candidates.append(row)
    matches = exact or candidates
    if len(matches) == 1:
        row = matches[0]
        extra = row[3] if isinstance(row[3],dict) else {}
        return row[1],extra.get('client_id')
    if not matches and len(running) == 1:
        # Last-resort compatibility for a core that mutates this node's inputs too:
        # only accept the sole running prompt when it still contains this exact node id/type.
        row = running[0]
        if (isinstance(row,(list,tuple)) and len(row) >= 4 and isinstance(row[2],dict)
                and isinstance(row[2].get(node_id),dict)
                and row[2][node_id].get('class_type') == 'MangaWorkflowInput'):
            extra = row[3] if isinstance(row[3],dict) else {}
            return row[1],extra.get('client_id')
    if len(matches) > 1:
        raise ProjectError('현재 ComfyUI 실행 문맥이 둘 이상이라 프로젝트 시작 작업을 식별할 수 없습니다.')
    raise ProjectError('현재 ComfyUI 실행 문맥을 찾을 수 없습니다.')


def _queued_prompt(server, ident):
    """Return the untouched queued graph for persistence and child-page submission.

    The hidden PROMPT passed to a node is an execution working copy and can contain
    non-JSON runtime values such as NaN from IS_CHANGED. The queue copy is the
    canonical API graph accepted by ComfyUI and is therefore the only graph a folder
    project should save and replay.
    """
    running,_ = server.prompt_queue.get_current_queue()
    matches = [row for row in running
               if isinstance(row,(list,tuple)) and len(row) >= 3
               and row[1] == ident and isinstance(row[2],dict)]
    if len(matches) != 1:
        raise ProjectError('프로젝트에 저장할 원본 ComfyUI 워크플로우를 찾을 수 없습니다.')
    return deepcopy(matches[0][2])


def _encode(report): return json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)


class MangaWorkflowInput:
    CATEGORY = 'Manga Translator/Project'
    RETURN_TYPES = ('IMAGE','MASK','STRING')
    RETURN_NAMES = ('image','mask','project_report')
    FUNCTION = 'load'

    @classmethod
    def INPUT_TYPES(cls):
        try:
            import folder_paths
            root = Path(folder_paths.get_input_directory())
            files = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff','.gif'))
        except (ImportError,AttributeError,OSError): files = []
        return {'required':{
            'input_mode':(['이미지 한 장','폴더 프로젝트'],{'default':'이미지 한 장'}),
            'image':(['']+files,{'image_upload':True,'tooltip':'이미지 한 장 모드에서 사용합니다. 폴더 모드에서는 무시합니다.'}),
            'input_folder':('STRING',{'default':'manga_book','tooltip':'ComfyUI/input 기준 하위 폴더. 예: manga_book/volume1'}),
            'project_name':('STRING',{'default':'book_01','tooltip':'결과와 재개 기록을 구분하는 이름. 설정을 바꾼 새 실행은 새 이름을 사용하세요.'}),
            'action':(['시작·재개','실패 재시도','상태 확인','일시정지'],{'default':'시작·재개','tooltip':'폴더 프로젝트의 실행 동작입니다. 현재 페이지를 마친 뒤 일시정지합니다.'})},
            'hidden':{'prompt':'PROMPT','unique_id':'UNIQUE_ID','extra_pnginfo':'EXTRA_PNGINFO'}}

    @classmethod
    def VALIDATE_INPUTS(cls, input_mode, image, input_folder, project_name, action):
        import folder_paths
        if input_mode == '폴더 프로젝트':
            try:
                PROJECTS.destination(folder_paths.get_output_directory(),project_name)
                if action in ('시작·재개','실패 재시도'):
                    PROJECTS.inputs(folder_paths.get_input_directory(),input_folder)
            except ProjectError as exc: return str(exc)
            return True
        return True if image and folder_paths.exists_annotated_filepath(image) else '원본 이미지를 선택하세요.'

    @classmethod
    def IS_CHANGED(cls, input_mode, image, **kwargs):
        if input_mode == '폴더 프로젝트': return float('nan')
        import nodes
        return nodes.LoadImage.IS_CHANGED(image)

    def load(self, input_mode, image, input_folder, project_name, action,
             prompt=None, unique_id=None, extra_pnginfo=None):
        marker = (extra_pnginfo or {}).get('manga_project_page')
        if marker is not None:
            # Page jobs never launch another project, even if the saved action is start.
            if (not isinstance(marker,dict) or marker.get('source_node') != str(unique_id)
                    or not re.fullmatch(r'[a-f0-9]{32}',str(marker.get('project','')))
                    or not re.fullmatch(r'p[a-f0-9]{20}',str(marker.get('page','')))
                    or type(marker.get('attempt')) is not int or marker['attempt'] < 1):
                raise ProjectError('프로젝트 페이지 실행 정보가 올바르지 않습니다.')
            import nodes
            pixels,mask = nodes.LoadImage().load_image(image)
            return pixels,mask,_encode({'page':marker,'status':'page_running'})
        if input_mode == '이미지 한 장':
            import nodes
            pixels,mask = nodes.LoadImage().load_image(image)
            return pixels,mask,_encode({'status':'single_image'})
        from comfy_execution.graph import ExecutionBlocker
        import folder_paths
        from server import PromptServer
        server = PromptServer.instance
        folder = PROJECTS.destination(folder_paths.get_output_directory(),project_name)
        if action == '일시정지': report = PROJECTS.stop(folder)
        elif action == '상태 확인': report = PROJECTS.snapshot(folder)
        else:
            inputs = PROJECTS.inputs(folder_paths.get_input_directory(),input_folder)
            ident,client_id = _context(server,prompt,unique_id)
            graph = _queued_prompt(server,ident)
            client = NativeComfyClient(server,folder_paths.get_input_directory(),folder_paths.get_output_directory(),unique_id,extra_pnginfo,client_id)
            previews = [key for key,node in graph.items() if node['class_type']=='PreviewAny' and node['inputs'].get('source') == [str(unique_id),2]]
            def publish(value):
                if client_id is None: return
                for node in previews:
                    server.send_sync('executed',{'node':node,'display_node':node,'prompt_id':ident,
                                     'output':{'text':[_encode(value)]}},client_id)
            report = PROJECTS.start(folder,inputs,graph,client,action == '실패 재시도',publish)
        return ExecutionBlocker(None),ExecutionBlocker(None),_encode(report)


NODE_CLASS_MAPPINGS = {'MangaWorkflowInput':MangaWorkflowInput}
NODE_DISPLAY_NAME_MAPPINGS = {'MangaWorkflowInput':'워크플로우 입력 · 이미지 / 폴더 프로젝트'}