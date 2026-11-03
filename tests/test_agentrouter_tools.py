import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

import agentrouter_tools as tools


@pytest.fixture
def lab():
    server = tools.make_lab(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def post(port, path, body):
    req = Request(f'http://127.0.0.1:{port}{path}', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    return urlopen(req, timeout=3)


def test_lab_normal_and_models(lab):
    with urlopen(f'http://127.0.0.1:{lab}/v1/models') as r:
        assert 'lab-normal' in [x['id'] for x in json.load(r)['data']]
    with post(lab, '/v1/messages', {'model': 'lab-normal', 'max_tokens': 20, 'messages': []}) as r:
        assert json.load(r)['content'][0]['text'] == 'lab response'
    with post(lab, '/v1/chat/completions', {'model': 'lab-normal', 'messages': []}) as r:
        assert json.load(r)['choices'][0]['message']['content'] == 'lab response'


def test_lab_stream_and_errors(lab):
    from urllib.error import HTTPError
    with post(lab, '/v1/messages', {'model': 'lab-split', 'messages': [], 'stream': True}) as r:
        b = r.read(); assert b'event: message_stop' in b and b'lab response' in b
    with post(lab, '/v1/messages', {'model': 'lab-billing', 'messages': [], 'stream': True}) as r:
        assert b'event: billing_summary' in r.read()
    with pytest.raises(HTTPError) as exc:
        post(lab, '/v1/messages', {'model': 'lab-503'})
    assert exc.value.code == 503
    with post(lab, '/v1/messages', {'model': 'lab-malformed'}) as r:
        with pytest.raises(ValueError): json.load(r)


def test_lab_slow_and_disconnect(lab):
    start = time.monotonic()
    with post(lab, '/v1/messages', {'model': 'lab-delay'}) as r:
        assert r.status == 200
    assert time.monotonic() - start >= .1
    with post(lab, '/v1/messages', {'model': 'lab-disconnect', 'stream': True}) as r:
        assert b'message_stop' not in r.read()


def test_referee_selection_and_no_protocol_mismatch(lab):
    state = tools.recommend('anthropic', lab, 1, timeout=.2)
    assert state['recommendation'] == 'go'
    assert state['probes']['go']['ready'] is True
    assert tools.recommend('openai', 1, lab, timeout=.2)['recommendation'] is None
    assert tools.recommend('anthropic', 1, lab, timeout=.2)['recommendation'] == 'opencode'


def test_explain_is_redacted_and_does_not_echo_untrusted_keys():
    body = {'model': 'secret-model', 'thinking': {'secret-object': 'token123'}, 'output_config': {'effort': 'high'}, 'messages': [{'content': 'private prompt'}], 'evil-secret-key': 'xxx', 'stream': True}
    headers = {'Authorization': 'Bearer token123', 'x-api-key': 'more-secret', 'X-Proxy-Token': 'local-secret', 'sk-secret-as-key': 'x'}
    result = tools.explain('opencode', '/v1/messages', headers, body, 'unknown')
    text = json.dumps(result)
    for secret in ('token123', 'more-secret', 'local-secret', 'private prompt', 'secret-model', 'evil-secret-key', 'sk-secret-as-key', 'secret-object'):
        assert secret not in text
    assert set(result['removed_fields']) == {'thinking', 'output_config'}
    assert result['credential_behavior'] == 'server-configured key; inbound credentials ignored'
    go = tools.explain('go', '/v1/chat/completions', headers, body, 'disabled')
    assert go['credential_behavior'] == 'inbound Authorization and x-api-key may be forwarded upstream'
    assert go['system_prompt'] == 'disabled'
    assert go['removed_fields'] == []
    assert go['unknown_body_field_count'] == 1


def test_invalid_preview_and_probe_validation():
    with pytest.raises(ValueError): tools.explain('opencode', '/v1/chat/completions', {}, {}, 'disabled')
    for port in (-1, 65536):
        with pytest.raises(ValueError): tools.recommend('anthropic', port, 7187)
    with pytest.raises(ValueError): tools.recommend('anthropic', 8318, 7187, timeout=0)


def test_slow_upload_is_bounded(lab):
    start = time.monotonic()
    result = tools.slow_upload(lab, delay=.05, timeout=.5)
    assert result['connected'] is True
    assert time.monotonic() - start < 2


def test_referee_rejects_circuit_open_and_bad_json():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            raw = b'{"ok":true,"circuitOpen":true}' if self.path == '/health' else b'not-json'
            self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        assert not tools.probe('go', server.server_port, .5)['ready']
        assert not tools.probe('opencode', server.server_port, .5)['ready']
    finally:
        server.shutdown(); server.server_close(); thread.join()
    with pytest.raises(ValueError): tools.recommend('anthropic', 7187, 7187)


def test_preview_cli_does_not_leak_on_bad_json(monkeypatch, capsys):
    import io
    monkeypatch.setattr(tools.sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'{"secret-value-bad-json"'), encoding='utf8'))
    assert tools.main(['explain', '--proxy', 'go']) == 2
    output = capsys.readouterr()
    assert 'secret-value-bad-json' not in output.out + output.err


def test_lab_with_actual_pinned_sidecars(lab):
    """Opt-in: run real sidecars, not stubs, against only the synthetic lab."""
    import os
    from pathlib import Path
    import subprocess
    from urllib.error import URLError
    install = os.environ.get('OWL_TEST_UPSTREAM_INSTALL')
    if not install:
        pytest.skip('set OWL_TEST_UPSTREAM_INSTALL to a separate upstream installation')
    root = Path(__file__).resolve().parents[1]
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]
    go_port, oc_port = free_port(), free_port()
    while oc_port == go_port: oc_port = free_port()
    env = dict(os.environ, OWL_AGENTROUTER_HOME=install, TARGET_PROTOCOL='http', TARGET_HOST='127.0.0.1', TARGET_PORT=str(lab), LISTEN_PORT=str(go_port), AR_API_KEY='', PROXY_AUTH_TOKEN='', MODELS_CSV='lab-normal,lab-split,lab-billing,lab-503', MAX_RETRIES='0', LOG_LEVEL='error')
    go = subprocess.Popen([str(root / 'scripts/run-agentrouter-proxy.sh'), 'go'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    oc = subprocess.Popen([str(Path(install) / 'opencode-venv/bin/python'), str(root / 'agentrouter_tools.py'), 'opencode-lab', '--lab-port', str(lab), '--port', str(oc_port), '--install-dir', install], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for proc, port, path in [(go, go_port, '/health'), (oc, oc_port, '/v1/models')]:
            for _ in range(100):
                if proc.poll() is not None: pytest.fail('sidecar exited before readiness')
                try:
                    with urlopen(f'http://127.0.0.1:{port}{path}', timeout=.2): break
                except (URLError, TimeoutError): time.sleep(.05)
            else: pytest.fail('sidecar readiness timeout')
        with post(go_port, '/v1/chat/completions', {'model':'lab-normal', 'messages': []}) as r:
            assert json.load(r)['choices'][0]['message']['content'] == 'lab response'
        from urllib.error import HTTPError
        with pytest.raises(HTTPError) as error:
            post(go_port, '/v1/chat/completions', {'model':'lab-503', 'messages': []})
        assert error.value.code == 503
        assert tools.slow_upload(go_port, delay=.05, timeout=.2)['connected']
        with post(go_port, '/v1/messages', {'model':'lab-split', 'messages': [], 'max_tokens':10, 'stream': True}) as r:
            data = r.read(); assert b'lab response' in data and b'message_stop' in data
        with post(oc_port, '/v1/messages', {'model':'lab-normal', 'messages': [], 'max_tokens':10}) as r:
            assert json.load(r)['content'][0]['text'] == 'lab response'
        with post(oc_port, '/v1/messages', {'model':'lab-billing', 'messages': [], 'max_tokens':10, 'stream':True}) as r:
            data = r.read(); assert b'message_stop' in data and b'billing_summary' not in data
        with post(oc_port, '/v1/messages', {'model':'lab-split', 'messages': [], 'max_tokens':10, 'stream':True}) as r:
            data = r.read(); assert b'message_stop' in data and b'lab response' in data
        result = tools.recommend('anthropic', go_port, oc_port, timeout=1)
        assert result['recommendation'] == 'go' and all(x['ready'] for x in result['probes'].values())
    finally:
        for proc in (go, oc):
            proc.terminate()
        for proc in (go, oc):
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
