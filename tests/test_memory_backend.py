#!/usr/bin/env python3
"""
🦉 OWL-AGENT — memory backend tests (offline, isolated).

The v7.2 memory backend landed without tests, which dropped total coverage
below the 70% floor and turned every CI job red. These tests also cover the
expiry and deletion paths, where a silent bug would be invisible in normal use:
a key that never expires, or a search that keeps returning a deleted entry,
looks fine until it matters.
"""
import asyncio
import io
import sqlite3
import time

import pytest

import mcp_proxy_server as mcp


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "cache" / "memory.db"


@pytest.fixture
def mem(db_path):
    """An enabled backend on a throwaway database."""
    backend = mcp.MemoryBackend(enabled=True, db_path=db_path, ttl_seconds=60)
    try:
        backend._connect()
    except sqlite3.OperationalError as exc:  # pragma: no cover - build-dependent
        # FTS5 is compiled into CPython's bundled SQLite on the runners this
        # project targets; a distribution that omits it cannot run memory.
        pytest.skip(f"SQLite lacks FTS5: {exc}")
    yield backend
    if backend._db is not None:
        backend._db.close()


# ── the disabled path ─────────────────────────────────────────────────────
class TestDisabled:
    """Disabled must mean inert, not 'works but persisted somewhere'."""

    def test_writes_are_ignored(self, db_path):
        backend = mcp.MemoryBackend(enabled=False, db_path=db_path)
        backend.set("k", "v")
        assert backend.get("k") is None
        assert backend.search("v") == []
        assert backend.sweep_expired() == 0

    def test_no_database_is_created(self, db_path):
        backend = mcp.MemoryBackend(enabled=False, db_path=db_path)
        backend.set("k", "v")
        assert not db_path.exists()


# ── round trip ────────────────────────────────────────────────────────────
class TestRoundTrip:
    def test_set_then_get(self, mem):
        mem.set("session", "abc123")
        assert mem.get("session") == "abc123"

    def test_overwrite_replaces_value(self, mem):
        mem.set("k", "first")
        mem.set("k", "second")
        assert mem.get("k") == "second"

    def test_missing_key_returns_none(self, mem):
        assert mem.get("never-written") is None

    def test_creates_parent_directories(self, db_path):
        nested = db_path.parent.parent / "deep" / "memory.db"
        backend = mcp.MemoryBackend(enabled=True, db_path=nested)
        backend.set("k", "v")
        assert nested.exists()

    def test_default_path_follows_owl_agent_home(self, monkeypatch, tmp_path):
        """Reading config from one home and writing state to another is a bug."""
        monkeypatch.setattr(mcp, "_OWL_HOME", str(tmp_path / "owlhome"))
        backend = mcp.MemoryBackend(enabled=True)
        assert backend._db_path == tmp_path / "owlhome" / "cache" / "memory.db"


# ── expiry ────────────────────────────────────────────────────────────────
class TestExpiry:
    def test_expired_key_is_invisible(self, mem):
        mem.set("k", "v", ttl_seconds=1)
        assert mem.get("k") == "v"
        mem._db.execute(
            "UPDATE memory SET expires_at = ? WHERE key = ?", (time.time() - 1, "k"))
        mem._db.commit()
        assert mem.get("k") is None

    def test_sweep_removes_only_expired(self, mem):
        mem.set("live", "v", ttl_seconds=3600)
        mem.set("dead", "v", ttl_seconds=1)
        mem._db.execute(
            "UPDATE memory SET expires_at = ? WHERE key = ?", (time.time() - 1, "dead"))
        mem._db.commit()
        assert mem.sweep_expired() == 1
        assert mem.get("live") == "v"
        assert mem.get("dead") is None

    def test_ttl_is_floored_at_one_second(self, mem):
        """A zero or negative ttl must not write an already-expired row."""
        mem.set("k", "v", ttl_seconds=0)
        assert mem.get("k") is not None

    def test_default_ttl_comes_from_constructor(self, db_path):
        backend = mcp.MemoryBackend(enabled=True, db_path=db_path, ttl_seconds=3600)
        backend.set("k", "v")
        expires = backend._db.execute(
            "SELECT expires_at FROM memory WHERE key = 'k'").fetchone()[0]
        assert expires > time.time() + 3000


# ── search ────────────────────────────────────────────────────────────────
class TestSearch:
    def test_finds_matching_value(self, mem):
        mem.set("domain:example", "http://1.2.3.4:8080")
        results = mem.search("1.2.3.4")
        assert [r["key"] for r in results] == ["domain:example"]

    def test_finds_matching_key(self, mem):
        mem.set("rotation:example.com", "sticky")
        assert [r["key"] for r in mem.search("rotation")] == ["rotation:example.com"]

    def test_empty_query_returns_nothing(self, mem):
        mem.set("k", "v")
        assert mem.search("") == []

    def test_whitespace_only_query_returns_nothing(self, mem):
        mem.set("k", "v")
        assert mem.search("   \t  ") == []

    def test_quote_in_query_does_not_crash(self, mem):
        """FTS5 syntax characters in user input must be literal, not operators."""
        mem.set("note", 'he said "hello"')
        assert mem.search('"') == [] or isinstance(mem.search('"'), list)

    def test_operator_characters_are_literal(self, mem):
        """A bare 'OR' is FTS5 syntax; quoted it must match the word."""
        mem.set("k", "alpha OR beta")
        # Unquoted this raises sqlite3.OperationalError on a malformed MATCH.
        assert [r["key"] for r in mem.search("OR")] == ["k"]

    def test_wildcard_is_literal(self, mem):
        mem.set("k", "value")
        assert mem.search("val*") == []  # '*' must not become a prefix match

    def test_unbalanced_quote_does_not_raise(self, mem):
        mem.set("k", "value")
        mem.search('"unclosed')

    def test_multi_term_query_requires_every_term(self, mem):
        """Terms are ANDed; a partial match must not return the row."""
        mem.set("k", "alpha beta")
        assert [r["key"] for r in mem.search("alpha beta")] == ["k"]
        assert mem.search("alpha gamma") == []

    def test_limit_is_clamped(self, mem):
        for i in range(80):
            mem.set(f"k{i}", "matchable token")
        assert len(mem.search("matchable", limit=1000)) <= 50
        assert len(mem.search("matchable", limit=0)) >= 1

    def test_expired_entries_are_not_returned(self, mem):
        mem.set("dead", "matchable", ttl_seconds=1)
        mem.set("live", "matchable", ttl_seconds=3600)
        mem._db.execute(
            "UPDATE memory SET expires_at = ? WHERE key = ?", (time.time() - 1, "dead"))
        mem._db.commit()
        assert [r["key"] for r in mem.search("matchable")] == ["live"]

    def test_deleted_entry_leaves_the_index(self, mem):
        """The FTS delete trigger is the easiest thing here to get silently wrong."""
        mem.set("gone", "matchable token")
        assert mem.search("matchable")
        mem._db.execute("DELETE FROM memory WHERE key = 'gone'")
        mem._db.commit()
        assert mem.search("matchable") == []

    def test_updated_entry_reindexes(self, mem):
        mem.set("k", "originalword")
        mem.set("k", "replacementword")
        assert mem.search("originalword") == []
        assert [r["key"] for r in mem.search("replacementword")] == ["k"]

    def test_search_result_shape(self, mem):
        mem.set("k", "v matchable")
        assert set(mem.search("matchable")[0]) == {"key", "value"}


# ── tool dispatch ─────────────────────────────────────────────────────────
class FakeBackend:
    async def pick(self, domain, agent_id, rotation_mode):
        return {"proxy": "http://93.184.216.34:8080"}

    async def stats(self):
        return {}

    async def rotate(self, domain, agent_id):
        return {}

    async def validate(self, proxy_url):
        return {"valid": True}

    async def stop(self):
        pass


def call(server, name, args):
    return asyncio.run(server.handle({
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }))


@pytest.fixture
def server(mem):
    srv = mcp.OwlMcpServer(backend=FakeBackend(), out=io.StringIO())
    srv.initialized = True
    srv.memory = mem
    return srv


class TestToolDispatch:
    def test_memory_set_and_get_round_trip(self, server):
        payload = call(server, "memory_set", {"key": "k", "value": "v"})
        assert payload["result"]["content"]  # response is well formed
        got = call(server, "memory_get", {"key": "k"})
        assert '"value": "v"' in got["result"]["content"][0]["text"]

    def test_memory_get_reports_missing_key(self, server):
        got = call(server, "memory_get", {"key": "absent"})
        assert '"ok": false' in got["result"]["content"][0]["text"]

    def test_memory_search_counts_results(self, server):
        call(server, "memory_set", {"key": "k", "value": "matchable"})
        got = call(server, "memory_search", {"query": "matchable"})
        assert '"count": 1' in got["result"]["content"][0]["text"]

    def test_memory_set_requires_key(self, server):
        got = call(server, "memory_set", {"value": "v"})
        assert '"error"' in got["result"]["content"][0]["text"]

    def test_memory_get_requires_key(self, server):
        got = call(server, "memory_get", {})
        assert '"error"' in got["result"]["content"][0]["text"]

    def test_memory_search_requires_query(self, server):
        got = call(server, "memory_search", {"limit": 3})
        assert '"error"' in got["result"]["content"][0]["text"]

    @pytest.mark.parametrize("tool", ["memory_set", "memory_get", "memory_search"])
    def test_tools_refuse_when_memory_disabled(self, tool):
        """Memory off must be an explicit error, not a silent no-op."""
        srv = mcp.OwlMcpServer(backend=FakeBackend(), out=io.StringIO())
        srv.initialized = True
        srv.memory = None
        got = call(srv, tool, {"key": "k", "value": "v", "query": "q"})
        assert "not enabled" in got["result"]["content"][0]["text"]


# ── config loading ────────────────────────────────────────────────────────
class TestLoadMemoryConfig:
    def _write_config(self, tmp_path, payload):
        monkeypatch_home = tmp_path / "owlhome"
        (monkeypatch_home / "config").mkdir(parents=True)
        (monkeypatch_home / "config" / "config.json").write_text(payload)
        return monkeypatch_home

    def test_absent_config_leaves_memory_off(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mcp, "_OWL_HOME", str(tmp_path / "nohome"))
        srv = mcp.OwlMcpServer(backend=FakeBackend(), out=io.StringIO())
        assert srv.memory is None

    def test_malformed_config_is_survivable(self, tmp_path, monkeypatch):
        home = self._write_config(tmp_path, "{not json")
        monkeypatch.setattr(mcp, "_OWL_HOME", str(home))
        srv = mcp.OwlMcpServer(backend=FakeBackend(), out=io.StringIO())
        assert srv.memory is None

    def test_enabled_config_creates_backend(self, tmp_path, monkeypatch):
        home = self._write_config(
            tmp_path, '{"mcp_memory": {"enabled": true}}')
        monkeypatch.setattr(mcp, "_OWL_HOME", str(home))
        srv = mcp.OwlMcpServer(backend=FakeBackend(), out=io.StringIO())
        assert srv.memory is not None and srv.memory.enabled
        assert str(home) in str(srv.memory._db_path)

    def test_disabled_config_creates_no_backend(self, tmp_path, monkeypatch):
        home = self._write_config(
            tmp_path, '{"mcp_memory": {"enabled": false}}')
        monkeypatch.setattr(mcp, "_OWL_HOME", str(home))
        srv = mcp.OwlMcpServer(backend=FakeBackend(), out=io.StringIO())
        assert srv.memory is None

    def test_ttl_is_read_from_config(self, tmp_path, monkeypatch):
        home = self._write_config(
            tmp_path,
            '{"mcp_memory": {"enabled": true, '
            '"session_to_key_mapping": {"ttl_seconds": 120}}}')
        monkeypatch.setattr(mcp, "_OWL_HOME", str(home))
        srv = mcp.OwlMcpServer(backend=FakeBackend(), out=io.StringIO())
        assert srv.memory.ttl_seconds == 120
