"""ComfyUI project panel routes; graph execution stays on ComfyUI's own queue."""
from collections import Counter
from pathlib import Path, PurePosixPath
import re
import threading
from urllib.parse import urlsplit
import uuid

from .tools.run_project import (Project, ProjectError, Paused, ComfyClient, EXTENSIONS,
                                MAX_INPUT_BYTES, atomic_write, json_bytes, read_json,
                                workflow_bindings, natural_key)


class ProjectPanel:
    def __init__(self, inputs, outputs, client_factory):
        self.inputs = Path(inputs).resolve()
        self.root = Path(outputs).resolve()/'manga_translator'/'folder_projects'
        self.client_factory = client_factory
        self.guard = threading.Lock()
        self.worker = None
        self.active = None
        self.stop_event = threading.Event()

    def folder(self, relative):
        if not isinstance(relative, str) or '\\' in relative:
            raise ProjectError('입력 폴더 경로가 올바르지 않습니다.')
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ProjectError('ComfyUI input 안의 폴더를 선택하세요.')
        resolved = (self.inputs/path).resolve()
        if not resolved.is_relative_to(self.inputs) or not resolved.is_dir():
            raise ProjectError('ComfyUI input 안에서 존재하는 폴더를 선택하세요.')
        return resolved

    def browse(self, relative=''):
        folder = self.folder(relative)
        children = sorted((p for p in folder.iterdir() if p.is_dir() and not p.is_symlink()
                           and not (folder == self.inputs and p.name == 'manga_translator')),
                          key=lambda p: natural_key(p.name))
        return {'path':'' if folder == self.inputs else folder.relative_to(self.inputs).as_posix(),
                'folders':[{'name':p.name, 'path':p.relative_to(self.inputs).as_posix()} for p in children],
                'images':sum(p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTENSIONS for p in folder.iterdir())}

    def directory(self, ident):
        if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident):
            raise ProjectError('프로젝트 ID가 올바르지 않습니다.')
        result = self.root/ident
        if not (result/'panel.json').is_file():
            raise ProjectError('프로젝트를 찾을 수 없습니다.')
        return result

    def create(self, relative, name, graph):
        workflow_bindings(graph)
        inputs = self.folder(relative)
        if inputs == self.inputs or inputs.relative_to(self.inputs).parts[0] == 'manga_translator':
            raise ProjectError('프로젝트 원본을 모은 input 하위 폴더를 선택하세요. input 전체와 내부 작업 폴더는 실행할 수 없습니다.')
        if not isinstance(name,str) or not name.strip() or len(name)>80:
            raise ProjectError('프로젝트 이름은 1~80자로 입력하세요.')
        ident = uuid.uuid4().hex
        folder = self.root/ident
        atomic_write(folder/'workflow.api.json',json_bytes(graph))
        atomic_write(folder/'panel.json',json_bytes({'id':ident,'name':name.strip(),
                     'input':relative,'status':'ready','message':''}))
        return ident

    def _metadata(self, ident, **changes):
        path = self.directory(ident)/'panel.json'
        value = read_json(path); value.update(changes)
        atomic_write(path,json_bytes(value))

    def start(self, ident, retry_failed=False):
        with self.guard:
            folder = self.directory(ident)
            if self.worker and self.worker.is_alive():
                raise ProjectError('진행 중인 폴더 프로젝트가 있습니다. 완료 또는 일시정지 후 실행하세요.')
            meta = read_json(folder/'panel.json')
            inputs = self.folder(meta['input'])
            graph = read_json(folder/'workflow.api.json')
            self.stop_event = threading.Event()
            project = Project(inputs,folder,graph,self.client_factory(),retry_failed=retry_failed,
                              should_stop=self.stop_event.is_set)
            self._metadata(ident,status='running',message='페이지 목록을 확인하고 있습니다.')
            self.active = ident
            self.worker = threading.Thread(target=self._run,args=(ident,project),daemon=True,
                                           name='manga-folder-project')
            self.worker.start()
        return self.snapshot(ident)

    def _run(self, ident, project):
        status, message = 'paused', '작업이 중단되었습니다. 재개 시 기존 작업을 확인합니다.'
        try:
            report = project.run(export=True)
            partial = any(n and s not in ('completed','unchanged_blank') for s,n in report['counts'].items())
            status, message = ('review' if partial else 'completed'), '처리가 끝났습니다. 페이지별 결과를 확인하세요.'
        except Paused as exc:
            status, message = 'paused', str(exc)
        except Exception as exc:
            # Keep all durable page/prompt identities even for unexpected failures.
            import logging
            logging.exception('Manga folder project paused: %s',ident)
            status, message = 'paused', f'{type(exc).__name__}: {exc}'
        finally:
            # Finish and stop must not overwrite each other's terminal state.
            with self.guard:
                try:
                    self._metadata(ident,status=status,message=message)
                finally:
                    self.active = None

    def stop(self, ident):
        self.directory(ident)
        with self.guard:
            if ident != self.active or not self.worker or not self.worker.is_alive():
                raise ProjectError('현재 실행 중인 프로젝트가 아닙니다.')
            self.stop_event.set()
            self._metadata(ident,status='stopping',message='현재 페이지를 정리한 뒤 일시정지합니다.')
        return self.snapshot(ident)

    def snapshot(self, ident):
        folder = self.directory(ident)
        meta = read_json(folder/'panel.json')
        running = ident == self.active and bool(self.worker and self.worker.is_alive())
        if not running and meta['status'] in ('running','stopping'):
            meta.update(status='paused',message='서버가 재시작되었습니다. 재개하면 기존 작업부터 확인합니다.')
        rows = []
        manifest = read_json(folder/'project.json') if (folder/'project.json').exists() else {'pages':[]}
        for page in manifest['pages']:
            # Identities are generated by the runner, never a client-supplied path.
            if not re.fullmatch(r'p[a-f0-9]{20}',str(page.get('id',''))):
                raise ProjectError('페이지 기록이 손상되었습니다. 기존 파일을 보존하세요.')
            row = {'id':page['id'],'relative_path':page['relative_path'],'status':'pending'}
            states = sorted((folder/'pages'/page['id']).glob('attempt-*/state.json'))
            if states:
                state = read_json(states[-1])
                if state.get('input_sha256') == page['input_sha256']:
                    row.update({key:state[key] for key in ('status','reason','failure_node','failure_message','prompt_id') if key in state})
                    row['attempt'] = state['attempt']
                    row['artifacts'] = [n for n in ('result.png','source.json','target.json','input.png') if (states[-1].parent/n).is_file()]
            rows.append(row)
        summary = read_json(folder/'summary.json') if (folder/'summary.json').exists() else {}
        return {**meta,'running':running,'pages':rows,'counts':dict(Counter(r['status'] for r in rows)),
                'output_folder':str(folder),'export':summary.get('export'),
                'removed_inputs':manifest.get('removed_inputs',[])}

    def listing(self):
        if not self.root.exists(): return []
        result = []
        for path in sorted(self.root.glob('*/panel.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]:
            if re.fullmatch(r'[a-f0-9]{32}',path.parent.name):
                try:
                    meta = read_json(path)
                    result.append({key:meta[key] for key in ('id','name','status')})
                except (OSError,ValueError,KeyError,TypeError):
                    result.append({'id':path.parent.name,'name':'기록 확인 필요 · '+path.parent.name[:8],'status':'paused'})
        return result

    def artifact(self, ident, page, attempt, name):
        folder = self.directory(ident)
        if (not re.fullmatch(r'p[a-f0-9]{20}',page) or not re.fullmatch(r'[1-9][0-9]{0,5}',attempt)
                or name not in ('result.png','source.json','target.json','input.png')):
            raise ProjectError('결과 파일 경로가 올바르지 않습니다.')
        path = folder/'pages'/page/f'attempt-{int(attempt):06d}'/name
        if not path.resolve().is_relative_to(folder.resolve()) or not path.is_file():
            raise ProjectError('결과 파일이 없습니다.')
        return path


def register_routes():
    # Importing node schemas in offline tools must not require a running server.
    try:
        from server import PromptServer
        import folder_paths
    except ModuleNotFoundError as exc:
        if exc.name not in ('server','folder_paths'): raise
        return
    from aiohttp import web
    server = PromptServer.instance
    if server is None: return

    def client():
        address = getattr(server,'address','127.0.0.1')
        if address in ('0.0.0.0',''): address = '127.0.0.1'
        if address == '::': address = '::1'
        if ':' in address: address = '['+address+']'
        return ComfyClient(f'http://{address}:{server.port}')

    panel = ProjectPanel(folder_paths.get_input_directory(),folder_paths.get_output_directory(),client)
    prefix = '/manga/projects'

    def route(method, path):
        def decorate(handler):
            async def wrapped(request):
                origin = request.headers.get('Origin')
                if method != 'get' and origin and urlsplit(origin).netloc != request.host:
                    return web.json_response({'error':'다른 사이트에서는 프로젝트를 변경할 수 없습니다.'},status=403)
                try:
                    return await handler(request)
                except (ProjectError,ValueError,KeyError,TypeError,OSError) as exc:
                    return web.json_response({'error':str(exc)},status=400)
            getattr(server.routes,method)(prefix+path)(wrapped)
            return wrapped
        return decorate

    async def body(request):
        data = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            data.extend(chunk)
            if len(data)>4*1024*1024: raise ProjectError('프로젝트 설정이 너무 큽니다.')
        import json
        value = json.loads(data)
        if not isinstance(value,dict): raise ProjectError('설정은 JSON 객체여야 합니다.')
        return value

    @route('get','/folders')
    async def browse(request):
        return web.json_response(panel.browse(request.query.get('path','')))

    @route('get','')
    async def listing(request):
        return web.json_response({'projects':panel.listing()})

    @route('post','')
    async def create(request):
        data = await body(request)
        ident = panel.create(data['input'],data['name'],data['graph'])
        return web.json_response(panel.snapshot(ident))

    @route('post','/import')
    async def new_import(request):
        ident = uuid.uuid4().hex
        (panel.inputs/'manga_projects'/ident).mkdir(parents=True)
        return web.json_response({'input':'manga_projects/'+ident})

    @route('post','/import/{ident}')
    async def upload(request):
        ident = request.match_info['ident']
        if not re.fullmatch(r'[a-f0-9]{32}',ident): raise ProjectError('업로드 ID가 올바르지 않습니다.')
        root = panel.inputs/'manga_projects'/ident
        if not root.is_dir(): raise ProjectError('업로드 폴더가 없습니다.')
        relative = request.query.get('path','')
        path = PurePosixPath(relative)
        if (not relative or path.is_absolute() or '..' in path.parts or '\\' in relative
                or path.suffix.lower() not in EXTENSIONS):
            raise ProjectError('이미지 파일 경로가 올바르지 않습니다.')
        destination = root/path
        if not destination.resolve().is_relative_to(root.resolve()): raise ProjectError('잘못된 업로드 경로입니다.')
        reader = await request.multipart()
        part = await reader.next()
        if part is None or part.name != 'image': raise ProjectError('이미지 파일이 필요합니다.')
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary = destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
        count = 0
        try:
            with temporary.open('xb') as handle:
                while chunk := await part.read_chunk(1024*1024):
                    count += len(chunk)
                    if count>MAX_INPUT_BYTES: raise ProjectError('이미지는 256MiB 이하만 업로드할 수 있습니다.')
                    handle.write(chunk)
            # Never overwrite another upload or an existing project input.
            import os
            os.link(temporary,destination)
        finally:
            temporary.unlink(missing_ok=True)
        return web.json_response({'path':relative})

    @route('get','/{ident}')
    async def status(request):
        return web.json_response(panel.snapshot(request.match_info['ident']))

    @route('post','/{ident}/start')
    async def start(request):
        data = await body(request)
        retry = data.get('retry_failed',False)
        if type(retry) is not bool: raise ProjectError('다시 시도 설정이 올바르지 않습니다.')
        return web.json_response(panel.start(request.match_info['ident'],retry))

    @route('post','/{ident}/stop')
    async def stop(request):
        return web.json_response(panel.stop(request.match_info['ident']))

    @route('get','/{ident}/file/{page}/{attempt}/{name}')
    async def artifact(request):
        return web.FileResponse(panel.artifact(**{k:request.match_info[k] for k in ('ident','page','attempt','name')}))
