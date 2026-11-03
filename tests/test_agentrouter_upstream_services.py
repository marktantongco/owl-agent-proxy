"""Optional smoke tests against installed, unchanged upstream projects (no network)."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

from launcher_test_support import bind_test_listener, write_uvicorn_shim

ROOT = Path(__file__).resolve().parents[1]
INSTALL = os.environ.get('OWL_TEST_UPSTREAM_INSTALL')
pytestmark = pytest.mark.skipif(not INSTALL, reason='set OWL_TEST_UPSTREAM_INSTALL to test installed upstream services')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_go_proxy_auth_headers_and_chat():
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            self.send_response(200); self.end_headers()
        def do_POST(self):
            data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            received.append((self.path, dict(self.headers), json.loads(data)))
            body = b'{"id":"mock","choices":[]}'
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    port = free_port()
    env = dict(os.environ, OWL_AGENTROUTER_HOME=INSTALL, TARGET_PROTOCOL='http', TARGET_HOST='127.0.0.1', TARGET_PORT=str(upstream.server_port), LISTEN_PORT=str(port), PROXY_AUTH_TOKEN='local-test-token', LOG_LEVEL='error')
    proc = subprocess.Popen([str(ROOT / 'scripts/run-agentrouter-proxy.sh'), 'go'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f'http://127.0.0.1:{port}'
        for _ in range(100):
            if proc.poll() is not None: pytest.fail('Go proxy exited before readiness')
            try:
                with urlopen(base + '/health', timeout=.2): break
            except (URLError, TimeoutError): time.sleep(.05)
        else: pytest.fail('Go proxy did not start')
        payload = json.dumps({'model': 'test', 'messages': [{'role': 'user', 'content': 'hello'}]}).encode()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + '/v1/chat/completions', data=payload, headers={'Content-Type': 'application/json'}))
        assert error.value.code == 401
        req = Request(base + '/v1/chat/completions', data=payload, headers={'Content-Type': 'application/json', 'X-Proxy-Token': 'local-test-token', 'Authorization': 'Bearer upstream-test-token'})
        with urlopen(req, timeout=3) as resp:
            assert resp.status == 200
            assert json.load(resp)['id'] == 'mock'
        path, headers, body = received[-1]
        assert path == '/v1/chat/completions'
        assert headers['Authorization'] == 'Bearer upstream-test-token'
        assert 'X-Proxy-Token' not in headers
        assert body['messages'] == [{'role': 'user', 'content': 'hello'}]
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        upstream.shutdown(); upstream.server_close()


def test_upstream_opencode_messages_with_mock_transport():
    source = r'''
import importlib.util, json, os
from fastapi.testclient import TestClient
import anthropic, httpx
spec = importlib.util.spec_from_file_location('upstream_proxy', os.path.join(os.environ['OWL_TEST_UPSTREAM_INSTALL'], 'opencode', 'proxy.py'))
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
seen = []
def handler(request):
    seen.append((str(request.url), json.loads(request.content)))
    if seen[-1][1].get('stream'):
        return httpx.Response(200, headers={'content-type':'text/event-stream'}, content=b'event: billing_summary\ndata: {}\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n')
    return httpx.Response(200, json={'id':'msg_test','type':'message','role':'assistant','model':'test','content':[],'stop_reason':'end_turn','stop_sequence':None,'usage':{'input_tokens':1,'output_tokens':1}})
p._anthropic_client = anthropic.Anthropic(api_key='test', base_url='https://agentrouter.org', max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
with TestClient(p.app) as c:
    body = {'model':'test','max_tokens':10,'messages':[],'thinking':{'type':'adaptive'},'output_config':{'effort':'high'}}
    r = c.post('/messages', json=body); assert r.status_code == 200 and r.json()['id'] == 'msg_test'
    r = c.post('/v1/messages', json=dict(body, stream=True)); assert r.status_code == 200 and 'message_stop' in r.text and 'billing_summary' not in r.text
    assert c.get('/v1/models').status_code == 200
assert all(url == 'https://agentrouter.org/v1/messages' and 'thinking' not in body and 'output_config' not in body for url, body in seen)
'''
    subprocess.run([str(Path(INSTALL) / 'opencode-venv/bin/python'), '-c', source], check=True, env=os.environ, timeout=20)


def test_opencode_launcher_serves_local_models(tmp_path):
    # Exercise the real launcher and its default host/port arguments without
    # binding 7187 or accidentally connecting to someone else's process.
    # Pass the already-listening socket into the child: no check-then-bind race.
    write_uvicorn_shim(tmp_path)
    env = dict(os.environ, OWL_AGENTROUTER_HOME=INSTALL, PYTHONPATH=str(tmp_path),
               AGENTROUTER_API_KEY='test-only-key')
    env.pop('ANTHROPIC_AUTH_TOKEN', None)
    with bind_test_listener() as listener:
        port = listener.getsockname()[1]
        env['OWL_TEST_LISTEN_FD'] = str(listener.fileno())
        proc = subprocess.Popen([str(ROOT / 'scripts/run-agentrouter-proxy.sh'), 'opencode'],
                                env=env, pass_fds=(listener.fileno(),),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    error = proc.stderr.read().decode(errors='replace')
                    pytest.fail(f'OpenCode proxy exited before readiness: {error}')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=.2) as resp:
                        assert resp.status == 200
                        assert resp.headers.get_content_type() == 'application/json'
                        assert 'data' in json.load(resp)
                        break
                except (URLError, TimeoutError):
                    time.sleep(.05)
            else:
                pytest.fail('OpenCode proxy did not start')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.stderr.close()
