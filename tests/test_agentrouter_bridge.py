"""Offline tests for the optional AgentRouter bridge."""
import json
import threading

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("anthropic")
from fastapi.testclient import TestClient
import httpx
import anthropic
import agentrouter_bridge as bridge


@pytest.fixture
def mock_upstream(monkeypatch):
    calls = []
    def handler(request):
        calls.append((request, threading.current_thread().name))
        body = json.loads(request.content)
        if body.get("model") == "unavailable":
            return httpx.Response(503, json={"error": {"type": "api_error", "message": "unavailable"}})
        if body.get("stream"):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
                b'event: billing_summary\ndata: {"cost":1}\n\n'
                b'event: message_stop\ndata: {"type":"message_stop"}\n\n'))
        return httpx.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": "test", "content": [], "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})
    upstream = anthropic.Anthropic(api_key="test", base_url="https://agentrouter.org", max_retries=0,
                                   http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(bridge, "_client_instance", upstream)
    with TestClient(bridge.app) as client:
        yield client, calls


def test_messages_routes_and_sdk_translation(mock_upstream):
    client, calls = mock_upstream
    for path in ("/messages", "/v1/messages"):
        response = client.post(path, json={"model": "test", "max_tokens": 8, "messages": [], "thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}})
        assert response.status_code == 200
        assert response.json()["id"] == "msg_1"
    for request, thread in calls:
        assert str(request.url) == "https://agentrouter.org/v1/messages"
        body = json.loads(request.content)
        assert "thinking" not in body and "output_config" not in body
        assert thread != "MainThread"


def test_stream_filters_and_errors(mock_upstream):
    client, calls = mock_upstream
    r = client.post('/messages', json={"model": "test", "max_tokens": 8, "messages": [], "stream": True})
    assert r.status_code == 200 and "message_stop" in r.text and "billing_summary" not in r.text
    assert json.loads(calls[-1][0].content)["stream"] is True
    for stream in (False, True):
        r = client.post('/messages', json={"model": "unavailable", "max_tokens": 8, "messages": [], "stream": stream})
        assert r.status_code == 503


def test_filter_split_crlf_and_unterminated():
    data = b'event: billing_summary\r\ndata: secret\r\n\r\nevent: ping\r\ndata: ok\r\n\r\nevent: billing_summary\ndata: hidden'
    assert b''.join(bridge.filtered_events([data[i:i+1] for i in range(len(data))])) == b'event: ping\r\ndata: ok\r\n\r\n'


def test_models_and_input(mock_upstream, monkeypatch):
    client, calls = mock_upstream
    monkeypatch.setenv("AGENTROUTER_MODELS", "one, two")
    assert [x['id'] for x in client.get('/v1/models').json()['data']] == ['one', 'two']
    assert client.get('/models').json() == client.get('/v1/models').json()
    assert client.post('/messages', content='not json').status_code == 400
    assert client.post('/messages', json={"stream": "yes"}).status_code == 400
    assert not calls


def test_target_and_key(monkeypatch, tmp_path):
    monkeypatch.setenv('AGENTROUTER_BASE_URL', 'https://example.com/v1')
    with pytest.raises(ValueError):
        bridge.target_url()
    monkeypatch.setenv('AGENTROUTER_BASE_URL', 'https://example.com/')
    assert bridge.target_url() == 'https://example.com'
    key = tmp_path / 'key'
    key.write_text('file-key\n')
    monkeypatch.setattr(bridge, 'KEY_FILE', key)
    monkeypatch.delenv('AGENTROUTER_API_KEY', raising=False)
    assert bridge.api_key() == 'file-key'
    monkeypatch.setenv('AGENTROUTER_API_KEY', 'env-key')
    assert bridge.api_key() == 'env-key'
