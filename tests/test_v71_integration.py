#!/usr/bin/env python3
"""
🦉 OWL-AGENT v7.1 — pool / client integration tests (offline).

Covers the parts of the v7.1 upgrade that live inside proxy_defense.py:
sticky selection, rotation modes, harvested-entry quarantine, honeypot
rejection, tier trimming, cache persistence and config merge.
"""
import asyncio
import json
import time
from pathlib import Path

import pytest

import proxy_harvester
import proxy_defense as pd
from proxy_defense import (
    CachedResponse,
    ProxyEntry,
    ProxyRotator,
    RequestDeduplicator,
    ResilientClient,
)


def entry(url: str, *, tier: int = 1, latency: float = 10.0, healthy: bool = True,
          validated: bool = True, **kwargs) -> ProxyEntry:
    return ProxyEntry(url=url, proxy_type="dc", protocol="http", source="test",
                      tier=tier, latency_ms=latency, healthy=healthy,
                      validated=validated, **kwargs)


@pytest.fixture
def config_file(tmp_path):
    def make(**overrides):
        config = {
            "use_upstream_harvester": False,
            "session_ttl": 900,
            "harvest_interval": 600,
            "honeypot_check": True,
            "max_proxies": 50,
            "validator_concurrency": 2,
            "validator_timeout": 1,
            "persist_proxy_cache": False,
            "cache_ttl": 300,
            "rate_limit": 1.0,
            "max_retries": 1,
        }
        config.update(overrides)
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))
        return path
    return make


class FakeHarvester:
    """Stands in for UpstreamHarvester.harvest()."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = 0

    async def harvest(self, max_per_source=300):
        self.calls += 1
        return self.batches.pop(0) if self.batches else []

    async def __aexit__(self, *exc):
        return None


# ── entry serialisation ───────────────────────────────────────────────────
class TestProxyEntry:
    def test_roundtrip_preserves_v71_fields(self):
        original = entry("http://93.184.216.34:8080", tier=4, latency=42.5,
                         healthy=False, validated=False, fail_count=2)
        restored = ProxyEntry.from_dict(json.loads(json.dumps(original.to_dict())))
        assert restored.url == original.url
        assert restored.tier == 4
        assert restored.validated is False
        assert restored.healthy is False
        assert restored.fail_count == 2
        assert restored.latency_ms == pytest.approx(42.5)
        assert restored.added_at == pytest.approx(original.added_at)

    def test_from_dict_defaults(self):
        restored = ProxyEntry.from_dict({"url": "http://1.1.1.1:80"})
        assert restored.protocol == "http"
        assert restored.tier == 4
        assert restored.validated is False


# ── selection ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestStickySelection:
    async def test_sticky_is_stable_per_agent_and_domain(self):
        rotator = ProxyRotator([entry("http://p1:80", latency=5),
                                entry("http://p2:80", latency=50)])
        first = await rotator.get_proxy(domain="example.com", agent_id="a1")
        for _ in range(5):
            again = await rotator.get_proxy(domain="example.com", agent_id="a1")
            assert again.url == first.url

    async def test_bindings_are_isolated(self):
        rotator = ProxyRotator([entry("http://p1:80", latency=5),
                                entry("http://p2:80", latency=50)])
        a = await rotator.get_proxy(domain="example.com", agent_id="a1")
        await rotator.get_proxy(domain="example.com", agent_id="a2")
        stats = await rotator.session_stats()
        assert stats["active"] == 2
        assert stats["by_domain"] == {"example.com": 2}
        assert await rotator.get_proxy(domain="other.com", agent_id="a1") is not None
        assert (await rotator.session_stats())["active"] == 3
        # first binding unchanged by the unrelated domain
        assert await rotator.get_proxy(domain="example.com", agent_id="a1") == a

    async def test_dead_binding_is_replaced(self):
        p1 = entry("http://p1:80", latency=5)
        p2 = entry("http://p2:80", latency=50)
        rotator = ProxyRotator([p1, p2])
        bound = await rotator.get_proxy(domain="example.com", agent_id="a1")
        bound.healthy = False
        replacement = await rotator.get_proxy(domain="example.com", agent_id="a1")
        assert replacement is not None and replacement.url != bound.url
        assert (await rotator.get_proxy(domain="example.com", agent_id="a1")).url == replacement.url

    async def test_rotate_clears_binding(self):
        rotator = ProxyRotator([entry("http://p1:80", latency=5),
                                entry("http://p2:80", latency=50)])
        await rotator.get_proxy(domain="example.com", agent_id="a1")
        assert (await rotator.session_stats())["active"] == 1
        assert await rotator.rotate(agent_id="a1", domain="example.com") is True
        assert (await rotator.session_stats())["active"] == 0
        assert await rotator.rotate(agent_id="a1", domain="example.com") is False

    async def test_round_robin_and_random_modes(self):
        rotator = ProxyRotator([entry("http://p1:80"), entry("http://p2:80")])
        picked = {(await rotator.get_proxy(domain="d.com", agent_id="a",
                                           rotation_mode="round_robin")).url
                  for _ in range(4)}
        assert picked == {"http://p1:80", "http://p2:80"}

        random_pick = await rotator.get_proxy(domain="d.com", agent_id="a",
                                              rotation_mode="random")
        assert random_pick.url in {"http://p1:80", "http://p2:80"}

    async def test_round_robin_does_not_bind(self):
        rotator = ProxyRotator([entry("http://p1:80"), entry("http://p2:80")])
        await rotator.get_proxy(domain="d.com", rotation_mode="round_robin")
        assert (await rotator.session_stats())["active"] == 0

    async def test_invalid_mode_falls_back_to_sticky(self):
        rotator = ProxyRotator([entry("http://p1:80")])
        first = await rotator.get_proxy(domain="d.com", rotation_mode="bogus")
        second = await rotator.get_proxy(domain="d.com", rotation_mode="bogus")
        assert first.url == second.url
        assert (await rotator.session_stats())["active"] == 1

    async def test_legacy_zero_argument_call_still_rotates(self):
        rotator = ProxyRotator([entry("http://p1:80"), entry("http://p2:80")])
        urls = {(await rotator.get_proxy()).url for _ in range(2)}
        assert urls == {"http://p1:80", "http://p2:80"}

    async def test_empty_pool_returns_none(self):
        rotator = ProxyRotator([])
        assert await rotator.get_proxy(domain="example.com") is None
        stats = await rotator.session_stats()
        assert stats["active"] == 0
        assert stats["ttl_seconds"] == rotator.session_ttl
        assert stats["by_domain"] == {}


# ── harvesting into the pool ──────────────────────────────────────────────
@pytest.mark.asyncio
class TestHarvestIntegration:
    async def test_harvested_entries_are_quarantined(self):
        rotator = ProxyRotator([entry("http://managed:80")],
                               max_proxies=10, max_per_source=10)
        rotator._harvester = FakeHarvester([[
            {"url": "http://93.184.216.34:8080", "protocol": "http",
             "source": "maxfeix_txt", "latency_ms": 120.0},
            {"url": "http://8.8.8.8:1080", "protocol": "socks5",
             "source": "monosans_txt"},
        ]])
        added = await rotator.harvest_once()
        assert added == 2
        harvested = [p for p in rotator.proxies if p.tier == 4]
        assert len(harvested) == 2
        assert all(p.healthy is False and p.validated is False for p in harvested)
        assert rotator._validation_queue.qsize() == 2

        picked = await rotator.get_proxy(domain="example.com")
        assert picked.url == "http://managed:80"       # unvalidated never selected

    async def test_second_harvest_does_not_duplicate(self):
        rotator = ProxyRotator([], max_proxies=10)
        item = {"url": "http://93.184.216.34:8080", "protocol": "http",
                "source": "maxfeix_txt"}
        rotator._harvester = FakeHarvester([[dict(item)], [dict(item)]])
        assert await rotator.harvest_once() == 1
        assert await rotator.harvest_once() == 0
        assert len(rotator.proxies) == 1

    async def test_trim_evicts_unvalidated_and_keeps_managed(self):
        rotator = ProxyRotator([entry("http://managed:80", tier=1)],
                               max_proxies=3, max_per_source=10)
        rotator._harvester = FakeHarvester([[
            {"url": f"http://93.184.216.{i}:8080", "protocol": "http"} for i in range(1, 7)
        ]])
        await rotator.harvest_once()
        assert len(rotator.proxies) == 3
        assert any(p.url == "http://managed:80" for p in rotator.proxies)

    async def test_validation_promotes_good_proxy(self, monkeypatch):
        rotator = ProxyRotator([entry("http://p1:80", healthy=False, validated=False, tier=4)],
                               validator_timeout=0.5)
        rotator._sem = asyncio.Semaphore(1)

        async def fake_validate(url, timeout=8.0, probe_url=""):
            return {"url": url, "tcp_ms": 20.0, "http_ms": 30.0, "ok": True, "status": 200}

        monkeypatch.setattr(proxy_harvester, "validate_proxy", fake_validate)
        await rotator._validate_entry("http://p1:80")
        proxy = rotator.proxies[0]
        assert proxy.healthy is True
        assert proxy.validated is True

    async def test_validation_rejects_dead_proxy(self, monkeypatch):
        rotator = ProxyRotator([entry("http://p1:80", healthy=False, validated=False, tier=4)])

        async def fake_validate(url, timeout=8.0, probe_url=""):
            return None

        monkeypatch.setattr(proxy_harvester, "validate_proxy", fake_validate)
        rotator._sem = asyncio.Semaphore(1)
        await rotator._validate_entry("http://p1:80")
        assert rotator.proxies[0].healthy is False
        assert rotator.proxies[0].fail_count == 1

    async def test_honeypot_tampering_evicts_proxy(self, monkeypatch):
        rotator = ProxyRotator([entry("http://p1:80", healthy=False, validated=False, tier=4)])
        rotator._sem = asyncio.Semaphore(1)

        class TamperingDetector:
            async def check(self, url):
                return False, "content-mismatch-scripts:2"

        rotator._honeypot = TamperingDetector()

        async def fake_validate(url, timeout=8.0, probe_url=""):
            return {"ok": True, "tcp_ms": 5.0, "http_ms": 5.0, "status": 200}

        monkeypatch.setattr(proxy_harvester, "validate_proxy", fake_validate)
        await rotator._validate_entry("http://p1:80")
        assert rotator.proxies == []
        assert rotator.upstream_stats()["honeypot_rejections"] == 1

    async def test_honeypot_connectivity_noise_does_not_evict(self, monkeypatch):
        rotator = ProxyRotator([entry("http://p1:80", healthy=False, validated=False, tier=4)])
        rotator._sem = asyncio.Semaphore(1)

        class FlakyDetector:
            async def check(self, url):
                return False, "error:ConnectTimeout"

        rotator._honeypot = FlakyDetector()

        async def fake_validate(url, timeout=8.0, probe_url=""):
            return {"ok": True, "tcp_ms": 5.0, "http_ms": 5.0, "status": 200}

        monkeypatch.setattr(proxy_harvester, "validate_proxy", fake_validate)
        await rotator._validate_entry("http://p1:80")
        assert len(rotator.proxies) == 1
        assert rotator.proxies[0].healthy is True

    async def test_upstream_stats_shape(self):
        rotator = ProxyRotator([entry("http://p1:80")])
        stats = rotator.upstream_stats()
        for key in ("enabled", "running", "harvested_total", "honeypot_rejections",
                    "unvalidated", "pending_validation", "sources"):
            assert key in stats
        assert rotator.source_health() == {}


# ── persistence ───────────────────────────────────────────────────────────
class TestCachePersistence:
    def test_save_and_load(self, tmp_path):
        cache_file = tmp_path / "proxy_cache.json"
        rotator = ProxyRotator([entry("http://p1:80", validated=True)], cache_file=cache_file)
        rotator.save_cache()
        assert cache_file.exists()

        restored = ProxyRotator([], cache_file=cache_file)
        assert restored.load_cache() == 1
        assert restored.proxies[0].url == "http://p1:80"

    def test_load_ignores_duplicates_and_bad_rows(self, tmp_path):
        cache_file = tmp_path / "proxy_cache.json"
        cache_file.write_text(json.dumps({"proxies": [
            {"url": "http://p1:80"},
            {"url": "http://p1:80"},
            {"no_url": True},
        ]}))
        rotator = ProxyRotator([entry("http://p1:80")], cache_file=cache_file)
        assert rotator.load_cache() == 0
        assert len(rotator.proxies) == 1

    def test_missing_cache_is_not_an_error(self, tmp_path):
        rotator = ProxyRotator([], cache_file=tmp_path / "nope.json")
        assert rotator.load_cache() == 0


# ── client wiring ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestResilientClientV71:
    async def test_config_merge(self, config_file):
        path = config_file(session_ttl=42, harvest_interval=99,
                           use_upstream_harvester=True, max_proxies=7)
        client = ResilientClient(config_path=path)
        assert client.session_ttl == 42
        assert client.harvest_interval == 99
        assert client.use_upstream_harvester is True
        assert client.rotator.session_ttl == 42
        assert client.rotator.max_proxies == 7

    async def test_explicit_args_override_config(self, config_file):
        client = ResilientClient(config_path=config_file(session_ttl=42),
                                 session_ttl=10, use_upstream_harvester=False)
        assert client.session_ttl == 10
        assert client.rotator.session_ttl == 10

    async def test_legacy_keys_are_honoured(self, config_file):
        client = ResilientClient(config_path=config_file(
            cache_ttl=120, rate_limit=3.5, max_retries=5))
        assert client.cache_ttl == 120
        assert client.cache.ttl == 120
        assert client.rate_limit == 3.5
        assert client.max_retries == 5

    async def test_missing_config_is_tolerated(self, tmp_path):
        client = ResilientClient(config_path=tmp_path / "absent.json")
        assert client.use_upstream_harvester is False
        assert client.session_ttl == pytest.approx(900.0)

    async def test_malformed_config_is_tolerated(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        client = ResilientClient(config_path=path)
        assert client.config == {}

    async def test_stats_expose_v71_keys(self, config_file):
        client = ResilientClient(auto_load_proxies=False,
                                 config_path=config_file())
        async with client:
            stats = await client.get_stats()
        assert stats["version"] == "7.1"
        assert stats["source_health"] == {}
        assert stats["session_affinity"]["active"] == 0
        assert stats["upstream_harvester"]["enabled"] is False
        assert "protocols_available" in stats

    async def test_request_passes_agent_identity_to_pool(self, config_file, monkeypatch):
        client = ResilientClient(auto_load_proxies=False, config_path=config_file())
        captured = {}

        async def fake_get_proxy(domain=None, agent_id="default", rotation_mode="sticky"):
            captured.update(domain=domain, agent_id=agent_id,
                            rotation_mode=rotation_mode)
            return None

        async def fake_http1(method, url, params, headers, proxy_url, **kwargs):
            return CachedResponse(status=200, content=b"ok", headers={},
                                  timestamp=0, ttl=0, protocol="http/1.1")

        monkeypatch.setattr(client.rotator, "get_proxy", fake_get_proxy)
        monkeypatch.setattr(client, "_request_http1", fake_http1)

        async with client:
            response = await client.request("GET", "https://example.com/thing",
                                            agent_id="agent-7",
                                            rotation_mode="round_robin")

        assert response.status == 200
        assert captured == {"domain": "example.com", "agent_id": "agent-7",
                            "rotation_mode": "round_robin"}

    async def test_upstream_start_is_skipped_when_disabled(self, config_file):
        client = ResilientClient(auto_load_proxies=False, config_path=config_file())
        async with client:
            assert await client.rotator.start_upstream() is False


# ── deduplication ────────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestDeduplicator:
    async def test_failure_is_propagated_and_state_cleared(self):
        dedup = RequestDeduplicator()

        async def boom():
            raise RuntimeError("upstream down")

        with pytest.raises(RuntimeError, match="upstream down"):
            await dedup.execute("GET", "https://example.com/a", None, "http/1.1", boom)
        assert dedup._in_flight == {}

    async def test_concurrent_callers_share_one_failure(self):
        dedup = RequestDeduplicator()
        calls = {"n": 0}

        async def boom():
            calls["n"] += 1
            await asyncio.sleep(0.01)
            raise RuntimeError("shared failure")

        results = await asyncio.gather(
            dedup.execute("GET", "https://example.com/b", None, "http/1.1", boom),
            dedup.execute("GET", "https://example.com/b", None, "http/1.1", boom),
            return_exceptions=True,
        )
        assert all(isinstance(r, RuntimeError) for r in results)
        assert calls["n"] == 1


# ── http/2 proxy plumbing ────────────────────────────────────────────────
class FakeHttpxClient:
    """Stands in for httpx.AsyncClient; records constructor kwargs and calls."""

    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.closed = False
        FakeHttpxClient.instances.append(self)

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return type("Resp", (), {"status_code": 200, "content": b"ok",
                                 "headers": {"content-type": "text/plain"}})()

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
class TestHttp2Proxies:
    """httpx has no per-request proxy argument: clients must be bound per proxy."""

    async def _client_with_fakes(self, config_file, monkeypatch):
        FakeHttpxClient.instances = []
        monkeypatch.setattr(pd.httpx, "AsyncClient", FakeHttpxClient)
        client = ResilientClient(auto_load_proxies=False, config_path=config_file())
        client._httpx_client = FakeHttpxClient(http2=True)
        return client

    async def test_proxied_request_uses_a_client_bound_to_the_proxy(self, config_file, monkeypatch):
        client = await self._client_with_fakes(config_file, monkeypatch)
        await client._request_http2("GET", "https://example.com", None, None,
                                    "http://93.184.216.34:8080")

        assert len(FakeHttpxClient.instances) == 2          # base + proxied
        proxied = FakeHttpxClient.instances[1]
        assert proxied.kwargs == {"http2": True, "timeout": 30.0,
                                  "proxy": "http://93.184.216.34:8080"}
        assert proxied.calls[0]["url"] == "https://example.com"
        # no proxy kwarg leaked into the request call (that is what used to raise)
        assert "proxy" not in proxied.calls[0]

    async def test_proxied_clients_are_reused(self, config_file, monkeypatch):
        client = await self._client_with_fakes(config_file, monkeypatch)
        for _ in range(3):
            await client._request_http2("GET", "https://example.com", None, None,
                                        "http://93.184.216.34:8080")
        assert len(client._httpx_proxied) == 1
        assert len(FakeHttpxClient.instances) == 2

    async def test_direct_request_uses_the_shared_client(self, config_file, monkeypatch):
        client = await self._client_with_fakes(config_file, monkeypatch)
        await client._request_http2("GET", "https://example.com", None, None, None)
        assert client._httpx_proxied == {}
        assert client._httpx_client.calls[0]["url"] == "https://example.com"

    async def test_proxied_clients_are_closed_on_exit(self, config_file, monkeypatch):
        client = await self._client_with_fakes(config_file, monkeypatch)
        client._session = None
        await client._request_http2("GET", "https://example.com", None, None,
                                    "http://93.184.216.34:8080")
        proxied = FakeHttpxClient.instances[1]
        await client.__aexit__(None, None, None)
        assert proxied.closed is True
        assert client._httpx_proxied == {}

    async def test_proxy_client_cache_is_bounded(self, config_file, monkeypatch):
        client = await self._client_with_fakes(config_file, monkeypatch)
        cap = pd.MAX_PROXIED_CLIENTS
        for i in range(cap + 3):
            await client._request_http2("GET", "https://example.com", None, None,
                                        f"http://93.184.216.{i}:8080")
        assert len(client._httpx_proxied) <= cap
        await asyncio.sleep(0)      # let eviction closes run


@pytest.mark.asyncio
class TestConfigPlumbing:
    async def test_max_per_source_is_passed_to_the_rotator(self, config_file):
        client = ResilientClient(config_path=config_file(max_per_source=42))
        assert client.rotator.max_per_source == 42


# ── test hygiene ─────────────────────────────────────────────────────────
class TestNetworkGuard:
    """Proves tests/conftest.py actually isolates the suite from the runner."""

    def test_outbound_connection_is_blocked(self):
        import socket

        with pytest.raises(OSError, match="outbound network access"):
            socket.create_connection(("1.1.1.1", 80), timeout=0.1)

    def test_loopback_is_allowed(self):
        import socket

        # nothing listens on port 9, but the guard must not be what rejects it
        with pytest.raises(OSError) as excinfo:
            socket.create_connection(("127.0.0.1", 9), timeout=0.2)
        assert "outbound network access" not in str(excinfo.value)
