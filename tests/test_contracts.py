from pathlib import Path
import importlib.util
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('manga_tests');pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
def module(name):
    spec=importlib.util.spec_from_file_location(pkg.__name__+'.'+name,ROOT/(name.replace('.','/')+'.py'))
    value=importlib.util.module_from_spec(spec);sys.modules[spec.name]=value;spec.loader.exec_module(value);return value
N=module('nodes')
M=module('models')


def source():
    return {'regions':[{'id':'a','bbox':[100,100,500,500],'source':'先生'},
                       {'id':'b','bbox':[100,600,900,900],'source':'こんにちは'}]}


@pytest.mark.parametrize('box',[[0,0,0,10],[100,0,90,10],[-1,0,10,10],[0,0,1001,10],[0,0,float('nan'),10],[True,0,10,10]])
def test_reject_invalid_coordinates(box):
    with pytest.raises(ValueError):N.layout(json.dumps({'regions':[{'id':'a','bbox':box}]}))


def test_duplicate_region_ids_rejected():
    data=source();data['regions'][1]['id']='a'
    with pytest.raises(ValueError):N.layout(N.encode(data))


def test_translation_ids_not_response_order_determine_mapping():
    data=N.translations(source(),{'translations':[{'id':'b','target':'안녕하세요'},{'id':'a','target':'선생님'}]})
    assert [r['target'] for r in data['regions']]==['선생님','안녕하세요']
    assert [r['source'] for r in data['regions']]==['先生','こんにちは']


@pytest.mark.parametrize('rows',[[{'id':'a','target':'선생님'}],[{'id':'a','target':'선생님'},{'id':'a','target':'다른'}],[{'id':'a','target':''},{'id':'b','target':'안녕'}],[{'id':'a','target':'선생님'},{'id':'c','target':'안녕'}]])
def test_partial_or_wrong_translation_is_rejected(rows):
    with pytest.raises(ValueError):N.translations(source(),{'translations':rows})


def test_prompt_keeps_exact_quoted_characters_and_line_breaks():
    target='"선생님"\n다음 줄!'
    data=N.translations(source(),{'translations':[{'id':'a','target':target},{'id':'b','target':'안녕'}]})
    prompt=N.MangaEditPrompt().build(N.encode(data),'Preserve artwork.')[0]
    payloads=[json.loads(s) for s in prompt.splitlines() if s.startswith('{')]
    assert payloads[0]['target']==target and payloads[0]['source']=='先生'
    assert 'bbox' in payloads[0]


def test_ocr_count_and_empty_result_are_rejected():
    for text in [['先生'],['先生','']]:
        with pytest.raises(ValueError):N.MangaCollectOCR().collect(text,[N.encode(source())])


def test_manual_translation_bypasses_server(monkeypatch):
    monkeypatch.setattr(N,'api_json',lambda *a,**kw:pytest.fail('API should not be called'))
    override=N.encode({'translations':[{'id':'a','target':'선생님'},{'id':'b','target':'안녕'}]})
    value=N.MangaTranslate().translate(N.encode(source()),'http://unused/v1','','Korean','',4096,300,override)[0]
    assert json.loads(value)['regions'][0]['target']=='선생님'


def test_actual_http_contract_and_unicode_json():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def respond(self,value):
            body=N.encode(value).encode('utf-8');self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            calls.append(self.path);self.respond({'data':[{'id':'fixture-model'}]})
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['model']=='fixture-model'
            assert json.loads(body['messages'][1]['content'])['regions'][0]['source']=='先生'
            calls.append(self.path)
            self.respond({'choices':[{'finish_reason':'stop','message':{'content':N.encode({'translations':[{'id':'b','target':'안녕'},{'id':'a','target':'선생님'}]})}}]})
    server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        value=N.MangaTranslate().translate(N.encode(source()),f'http://127.0.0.1:{server.server_port}/v1','','Korean','',4096,10)[0]
        assert json.loads(value)['regions'][0]['target']=='선생님'
        assert calls==['/v1/models','/v1/chat/completions']
    finally:server.shutdown();server.server_close();thread.join()


def test_detector_dedupes_only_matching_label_and_preserves_scaled_boxes():
    items=[{'label':'text','bbox':[10,10,50,50],'score':0.9},
           {'label':'text','bbox':[11,11,50,50],'score':0.8},
           {'label':'onomatopoeia','bbox':[10,10,50,50],'score':0.7},
           {'label':'bubble','bbox':[0,0,100,100],'score':0.95}]
    raw={'protocol':1,'image_width':100,'image_height':100,'detections':items}
    one=json.loads(N.MangaDetectionRegions().convert(raw)[0])
    assert len(one['regions'])==1 and one['regions'][0]['bbox']==[100.,100.,500.,500.]
    assert len(json.loads(N.MangaDetectionRegions().convert(raw,True)[0])['regions'])==2


class Tensor:
    """Geometry test double only; does not exercise real PyTorch or CUDA."""
    def __init__(self,array):self.array=np.asarray(array);self.device='cpu'
    @property
    def shape(self):return self.array.shape
    @property
    def ndim(self):return self.array.ndim
    @property
    def dtype(self):return self.array.dtype
    def __getitem__(self,key):return Tensor(self.array[key])
    def __setitem__(self,key,value):self.array[key]=value
    def clone(self):return Tensor(self.array.copy())
    def detach(self):return self
    def cpu(self):return self
    def numpy(self):return self.array


def test_crop_geometry_and_edit_mask_use_regions_not_glyphs(monkeypatch):
    monkeypatch.setitem(sys.modules,'torch',types.SimpleNamespace(zeros=lambda shape,**kw:Tensor(np.zeros(shape,dtype=kw['dtype']))))
    page=Tensor(np.ones((1,100,100,3),dtype=np.float32))
    crops,manifest,mask,plans=N.MangaRegionCrops().crop(page,N.encode(source()),4,12)
    assert plans == ['{}','{}']
    assert crops[0].shape==(1,48,48,3)
    assert crops[1].shape==(1,38,88,3)
    assert mask.shape==(1,100,100) and mask.array[0,0,0]==1
    assert mask.array[0,0,99]==0
    assert json.loads(manifest)['regions'][0]['crop_bbox_pixels']==[6,6,54,54]


def test_ocr_retries_only_known_repetition(monkeypatch):
    H=module('adapters.hayai')
    calls=[]
    class Model:
        def ocr(self,image,options,**kw):
            calls.append((options.repetition_penalty,kw['max_patches']))
            if len(calls)==1:raise H.HayaiOutputError('ocr_repetition_loop')
            return {'text':'先生'}
    value=M.MangaOCR().read(Tensor(np.ones((1,20,20,3),dtype=np.float32)),Model())
    assert value==('先生',) and calls==[(1.,1024),(1.1,1024)]


def test_hayai_preprocessing_patch_budget_is_preserved():
    from PIL import Image
    H=module('adapters.hayai')
    for budget in [256,512,1024]:
        patches,mask,shape=H.preprocess(Image.new('RGB',(1084,403)),budget)
        assert patches.shape==(1,budget,768)
        assert mask.sum()<=budget and shape[0,0]*shape[0,1]==mask.sum()


def test_workflow_json_edges_match_api_and_new_nodes_have_no_old_plugin_dependency():
    for path in (ROOT/'workflows').glob('*.json'):
        if path.name.endswith('.api.json'):continue
        workflow=json.loads(path.read_text(encoding='utf-8'))
        api=json.loads(path.with_name(path.stem+'.api.json').read_text(encoding='utf-8'))
        nodes={n['id']:n for n in workflow['nodes']}
        for linkid,src,out,dst,inp,typ in workflow['links']:
            target=nodes[dst]['inputs'][inp]
            assert target['link']==linkid
            assert linkid in nodes[src]['outputs'][out]['links']
            assert api[str(dst)]['inputs'][target['name']]==[str(src),out]
            assert target['type']==typ==nodes[src]['outputs'][out]['type']
        classes={n['class_type'] for n in api.values()}
        assert not any(name.startswith('Koharu') for name in classes)
        assert api['60']['inputs']['mask']==['45',2]
        assert api['61']['class_type']=='SaveImage'
        assert api['9']['inputs']['cfg']==1 and api['7']['inputs']['sampler_name']=='euler'
        assert len(api['8']['inputs']['sigmas'].split(','))==9


def test_review_rejects_path_traversal_and_keeps_existing_file(monkeypatch,tmp_path):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    node=N.MangaSaveReview()
    with pytest.raises(ValueError):node.save(N.encode(source()),'../secrets')
    result=node.save(N.encode(source()),'manga_translator/review')
    assert result['result']==(result['ui']['text'][0],)
    assert json.loads(result['ui']['text'][0])==source()
    assert result['ui']['manga_review_files']==[{'filename':'review_00001.json','subfolder':'manga_translator','type':'output'}]
    node.save(N.encode(source()),'manga_translator/review')
    assert len(list(tmp_path.rglob('*.json')))==2


@pytest.mark.parametrize('value',['http://user:pass@host/v1','file:///etc/passwd','http://host/v1?token=secret'])
def test_endpoint_has_no_embedded_credentials(value):
    with pytest.raises(ValueError):N.endpoint(value)
