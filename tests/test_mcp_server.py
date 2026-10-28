#!/usr/bin/env python3
"""
🦉 OWL-AGENT v7.1 — MCP server tests (offline).

The protocol layer is exercised in-process with a fake backend; the real
subprocess path is exercised with harvesting disabled and an isolated HOME so
nothing touches the user's pool or needs network egress.
"""
import asyncio
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import mcp_proxy_server as mcp
from mcp_proxy_server import (
    OwlMcpServer,
    ProtocolError,
    ProxyBackend,
    TOOLS,
    encode_message,
    read_message,
)

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcp_proxy_server.py"


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.stopped = False

    async def pick(self, domain, agent_id, rotation_mode):
        self.calls.append(("pick", domain, agent_id, rotation_mode))
        return {"proxy": "http://93.184.216.34:8080", "domain": domain,
                "agent_id": agent_id, "rotation_mode": rotation_mode}

    async def stats(self):
        self.calls.append(("stats",))
        return {"proxies_total": 2, "proxies_healthy": 1,
                "session_affinity": {"active": 1}, "source_health": {}}

    async def rotate(self, domain, agent_id):
        self.calls.append(("rotate", domain, agent_id))
        return {"rotated": True, "domain": domain, "agent_id": agent_id}

    async def validate(self, proxy_url):
        self.calls.append(("validate", proxy_url))
        return {"valid": True, "trusted": True, "reason": "ok", "url": proxy_url}

    async def stop(self):
        self.stopped = True


def run_frame(server, request):
    """Feed one decoded request through handle() and return the response."""
    return asyncio.run(server.handle(request))


def serve_lines(server, lines):
    stream = io.StringIO("\n".join(lines) + "\n")
    asyncio.run(server.serve(stream))
    return [json.loads(line) for line in server._out.getvalue().splitlines() if line.strip()]


def make_server(backend=None):
    out = io.StringIO()
    return OwlMcpServer(backend=backend or FakeBackend(), out=out), out


# ── registry + framing ────────────────────────────────────────────────────
class TestRegistry:
    def test_tool_names(self):
        assert {tool["name"] for tool in TOOLS} == {
            "proxy_pick", "proxy_stats", "proxy_rotate", "proxy_validate"}

    def test_every_tool_has_schema(self):
        for tool in TOOLS:
            assert tool["inputSchema"]["type"] == "object"
            assert tool["description"]
            assert isinstance(tool["inputSchema"].get("properties", {}), dict)

    def test_required_fields(self):
        schemas = {tool["name"]: tool["inputSchema"] for tool in TOOLS}
        assert schemas["proxy_pick"]["required"] == ["domain"]
        assert schemas["proxy_rotate"]["required"] == ["domain"]
        assert schemas["proxy_validate"]["required"] == ["proxy_url"]
        assert schemas["proxy_pick"]["properties"]["rotation_mode"]["enum"] == [
            "sticky", "random", "round_robin"]


class TestFraming:
    def test_encode_is_single_line(self):
        frame = encode_message({"jsonrpc": "2.0", "id": 1, "result": {"a": 1}})
        assert frame.endswith("\n")
        assert frame.count("\n") == 1

    def test_read_newline_delimited(self):
        message = read_message(io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\n'))
        assert message["id"] == 7

    def test_read_skips_blank_lines(self):
        stream = io.StringIO('\n\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        assert read_message(stream)["id"] == 1

    def test_read_content_length_framing(self):
        payload = '{"jsonrpc":"2.0","id":3,"method":"ping"}'
        stream = io.StringIO(f"Content-Length: {len(payload)}\r\n\r\n{payload}Content-Length: 0\r\n\r\n")
        assert read_message(stream)["id"] == 3

    def test_read_eof(self):
        assert read_message(io.StringIO("")) is None

    def test_malformed_json_raises_protocol_error(self):
        with pytest.raises(ProtocolError) as excinfo:
            read_message(io.StringIO("{nope}\n"))
        assert excinfo.value.code == -32700


# ── protocol ─────────────────────────────────────────────────────────────
class TestProtocol:
    def test_initialize(self):
        server, out = make_server()
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}}})
        assert response["result"]["serverInfo"] == {"name": "owl-proxy", "version": "7.1.0"}
        assert response["result"]["protocolVersion"] == "2025-06-18"
        assert "tools" in response["result"]["capabilities"]
        assert server.initialized is True

    def test_initialize_negotiates_known_version(self):
        server, _ = make_server()
        response = run_frame(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "2024-11-05"}})
        assert response["result"]["protocolVersion"] == "2024-11-05"

    def test_initialize_falls_back_for_unknown_version(self):
        server, _ = make_server()
        response = run_frame(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "1999-01-01"}})
        assert response["result"]["protocolVersion"] == mcp.DEFAULT_PROTOCOL_VERSION

    def test_notifications_get_no_response(self):
        server, out = make_server()
        frames = serve_lines(server, [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled",
                        "params": {"requestId": 9}}),
        ])
        assert [frame["id"] for frame in frames] == [1]

    def test_tools_list(self):
        server, _ = make_server()
        response = run_frame(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert {tool["name"] for tool in response["result"]["tools"]} == {
            "proxy_pick", "proxy_stats", "proxy_rotate", "proxy_validate"}

    def test_empty_resource_and_prompt_lists(self):
        server, out = make_server()
        frames = serve_lines(server, [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "resources/templates/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "prompts/list"}),
        ])
        by_id = {frame["id"]: frame for frame in frames}
        assert by_id[1]["result"] == {"resources": []}
        assert by_id[2]["result"] == {"resourceTemplates": []}
        assert by_id[3]["result"] == {"prompts": []}

    def test_ping(self):
        server, _ = make_server()
        assert run_frame(server, {"jsonrpc": "2.0", "id": 5, "method": "ping"})["result"] == {}

    def test_unknown_method(self):
        server, _ = make_server()
        response = run_frame(server, {"jsonrpc": "2.0", "id": 6, "method": "no/such"})
        assert response["error"]["code"] == -32601
        assert "no/such" in response["error"]["message"]

    def test_unknown_notification_is_silent(self):
        server, _ = make_server()
        assert run_frame(server, {"jsonrpc": "2.0", "method": "no/such"}) is None

    def test_batch_request(self):
        server, _ = make_server()
        response = asyncio.run(server.handle([
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]))
        assert [frame["id"] for frame in response] == [1, 2]

    def test_parse_error_frame_is_reported(self):
        server, _ = make_server()
        frames = serve_lines(server, ["{broken", json.dumps({"jsonrpc": "2.0", "id": 2,
                                                            "method": "ping"})])
        assert frames[0]["error"]["code"] == -32700
        assert frames[0]["id"] is None
        assert frames[1]["id"] == 2

    def test_invalid_request_object(self):
        server, _ = make_server()
        response = run_frame(server, {"jsonrpc": "2.0", "id": 1})
        assert response["error"]["code"] == -32600

    def test_shutdown_stops_loop_and_backend(self):
        backend = FakeBackend()
        server, out = make_server(backend)
        frames = serve_lines(server, [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "shutdown"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        ])
        assert [frame["id"] for frame in frames] == [1]
        assert backend.stopped is True


# ── tools ────────────────────────────────────────────────────────────────
class TestTools:
    def test_proxy_pick(self):
        backend = FakeBackend()
        server, _ = make_server(backend)
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "proxy_pick",
                       "arguments": {"domain": "example.com", "agent_id": "a1"}}})
        assert response["result"]["isError"] is False
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["proxy"] == "http://93.184.216.34:8080"
        assert backend.calls == [("pick", "example.com", "a1", "sticky")]
        assert response["result"]["structuredContent"]["domain"] == "example.com"

    def test_proxy_pick_requires_domain(self):
        server, _ = make_server()
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "proxy_pick", "arguments": {}}})
        assert response["result"]["isError"] is True
        assert "domain required" in response["result"]["content"][0]["text"]

    def test_proxy_pick_rejects_bad_rotation_mode(self):
        server, _ = make_server()
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "proxy_pick",
                       "arguments": {"domain": "x.com", "rotation_mode": "chaos"}}})
        assert response["result"]["isError"] is True

    def test_proxy_stats(self):
        server, _ = make_server()
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "proxy_stats", "arguments": {}}})
        stats = response["result"]["structuredContent"]
        assert stats["proxies_healthy"] == 1

    def test_proxy_rotate(self):
        backend = FakeBackend()
        server, _ = make_server(backend)
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "proxy_rotate",
                       "arguments": {"domain": "example.com", "agent_id": "a1"}}})
        assert response["result"]["structuredContent"]["rotated"] is True
        assert backend.calls == [("rotate", "example.com", "a1")]

    def test_proxy_validate(self):
        backend = FakeBackend()
        server, _ = make_server(backend)
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "proxy_validate",
                       "arguments": {"proxy_url": "http://1.2.3.4:8080"}}})
        assert response["result"]["structuredContent"]["valid"] is True

    def test_unknown_tool(self):
        server, _ = make_server()
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "not_a_tool", "arguments": {}}})
        assert response["error"]["code"] == -32602

    def test_tool_exception_is_reported_not_raised(self):
        class ExplodingBackend(FakeBackend):
            async def stats(self):
                raise RuntimeError("pool exploded")

        server, _ = make_server(ExplodingBackend())
        response = run_frame(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "proxy_stats", "arguments": {}}})
        assert response["result"]["isError"] is True
        assert "pool exploded" in response["result"]["content"][0]["text"]

    def test_backend_print_cannot_corrupt_stdout(self, capsys):
        class ChattyBackend(FakeBackend):
            async def pick(self, domain, agent_id, rotation_mode):
                print("chatty backend noise")
                return {"proxy": None, "domain": domain}

        server, out = make_server(ChattyBackend())
        frames = serve_lines(server, [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "proxy_pick",
                                   "arguments": {"domain": "x.com"}}})])
        assert frames[0]["id"] == 1
        captured = capsys.readouterr()
        assert "chatty backend noise" in captured.err
        assert "chatty backend noise" not in captured.out
        assert "chatty backend noise" not in out.getvalue()
        json.loads(out.getvalue().strip())  # still valid single JSON line


# ── real backend adapter ─────────────────────────────────────────────────
@pytest.mark.asyncio
class TestProxyBackend:
    async def test_validate_rejects_malformed_url_without_network(self):
        backend = ProxyBackend(harvest=False, warmup_seconds=0)
        result = await backend.validate("not-a-proxy")
        assert result["valid"] is False
        assert result["reason"] == "tcp-or-http-probe-failed"
        assert backend.started is False

    async def test_pick_with_empty_pool_returns_null(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backend = ProxyBackend(harvest=False, warmup_seconds=0)
        result = await backend.pick("example.com", "agent", "sticky")
        assert result["proxy"] is None
        assert "fall back" in result["reason"]
        await backend.stop()

    async def test_stats_shape(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backend = ProxyBackend(harvest=False, warmup_seconds=0)
        stats = await backend.stats()
        assert stats["server"]["name"] == "owl-proxy"
        assert "proxies_total" in stats
        await backend.stop()


# ── subprocess / real stdio ──────────────────────────────────────────────
def _env(tmp_path):
    env = dict(os.environ)
    env.update({"OWL_MCP_HARVEST": "0", "OWL_MCP_WARMUP_SEC": "0",
                "HOME": str(tmp_path), "OWL_AGENT_HOME": str(tmp_path / ".owl-agent")})
    return env


class TestStdio:
    def test_selftest(self):
        result = subprocess.run([sys.executable, str(SERVER), "--selftest"],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert "selftest OK" in result.stdout

    def test_handshake_over_stdio(self, tmp_path):
        frames = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18",
                                   "capabilities": {},
                                   "clientInfo": {"name": "t", "version": "0"}}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]
        result = subprocess.run([sys.executable, str(SERVER)],
                                input="\n".join(frames) + "\n",
                                capture_output=True, text=True, timeout=60,
                                env=_env(tmp_path))
        assert result.returncode == 0, result.stderr
        responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        assert len(responses) == 2                       # notification produced nothing
        assert responses[0]["result"]["serverInfo"]["name"] == "owl-proxy"
        assert len(responses[1]["result"]["tools"]) == 4
        # stdout purity: every line is JSON, nothing else
        for line in result.stdout.splitlines():
            if line.strip():
                json.loads(line)

    def test_tool_call_over_stdio_with_empty_pool(self, tmp_path):
        frames = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "proxy_pick",
                                   "arguments": {"domain": "example.com"}}}),
        ]
        result = subprocess.run([sys.executable, str(SERVER)],
                                input="\n".join(frames) + "\n",
                                capture_output=True, text=True, timeout=90,
                                env=_env(tmp_path))
        assert result.returncode == 0, result.stderr
        responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        picked = json.loads(responses[1]["result"]["content"][0]["text"])
        assert picked["proxy"] is None
        assert responses[1]["result"]["isError"] is False
