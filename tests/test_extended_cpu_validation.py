"""Additional real CPU, local TLS and batch contracts; models remain doubles."""
from contextlib import contextmanager
import gc
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
import subprocess
import threading
import numpy as np
import sys
import pytest
from tests.test_hybrid_lettering import fixture, hybrid
from tests.test_project_runner import P, FakeComfy, make_page, project
from tests.test_http_transport_boundaries import N,L,call,BODY
from tools.simulate_ownership_scenarios import module
K=module('stage_cache')


@pytest.mark.parametrize('direction',['horizontal','vertical_rtl','vertical_ltr'])
@pytest.mark.parametrize('mode',['source','bubble','strict'])
@pytest.mark.parametrize('policy',['source_ratio','readable'])
@pytest.mark.parametrize('font_size',[7,24])
@pytest.mark.parametrize('padding',[0,8])
def test_typography_option_matrix(direction,mode,policy,font_size,padding):
    values=fixture('가나',font_size=font_size)
    kwargs=dict(page_direction=direction,mode=mode,fit_policy=policy,padding=padding,fit_failure_policy='preserve_review')
    if font_size==7 and mode=='strict':
        with pytest.raises(ValueError,match='below readability'):hybrid.build_plan(*values,**kwargs)
        return
    plan,_,_=hybrid.build_plan(*values,**kwargs)
    result,alpha,raw=hybrid.render_plan(plan);report=json.loads(raw)
    assert np.isfinite(result).all() and ((0<=result)&(result<=1)).all()
    assert np.array_equal(result[alpha==0],plan['cleaned'][alpha==0])
    if report['regions']:
        assert len(report['regions'])==1 and report['regions'][0]['render']['text']=='가나'
        assert report['regions'][0]['render']['font_size']>=10
        assert alpha.any()
    else:
        assert report['needs_review'] and report['lettering_review']
        assert not alpha.any()
        for a,b,c,d in plan['protected_boxes_pixels']:
            assert np.array_equal(result[b:d,a:c],values[0][b:d,a:c])
    if font_size==24 or policy=='readable':assert len(report['regions'])==1
    else:
        assert not report['regions']
        assert report['lettering_review'][0]['reason']=='source_below_readability_minimum'


@pytest.fixture(scope='module')
def certificate(tmp_path_factory):
    folder=tmp_path_factory.mktemp('local-tls')
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
        '-keyout',str(folder/'key.pem'),'-out',str(folder/'cert.pem'),'-subj','/CN=localhost',
        '-addext','subjectAltName=DNS:localhost'],check=True,capture_output=True,timeout=20)
    return folder


@contextmanager
def tls_server(folder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):self.do_GET()
        def do_GET(self):
            if self.headers.get('Content-Length'):self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200);self.send_header('Content-Length',str(len(BODY)));self.end_headers();self.wfile.write(BODY)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(folder/'cert.pem',folder/'key.pem')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True);thread.start()
    try:yield server.server_port
    finally:server.shutdown();server.server_close();thread.join(3)


@pytest.mark.parametrize('client',['nodes','lettering','comfy'])
@pytest.mark.parametrize('trust',['trusted','untrusted','wrong_hostname'])
def test_real_tls_certificate_and_hostname_enforcement(certificate,monkeypatch,client,trust):
    original=N.request.urlopen
    context=ssl.create_default_context(cafile=str(certificate/'cert.pem')) if trust!='untrusted' else ssl.create_default_context()
    def opening(req,timeout):return original(req,timeout=timeout,context=context)
    monkeypatch.setattr(N.request,'urlopen',opening);monkeypatch.setattr(L,'urlopen',opening)
    with tls_server(certificate) as port:
        host='127.0.0.1' if trust=='wrong_hostname' else 'localhost'
        url=f'https://{host}:{port}'
        if trust=='trusted':
            result=call(client,url)
            assert result=='번역' if client=='lettering' else result['ok']=='한글'
        else:
            with pytest.raises((RuntimeError,OSError)):call(client,url)


def test_three_hundred_page_mixed_book_resume_and_artifact_integrity(tmp_path,record_property):
    modes=['success','no_text','lettering_error']*100
    for i in range(300):make_page(tmp_path/'input'/f'{i+1}.png',size=(80,60))
    client=FakeComfy(modes);runner=project(tmp_path,client)
    report=runner.run()
    assert report['counts']=={'completed':100,'needs_review':100,'failed':100}
    assert len(client.submissions)==300
    for page in runner.pages:
        state=runner.state(page)
        if state['status'] in ('completed','needs_review'):
            for name,wanted in state['artifacts'].items():
                assert hashlib.sha256((runner._attempt_dir(state)/name).read_bytes()).hexdigest()==wanted
    assert runner.run()['counts']==report['counts'] and len(client.submissions)==300
    record_property('counts',json.dumps(report['counts']));record_property('resume_extra_submissions',0)


def test_repeated_real_lettering_and_cache_cycles_are_bounded(tmp_path,monkeypatch,record_property):
    import torch
    monkeypatch.setattr(K,'root',lambda:tmp_path)
    if not sys.platform.startswith('linux'):pytest.skip('Linux getrusage memory evidence only')
    import resource
    samples=[];key='c'*64
    values=fixture('반복 검증',font_size=24)
    for i in range(1500):
        plan,_,_=hybrid.build_plan(*values,fit_policy='readable')
        result,alpha,raw=hybrid.render_plan(plan)
        assert json.loads(raw)['regions'][0]['render']['text']=='반복 검증'
        value=torch.from_numpy(result)[None]
        K.write(key,'image',value,json.dumps({'iteration':i}))
        found=K.read_entry(key,'image')
        assert found is not None and found[1]['iteration']==i
        assert np.array_equal(found[0].numpy(),value.numpy())
        del plan,result,alpha,raw,value,found
        if i in (99,299,599,899,1199,1499):gc.collect();samples.append(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    # This is a bounded-run peak-growth guard after warmup, not an hours-long soak.
    assert max(samples[1:])-samples[0]<48*1024*1024,samples
    assert len(list(tmp_path.rglob('*tmp')))==0
    assert len(list(tmp_path.rglob('value.bin')))==1
    record_property('peak_rss_bytes_after_warmup',json.dumps(samples))
    record_property('cycles',1500)
