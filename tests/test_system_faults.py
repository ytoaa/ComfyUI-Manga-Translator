"""Fault injection at user-visible service and disk boundaries."""
import json
import pytest
from tools.simulate_ownership_scenarios import module
T=module('lettering.translate')
P=module('tools.run_project')

@pytest.mark.parametrize('payload',[None,[],{'choices':None},{'choices':[None]},
 {'choices':[{'finish_reason':'stop','message':None}]},{'choices':{}},
 {'choices':[{'finish_reason':'length','message':{'content':'truncated'}}]}])
def test_malformed_chat_response_is_explicit_validation_error(monkeypatch,payload):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps(payload).encode()
    monkeypatch.setattr(T,'urlopen',lambda *a,**k:Response())
    with pytest.raises(ValueError):T.translate('原文',model='controlled')

@pytest.mark.parametrize('payload',[{'data':None},{'data':[None]},{'data':[{'id':''}]},{'data':{}}])
def test_bad_model_inventory_is_explicit_validation_error(monkeypatch,payload):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps(payload).encode()
    monkeypatch.setattr(T,'urlopen',lambda *a,**k:Response())
    with pytest.raises(ValueError):T.translate('原文')

@pytest.mark.parametrize('operation',['fsync','replace'])
def test_failed_output_commit_retains_previous_file_and_no_temporary(monkeypatch,tmp_path,operation):
    path=tmp_path/'result.json';path.write_bytes(b'previous')
    def fail(*args):raise OSError('injected disk failure')
    monkeypatch.setattr(P.os,operation,fail)
    with pytest.raises(OSError):P.atomic_write(path,b'new')
    assert path.read_bytes()==b'previous'
    assert sorted(p.name for p in tmp_path.iterdir())==['result.json']

def test_review_save_cleans_partial_file_after_disk_failure(monkeypatch,tmp_path):
    import sys,types
    N=module('nodes')
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    def fail(data,handle,**kwargs):
        handle.write('{partial');raise OSError('disk full')
    monkeypatch.setattr(N.json,'dump',fail)
    with pytest.raises(OSError):N.MangaSaveReview().save('{"regions":[]}','review')
    assert not list(tmp_path.glob('*.json'))

def test_review_save_rejects_symlink_escape(monkeypatch,tmp_path):
    import sys,types
    N=module('nodes');root=tmp_path/'output';root.mkdir();outside=tmp_path/'outside';outside.mkdir()
    (root/'linked').symlink_to(outside,target_is_directory=True)
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(root)))
    with pytest.raises(ValueError,match='output folder'):N.MangaSaveReview().save('{"regions":[]}','linked/review')
    assert not list(outside.iterdir())

def test_every_node_input_matches_signature_and_default_range(monkeypatch,tmp_path):
    import sys,types,inspect
    folder=types.SimpleNamespace(models_dir=str(tmp_path),folder_names_and_paths={},
        add_model_folder_path=lambda *a:None,get_folder_paths=lambda *a:[],get_input_directory=lambda:str(tmp_path))
    monkeypatch.setitem(sys.modules,'folder_paths',folder)
    plugin=sys.modules['ownership_image_simulation']
    for name,cls in plugin.NODE_CLASS_MAPPINGS.items():
        schema=cls.INPUT_TYPES();signature=inspect.signature(getattr(cls,cls.FUNCTION))
        variadic=any(p.kind==p.VAR_KEYWORD for p in signature.parameters.values())
        for section in ('required','optional','hidden'):
            for key,spec in schema.get(section,{}).items():
                assert key in signature.parameters or variadic,(name,key)
                if not isinstance(spec,tuple) or len(spec)<2 or not isinstance(spec[1],dict):continue
                settings=spec[1];default=settings.get('default')
                if default is None:continue
                if isinstance(spec[0],list):assert default in spec[0],(name,key)
                if isinstance(default,(int,float)):
                    assert settings.get('min',default)<=default<=settings.get('max',default),(name,key)

@pytest.mark.parametrize('failure',['hash','timeout','cancel'])
def test_failed_model_acquisition_leaves_no_partial_bundle(monkeypatch,tmp_path,failure):
    import sys,types,hashlib
    E=module('ocr_engines')
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(models_dir=str(tmp_path)))
    monkeypatch.setattr(E,'spec',lambda engine:('repo','rev',{'weights.bin':hashlib.sha256(b'correct').hexdigest()},
        {'weights.bin':'https://invalid.test/controlled'},'test-bundle'))
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):
            if failure=='timeout':raise TimeoutError('injected')
            if failure=='cancel':raise KeyboardInterrupt('injected')
            return b'wrong' if not getattr(self,'done',False) and not setattr(self,'done',True) else b''
    monkeypatch.setattr(E,'urlopen',lambda *a,**k:Response())
    with pytest.raises({'hash':ValueError,'timeout':TimeoutError,'cancel':KeyboardInterrupt}[failure]):E.ensure(E.ENGINES[1])
    parent=tmp_path/'manga_translator'/'ocr'
    assert not list(parent.iterdir())

@pytest.mark.parametrize('message',[
 'Translation API returned HTTP 401; check URL, model, and server log',
 'Translation server HTTP 403','Translation API returned HTTP 429; check URL',
 'Translation server HTTP 503',
 'Translation API is unreachable or timed out; check the configured server',
 'Translation server unavailable (TimeoutError)'])
def test_actual_translation_service_errors_pause_before_next_page(tmp_path,message):
    from tests.test_project_runner import P as Runner,FakeComfy,project,make_page
    class ServiceError(FakeComfy):
        def history(self,ident):
            history=super().history(ident)
            if history and history['status']['status_str']=='error':
                history['status']['messages'][0][1].update(exception_type='RuntimeError',exception_message=message,node_type='MangaTranslate')
            return history
    make_page(tmp_path/'input/1.png');make_page(tmp_path/'input/2.png')
    client=ServiceError(['ocr_error','success']);runner=project(tmp_path,client)
    with pytest.raises(Runner.Paused):runner.run()
    assert len(client.submissions)==1
