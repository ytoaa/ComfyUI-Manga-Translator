"""Run one configured 08 API workflow serially over an image folder.

No models or ComfyUI core are replaced. Each page is an independent prompt;
durable attempt records reconcile existing jobs before any new submission.
"""
from argparse import ArgumentParser
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
from urllib import error, parse, request
import uuid
import warnings

from PIL import Image, ImageChops, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if __package__:
    from ..limits import (RESOURCE_CONTRACT_VERSION, LEGACY_PAGE_PIXELS,
                          MAX_SOURCE_PIXELS, MAX_INPUT_BYTES)
else:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from limits import (RESOURCE_CONTRACT_VERSION, LEGACY_PAGE_PIXELS,
                        MAX_SOURCE_PIXELS, MAX_INPUT_BYTES)

DEFAULT_WORKFLOW = ROOT/'lettering/example_workflows/08-integrated-tiled-cleanup-lettering.api.json'
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif'}
MAX_PAGE_PIXELS = MAX_SOURCE_PIXELS  # Backward-compatible public/CLI name.
ACTIVE = {'submitting', 'queued', 'running', 'collecting'}
FINISHED = {'completed', 'unchanged_blank', 'needs_review'}
PROJECT_CONTROL_INPUTS = ('input_mode', 'input_folder', 'project_name', 'action')
LEGACY_SIZE_FAILURE_MARKERS = (
    'at most 16 Mi pixels',
    'exceed 16 Mi pixels',
    'exceeds 4 Mi pixels',
    'at most 4 Mi pixels',
    'Total typography area exceeds 16 Mi pixels',
)


class ProjectError(RuntimeError):
    pass


class Paused(ProjectError):
    """Keep job identity: work may still be running, so never resubmit blindly."""


class RestartInterrupted(Paused):
    """Internal evidence-bearing signal; only explicit native restart recovery uses it."""
    def __init__(self, evidence):
        super().__init__('The native ComfyUI process restarted before this attempt could be reconciled')
        self.evidence = evidence


class InputError(ProjectError):
    pass


class ProtocolError(ProjectError):
    pass


class Rejected(ProjectError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


@contextmanager
def project_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'.project.lock').open('a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            if not handle.read(1):
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ProjectError('This project is already being run') from exc
            unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ProjectError('This project is already being run') from exc
            unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            yield
        finally:
            handle.seek(0); unlock()


def natural_key(value):
    return tuple((1, int(piece), len(piece)) if piece.isdecimal() else (0, piece.casefold())
                 for piece in re.split(r'(\d+)', value))


def scan_images(folder, recursive=True, allow_empty=False):
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise InputError('Input folder does not exist')
    def paths():
        if not recursive:
            yield from folder.iterdir()
            return
        def failed_scan(exc):
            raise InputError('Cannot scan complete input folder: '+str(exc)) from exc
        for current, directories, names in os.walk(folder,followlinks=False,onerror=failed_scan):
            for name in directories:
                if (Path(current)/name).is_symlink():
                    raise InputError('Linked input subfolder needs explicit resolution: '+str(Path(current)/name))
            for name in names: yield Path(current)/name
    found = []
    for path in paths():
        if path.suffix.lower() not in EXTENSIONS or not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(folder).as_posix()
        # Do not read a linked file outside the selected project inputs.
        issue = 'symlink_input' if path.is_symlink() or not path.resolve().is_relative_to(folder) else None
        try:
            sha = ''
            if not issue and path.stat().st_size > MAX_INPUT_BYTES:
                issue = 'oversized_input_file'
            if not issue:
                with path.open('rb') as handle:
                    hasher, count = hashlib.sha256(), 0
                    while chunk := handle.read(1024*1024):
                        count += len(chunk)
                        if count > MAX_INPUT_BYTES:
                            issue = 'oversized_input_file'; break
                        hasher.update(chunk)
                    if not issue: sha = hasher.hexdigest()
        except OSError as exc:
            sha, issue = '', type(exc).__name__
        found.append({'id': 'p'+digest(relative.encode())[:20], 'relative_path': relative,
                      'input_sha256': sha, 'scan_issue': issue})
    found.sort(key=lambda row: (natural_key(row['relative_path']), row['relative_path']))
    if not found and not allow_empty:
        raise InputError('No supported image files in the input folder')
    return found


def normalise_image(path, expected_sha, max_pixels):
    try:
        if path.is_symlink() or path.stat().st_size > MAX_INPUT_BYTES:
            raise InputError('Linked or oversized input file')
        with path.open('rb') as handle: data = handle.read(MAX_INPUT_BYTES+1)
        if len(data)>MAX_INPUT_BYTES: raise InputError('Input grew beyond file budget')
    except OSError as exc:
        raise InputError('Cannot read input file: '+type(exc).__name__) from exc
    if digest(data) != expected_sha:
        raise InputError('Input changed after project scan; run again to plan its new version')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.width*source.height > max_pixels:
                    raise InputError('Input exceeds configured pixel budget')
                if getattr(source, 'n_frames', 1) != 1:
                    raise InputError('Multi-frame image needs explicit page extraction')
                if source.mode.startswith('I;16') or source.mode in ('I', 'F'):
                    raise InputError('High-bit-depth image needs explicit conversion')
                picture = ImageOps.exif_transpose(source)
                if 'A' in picture.getbands() or 'transparency' in picture.info:
                    rgba = picture.convert('RGBA')
                    base = Image.new('RGBA', rgba.size, 'white')
                    base.alpha_composite(rgba)
                    picture = base.convert('RGB')
                else:
                    picture = picture.convert('RGB')
                picture.load()
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InputError(f'Cannot decode input image: {type(exc).__name__}') from exc
    encoded = BytesIO(); picture.save(encoded, format='PNG')
    return encoded.getvalue(), list(picture.size), all(a == b for a, b in picture.getextrema())


def workflow_bindings(graph):
    if (not isinstance(graph, dict) or 'nodes' in graph or not graph
            or any(not isinstance(node, dict) or not isinstance(node.get('inputs'), dict)
                   or not isinstance(node.get('class_type'), str) for node in graph.values())):
        raise ProjectError('Use a configured API-format 08 workflow, not the GUI workflow JSON')
    def single(kind):
        matches = [key for key, node in graph.items() if node['class_type'] == kind]
        if len(matches) != 1:
            raise ProjectError(f'Project workflow needs exactly one {kind}')
        return matches[0]
    sources = [key for key,node in graph.items() if node['class_type'] in ('LoadImage','MangaWorkflowInput')]
    if len(sources) != 1: raise ProjectError('Project workflow needs exactly one image/page input')
    load, final = sources[0], single('SaveImage')
    single('MangaDetectorDetail')  # Require detector-backed selection for automatic folder pages.
    single('MangaRegionCrops')
    collect, translate = single('MangaCollectOCR'), single('MangaTranslate')
    saves = [key for key, node in graph.items() if node['class_type'] == 'MangaSaveReview']
    source = next((key for key in saves if graph[key]['inputs'].get('translated_json') == [collect, 0]), None)
    target = next((key for key in saves if graph[key]['inputs'].get('translated_json') == [translate, 0]), None)
    def preview(saved):
        matches = [key for key, node in graph.items() if node['class_type'] == 'PreviewAny'
                   and node['inputs'].get('source') == [saved, 0]]
        if not saved or len(matches) != 1:
            raise ProjectError('Connect a native PreviewAny to each OCR/translation review save')
        return matches[0]
    return {'load': load, 'final': final, 'source': source, 'target': target,
            'source_preview': preview(source), 'target_preview': preview(target)}


def workflow_fingerprint(graph, bind=None, *, legacy=False):
    """Hash semantic page-processing settings, not folder-control/location widgets."""
    bind = bind or workflow_bindings(graph)
    canonical = {key:{'class_type':node['class_type'],'inputs':deepcopy(node['inputs'])}
                 for key,node in graph.items()}
    load = canonical[bind['load']]
    load['inputs']['image'] = ''
    if not legacy and load['class_type'] == 'MangaWorkflowInput':
        for key in PROJECT_CONTROL_INPUTS:
            load['inputs'].pop(key, None)
    for key in ('final', 'source', 'target'):
        canonical[bind[key]]['inputs']['filename_prefix'] = key
    return digest(json.dumps(canonical,ensure_ascii=False,sort_keys=True,
                             allow_nan=False,separators=(',',':')).encode())


class ComfyClient:
    def __init__(self, base='http://127.0.0.1:8188', timeout=30):
        parsed = parse.urlsplit(base)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProjectError('Invalid ComfyUI server URL')
        self.base, self.timeout = base.rstrip('/'), timeout

    def _request(self, route, data=None, content_type='application/json', raw=False):
        headers = {}
        if data is not None: headers['Content-Type'] = content_type
        token = os.environ.get('COMFY_API_TOKEN', '').strip()
        if token: headers['Authorization'] = 'Bearer '+token
        req = request.Request(self.base+route, data=data, headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                value = response.read(128*1024*1024+1)
        except error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise Rejected(f'ComfyUI rejected {route.split("?")[0]}: HTTP {exc.code}') from exc
            raise OSError(f'ComfyUI HTTP {exc.code}') from exc
        if len(value) > 128*1024*1024:
            raise ProtocolError('ComfyUI response exceeds transfer budget')
        try:
            decoded = value if raw else json.loads(value)
        except (ValueError, UnicodeError) as exc:
            raise ProtocolError('ComfyUI returned invalid JSON') from exc
        if not raw and not isinstance(decoded,dict):
            raise ProtocolError('ComfyUI JSON response must be an object')
        return decoded

    def object_info(self): return self._request('/object_info')
    def history(self, ident):
        result = self._request('/history/'+parse.quote(ident, safe='')).get(ident)
        if result is not None and not isinstance(result,dict):
            raise ProtocolError('Invalid ComfyUI history entry')
        return result
    def queue(self): return self._request('/queue')
    def submit(self, graph, ident, token):
        return self._request('/prompt', json_bytes({'prompt':graph, 'prompt_id':ident,
            'client_id':token['project'], 'extra_data':{'manga_project':token}}))
    def download(self, descriptor): return self._request('/view?'+parse.urlencode(descriptor), raw=True)
    def upload(self, data, name, subfolder):
        boundary = 'manga'+uuid.uuid4().hex
        parts = []
        for key, value in (('type','input'), ('overwrite','false'), ('subfolder',subfolder)):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: image/png\r\n\r\n'.encode()+data+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        return self._request('/upload/image', b''.join(parts), 'multipart/form-data; boundary='+boundary)


class Project:
    def __init__(self, inputs, destination, graph, client=None, *, recursive=True, max_pixels=MAX_SOURCE_PIXELS,
                 page_timeout=3600, poll_interval=1, retry_failed=False, stop_on_error=False,
                 clock=time.monotonic, sleep=time.sleep, progress=None, should_stop=None):
        self.inputs, self.destination = Path(inputs).resolve(), Path(destination).resolve()
        if self.destination == self.inputs or self.destination.is_relative_to(self.inputs):
            raise ProjectError('Project output must be outside the scanned input folder')
        self.graph, self.bind = deepcopy(graph), workflow_bindings(graph)
        self.client = client or ComfyClient()
        self.recursive, self.max_pixels = recursive, max_pixels
        if (type(max_pixels) is not int or not 1 <= max_pixels <= MAX_SOURCE_PIXELS
                or not math.isfinite(page_timeout) or page_timeout <= 0 or not 0 < poll_interval <= 10):
            raise ProjectError(f'Invalid project budget; source pages support at most {MAX_SOURCE_PIXELS:,} pixels')
        self.page_timeout, self.poll_interval = page_timeout, poll_interval
        self.retry_failed, self.stop_on_error = retry_failed, stop_on_error
        self.clock, self.sleep = clock, sleep
        self.progress = progress or (lambda value: None)
        self.should_stop = should_stop or (lambda: False)
        self.workflow_sha256 = workflow_fingerprint(graph,self.bind)
        self.legacy_workflow_sha256 = workflow_fingerprint(graph,self.bind,legacy=True)
        self.config = {'identity_version':2, 'server':self.client.base,
                       'workflow_sha256':self.workflow_sha256, 'recursive':recursive,
                       'source_pixel_limit':max_pixels, 'normalisation':'exif_rgb_white_alpha_v1'}
        self._retry_policy_failures = False

    def _compatible_previous_config(self, previous):
        """Permit path/control-only migration and monotonic source-budget increases."""
        if not isinstance(previous,dict): return False, False
        if previous == self.config: return True, False
        if previous.get('server') != self.config['server'] or previous.get('recursive') != self.config['recursive']:
            return False, False
        if previous.get('normalisation') != self.config['normalisation']:
            return False, False
        previous_sha = previous.get('workflow_sha256')
        if previous_sha not in (self.workflow_sha256, self.legacy_workflow_sha256):
            return False, False
        previous_limit = previous.get('source_pixel_limit', previous.get('max_pixels'))
        if type(previous_limit) is not int or previous_limit < 1 or previous_limit > self.max_pixels:
            return False, False
        return True, previous_limit < self.max_pixels

    def _page_dir(self, page): return self.destination/'pages'/page['id']
    def state(self, page):
        paths = sorted(self._page_dir(page).glob('attempt-*/state.json'))
        if not paths: return None
        state = read_json(paths[-1])
        if (not isinstance(state,dict) or state.get('id') != page['id']
                or state.get('relative_path') != page['relative_path']
                or type(state.get('attempt')) is not int or state['attempt'] < 1
                or paths[-1].parent.name != f'attempt-{state["attempt"]:06d}'
                or state.get('status') not in ACTIVE | FINISHED | {'preparing','failed'}):
            raise ProjectError('Invalid project page state; preserve it for recovery')
        if state['status'] in FINISHED and (not isinstance(state.get('artifacts'),dict)
                or not {'input.png','result.png','source.json','target.json'} <= state['artifacts'].keys()):
            raise ProjectError('Completed project page has incomplete artifact records')
        if ('artifacts' in state and (not isinstance(state['artifacts'],dict)
                or any(name not in ('input.png','result.png','source.json','target.json')
                       or not re.fullmatch(r'[a-f0-9]{64}',str(sha)) for name,sha in state['artifacts'].items()))):
            raise ProjectError('Invalid project artifact records')
        if 'result' in state and state['result'] != (self._attempt_dir(state)/'result.png').relative_to(self.destination).as_posix():
            raise ProjectError('Invalid project result path')
        if state['status'] in ACTIVE:
            try: valid_id = str(uuid.UUID(state.get('prompt_id',''))) == state['prompt_id']
            except (ValueError,AttributeError,TypeError): valid_id = False
            expected = f'manga_translator/projects/{self.project_id}/{page["id"]}/a{state["attempt"]:06d}'
            if not valid_id or state.get('output_prefix') != expected:
                raise ProjectError('Invalid active job identity; preserve its state for recovery')
        return state
    def _attempt_dir(self, state): return self.destination/'pages'/state['id']/f'attempt-{state["attempt"]:06d}'
    def _save(self, state):
        state['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        if state['status'] in FINISHED | {'failed'}:
            state.setdefault('finished_at',state['updated_at'])
        atomic_write(self._attempt_dir(state)/'state.json', json_bytes(state))
        self.progress({key:state.get(key) for key in ('relative_path','status','reason','prompt_id')})
    def _new(self, page):
        folders = list(self._page_dir(page).glob('attempt-*'))
        number = max((int(p.name.split('-')[1]) for p in folders if re.fullmatch(r'attempt-\d{6}', p.name)), default=0)+1
        return {**page, 'attempt':number, 'status':'preparing', 'workflow_sha256':self.config['workflow_sha256'],
                'resource_contract_version':RESOURCE_CONTRACT_VERSION,
                'created_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}

    def _prepare_project(self):
        path = self.destination/'project.json'
        previous = read_json(path) if path.exists() else None
        if previous is not None and (not isinstance(previous,dict) or previous.get('schema') != 1
                or not isinstance(previous.get('pages'),list)
                or not re.fullmatch(r'[a-f0-9]{32}', str(previous.get('project_id','')))):
            raise ProjectError('Invalid existing project manifest; preserve it for recovery')
        if previous is not None:
            for page in previous['pages']:
                if (not isinstance(page,dict) or not isinstance(page.get('relative_path'),str)
                        or PurePosixPath(page['relative_path']).is_absolute()
                        or '..' in PurePosixPath(page['relative_path']).parts
                        or page.get('id') != 'p'+digest(page['relative_path'].encode())[:20]):
                    raise ProjectError('Invalid project input identity in existing manifest')
            removed = previous.get('removed_inputs',[])
            if (not isinstance(removed,list) or any(not isinstance(name,str) or PurePosixPath(name).is_absolute()
                                                  or '..' in PurePosixPath(name).parts for name in removed)):
                raise ProjectError('Invalid removed-input ledger')
            compatible, raised_limit = self._compatible_previous_config(previous.get('config'))
            if not compatible:
                raise ProjectError('Project model/workflow settings changed; use a new project directory to preserve prior results and active job identities')
            self._retry_policy_failures = raised_limit
        pages = scan_images(self.inputs, self.recursive, allow_empty=previous is not None)
        self.project_id = previous['project_id'] if previous else uuid.uuid4().hex
        self.pages = pages
        past = ({p['relative_path'] for p in previous['pages']} | set(previous.get('removed_inputs',[]))) if previous else set()
        removed = sorted(past - {p['relative_path'] for p in pages})
        self.removed = removed
        known = {p['id']:p for p in pages}
        if previous: known.update({p['id']:p for p in previous['pages']})
        for relative in removed:
            ident = 'p'+digest(relative.encode())[:20]
            known.setdefault(ident,{'id':ident,'relative_path':relative,'input_sha256':''})
        self.recovery_pages = list(known.values())
        document = {'schema':1, 'project_id':self.project_id, 'config':self.config,
                    'source_folder':str(self.inputs), 'pages':pages, 'removed_inputs':removed,
                    'quality_scope':'model_results_require_review'}
        atomic_write(path, json_bytes(document))
        if not (self.destination/'workflow.api.json').exists():
            atomic_write(self.destination/'workflow.api.json', json_bytes(self.graph))

    def _summary(self, halted=None):
        rows = []
        for page in self.pages:
            state = self.state(page)
            row = {key:page[key] for key in ('id','relative_path')}
            if state and state['input_sha256'] == page['input_sha256']:
                row.update({k:state[k] for k in ('status','reason','prompt_id','result','failure_node','failure_node_id','failure_diagnostics_missing') if k in state})
                row['state_file'] = (self._attempt_dir(state)/'state.json').relative_to(self.destination).as_posix()
                if state.get('failure_message'): row['detail'] = state['failure_message'][:240]
            else: row['status'] = 'pending'
            rows.append(row)
        result = {'schema':1, 'project_id':self.project_id, 'counts':dict(Counter(r['status'] for r in rows)),
                  'halted':halted, 'pages':rows, 'quality_scope':'completed_is_execution_not_semantic_accuracy'}
        result['removed_inputs'] = self.removed
        atomic_write(self.destination/'summary.json', json_bytes(result))
        return result

    def _export(self, report):
        # A stable edition directory avoids overwriting a previous book export
        # when inputs are added/changed and natural page numbers move.
        inventory = []
        for index, page in enumerate(self.pages, 1):
            state = self.state(page)
            inventory.append({'number':index,'relative_path':page['relative_path'],
                'id':page['id'],'input_sha256':page['input_sha256'],
                'status':report['pages'][index-1]['status'],
                'result_sha256':state.get('artifacts',{}).get('result.png') if state else None})
        edition = digest(json_bytes(inventory))[:20]
        folder = self.destination/'exports'/edition
        for item in inventory:
            if item['status'] not in ('completed','unchanged_blank'): continue
            state = self.state(item)
            data = (self.destination/state['result']).read_bytes()
            if digest(data) != item['result_sha256']:
                raise ProtocolError('Result changed during export; preserve it for review')
            name = f'{item["number"]:06d}.png'
            path = folder/name
            if path.exists() and path.read_bytes() != data:
                raise ProtocolError('Existing exported image changed; preserving it')
            if not path.exists(): atomic_write(path,data)
            item['file'] = name
        index = {'schema':1,'pages':inventory,'counts':report['counts'],
                 'missing_or_review_pages':[item['number'] for item in inventory if 'file' not in item]}
        atomic_write(folder/'index.json',json_bytes(index))
        return folder.relative_to(self.destination).as_posix()

    def _preflight(self):
        available = self.client.object_info()
        needed = {node['class_type'] for node in self.graph.values()}
        if not isinstance(available, dict) or needed-set(available):
            raise ProjectError('ComfyUI is missing required workflow nodes: '+', '.join(sorted(needed-set(available or {}))))

    def _queue_identity(self, state):
        queue = self.client.queue()
        if (not isinstance(queue,dict) or any(not isinstance(queue.get(k),list) for k in ('queue_running','queue_pending'))):
            raise ProtocolError('Unrecognized ComfyUI queue response')
        matches = []
        for item in queue.get('queue_running', [])+queue.get('queue_pending', []):
            if not isinstance(item, list) or len(item) < 4:
                raise ProtocolError('Unrecognized ComfyUI queue item')
            extra = item[3] if isinstance(item[3], dict) else {}
            if item[1] == state['prompt_id'] or extra.get('manga_project') == state['submission_token']:
                matches.append((item[1], 'running' if item in queue.get('queue_running', []) else 'queued'))
        if len(matches) > 1:
            raise Paused('Multiple jobs match this page; review the queue before continuing')
        return matches[0] if matches else None

    def _wait(self, state):
        deadline = self.clock()+self.page_timeout
        missing_polls = 0
        while self.clock() < deadline:
            try:
                history = self.client.history(state['prompt_id'])
                if history:
                    status = history.get('status', {})
                    if not isinstance(status,dict): raise ProtocolError('Invalid execution status')
                    if status.get('completed') or status.get('status_str') in ('error', 'success'):
                        return history
                queued = self._queue_identity(state)
                if queued:
                    missing_polls = 0
                    if (state['prompt_id'], state['status']) != queued:
                        state['prompt_id'], state['status'] = queued
                        self._save(state)
                elif not history:
                    # A completion may arrive between history and queue reads.
                    history = self.client.history(state['prompt_id'])
                    if history:
                        status = history.get('status',{})
                        if not isinstance(status,dict): raise ProtocolError('Invalid execution status')
                        if status.get('completed') or status.get('status_str') in ('error','success'):
                            return history
                    else:
                        missing_polls += 1
                        if missing_polls >= 3:
                            prove_restart = getattr(self.client, 'restart_evidence', None)
                            evidence = prove_restart(state) if self.retry_failed and callable(prove_restart) else None
                            if evidence and not self.should_stop():
                                # Check the original identity/token once more immediately
                                # before retiring an attempt. Never cancel or clear a queue.
                                if self.client.history(state['prompt_id']) or self._queue_identity(state):
                                    continue
                                raise RestartInterrupted(evidence)
                            raise Paused('Submitted page is absent from both history and queue; do not resubmit until its outcome is known')
            except (OSError, Rejected) as exc:
                raise Paused('Connection lost while reconciling a submitted page; resume this project') from exc
            self.sleep(self.poll_interval)
        raise Paused('Page wait timed out; its job may still be running. Resume before submitting more pages')

    def _review(self, history, key, state):
        outputs = history.get('outputs', {})
        if not isinstance(outputs,dict): raise ProtocolError('Invalid execution output map')
        output = outputs.get(self.bind[key], {})
        if not isinstance(output,dict): raise ProtocolError('Invalid saved-review output')
        if output.get('manga_review_files'):
            files = output['manga_review_files']
            if (not isinstance(files,list) or len(files)!=1 or not isinstance(files[0],dict)
                    or files[0].get('subfolder') != state['output_prefix'] or files[0].get('type') != 'output'
                    or not str(files[0].get('filename','')).startswith('ocr_' if key=='source' else 'translation_')):
                raise ProtocolError('Review JSON does not belong to this project page attempt')
        if 'text' not in output:
            output = outputs.get(self.bind[key+'_preview'], {})
        if not isinstance(output,dict): raise ProtocolError('Invalid review preview output')
        text = output.get('text')
        if not isinstance(text, list) or len(text) != 1 or not isinstance(text[0], str):
            raise ProtocolError('Missing or ambiguous '+key+' PreviewAny result')
        try: data = json.loads(text[0])
        except (ValueError, TypeError) as exc: raise ProtocolError('Invalid '+key+' review JSON') from exc
        if (not isinstance(data, dict) or not isinstance(data.get('regions'), list) or len(data['regions'])>64
                or any(type(data.get(k)) is not int for k in ('image_width','image_height'))
                or [data.get('image_width'),data.get('image_height')] != state['image_size']):
            raise ProtocolError('Review coordinates do not match the submitted page')
        return data

    def _artifact(self, state, name, data):
        path = self._attempt_dir(state)/name
        if path.exists() and path.read_bytes() != data:
            raise ProtocolError('Existing project artifact changed; preserving '+name)
        if not path.exists(): atomic_write(path, data)
        state.setdefault('artifacts', {})[name] = digest(data)
        return path.relative_to(self.destination).as_posix()

    def _collect(self, state, history):
        status = history.get('status', {})
        if not isinstance(status,dict) or type(status.get('completed')) is not bool:
            raise ProtocolError('Invalid completed-job status')
        if status.get('status_str') not in ('success','error') or (status['status_str']=='success' and status['completed'] is not True):
            raise ProtocolError('Contradictory terminal execution status')
        if status.get('status_str') != 'success' or status.get('completed') is not True:
            messages = status.get('messages', [])
            if not isinstance(messages, (list, tuple)):
                raise ProtocolError('Invalid execution message sequence')
            # Native PromptQueue keeps (event, data) tuples. HTTP JSON turns
            # them into lists; both clients must preserve the same failure.
            errors = [entry for entry in messages
                      if isinstance(entry, (list, tuple)) and len(entry) == 2
                      and entry[0] in ('execution_error', 'execution_interrupted')]
            event, failure = errors[-1] if errors else (None, {})
            if not isinstance(failure, dict): raise ProtocolError('Invalid execution failure record')
            missing = not errors or (event != 'execution_interrupted' and not
                                     (failure.get('exception_type') or failure.get('exception_message')))
            message = str(failure.get('exception_message') or '')
            if missing:
                message = 'ComfyUI returned an error status without usable execution_error details; inspect the prompt history or server log before retrying.'
            if len(message)>4000: message = message[:1950]+'\n[...truncated...]\n'+message[-1950:]
            node_id = failure.get('node_id')
            node_type = failure.get('node_type') or self.graph.get(str(node_id), {}).get('class_type')
            reason = failure.get('exception_type') or ('ExecutionInterrupted' if event == 'execution_interrupted' else 'execution_failed')
            trace = failure.get('traceback', [])
            if isinstance(trace, (list, tuple)):
                trace = ''.join(str(line) for line in trace)
            state.update(status='failed', reason=str(reason), failure_node=node_type,
                         failure_node_id=node_id, failure_message=message,
                         failure_event=event, failure_diagnostics_missing=missing,
                         failure_traceback=str(trace or '')[-12000:])
            # Partial reviews are useful, but are never a completed page.
            for key in ('source','target'):
                try: self._artifact(state,key+'.json',json_bytes(self._review(history,key,state)))
                except ProtocolError: pass
            self._save(state)
            explanation = (state['reason']+' '+state['failure_message']).lower()
            if any(word in explanation for word in ('outofmemory','out of memory','cuda error',
                    'no space left','disk full','errno 28','permission denied','connection refused',
                    'http error 401','http error 403','http error 429','rate limit')):
                raise Paused('Server resource/storage/service failure; check the server before continuing the project')
            if state['reason'] in ('InterruptProcessingException','ExecutionInterrupted') or any(
                    isinstance(entry,(list,tuple)) and entry and entry[0]=='execution_interrupted'
                    for entry in messages):
                raise Paused('ComfyUI에서 페이지 실행이 중지되었습니다. 프로젝트의 추가 제출을 멈췄습니다.')
            if state['reason'] in ('FileNotFoundError','ModuleNotFoundError','ImportError'):
                raise Paused('Server model/font/dependency configuration failed; check it before continuing')
            if missing:
                raise Paused('ComfyUI 오류 상세가 없어 원인을 분류할 수 없습니다. 추가 페이지 제출을 멈췄습니다. prompt 이력과 서버 로그를 확인한 뒤 실패 재시도를 선택하세요.')
            if self.stop_on_error: raise Paused('Stopped after a failed page by project policy')
            return
        state['status'] = 'collecting'; self._save(state)
        source, target = (self._review(history,key,state) for key in ('source','target'))
        if any(not isinstance(row,dict) for value in (source,target) for row in value['regions']):
            raise ProtocolError('Invalid review region object')
        source_ids = [row.get('id') for row in source['regions']]
        if (not all(isinstance(v,str) and v for v in source_ids) or len(set(source_ids)) != len(source_ids)
                or source_ids != [row.get('id') for row in target['regions']]
                or any(not isinstance(r.get('source'),str) or not r['source'].strip() for r in source['regions'])
                or any(not isinstance(r.get('target'),str) or not r['target'].strip() for r in target['regions'])):
            raise ProtocolError('Source/translation region identities or texts differ')
        for before, after in zip(source['regions'], target['regions']):
            box = before.get('bbox')
            if (not isinstance(box,list) or len(box) != 4
                    or any(type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v <= 1000 for v in box)
                    or not box[0] < box[2] or not box[1] < box[3]):
                raise ProtocolError('Invalid source region coordinates')
            if any(before.get(k) != after.get(k) for k in ('bbox','crop_bbox_pixels','edit_bbox_pixels','source')):
                raise ProtocolError('Translation changed source text or geometry')
        images = history.get('outputs', {}).get(self.bind['final'], {}).get('images')
        if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0],dict):
            raise ProtocolError('Expected exactly one final SaveImage result')
        descriptor = images[0]
        name = descriptor.get('filename','')
        subfolder = descriptor.get('subfolder')
        if (descriptor.get('type') != 'output' or not isinstance(subfolder,str)
                or subfolder.replace('\\','/') != state['output_prefix']
                or not isinstance(name,str) or PurePosixPath(name).name != name or '\\' in name
                or not name.startswith('result_') or not name.endswith('.png')):
            raise ProtocolError('Final output does not belong to this project page attempt')
        data = self.client.download({k:descriptor[k] for k in ('filename','subfolder','type')})
        try:
            with Image.open(BytesIO(data)) as picture:
                if list(picture.size) != state['image_size'] or picture.format != 'PNG' or picture.mode != 'RGB':
                    raise ProtocolError('Final image size/format differs from submitted page')
                picture.load()
                if not source['regions']:
                    if (source.get('page_status') != 'no_text_detected' or source.get('ocr_skipped') is not True
                            or target.get('translation_skipped') is not True):
                        raise ProtocolError('Unverified empty-page bypass metadata')
                    with Image.open(self._attempt_dir(state)/'input.png') as prepared:
                        if ImageChops.difference(picture.convert('RGB'), prepared.convert('RGB')).getbbox():
                            raise ProtocolError('No-text output changed original pixels')
        except (OSError, ValueError) as exc: raise ProtocolError('Invalid final image bytes') from exc
        state['result'] = self._artifact(state, 'result.png', data)
        self._artifact(state, 'source.json', json_bytes(source))
        self._artifact(state, 'target.json', json_bytes(target))
        if not source['regions']:
            state['status'] = 'unchanged_blank' if state['uniform_rgb'] and not source.get('needs_review') and not source.get('no_text_reason') else 'needs_review'
            state['reason'] = 'uniform_rgb_pixels' if state['status'] == 'unchanged_blank' else source.get('no_text_reason','no_text_detected_not_verified_blank')
        else: state['status'] = 'needs_review' if source.get('needs_review') else 'completed'
        self._save(state)

    def _resume(self, state):
        if not (self._attempt_dir(state)/'input.png').exists():
            try:
                encoded, _, _ = normalise_image(self.inputs/state['relative_path'], state['input_sha256'], self.max_pixels)
            except InputError:
                reference = state.get('uploaded_reference')
                if not isinstance(reference,dict): raise Paused('Missing normalized input and source; keep this job identity for recovery')
                encoded = self.client.download(reference)
            if digest(encoded) != state.get('artifacts',{}).get('input.png'):
                raise ProtocolError('Missing normalized input cannot be reconstructed exactly')
            self._artifact(state,'input.png',encoded)
        try:
            history = self._wait(state)
        except RestartInterrupted as exc:
            state.update(status='failed', reason='server_restarted_outcome_lost',
                         failure_message='서버 재시작 전 시도의 결과를 확인할 수 없습니다. 큐·이력 부재와 프로세스 시작 시각을 확인하고 명시적 실패 재시도로 새 시도를 허용했습니다.',
                         restart_recovery=exc.evidence)
            self._save(state)
            return
        self._collect(state, history)

    def _process(self, page):
        state = self.state(page)
        if state and state['status'] in ACTIVE:
            self._resume(state)
        if state and state['input_sha256'] == page['input_sha256']:
            if state['status'] == 'failed' and not self.retry_failed:
                if state.get('failure_diagnostics_missing'):
                    raise Paused('이전 실패의 ComfyUI 오류 상세가 없습니다. 서버 로그를 확인한 뒤 실패 재시도를 선택하세요.')
                if state.get('reason') == 'execution_failed' and not state.get('failure_message'):
                    # Repair pre-fix native tuple failures using their original
                    # prompt only. Never submit a page just to recover diagnostics.
                    history = self.client.history(state.get('prompt_id')) if state.get('prompt_id') else None
                    if not history:
                        raise Paused('이전 실패의 prompt 이력이 없어 원인을 복원할 수 없습니다. 서버 로그를 확인한 뒤 실패 재시도를 선택하세요.')
                    if history.get('status', {}).get('status_str') != 'error':
                        raise Paused('이전 실패 기록과 ComfyUI prompt 이력이 일치하지 않습니다. 추가 제출 없이 작업 상태를 확인하세요.')
                    self._collect(state, history)
            if state['status'] in FINISHED:
                missing = False
                for name, sha in state.get('artifacts', {}).items():
                    path = self._attempt_dir(state)/name
                    if not path.exists(): missing = True
                    elif digest(path.read_bytes()) != sha:
                        state.update(status='needs_review', reason='project_artifact_modified')
                        self._save(state); return
                if missing:
                    state['status'] = 'collecting'; self._save(state); self._resume(state)
                return
            policy_retry = (self._retry_policy_failures and state['status'] == 'failed'
                            and state.get('reason') == 'invalid_input'
                            and state.get('failure_message') == 'Input exceeds configured pixel budget')
            legacy_runtime_retry = (state['status'] == 'failed'
                                    and state.get('resource_contract_version',0) < RESOURCE_CONTRACT_VERSION
                                    and any(marker in str(state.get('failure_message',''))
                                            for marker in LEGACY_SIZE_FAILURE_MARKERS))
            if state['status'] == 'failed' and not self.retry_failed and not policy_retry and not legacy_runtime_retry:
                return
        state = self._new(page)
        self._save(state)
        try:
            if page['scan_issue']: raise InputError(page['scan_issue'])
            encoded, size, uniform = normalise_image(self.inputs/page['relative_path'], page['input_sha256'], self.max_pixels)
        except InputError as exc:
            state.update(status='failed', reason='invalid_input', failure_message=str(exc))
            self._save(state)
            if self.stop_on_error: raise Paused('Stopped after invalid input by project policy')
            return
        state.update(image_size=size, uniform_rgb=uniform)
        self._artifact(state,'input.png',encoded)
        uploaded = self.client.upload(encoded, page['id']+'_'+uuid.uuid4().hex+'.png', 'manga_translator/'+self.project_id)
        filename, subfolder = uploaded.get('name'), uploaded.get('subfolder','')
        if (not isinstance(filename,str) or not isinstance(subfolder,str) or uploaded.get('type') != 'input'
                or PurePosixPath(filename).name != filename or '\\' in filename or '\\' in subfolder
                or PurePosixPath(subfolder).is_absolute() or '..' in PurePosixPath(subfolder).parts
                or subfolder != 'manga_translator/'+self.project_id or not filename.startswith(page['id']+'_')):
            raise ProtocolError('Invalid uploaded-image reference')
        graph = deepcopy(self.graph)
        load = graph[self.bind['load']]
        load['inputs']['image'] = str(PurePosixPath(subfolder)/filename)
        if load['class_type'] == 'MangaWorkflowInput':
            # Child jobs are ordinary single-image jobs. The trusted extra_pnginfo marker
            # identifies them as project pages without re-validating/relaunching the folder.
            load['inputs']['input_mode'] = '이미지 한 장'
            load['inputs']['input_folder'] = ''
            load['inputs']['action'] = '상태 확인'
        prefix = f'manga_translator/projects/{self.project_id}/{page["id"]}/a{state["attempt"]:06d}'
        for key, basename in (('final','result'),('source','ocr'),('target','translation')):
            graph[self.bind[key]]['inputs']['filename_prefix'] = prefix+'/'+basename
        token = {'project':self.project_id, 'page':page['id'], 'attempt':state['attempt']}
        state.update(status='submitting', prompt_id=str(uuid.uuid4()), submission_token=token,
                     output_prefix=prefix,uploaded_reference={'filename':filename,'subfolder':subfolder,'type':'input'})
        context = getattr(self.client, 'execution_context', None)
        if isinstance(context, dict): state['execution_context'] = deepcopy(context)
        self._save(state)  # Durable identity BEFORE POST, including a lost HTTP reply.
        try:
            answer = self.client.submit(graph, state['prompt_id'], token)
        except Rejected:
            state.update(status='failed', reason='prompt_rejected'); self._save(state)
            raise
        except OSError as exc:
            raise Paused('Prompt submission reply was lost; resume to reconcile this job, not resubmit') from exc
        if not isinstance(answer,dict) or not isinstance(answer.get('prompt_id'),str):
            raise Paused('Prompt acceptance is uncertain; inspect/reconcile the saved submission identity')
        try: valid_id = str(uuid.UUID(answer['prompt_id'])) == answer['prompt_id']
        except (ValueError,AttributeError,TypeError): valid_id = False
        if not valid_id: raise Paused('Invalid prompt receipt; reconcile the original saved submission identity')
        state.update(prompt_id=answer['prompt_id'], status='queued')
        self._save(state)
        self._resume(state)

    def run(self, plan_only=False, export=False):
        with project_lock(self.destination):
            self._prepare_project()
            if plan_only: return self._summary('plan_only_no_submission')
            try:
                # Reconcile outstanding jobs first, even if a new page sorts
                # before them or their original input has since been removed.
                for page in self.recovery_pages:
                    state = self.state(page)
                    if state and state['status'] in ACTIVE: self._resume(state)
                self._preflight()
                for page in self.pages:
                    if self.should_stop():
                        raise Paused('사용자 요청으로 일시정지했습니다. 재개하면 완료한 페이지는 건너뜁니다.')
                    self._process(page)
                    settled = self.state(page)
                    if not settled or settled['status'] not in FINISHED | {'failed'}:
                        raise Paused('Page outcome was not durably settled; stop before submitting another page')
                result = self._summary()
                if export:
                    exportable = any(row['status'] in ('completed','unchanged_blank') for row in result['pages'])
                    result['export'] = self._export(result) if exportable else None
                    atomic_write(self.destination/'summary.json',json_bytes(result))
                return result
            except (ProjectError, OSError, KeyboardInterrupt) as exc:
                self._summary(type(exc).__name__+': '+str(exc))
                raise


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='Source image folder (never modified)')
    parser.add_argument('--project', required=True, help='Persistent output/state folder outside input')
    parser.add_argument('--workflow', type=Path, default=DEFAULT_WORKFLOW, help='Configured 08 API-format JSON')
    parser.add_argument('--server', default='http://127.0.0.1:8188')
    parser.add_argument('--plan', action='store_true', help='Local inventory only; no server requests')
    parser.add_argument('--export', action='store_true', help='Copy completed pages to an ordered edition; gaps remain for failed/review pages')
    parser.add_argument('--non-recursive', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--stop-on-error', action='store_true')
    parser.add_argument('--max-pixels', type=int, default=MAX_SOURCE_PIXELS)
    parser.add_argument('--page-timeout', type=float, default=3600)
    args = parser.parse_args()
    try:
        project = Project(args.input, args.project, read_json(args.workflow), ComfyClient(args.server),
            recursive=not args.non_recursive, retry_failed=args.retry_failed, stop_on_error=args.stop_on_error,
            max_pixels=args.max_pixels, page_timeout=args.page_timeout,
            progress=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
        report = project.run(args.plan,args.export)
        print(json.dumps(report['counts'], ensure_ascii=False))
        if not args.plan and any(status not in ('completed','unchanged_blank') and count
                                 for status,count in report['counts'].items()):
            raise SystemExit(3)
    except (ProjectError, OSError, ValueError) as exc:
        parser.exit(2, f'{type(exc).__name__}: {exc}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Stopped submitting pages. Existing server jobs were not interrupted; resume this project.\n')


if __name__ == '__main__': main()
