"""Real loopback HTTP; fabricated credentials, no remote model or ComfyUI."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import pytest
from tools.simulate_ownership_scenarios import module
from tests.test_project_runner import P
N=module('nodes');L=module('lettering.translate')
BODY=json.dumps({'choices':[{'message':{'content':'번역'},'finish_reason':'stop'}],'ok':'한글'},ensure_ascii=False).encode()


@contextmanager
def server(mode='ok',redirect=None):
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_POST(self):self.do_GET()
        def do_GET(self):
            seen.append((self.path,self.headers.get('Authorization')))
            if self.headers.get('Content-Length'):self.rfile.read(int(self.headers['Content-Length']))
            if mode=='redirect' and self.path!='/final':
                self.send_response(302);self.send_header('Location',redirect or '/final');self.send_header('Content-Length','0');self.end_headers();return
            if isinstance(mode,int):
                self.send_response(mode);self.send_header('Content-Length','0');self.end_headers();return
            self.send_response(200)
            if mode=='chunk':self.send_header('Transfer-Encoding','chunked')
            else:self.send_header('Content-Length',str(len(BODY)+(30 if mode=='length' else 0)))
            self.end_headers()
            if mode=='timeout':time.sleep(.35)
            try:
                self.wfile.write((b'100\r\n'+BODY) if mode=='chunk' else BODY);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):pass
            self.close_connection=True
    host=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=lambda:host.serve_forever(poll_interval=.01),daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{host.server_port}',seen
    finally:host.shutdown();host.server_close();thread.join(2)


def call(client,url,timeout=2):
    if client=='nodes':return N.api_json(url,'/v1/chat/completions','TEST_MANGA_TOKEN',timeout)
    if client=='lettering':return L.translate('原文',url+'/v1',model='test',timeout=timeout,key_environment='TEST_MANGA_TOKEN')
    return P.ComfyClient(url,timeout=timeout)._request('/v1/chat/completions')


@pytest.fixture(autouse=True)
def fake_tokens(monkeypatch):
    monkeypatch.setenv('TEST_MANGA_TOKEN','local-test-only');monkeypatch.setenv('COMFY_API_TOKEN','local-test-only')


@pytest.mark.parametrize('client',['nodes','lettering','comfy'])
def test_real_utf8_response_and_initial_auth(client):
    with server() as (url,seen):result=call(client,url)
    assert result=='번역' if client=='lettering' else result['ok']=='한글'
    assert seen[0][1]=='Bearer local-test-only'


@pytest.mark.parametrize('client',['nodes','lettering','comfy'])
@pytest.mark.parametrize('mode',['length','chunk'])
def test_cut_transfer_is_not_accepted_even_with_valid_json_body(client,mode):
    with server(mode) as (url,_):
        with pytest.raises((RuntimeError,OSError),match='unreachable|unavailable|interrupted'):call(client,url)


@pytest.mark.parametrize('client',['nodes','lettering','comfy'])
@pytest.mark.parametrize('status',[401,429,503])
def test_http_service_errors_remain_classifiable(client,status):
    with server(status) as (url,_):
        with pytest.raises((RuntimeError,OSError,P.Rejected),match=str(status)):call(client,url)


@pytest.mark.parametrize('client',['nodes','lettering','comfy'])
def test_body_timeout_is_bounded(client,monkeypatch):
    if client=='lettering':
        original=L.urlopen;monkeypatch.setattr(L,'urlopen',lambda req,timeout:original(req,timeout=.08))
    with server('timeout') as (url,_):
        with pytest.raises((RuntimeError,OSError)):call(client,url,2 if client=='lettering' else .08)


@pytest.mark.parametrize('client',['nodes','lettering','comfy'])
@pytest.mark.parametrize('foreign',[False,True])
def test_redirect_does_not_forward_authentication(client,foreign):
    with server() as (target,target_seen):
        with server('redirect',target+'/final' if foreign else None) as (url,seen):call(client,url)
        assert seen[0][1]=='Bearer local-test-only'
        following=target_seen if foreign else seen[1:]
        assert following and all(auth is None for _,auth in following)
