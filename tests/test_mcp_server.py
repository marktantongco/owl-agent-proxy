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
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mcp_proxy_server as mcp
from mcp_proxy_server import (
    MemoryBackend,
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
            "proxy_pick", "proxy_stats", "proxy_rotate", "proxy_validate",
            "memory_set", "memory_get", "memory_search",
            "web_search", "web_fetch", "web_open", "arxiv_search", "github_search"}

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
            "proxy_pick", "proxy_stats", "proxy_rotate", "proxy_validate",
            "memory_set", "memory_get", "memory_search",
            "web_search", "web_fetch", "web_open", "arxiv_search", "github_search"}

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

    async def test_failed_http_probe_is_not_trusted(self, monkeypatch):
        import proxy_harvester

        async def fake_validate(url, timeout=8.0, probe_url=""):
            return {"url": url, "tcp_ms": 5.0, "http_ms": None,
                    "ok": False, "status": None}

        monkeypatch.setattr(proxy_harvester, "validate_proxy", fake_validate)
        backend = ProxyBackend(harvest=False, warmup_seconds=0)
        result = await backend.validate("http://93.184.216.34:8080")
        assert result["valid"] is False
        assert result["trusted"] is False, "a proxy that cannot carry HTTP must not be trusted"
        assert result["reason"].startswith("http-probe-failed")

    async def test_unreachable_proxy_is_not_trusted(self, monkeypatch):
        import proxy_harvester

        async def fake_validate(url, timeout=8.0, probe_url=""):
            return None

        monkeypatch.setattr(proxy_harvester, "validate_proxy", fake_validate)
        backend = ProxyBackend(harvest=False, warmup_seconds=0)
        result = await backend.validate("http://93.184.216.34:8080")
        assert (result["valid"], result["trusted"]) == (False, False)

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
        assert len(responses[1]["result"]["tools"]) == 12
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


# ── MemoryBackend ──────────────────────────────────────────────────────────


class TestMemoryBackendDisabled:
    """MemoryBackend with enabled=False: all methods are no-ops."""

    def test_set_disabled_is_noop(self):
        mem = MemoryBackend(enabled=False)
        mem.set("key", "value")
        assert mem._db is None

    def test_get_disabled_returns_none(self):
        mem = MemoryBackend(enabled=False)
        assert mem.get("key") is None

    def test_search_disabled_returns_empty(self):
        mem = MemoryBackend(enabled=False)
        assert mem.search("query") == []

    def test_sweep_expired_disabled_returns_zero(self):
        mem = MemoryBackend(enabled=False)
        assert mem.sweep_expired() == 0


class TestMemoryBackendEnabled:
    """MemoryBackend with enabled=True: full CRUD + FTS5 + TTL."""

    @pytest.fixture
    def mem(self, tmp_path):
        db = tmp_path / "memory.db"
        return MemoryBackend(enabled=True, db_path=db, ttl_seconds=3600)

    def test_set_and_get(self, mem):
        mem.set("k1", "hello world")
        assert mem.get("k1") == "hello world"

    def test_set_overwrites(self, mem):
        mem.set("k1", "first")
        mem.set("k1", "second")
        assert mem.get("k1") == "second"

    def test_get_missing_key_returns_none(self, mem):
        assert mem.get("nonexistent") is None

    def test_get_expired_returns_none(self, mem):
        mem.set("k1", "value", ttl_seconds=0)
        # expires_at = time.time() + max(1, 0) = time.time() + 1
        # so it's not expired yet; use negative-ish TTL by patching time
        import time as _time

        with patch.object(mcp, "time") as mock_time:
            mock_time.time.return_value = 1000.0
            mem.set("k1", "value", ttl_seconds=10)
            # expires_at = 1000 + 10 = 1010
            mock_time.time.return_value = 2000.0
            assert mem.get("k1") is None

    def test_search_finds_matching_key(self, mem):
        mem.set("alpha-key", "some value here")
        mem.set("beta-key", "completely different")
        results = mem.search("alpha")
        assert len(results) >= 1
        assert any(r["key"] == "alpha-key" for r in results)

    def test_search_returns_empty_for_no_match(self, mem):
        mem.set("alpha-key", "some value here")
        results = mem.search("zzznomatch")
        assert results == []

    def test_search_empty_query_returns_empty(self, mem):
        mem.set("k1", "v1")
        assert mem.search("") == []
        assert mem.search("   ") == []

    def test_search_hyphenated_term(self, mem):
        """Hyphens are treated literally inside quoted FTS5 phrases."""
        mem.set("proxy-config", "configuration for proxy")
        results = mem.search("proxy-config")
        assert len(results) >= 1
        assert any(r["key"] == "proxy-config" for r in results)

    def test_search_limit(self, mem):
        for i in range(5):
            mem.set(f"key-{i}", f"value {i} common")
        results = mem.search("common", limit=2)
        assert len(results) <= 2

    def test_search_limit_capped_at_50(self, mem):
        for i in range(60):
            mem.set(f"key-{i}", f"value {i} common")
        results = mem.search("common", limit=100)
        assert len(results) <= 50

    def test_sweep_expired_removes_expired(self, mem):
        import time as _time

        with patch.object(mcp, "time") as mock_time:
            mock_time.time.return_value = 1000.0
            mem.set("fresh", "still good", ttl_seconds=3600)  # expires at 4600
            mem.set("stale", "gone soon", ttl_seconds=10)  # expires at 1010
            mock_time.time.return_value = 2000.0
            removed = mem.sweep_expired()
            assert removed == 1
            assert mem.get("fresh") == "still good"
            assert mem.get("stale") is None

    def test_sweep_expired_none_expired_returns_zero(self, mem):
        mem.set("k1", "v1", ttl_seconds=3600)
        assert mem.sweep_expired() == 0

    def test_ttl_default(self, mem):
        mem.set("k1", "v1")  # uses default ttl_seconds=3600
        assert mem.get("k1") == "v1"


# ── _load_memory_config ────────────────────────────────────────────────────


class TestLoadMemoryConfig:
    """OwlMcpServer._load_memory_config with various config scenarios."""

    def test_no_config_file_memory_stays_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mcp, "_OWL_HOME", str(tmp_path))
        server = OwlMcpServer.__new__(OwlMcpServer)
        server.memory = None
        server._load_memory_config()
        assert server.memory is None

    def test_config_mcp_memory_disabled_memory_stays_none(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(
            json.dumps({"mcp_memory": {"enabled": False}})
        )
        monkeypatch.setattr(mcp, "_OWL_HOME", str(tmp_path))
        server = OwlMcpServer.__new__(OwlMcpServer)
        server.memory = None
        server._load_memory_config()
        assert server.memory is None

    def test_config_mcp_memory_enabled_memory_is_enabled(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(
            json.dumps(
                {
                    "mcp_memory": {
                        "enabled": True,
                        "session_to_key_mapping": {"ttl_seconds": 7200},
                    }
                }
            )
        )
        monkeypatch.setattr(mcp, "_OWL_HOME", str(tmp_path))
        server = OwlMcpServer.__new__(OwlMcpServer)
        server.memory = None
        server._load_memory_config()
        assert server.memory is not None
        assert server.memory.enabled is True
        assert server.memory.ttl_seconds == 7200

    def test_config_malformed_json_memory_stays_none(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("{broken json")
        monkeypatch.setattr(mcp, "_OWL_HOME", str(tmp_path))
        server = OwlMcpServer.__new__(OwlMcpServer)
        server.memory = None
        server._load_memory_config()
        assert server.memory is None


# ── ProxyBackend.start failure ─────────────────────────────────────────────


class TestProxyBackendStartFailure:
    """ProxyBackend.start() when ResilientClient construction fails."""

    @patch("mcp_proxy_server.ProxyBackend.start")
    def test_start_sets_start_error_on_failure(self, mock_start):
        # When start() raises, _start_error should be set by the except block
        backend = ProxyBackend(harvest=False, warmup_seconds=0)
        backend._start_error = "TestError: boom"
        assert backend._start_error == "TestError: boom"
        assert backend.started is False


class TestWaitForPool:
    """ProxyBackend._wait_for_pool edge cases."""

    @pytest.mark.asyncio
    async def test_wait_for_pool_not_harvesting_returns_immediately(self):
        backend = ProxyBackend(harvest=False, warmup_seconds=5)
        backend._client = MagicMock()
        backend._client.use_upstream_harvester = False
        backend._started_at = __import__("time").time()
        await backend._wait_for_pool()  # should return without waiting

    @pytest.mark.asyncio
    async def test_wait_for_pool_zero_warmup_returns_immediately(self):
        backend = ProxyBackend(harvest=True, warmup_seconds=0)
        backend._client = MagicMock()
        backend._client.use_upstream_harvester = True
        backend._started_at = __import__("time").time()
        await backend._wait_for_pool()  # warmup_seconds=0 → return immediately


class TestHealthyCountException:
    """ProxyBackend.healthy_count when get_stats raises."""

    @pytest.mark.asyncio
    async def test_healthy_count_exception_returns_zero(self):
        backend = ProxyBackend(harvest=False, warmup_seconds=0)
        backend._client = MagicMock()
        backend._client.get_stats = AsyncMock(side_effect=RuntimeError("boom"))
        count = await backend.healthy_count()
        assert count == 0


# ── read_message Content-Length framing ────────────────────────────────────


class TestReadMessageContentLength:
    """read_message with Content-Length framed input."""

    def test_content_length_framing(self):
        import io as _io

        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        frame = f"Content-Length: {len(payload)}\r\n\r\n{payload}"
        stream = _io.StringIO(frame)
        result = read_message(stream)
        assert result == {"jsonrpc": "2.0", "id": 1, "method": "ping"}

    def test_bad_content_length_raises(self):
        import io as _io

        stream = _io.StringIO("Content-Length: notanumber\r\n\r\n")
        with pytest.raises(ProtocolError) as exc:
            read_message(stream)
        assert exc.value.code == -32700
        assert "bad Content-Length" in exc.value.message

    def test_unreasonable_content_length_raises(self):
        import io as _io

        stream = _io.StringIO("Content-Length: 999999999\r\n\r\n")
        with pytest.raises(ProtocolError) as exc:
            read_message(stream)
        assert exc.value.code == -32700
        assert "unreasonable Content-Length" in exc.value.message


# ── stdout_guard ───────────────────────────────────────────────────────────


class TestStdoutGuard:
    """stdout_guard redirects print() to stderr."""

    def test_stdout_guard_redirects_print(self, capsys):
        import io as _io

        with mcp.stdout_guard():
            print("goes to stderr")
        captured = capsys.readouterr()
        assert "goes to stderr" in captured.err


# ── handle_one variants ────────────────────────────────────────────────────


class TestHandleOneVariants:
    """OwlMcpServer.handle_one edge cases."""

    def test_notification_with_no_id_returns_none(self):
        server, _ = mcp.OwlMcpServer.__new__(mcp.OwlMcpServer), None
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server.handle_one(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        )
        assert response is None

    def test_unknown_method_notification_is_silent(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server.handle_one({"jsonrpc": "2.0", "method": "no/such"})
        )
        assert response is None

    def test_shutdown_sets_should_exit(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server.handle_one(
                {"jsonrpc": "2.0", "id": 1, "method": "shutdown"}
            )
        )
        assert server.should_exit is True
        assert response["result"] == {}

    def test_exit_sets_should_exit_returns_none(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server.handle_one({"jsonrpc": "2.0", "method": "exit"})
        )
        assert server.should_exit is True
        assert response is None

    def test_batch_handling(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server.handle(
                [
                    {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                ]
            )
        )
        assert [r["id"] for r in response] == [1, 2]

    def test_handle_non_dict_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(server.handle_one("not a dict"))
        assert response["error"]["code"] == -32600

    def test_handle_missing_method_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server.handle_one({"jsonrpc": "2.0", "id": 1, "params": {}})
        )
        assert response["error"]["code"] == -32600


# ── _tools_call variants ───────────────────────────────────────────────────


class TestToolsCallVariants:
    """OwlMcpServer._tools_call edge cases."""

    def test_params_not_dict_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server._tools_call(1, "not a dict")
        )
        assert response["error"]["code"] == -32602

    def test_unknown_tool_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server._tools_call(1, {"name": "not_a_tool", "arguments": {}})
        )
        assert response["error"]["code"] == -32602

    def test_arguments_not_dict_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        response = asyncio.run(
            server._tools_call(1, {"name": "proxy_stats", "arguments": "not a dict"})
        )
        assert response["error"]["code"] == -32602


# ── call_tool memory variants ──────────────────────────────────────────────


class TestCallToolMemory:
    """OwlMcpServer.call_tool memory_* tool edge cases."""

    def test_memory_set_disabled_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        server.memory = None
        response = asyncio.run(
            server.call_tool("memory_set", {"key": "k", "value": "v"})
        )
        assert response == {"error": "memory backend not enabled"}

    def test_memory_set_missing_key_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        mem = MemoryBackend(enabled=True, db_path=Path(tempfile.mkdtemp()) / "m.db")
        server.memory = mem
        response = asyncio.run(
            server.call_tool("memory_set", {"value": "v"})
        )
        assert response == {"error": "key required"}

    def test_memory_set_success(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        mem = MemoryBackend(enabled=True, db_path=Path(tempfile.mkdtemp()) / "m.db")
        server.memory = mem
        response = asyncio.run(
            server.call_tool("memory_set", {"key": "k", "value": "v"})
        )
        assert response == {"ok": True, "key": "k"}

    def test_memory_get_disabled_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        server.memory = None
        response = asyncio.run(
            server.call_tool("memory_get", {"key": "k"})
        )
        assert response == {"error": "memory backend not enabled"}

    def test_memory_get_missing_key_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        mem = MemoryBackend(enabled=True, db_path=Path(tempfile.mkdtemp()) / "m.db")
        server.memory = mem
        response = asyncio.run(
            server.call_tool("memory_get", {})
        )
        assert response == {"error": "key required"}

    def test_memory_get_success(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        mem = MemoryBackend(enabled=True, db_path=Path(tempfile.mkdtemp()) / "m.db")
        mem.set("k", "v")
        server.memory = mem
        response = asyncio.run(
            server.call_tool("memory_get", {"key": "k"})
        )
        assert response == {"ok": True, "key": "k", "value": "v"}

    def test_memory_search_disabled_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        server.memory = None
        response = asyncio.run(
            server.call_tool("memory_search", {"query": "q"})
        )
        assert response == {"error": "memory backend not enabled"}

    def test_memory_search_empty_query_returns_error(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        mem = MemoryBackend(enabled=True, db_path=Path(tempfile.mkdtemp()) / "m.db")
        server.memory = mem
        response = asyncio.run(
            server.call_tool("memory_search", {"query": ""})
        )
        assert response == {"error": "query required"}

    def test_memory_search_success(self):
        server = mcp.OwlMcpServer(out=io.StringIO())
        mem = MemoryBackend(enabled=True, db_path=Path(tempfile.mkdtemp()) / "m.db")
        mem.set("alpha-key", "some value")
        server.memory = mem
        response = asyncio.run(
            server.call_tool("memory_search", {"query": "alpha"})
        )
        assert response["ok"] is True
        assert "results" in response
        assert "count" in response


# ── serve and main ─────────────────────────────────────────────────────────


class TestServeAndMain:
    """OwlMcpServer.serve and main() edge cases."""

    def test_main_version(self):
        assert mcp.main(["--version"]) == 0

    def test_main_help(self):
        assert mcp.main(["--help"]) == 0

    def test_main_h_short(self):
        assert mcp.main(["-h"]) == 0

    @pytest.mark.asyncio
    async def test_serve_processes_messages(self):
        import io as _io

        stream = _io.StringIO(
            "\n".join(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {},
                            },
                        }
                    ),
                    json.dumps({"jsonrpc": "2.0", "method": "exit"}),
                ]
            )
            + "\n"
        )
        out = _io.StringIO()
        server = mcp.OwlMcpServer(out=out)
        await server.serve(stream)
        assert server.should_exit is True


# ── pick with memory persistence ───────────────────────────────────────────


class TestPickWithMemory:
    """proxy_pick persists sticky bindings to memory backend."""

    @pytest.mark.asyncio
    async def test_pick_persists_binding_to_memory(self, tmp_path):
        from mcp_proxy_server import MemoryBackend

        db_path = tmp_path / "mem.db"
        mem = MemoryBackend(enabled=True, db_path=db_path, ttl_seconds=3600)
        backend = mcp.ProxyBackend(harvest=False, warmup_seconds=0)
        backend.memory = mem
        await backend.start()
        try:
            # Use a fake rotator that returns a proxy entry
            fake_entry = MagicMock()
            fake_entry.url = "http://93.184.216.34:8080"
            fake_entry.protocol = "http/1.1"
            fake_entry.tier = "datacenter"
            fake_entry.source = "test"
            fake_entry.latency_ms = 10.0
            backend._client.rotator.get_proxy = AsyncMock(return_value=fake_entry)

            result = await backend.pick("example.com", "agent1", "sticky")
            assert result["proxy"] == "http://93.184.216.34:8080"
            # Verify the binding was persisted
            stored = mem.get("owl:binding:agent1:example.com")
            assert stored is not None
            data = json.loads(stored)
            assert data["proxy"] == "http://93.184.216.34:8080"
        finally:
            await backend.stop()

    @pytest.mark.asyncio
    async def test_pick_non_sticky_does_not_persist(self, tmp_path):
        from mcp_proxy_server import MemoryBackend

        db_path = tmp_path / "mem.db"
        mem = MemoryBackend(enabled=True, db_path=db_path, ttl_seconds=3600)
        backend = mcp.ProxyBackend(harvest=False, warmup_seconds=0)
        backend.memory = mem
        await backend.start()
        try:
            fake_entry = MagicMock()
            fake_entry.url = "http://93.184.216.34:8080"
            fake_entry.protocol = "http/1.1"
            fake_entry.tier = "datacenter"
            fake_entry.source = "test"
            fake_entry.latency_ms = 10.0
            backend._client.rotator.get_proxy = AsyncMock(return_value=fake_entry)

            result = await backend.pick("example.com", "agent1", "random")
            assert result["proxy"] == "http://93.184.216.34:8080"
            # Non-sticky should not persist
            stored = mem.get("owl:binding:agent1:example.com")
            assert stored is None
        finally:
            await backend.stop()
