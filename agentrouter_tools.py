"""Opt-in loopback diagnostics for the two AgentRouter sidecars.

No user request is proxied or replayed by this module.
"""
import argparse
import http.client
import importlib.util
import json
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_INPUT = 1 << 20
SCENARIOS = ('lab-normal', 'lab-split', 'lab-billing', 'lab-503', 'lab-malformed', 'lab-delay', 'lab-disconnect')
BODY_FIELDS = frozenset({'model', 'messages', 'system', 'max_tokens', 'stream', 'thinking', 'output_config', 'temperature', 'top_p', 'top_k', 'stop_sequences', 'tools', 'tool_choice', 'metadata'})
HEADER_FIELDS = frozenset({'authorization', 'x-api-key', 'x-proxy-token', 'anthropic-version', 'anthropic-beta', 'content-type', 'user-agent'})
PATHS = ('/messages', '/v1/messages', '/v1/chat/completions')


def check_port(port, allow_zero=False):
    if isinstance(port, bool) or not isinstance(port, int) or not (0 if allow_zero else 1) <= port <= 65535:
        raise ValueError('port must be in the valid TCP range')
    return port


def probe(kind, port, timeout):
    """Read only localhost health metadata; never send an inference request."""
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        conn.request('GET', '/health' if kind == 'go' else '/v1/models')
        response = conn.getresponse()
        if response.status != 200:
            return {'ready': False, 'reason': 'HTTP status not 200'}
        raw = response.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            return {'ready': False, 'reason': 'response too large'}
        data = json.loads(raw)
        good = (isinstance(data, dict) and (data.get('ok') is True and data.get('circuitOpen') is not True if kind == 'go' else
                isinstance(data.get('data'), list)))
        return {'ready': bool(good), 'reason': 'local endpoint responds' if good else 'invalid health response'}
    except (OSError, ValueError, http.client.HTTPException):
        return {'ready': False, 'reason': 'unreachable or invalid response'}
    finally:
        conn.close()


def recommend(protocol, go_port=8318, opencode_port=7187, timeout=1.0):
    if protocol not in ('openai', 'anthropic'):
        raise ValueError('protocol must be openai or anthropic')
    check_port(go_port); check_port(opencode_port)
    if go_port == opencode_port:
        raise ValueError('sidecars must use distinct ports')
    if not .05 <= timeout <= 5:
        raise ValueError('timeout must be between 0.05 and 5 seconds')
    probes = {'go': probe('go', go_port, timeout), 'opencode': probe('opencode', opencode_port, timeout)}
    selected = 'go' if probes['go']['ready'] else ('opencode' if protocol == 'anthropic' and probes['opencode']['ready'] else None)
    return {'protocol': protocol, 'probes': probes, 'recommendation': selected,
            'notice': 'Local endpoint readiness only; upstream, authentication and model availability are not verified. No requests are replayed or client settings changed.'}


def explain(proxy, path, headers, body, prompt_mode='unknown'):
    """Summarize pinned-source behavior without ever outputting input values."""
    if proxy not in ('go', 'opencode') or path not in PATHS or (proxy == 'opencode' and path == '/v1/chat/completions'):
        raise ValueError('unsupported proxy or endpoint')
    if prompt_mode not in ('unknown', 'enabled', 'disabled') or not isinstance(headers, dict) or not isinstance(body, dict):
        raise ValueError('invalid preview input')
    known_headers = sorted({key.lower() for key in headers if isinstance(key, str) and key.lower() in HEADER_FIELDS})
    fields = sorted(key for key in body if isinstance(key, str) and key in BODY_FIELDS)
    removed = sorted(set(fields) & {'thinking', 'output_config'}) if proxy == 'opencode' else []
    return {
        'proxy': proxy, 'path': path, 'known_input_headers': known_headers,
        'unknown_header_count': len(headers) - sum(isinstance(k, str) and k.lower() in HEADER_FIELDS for k in headers),
        'known_input_body_fields': fields, 'unknown_body_field_count': len(body) - len(fields),
        'removed_fields': removed,
        'credential_behavior': ('inbound Authorization and x-api-key may be forwarded upstream' if proxy == 'go'
                                else 'server-configured key; inbound credentials ignored'),
        'header_behavior': ('Go applies profile-dependent spoof headers, content-type and WAF cookie; other client headers are not passed through except Authorization and x-api-key'
                            if proxy == 'go' else 'Anthropic SDK constructs upstream headers; inbound headers are not directly forwarded'),
        'system_prompt': (prompt_mode if proxy == 'go' else 'not injected by this proxy'),
        'system_prompt_note': ('Go injects only on Messages and Chat Completions when enabled; launcher defaults disabled; direct upstream defaults enabled' if proxy == 'go' else 'input system field is passed to the SDK'),
        'stream_note': ('Go may strip OpenAI thinking tags based on configuration' if proxy == 'go' else 'stream is handled separately; billing_summary SSE events are filtered'),
        'notice': 'Static estimate for pinned upstream versions, not a wire capture; no network request made. Values and unknown names are never shown.',
    }


class LabServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LabHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass  # Do not log paths, headers, request bodies, or credentials.

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def send_bytes(self, status, data, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/health':
            self.send_bytes(200, b'{"ok":true}')
        elif self.path in ('/models', '/v1/models'):
            self.send_bytes(200, json.dumps({'object': 'list', 'data': [{'id': m, 'object': 'model'} for m in SCENARIOS]}).encode())
        elif self.path == '/':
            self.send_response(200); self.send_header('Set-Cookie', 'acw_tc=lab-cookie; Path=/'); self.send_header('Content-Length', '0'); self.end_headers()
        else:
            self.send_bytes(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path not in PATHS:
            self.send_bytes(404, b'{"error":"not found"}'); return
        try:
            length = int(self.headers.get('Content-Length', '-1'))
            if length < 0 or length > MAX_INPUT:
                self.close_connection = True
                self.send_bytes(413, b'{"error":"invalid size"}'); return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict): raise ValueError('not object')
        except (ValueError, TimeoutError, OSError):
            self.close_connection = True
            try: self.send_bytes(400, b'{"error":"invalid request"}')
            except OSError: pass
            return
        model = body.get('model', 'lab-normal')
        if model not in SCENARIOS:
            self.send_bytes(400, b'{"error":"select a lab model"}'); return
        if model == 'lab-503':
            self.send_bytes(503, b'{"type":"error","error":{"type":"overloaded_error","message":"lab unavailable"}}'); return
        if model == 'lab-malformed':
            self.send_bytes(200, b'{not-json'); return
        if model == 'lab-delay':
            time.sleep(.15)
        anthropic = self.path != '/v1/chat/completions'
        if body.get('stream') is True:
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Connection', 'close'); self.end_headers()
            self.close_connection = True
            if anthropic:
                events = [
                    ('message_start', {'type':'message_start','message':{'id':'msg_lab','type':'message','role':'assistant','model':model,'content':[],'stop_reason':None,'stop_sequence':None,'usage':{'input_tokens':1,'output_tokens':0}}}),
                    ('content_block_start', {'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}}),
                    ('content_block_delta', {'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'lab response'}}),
                    ('content_block_stop', {'type':'content_block_stop','index':0}),
                    ('message_delta', {'type':'message_delta','delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':1}}),
                    ('message_stop', {'type':'message_stop'}),
                ]
                if model == 'lab-billing': events.insert(2, ('billing_summary', {'type':'billing_summary'}))
                if model == 'lab-disconnect': events = events[:1]
                data = b''.join(f'event: {event}\ndata: {json.dumps(payload)}\n\n'.encode() for event, payload in events)
            else:
                data = b'data: {"id":"chatcmpl-lab","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"lab response"},"finish_reason":null}]}\n\n'
                if model != 'lab-disconnect': data += b'data: [DONE]\n\n'
            try:
                step = 3 if model == 'lab-split' else len(data)
                for i in range(0, len(data), step):
                    self.wfile.write(data[i:i+step]); self.wfile.flush()
                    if model == 'lab-split': time.sleep(.001)
            except (OSError, BrokenPipeError):
                pass
            return
        if anthropic:
            payload = {'id':'msg_lab','type':'message','role':'assistant','model':model,'content':[{'type':'text','text':'lab response'}], 'stop_reason':'end_turn','stop_sequence':None,'usage':{'input_tokens':1,'output_tokens':1}}
        else:
            payload = {'id':'chatcmpl-lab','object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':'lab response'},'finish_reason':'stop'}]}
        self.send_bytes(200, json.dumps(payload).encode())


def make_lab(port=0):
    return LabServer(('127.0.0.1', check_port(port, allow_zero=True)), LabHandler)


def slow_upload(port, delay=.2, timeout=2.0):
    check_port(port)
    if not 0 <= delay <= 3 or not .05 <= timeout <= 5:
        raise ValueError('delay or timeout outside safe range')
    result = {'connected': False, 'status': None}
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as conn:
        result['connected'] = True
        conn.settimeout(timeout)
        conn.sendall(b'POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 32\r\nConnection: close\r\n\r\n{')
        time.sleep(delay)
        try:
            # Read at most a response status line; never dump a response body.
            with conn.makefile('rb') as stream:
                line = stream.readline(1024)
                parts = line.split()
                if len(parts) > 1 and parts[1].isdigit(): result['status'] = int(parts[1])
        except (socket.timeout, OSError):
            pass
    return result


def launch_opencode_lab(lab_port, listen_port, install):
    """Run the original OpenCode module pointing only at a fake localhost upstream."""
    check_port(lab_port); check_port(listen_port)
    for name in ('AGENTROUTER_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'):
        os.environ.pop(name, None)
    path = Path(install) / 'opencode' / 'proxy.py'
    if not path.is_file(): raise ValueError('installed OpenCode proxy not found')
    spec = importlib.util.spec_from_file_location('owl_upstream_opencode_lab', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TARGET = f'http://127.0.0.1:{lab_port}'
    module._api_key = lambda: 'lab-test-key'
    # Never inherit a user's API key or proxy-environment settings into the lab.
    module._HTTP_CLIENT.close()
    import httpx
    module._HTTP_CLIENT = httpx.Client(trust_env=False, timeout=httpx.Timeout(10.0))
    import uvicorn
    uvicorn.run(module.app, host='127.0.0.1', port=listen_port, log_level='warning', access_log=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local AgentRouter diagnostic tools; never replays requests.')
    sub = parser.add_subparsers(dest='command', required=True)
    ref = sub.add_parser('referee'); ref.add_argument('--protocol', choices=('anthropic','openai'), default='anthropic'); ref.add_argument('--go-port', type=int, default=8318); ref.add_argument('--opencode-port', type=int, default=7187); ref.add_argument('--timeout', type=float, default=1)
    lab = sub.add_parser('lab'); lab.add_argument('--port', type=int, default=8199)
    slow = sub.add_parser('slow-upload'); slow.add_argument('--port', type=int, required=True); slow.add_argument('--delay', type=float, default=.2); slow.add_argument('--timeout', type=float, default=2)
    exp = sub.add_parser('explain'); exp.add_argument('--proxy', choices=('go','opencode'), required=True); exp.add_argument('--path', choices=PATHS, default='/v1/messages'); exp.add_argument('--go-prompt', choices=('enabled','disabled','unknown'), default='unknown')
    opc = sub.add_parser('opencode-lab'); opc.add_argument('--lab-port', type=int, default=8199); opc.add_argument('--port', type=int, default=7188); opc.add_argument('--install-dir', default=os.environ.get('OWL_AGENTROUTER_HOME', str(Path.home()/'.owl-agent/agentrouter')))
    args = parser.parse_args(argv)
    try:
        if args.command == 'referee': result = recommend(args.protocol, args.go_port, args.opencode_port, args.timeout)
        elif args.command == 'slow-upload': result = slow_upload(args.port, args.delay, args.timeout)
        elif args.command == 'explain':
            raw = sys.stdin.buffer.read(MAX_INPUT+1)
            if len(raw) > MAX_INPUT: raise ValueError('input exceeds 1 MiB')
            data = json.loads(raw)
            if not isinstance(data, dict): raise ValueError('expected JSON object')
            result = explain(args.proxy, args.path, data.get('headers', {}), data.get('body', {}), args.go_prompt)
        elif args.command == 'opencode-lab':
            launch_opencode_lab(args.lab_port, args.port, args.install_dir); return
        else:
            with make_lab(args.port) as server:
                print(f'Lab listening on http://127.0.0.1:{server.server_address[1]}', flush=True)
                try: server.serve_forever()
                except KeyboardInterrupt: pass
            return
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, ImportError):
        # No untrusted JSON content or credentials are echoed in errors.
        print('Invalid input, local service unavailable, or required dependency missing.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
