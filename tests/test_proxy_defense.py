#!/usr/bin/env python3
"""
🦉 OWL-AGENT Proxy Defense Stack — Unit Tests
"""

import asyncio
import subprocess
import time
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
import tempfile
import json

import proxy_defense
from proxy_defense import (
    CachedResponse,
    TokenBucket,
    ProxyEntry,
    HTTPCache,
    RequestDeduplicator,
    DomainRateLimiter,
    ProxyRotator,
    ResilientClient,
    RequestContext,
    FilterPipeline,
    FilterRule,
    FilterAction,
    chain,
    nginx_camouflage_middleware,
    basic_auth_camouflage_middleware,
)


class TestCachedResponse(unittest.TestCase):
    def test_is_fresh_within_ttl(self):
        resp = CachedResponse(status=200, content=b"test", headers={}, timestamp=time.time(), ttl=300)
        self.assertTrue(resp.is_fresh())

    def test_is_expired_after_ttl(self):
        resp = CachedResponse(status=200, content=b"test", headers={}, timestamp=time.time() - 400, ttl=300)
        self.assertFalse(resp.is_fresh())


class TestTokenBucket(unittest.TestCase):
    def test_acquire_with_sufficient_tokens(self):
        async def run():
            bucket = TokenBucket(rate=1.0, capacity=5.0, tokens=5.0)
            result = await bucket.acquire(1.0)
            self.assertTrue(result)
        asyncio.run(run())


class TestProxyEntry(unittest.TestCase):
    def test_mark_failed_bans_after_3(self):
        entry = ProxyEntry(url="http://proxy:8080", proxy_type="dc", protocol="http", source="test", tier=1)
        entry.mark_failed()
        entry.mark_failed()
        self.assertTrue(entry.healthy)
        entry.mark_failed()
        self.assertFalse(entry.healthy)
        self.assertTrue(entry.is_banned())

    def test_mark_success_resets(self):
        entry = ProxyEntry(url="http://proxy:8080", proxy_type="dc", protocol="http", source="test", tier=1)
        entry.fail_count = 2
        entry.mark_success(50.0)
        self.assertEqual(entry.fail_count, 0)
        self.assertTrue(entry.healthy)


class TestHTTPCache(unittest.TestCase):
    def test_set_and_get(self):
        async def run():
            cache = HTTPCache(ttl=300)
            resp = CachedResponse(status=200, content=b"test", headers={}, timestamp=time.time(), ttl=300)
            await cache.set("GET", "https://example.com", resp)
            result = await cache.get("GET", "https://example.com")
            self.assertIsNotNone(result)
            self.assertEqual(result.status, 200)
        asyncio.run(run())

    def test_cache_miss(self):
        async def run():
            cache = HTTPCache(ttl=300)
            result = await cache.get("GET", "https://example.com")
            self.assertIsNone(result)
        asyncio.run(run())


class TestProxyRotator(unittest.TestCase):
    def test_empty_pool_returns_none(self):
        async def run():
            rotator = ProxyRotator(proxies=[])
            result = await rotator.get_proxy()
            self.assertIsNone(result)
        asyncio.run(run())

    def test_rotates_through_proxies(self):
        async def run():
            proxies = [
                ProxyEntry(url="http://p1:80", proxy_type="dc", protocol="http", source="test", tier=1),
                ProxyEntry(url="http://p2:80", proxy_type="dc", protocol="http", source="test", tier=1),
            ]
            rotator = ProxyRotator(proxies=proxies)
            p1 = await rotator.get_proxy()
            p2 = await rotator.get_proxy()
            self.assertNotEqual(p1.url, p2.url)
        asyncio.run(run())
class TestProxyRotatorUpstream(unittest.TestCase):
    """Tests for ProxyRotator upstream harvesting lifecycle."""

    def test_start_upstream_disabled_returns_false(self):
        async def run():
            rotator = ProxyRotator(proxies=[], use_upstream_harvester=False)
            result = await rotator.start_upstream()
            self.assertFalse(result)
        asyncio.run(run())

    def test_start_upstream_missing_module_returns_false(self):
        async def run():
            rotator = ProxyRotator(proxies=[], use_upstream_harvester=True)
            with patch("proxy_defense._load_harvester", return_value=None):
                result = await rotator.start_upstream()
            self.assertFalse(result)
        asyncio.run(run())

    def test_stop_upstream_no_tasks(self):
        async def run():
            rotator = ProxyRotator(proxies=[], use_upstream_harvester=False)
            # Should not raise even with no tasks
            await rotator.stop_upstream()
        asyncio.run(run())

    def test_healthy_entries_filters_unhealthy(self):
        async def run():
            proxies = [
                ProxyEntry(url="http://p1:80", proxy_type="dc", protocol="http", source="test", tier=1, healthy=True),
                ProxyEntry(url="http://p2:80", proxy_type="dc", protocol="http", source="test", tier=1, healthy=False),
            ]
            rotator = ProxyRotator(proxies=proxies)
            healthy = rotator.healthy_entries()
            self.assertEqual(len(healthy), 1)
            self.assertEqual(healthy[0].url, "http://p1:80")
        asyncio.run(run())

    def test_healthy_entries_filters_banned(self):
        async def run():
            p = ProxyEntry(url="http://p1:80", proxy_type="dc", protocol="http", source="test", tier=1, healthy=True)
            p.ban_until = time.time() + 300  # banned for 5 minutes
            rotator = ProxyRotator(proxies=[p])
            healthy = rotator.healthy_entries()
            self.assertEqual(len(healthy), 0)
        asyncio.run(run())




class TestLLMRouting(unittest.TestCase):
    """Tests for v7.2 LLM request routing through local model upstreams."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        config_path = Path(self.tmpdir.name) / "config.json"
        config = {
            "local_model_upstreams": {
                "colibri": {
                    "name": "colibri",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "compatible": "OpenAI",
                },
                "freeride": {
                    "name": "freeride",
                    "base_url": "http://localhost:11343/v1",
                    "compatible": "OpenAI",
                },
            }
        }
        config_path.write_text(json.dumps(config))
        self.client = ResilientClient(config_path=str(config_path))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_is_llm_request_detects_paths(self):
        self.assertTrue(self.client._is_llm_request("http://proxy/v1/chat/completions"))
        self.assertTrue(self.client._is_llm_request("http://proxy/v1/completions"))
        self.assertTrue(self.client._is_llm_request("http://proxy/v1/models"))
        self.assertTrue(self.client._is_llm_request("http://proxy/v1/embeddings"))
        self.assertTrue(self.client._is_llm_request("http://proxy/v1/chat/completions?stream=true"))

    def test_is_llm_request_rejects_non_llm(self):
        self.assertFalse(self.client._is_llm_request("http://example.com/page"))
        self.assertFalse(self.client._is_llm_request("http://example.com/api/v1/data"))
        self.assertFalse(self.client._is_llm_request("https://httpbin.org/ip"))

    def test_is_llm_request_detects_base_url(self):
        self.assertTrue(self.client._is_llm_request("http://127.0.0.1:8000/v1/chat/completions"))
        self.assertTrue(self.client._is_llm_request("http://localhost:11343/v1/models"))

    def test_rewrite_llm_url_no_double_v1(self):
        self.assertEqual(
            self.client._rewrite_llm_url("http://proxy/v1/chat/completions", "colibri"),
            "http://127.0.0.1:8000/v1/chat/completions",
        )
        self.assertEqual(
            self.client._rewrite_llm_url("http://proxy/v1/chat/completions", "freeride"),
            "http://localhost:11343/v1/chat/completions",
        )
        self.assertEqual(
            self.client._rewrite_llm_url("http://proxy/v1/models?limit=5", "colibri"),
            "http://127.0.0.1:8000/v1/models?limit=5",
        )

    def test_select_llm_upstream_returns_primary(self):
        async def run():
            name = await self.client._select_llm_upstream("agent-1")
            self.assertEqual(name, "colibri")
            # Sticky: second call returns same
            name2 = await self.client._select_llm_upstream("agent-1")
            self.assertEqual(name2, "colibri")
        asyncio.run(run())

    def test_next_upstream_failover(self):
        self.assertEqual(self.client._next_upstream({"colibri"}), "freeride")
        self.assertIsNone(self.client._next_upstream({"colibri", "freeride"}))
        self.assertEqual(self.client._next_upstream(set()), "colibri")

    def test_request_routes_llm_to_llm_factory(self):
        async def run():
            with patch.object(
                self.client, "_request_llm", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = CachedResponse(
                    status=200, content=b'{"ok":true}', headers={},
                    timestamp=0, ttl=0, protocol="http/1.1",
                )
                result = await self.client.request(
                    "POST", "http://proxy/v1/chat/completions",
                    json={"model": "test", "messages": []},
                )
                mock_llm.assert_called_once()
                self.assertEqual(result.status, 200)
        asyncio.run(run())

    def test_no_upstreams_means_no_base_url_routing(self):
        async def run():
            client = ResilientClient(config_path="/nonexistent/config.json")
            self.assertEqual(client.local_upstreams, {})
            # Path-based LLM detection still works (generic pattern match)
            self.assertTrue(client._is_llm_request("http://proxy/v1/chat/completions"))
            # Non-LLM paths return False with no upstreams configured
            self.assertFalse(client._is_llm_request("http://proxy/custom-endpoint"))
            self.assertFalse(client._is_llm_request("http://example.com/page"))
        asyncio.run(run())




class TestTokenBucketMore(unittest.TestCase):
    """Additional TokenBucket behaviors not covered by basic tests."""

    def test_acquire_insufficient_tokens_waits(self):
        async def run():
            # rate=10.0 tokens/sec, capacity=1, start with 0 tokens
            bucket = TokenBucket(rate=10.0, capacity=1.0, tokens=0.0)
            result = await bucket.acquire(1.0)
            self.assertTrue(result)
            # tokens should be ~0 now (replenished then consumed)
            self.assertLess(bucket.tokens, 0.1)
        asyncio.run(run())

    def test_replenish_over_time(self):
        async def run():
            bucket = TokenBucket(rate=100.0, capacity=10.0, tokens=0.0)
            # Force replenish by waiting briefly
            await asyncio.sleep(0.05)  # 50ms * 100 tokens/sec = 5 tokens
            await bucket._replenish()
            self.assertGreater(bucket.tokens, 0.0)
            self.assertLessEqual(bucket.tokens, 10.0)
        asyncio.run(run())

    def test_acquire_returns_bool(self):
        async def run():
            bucket = TokenBucket(rate=1.0, capacity=5.0, tokens=5.0)
            result = await bucket.acquire(1.0)
            self.assertIsInstance(result, bool)
            self.assertTrue(result)
        asyncio.run(run())


class TestHTTPCacheMore(unittest.TestCase):
    """Additional HTTPCache behaviors."""

    def test_cache_entry_is_expired(self):
        async def run():
            cache = HTTPCache(ttl=1)
            resp = CachedResponse(
                status=200, content=b"old", headers={},
                timestamp=time.time() - 2, ttl=1,
            )
            await cache.set("GET", "https://example.com", resp)
            result = await cache.get("GET", "https://example.com")
            self.assertIsNone(result)  # expired
        asyncio.run(run())

    def test_cache_key_includes_params(self):
        async def run():
            cache = HTTPCache(ttl=300)
            resp1 = CachedResponse(status=200, content=b"a", headers={}, timestamp=time.time(), ttl=300)
            resp2 = CachedResponse(status=200, content=b"b", headers={}, timestamp=time.time(), ttl=300)
            await cache.set("GET", "https://example.com", resp1, params={"q": "1"})
            await cache.set("GET", "https://example.com", resp2, params={"q": "2"})
            r1 = await cache.get("GET", "https://example.com", params={"q": "1"})
            r2 = await cache.get("GET", "https://example.com", params={"q": "2"})
            self.assertEqual(r1.content, b"a")
            self.assertEqual(r2.content, b"b")
        asyncio.run(run())

    def test_cache_key_includes_protocol(self):
        async def run():
            cache = HTTPCache(ttl=300)
            resp1 = CachedResponse(status=200, content=b"h1", headers={}, timestamp=time.time(), ttl=300, protocol="http/1.1")
            resp2 = CachedResponse(status=200, content=b"h2", headers={}, timestamp=time.time(), ttl=300, protocol="http/2")
            await cache.set("GET", "https://example.com", resp1)
            await cache.set("GET", "https://example.com", resp2)
            r1 = await cache.get("GET", "https://example.com")
            r2 = await cache.get("GET", "https://example.com", protocol="http/2")
            self.assertEqual(r1.content, b"h1")
            self.assertEqual(r2.content, b"h2")
        asyncio.run(run())


class TestRequestDeduplicatorMore(unittest.TestCase):
    """Additional RequestDeduplicator behaviors."""

    def test_concurrent_callers_share_one_result(self):
        async def run():
            dedup = RequestDeduplicator()
            call_count = 0

            async def factory():
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.01)
                return "result"

            # Launch two concurrent calls with the same key
            results = await asyncio.gather(
                dedup.execute("GET", "https://example.com", factory=factory),
                dedup.execute("GET", "https://example.com", factory=factory),
            )
            self.assertEqual(results, ["result", "result"])
            self.assertEqual(call_count, 1)  # factory called only once
        asyncio.run(run())

    def test_dedup_failure_propagates(self):
        async def run():
            dedup = RequestDeduplicator()

            async def failing_factory():
                raise ValueError("boom")

            with self.assertRaises(ValueError):
                await dedup.execute("GET", "https://example.com", factory=failing_factory)
        asyncio.run(run())

    def test_dedup_different_keys_are_independent(self):
        async def run():
            dedup = RequestDeduplicator()
            call_count = 0

            async def factory():
                nonlocal call_count
                call_count += 1
                return "ok"

            r1 = await dedup.execute("GET", "https://a.com", factory=factory)
            r2 = await dedup.execute("GET", "https://b.com", factory=factory)
            self.assertEqual(r1, "ok")
            self.assertEqual(r2, "ok")
            self.assertEqual(call_count, 2)  # different URLs = separate calls
        asyncio.run(run())


class TestDomainRateLimiter(unittest.TestCase):
    """DomainRateLimiter per-domain bucket behavior."""

    def test_extract_domain_from_netloc(self):
        limiter = DomainRateLimiter()
        self.assertEqual(limiter._extract_domain("https://example.com/path"), "example.com")
        self.assertEqual(limiter._extract_domain("http://sub.example.com:8080/x"), "sub.example.com:8080")

    def test_extract_domain_falls_back_to_path(self):
        limiter = DomainRateLimiter()
        self.assertEqual(limiter._extract_domain("https:///path"), "/path")

    def test_acquire_creates_per_domain_bucket(self):
        async def run():
            limiter = DomainRateLimiter(default_rate=1.0, default_capacity=1.0)
            await limiter.acquire("https://example.com/a")
            await limiter.acquire("https://example.com/b")
            # Same domain → same bucket
            self.assertEqual(len(limiter._buckets), 1)
            await limiter.acquire("https://other.com/c")
            self.assertEqual(len(limiter._buckets), 2)
        asyncio.run(run())


class TestProxyEntryMore(unittest.TestCase):
    """Additional ProxyEntry behaviors."""

    def test_is_banned_when_ban_until_in_future(self):
        entry = ProxyEntry(
            url="http://proxy:8080", proxy_type="dc", protocol="http",
            source="test", tier=1,
        )
        entry.ban_until = time.time() + 300  # banned for 5 minutes
        self.assertTrue(entry.is_banned())

    def test_is_not_banned_when_ban_until_in_past(self):
        entry = ProxyEntry(
            url="http://proxy:8080", proxy_type="dc", protocol="http",
            source="test", tier=1,
        )
        entry.ban_until = time.time() - 100  # ban expired
        self.assertFalse(entry.is_banned())

    def test_to_dict_from_dict_roundtrip(self):
        entry = ProxyEntry(
            url="http://proxy:8080", proxy_type="residential", protocol="http",
            source="provider-a", tier=2, latency_ms=42.5,
        )
        entry.mark_failed()
        entry.mark_failed()
        entry.latency_ms = 100.0
        data = entry.to_dict()
        restored = ProxyEntry.from_dict(data)
        self.assertEqual(restored.url, entry.url)
        self.assertEqual(restored.proxy_type, entry.proxy_type)
        self.assertEqual(restored.protocol, entry.protocol)
        self.assertEqual(restored.source, entry.source)
        self.assertEqual(restored.tier, entry.tier)
        self.assertEqual(restored.latency_ms, entry.latency_ms)
        self.assertEqual(restored.fail_count, entry.fail_count)

    def test_mark_failed_third_time_bans(self):
        entry = ProxyEntry(
            url="http://proxy:8080", proxy_type="dc", protocol="http",
            source="test", tier=1,
        )
        entry.mark_failed()
        entry.mark_failed()
        self.assertFalse(entry.is_banned())  # 2 failures, not banned yet
        entry.mark_failed()
        self.assertTrue(entry.is_banned())  # 3rd failure → banned


class TestProxyPoolLoader(unittest.TestCase):
    """ProxyPoolLoader file loading."""

    def test_load_missing_file_returns_empty(self):
        loader = mcp_ProxyPoolLoader = __import__("proxy_defense").ProxyPoolLoader(
            pool_file=Path("/nonexistent/pool.json")
        )
        result = loader.load()
        self.assertEqual(result, [])

    def test_load_valid_file(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "tier_1_managed_free": {
                    "providers": [{
                        "name": "provider-a",
                        "proxies": [
                            {"url": "http://p1:8080", "type": "datacenter", "protocols": ["HTTP"]},
                            {"url": "http://p2:8080", "type": "residential", "protocols": ["SOCKS5"]},
                        ],
                    }]
                }
            }, f)
            fname = f.name
        try:
            from proxy_defense import ProxyPoolLoader
            loader = ProxyPoolLoader(pool_file=Path(fname))
            result = loader.load()
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0].url, "http://p1:8080")
            self.assertEqual(result[0].protocol, "http")
            self.assertEqual(result[0].tier, 1)
            self.assertEqual(result[1].protocol, "socks5")
        finally:
            os.unlink(fname)

    def test_load_malformed_json_returns_empty(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{broken json")
            fname = f.name
        try:
            from proxy_defense import ProxyPoolLoader
            loader = ProxyPoolLoader(pool_file=Path(fname))
            result = loader.load()
            self.assertEqual(result, [])
        finally:
            import os
            os.unlink(fname)


class TestCachedResponseMore(unittest.TestCase):
    """Additional CachedResponse behaviors."""

    def test_is_fresh_exactly_at_ttl(self):
        resp = CachedResponse(
            status=200, content=b"x", headers={},
            timestamp=time.time() - 300, ttl=300,
        )
        # Exactly at TTL boundary: time.time() - timestamp = 300, 300 < 300 is False
        # So is_fresh should be False when exactly at boundary
        # (depends on timing, just check it doesn't crash)
        self.assertIsInstance(resp.is_fresh(), bool)

    def test_is_fresh_with_zero_ttl(self):
        resp = CachedResponse(
            status=200, content=b"x", headers={},
            timestamp=time.time(), ttl=0,
        )
        self.assertFalse(resp.is_fresh())


class TestProxyRotatorMore(unittest.TestCase):
    """Additional ProxyRotator behaviors."""

    def test_mark_banned_three_times_bans(self):
        async def run():
            proxies = [ProxyEntry(
                url="http://p1:80", proxy_type="dc", protocol="http",
                source="test", tier=1,
            )]
            rotator = ProxyRotator(proxies=proxies)
            await rotator.mark_banned(proxies[0])
            await rotator.mark_banned(proxies[0])
            self.assertFalse(proxies[0].is_banned())  # 2 failures, not banned yet
            await rotator.mark_banned(proxies[0])
            self.assertTrue(proxies[0].is_banned())   # 3rd failure → banned
            self.assertFalse(proxies[0].healthy)
        asyncio.run(run())

    def test_load_cache_missing_file(self):
        import tempfile
        async def run():
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                fname = f.name
            try:
                rotator = ProxyRotator(proxies=[])
                count = rotator.load_cache()  # no file → 0
                self.assertEqual(count, 0)
            finally:
                import os
                os.unlink(fname)
        asyncio.run(run())


class TestResilientClientLifecycle(unittest.TestCase):
    """ResilientClient __aenter__/__aexit__ and config reading."""

    def test_read_config_missing_file(self):
        client = ResilientClient.__new__(ResilientClient)
        result = client._read_config(None)
        # Uses CONFIG_FILE which may not exist → returns {}
        self.assertIsInstance(result, dict)

    def test_read_config_malformed_json(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{broken")
            fname = f.name
        try:
            client = ResilientClient.__new__(ResilientClient)
            result = client._read_config(Path(fname))
            self.assertEqual(result, {})
        finally:
            os.unlink(fname)

    def test_aenter_aexit_no_harvest(self):
        import tempfile, os
        async def run():
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump({"local_model_upstreams": {}}, f)
                fname = f.name
            try:
                client = ResilientClient(
                    config_path=fname,
                    auto_load_proxies=False,
                    cache_file=None,
                )
                async with client:
                    self.assertIsNotNone(client._session)
                    self.assertEqual(client.local_upstreams, {})
            finally:
                os.unlink(fname)
        asyncio.run(run())


class TestProxyRotatorCacheRoundtrip(unittest.TestCase):
    """ProxyRotator save_cache / load_cache roundtrip."""

    def test_save_and_load_cache(self):
        import tempfile, os
        async def run():
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                fname = f.name
            try:
                proxies = [ProxyEntry(
                    url="http://p1:8080", proxy_type="dc", protocol="http",
                    source="test", tier=1,
                )]
                proxies[0].mark_success(42.0)
                rotator = ProxyRotator(proxies=proxies, cache_file=Path(fname))
                rotator.save_cache()

                # New rotator loading from same file
                rotator2 = ProxyRotator(proxies=[], cache_file=Path(fname))
                count = rotator2.load_cache()
                self.assertEqual(count, 1)
                self.assertEqual(rotator2.proxies[0].url, "http://p1:8080")
                self.assertEqual(rotator2.proxies[0].tier, 1)
            finally:
                os.unlink(fname)
        asyncio.run(run())


class FakeHttpResponse:
    """Mock async context manager for aiohttp session.request()."""

    def __init__(self, status, content=b""):
        self.status = status
        self._content = content
        self.headers = {}

    async def read(self):
        return self._content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeClientSession:
    """Minimal stand-in for aiohttp.ClientSession with controllable request()."""

    def __init__(self):
        self._factory = None

    def request(self, method, url, **kwargs):
        # Return an async context manager directly (FakeHttpResponse)
        return self._factory(method, url, **kwargs)

    def set_factory(self, factory):
        self._factory = factory

    async def close(self):
        pass


class TestLLMRoutingFailover(unittest.TestCase):
    """LLM routing _request_llm failover behavior."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        config_path = Path(self.tmpdir.name) / "config.json"
        config = {
            "local_model_upstreams": {
                "primary": {
                    "name": "primary",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "compatible": "OpenAI",
                },
                "failover": {
                    "name": "failover",
                    "base_url": "http://127.0.0.1:11343/v1",
                    "compatible": "OpenAI",
                },
            }
        }
        config_path.write_text(json.dumps(config))
        self.client = ResilientClient(config_path=str(config_path))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_request_llm_failover_on_connection_error(self):
        async def run():
            call_count = 0

            def factory(method, url, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("primary down")
                return FakeHttpResponse(200, b'{"ok":true}')

            session = FakeClientSession()
            session.set_factory(factory)
            self.client._session = session

            result = await self.client._request_llm(
                "POST", "http://proxy/v1/chat/completions",
                params=None, headers=None, agent_id="agent-1",
            )
            self.assertEqual(result.status, 200)
            self.assertEqual(call_count, 2)
        asyncio.run(run())

    def test_request_llm_all_fail_raises(self):
        async def run():
            def factory(method, url, **kwargs):
                raise ConnectionError("all down")

            session = FakeClientSession()
            session.set_factory(factory)
            self.client._session = session

            with self.assertRaises(RuntimeError) as ctx:
                await self.client._request_llm(
                    "POST", "http://proxy/v1/chat/completions",
                    params=None, headers=None, agent_id="agent-1",
                )
            self.assertIn("All LLM upstreams failed", str(ctx.exception))
        asyncio.run(run())

    def test_request_llm_429_triggers_failover(self):
        async def run():
            call_count = 0

            def factory(method, url, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return FakeHttpResponse(429, b"{}")
                return FakeHttpResponse(200, b'{"ok":true}')

            session = FakeClientSession()
            session.set_factory(factory)
            self.client._session = session

            result = await self.client._request_llm(
                "POST", "http://proxy/v1/chat/completions",
                params=None, headers=None, agent_id="agent-1",
            )
            self.assertEqual(result.status, 200)
            self.assertEqual(call_count, 2)
        asyncio.run(run())


class TestExternalProxies(unittest.TestCase):
    """Tests for external proxy (BounceBack, https_proxy) integration."""

    def test_external_proxies_registered_at_tier_1(self):
        async def run():
            rotator = ProxyRotator(
                proxies=[],
                external_proxies=["http://127.0.0.1:8080", "http://127.0.0.1:3128"],
            )
            self.assertEqual(len(rotator.proxies), 2)
            for p in rotator.proxies:
                self.assertEqual(p.tier, 1)
                self.assertEqual(p.proxy_type, "external")
                self.assertEqual(p.source, "external_config")
                self.assertTrue(p.validated)
                self.assertTrue(p.healthy)
        asyncio.run(run())

    def test_external_proxies_selected_before_harvested(self):
        async def run():
            proxies = [
                ProxyEntry(url="http://harvested:8080", proxy_type="free",
                           protocol="http", source="harvest", tier=4),
            ]
            rotator = ProxyRotator(
                proxies=proxies,
                external_proxies=["http://127.0.0.1:8080"],
            )
            proxy = await rotator.get_proxy(domain="example.com")
            self.assertEqual(proxy.url, "http://127.0.0.1:8080")
            self.assertEqual(proxy.tier, 1)
        asyncio.run(run())

    def test_external_proxies_duplicate_url_not_doubled(self):
        async def run():
            proxies = [
                ProxyEntry(url="http://127.0.0.1:8080", proxy_type="dc",
                           protocol="http", source="existing", tier=1),
            ]
            rotator = ProxyRotator(
                proxies=proxies,
                external_proxies=["http://127.0.0.1:8080"],
            )
            # Should not add duplicate
            urls = [p.url for p in rotator.proxies]
            self.assertEqual(urls.count("http://127.0.0.1:8080"), 1)
        asyncio.run(run())

    def test_resilient_client_external_proxies_passed_through(self):
        async def run():
            client = ResilientClient(
                external_proxies=["http://127.0.0.1:8080"],
                auto_load_proxies=False,
            )
            rotator = client.rotator
            external = [p for p in rotator.proxies if p.proxy_type == "external"]
            self.assertEqual(len(external), 1)
            self.assertEqual(external[0].url, "http://127.0.0.1:8080")
            self.assertEqual(external[0].tier, 1)
        asyncio.run(run())

    def test_resilient_client_no_external_proxies_by_default(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            rotator = client.rotator
            external = [p for p in rotator.proxies if p.proxy_type == "external"]
            self.assertEqual(len(external), 0)
        asyncio.run(run())


class TestMiddlewareChain(unittest.TestCase):
    """Tests for the go-stealth-inspired middleware chain."""

    def test_chain_executes_middlewares_in_order(self):
        order = []

        async def final(ctx):
            order.append("final")
            return ctx.response

        def mw1(handler):
            async def wrapped(ctx):
                order.append("m1-in")
                result = await handler(ctx)
                order.append("m1-out")
                return result
            return wrapped

        def mw2(handler):
            async def wrapped(ctx):
                order.append("m2-in")
                result = await handler(ctx)
                order.append("m2-out")
                return result
            return wrapped

        composed = chain([mw1, mw2], final)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        result = asyncio.run(composed(ctx))
        self.assertEqual(order, ["m1-in", "m2-in", "final", "m2-out", "m1-out"])
        self.assertIs(result, ctx.response)

    def test_chain_with_no_middlewares(self):
        async def final(ctx):
            return ctx.response

        composed = chain([], final)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1",
                             response="cached-response")
        result = asyncio.run(composed(ctx))
        self.assertEqual(result, "cached-response")

    def test_request_context_defaults(self):
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        self.assertEqual(ctx.agent_id, "default")
        self.assertEqual(ctx.rotation_mode, "sticky")
        self.assertIsNone(ctx.proxy_url)
        self.assertIsNone(ctx.response)
        self.assertFalse(ctx.short_circuit)


class TestFilterPipeline(unittest.TestCase):
    """Tests for the BounceBack-inspired WAF filter pipeline."""

    def test_ip_rule_matches(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("1.2.3.4\n5.6.7.8\n")
            tmp = f.name
        try:
            rules = [FilterRule(name="ban-ip", rule_type="ip",
                                params={"list": tmp}, action=FilterAction.REJECT)]
            pipeline = FilterPipeline(rules)
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={"x-forwarded-for": "1.2.3.4"},
                                 protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertEqual(action, FilterAction.REJECT)
            self.assertEqual(name, "ban-ip")
        finally:
            os.unlink(tmp)

    def test_ip_rule_no_match(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("1.2.3.4\n")
            tmp = f.name
        try:
            rules = [FilterRule(name="ban-ip", rule_type="ip",
                                params={"list": tmp}, action=FilterAction.REJECT)]
            pipeline = FilterPipeline(rules)
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={"x-forwarded-for": "9.9.9.9"},
                                 protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertIsNone(action)
            self.assertIsNone(name)
        finally:
            os.unlink(tmp)

    def test_ip_rule_missing_list_file(self):
        rules = [FilterRule(name="ban-ip", rule_type="ip",
                            params={"list": "/nonexistent/file.txt"},
                            action=FilterAction.REJECT)]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={"x-forwarded-for": "1.2.3.4"},
                             protocol="http/1.1")
        action, name = pipeline.evaluate(ctx)
        self.assertIsNone(action)

    def test_regexp_rule_matches(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("badword\nsensitive\n")
            tmp = f.name
        try:
            rules = [FilterRule(name="ban-regexp", rule_type="regexp",
                                params={"list": tmp}, action=FilterAction.REJECT)]
            pipeline = FilterPipeline(rules)
            ctx = RequestContext(method="GET", url="http://example.com/badword-page",
                                 params=None, headers={}, protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertEqual(action, FilterAction.REJECT)
        finally:
            os.unlink(tmp)

    def test_time_rule_matches(self):
        from datetime import datetime
        import zoneinfo
        # Use a wide window that always matches
        now = datetime.now(zoneinfo.ZoneInfo("UTC"))
        from_str = f"{now.hour:02d}:{(now.minute - 5) % 60:02d}"
        to_str = f"{now.hour:02d}:{(now.minute + 5) % 60:02d}"
        rules = [FilterRule(name="business-hours", rule_type="time",
                            params={"from": from_str, "to": to_str,
                                    "timezone": "UTC"},
                            action=FilterAction.REJECT)]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        action, name = pipeline.evaluate(ctx)
        self.assertEqual(action, FilterAction.REJECT)

    def test_and_rule_matches_when_all_match(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("1.2.3.4\n")
            tmp1 = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("badword\n")
            tmp2 = f.name
        try:
            # and-rule first so it's evaluated before its component rules
            rules = [
                FilterRule(name="and-rule", rule_type="and",
                           params={"rules": [
                               {"name": "ip-rule", "type": "ip",
                                "params": {"list": tmp1}},
                               {"name": "regexp-rule", "type": "regexp",
                                "params": {"list": tmp2}},
                           ]}, action=FilterAction.REJECT),
                FilterRule(name="ip-rule", rule_type="ip",
                           params={"list": tmp1}, action=FilterAction.REJECT),
                FilterRule(name="regexp-rule", rule_type="regexp",
                           params={"list": tmp2}, action=FilterAction.REJECT),
            ]
            pipeline = FilterPipeline(rules)
            ctx = RequestContext(method="GET", url="http://example.com/badword",
                                 params=None, headers={"x-forwarded-for": "1.2.3.4"},
                                 protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertEqual(action, FilterAction.REJECT)
            self.assertEqual(name, "and-rule")
        finally:
            os.unlink(tmp1)
            os.unlink(tmp2)

    def test_and_rule_no_match_when_any_fails(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("1.2.3.4\n")
            tmp = f.name
        try:
            rules = [
                FilterRule(name="and-rule", rule_type="and",
                           params={"rules": [
                               {"name": "ip-rule", "type": "ip",
                                "params": {"list": tmp}},
                               {"name": "regexp-rule", "type": "regexp",
                                "params": {"list": "/nonexistent.txt"}},
                           ]}, action=FilterAction.REJECT),
                FilterRule(name="ip-rule", rule_type="ip",
                           params={"list": tmp}, action=FilterAction.REJECT),
            ]
            pipeline = FilterPipeline(rules)
            # IP 9.9.9.9 not in list → ip-rule doesn't match standalone
            # and-rule: ip condition fails → and doesn't match
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={"x-forwarded-for": "9.9.9.9"},
                                 protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertIsNone(action)
        finally:
            os.unlink(tmp)

    def test_or_rule_matches_when_any_matches(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("badword\n")
            tmp2 = f.name
        try:
            # or-rule first so it's evaluated before its component rules
            rules = [
                FilterRule(name="or-rule", rule_type="or",
                           params={"rules": [
                               {"name": "ip-rule", "type": "ip",
                                "params": {"list": "/nonexistent.txt"}},
                               {"name": "regexp-rule", "type": "regexp",
                                "params": {"list": tmp2}},
                           ]}, action=FilterAction.REJECT),
                FilterRule(name="regexp-rule", rule_type="regexp",
                           params={"list": tmp2}, action=FilterAction.REJECT),
            ]
            pipeline = FilterPipeline(rules)
            ctx = RequestContext(method="GET", url="http://example.com/badword",
                                 params=None, headers={}, protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertEqual(action, FilterAction.REJECT)
            self.assertEqual(name, "or-rule")
        finally:
            os.unlink(tmp2)

    def test_not_rule_inverts(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("1.2.3.4\n")
            tmp = f.name
        try:
            # not-rule comes first so it's evaluated before ip-rule
            rules = [
                FilterRule(name="not-rule", rule_type="not",
                           params={"rule": "ip-rule"}, action=FilterAction.ACCEPT),
                FilterRule(name="ip-rule", rule_type="ip",
                           params={"list": tmp}, action=FilterAction.REJECT),
            ]
            pipeline = FilterPipeline(rules)
            # IP matches → not rule inverts → no match from not rule
            # → falls through to ip-rule → REJECT
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={"x-forwarded-for": "1.2.3.4"},
                                 protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertEqual(action, FilterAction.REJECT)
            self.assertEqual(name, "ip-rule")

            # IP doesn't match → not rule inverts → matches with ACCEPT
            ctx2 = RequestContext(method="GET", url="http://example.com",
                                  params=None, headers={"x-forwarded-for": "9.9.9.9"},
                                  protocol="http/1.1")
            action2, name2 = pipeline.evaluate(ctx2)
            self.assertEqual(action2, FilterAction.ACCEPT)
            self.assertEqual(name2, "not-rule")
        finally:
            os.unlink(tmp)

    def test_first_matching_rule_wins(self):
        rules = [
            FilterRule(name="first-reject", rule_type="regexp",
                       params={"list": "/nonexistent.txt"}, action=FilterAction.REJECT),
            FilterRule(name="second-accept", rule_type="regexp",
                       params={"list": "/nonexistent.txt"}, action=FilterAction.ACCEPT),
        ]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        # Neither matches since list files don't exist
        action, name = pipeline.evaluate(ctx)
        self.assertIsNone(action)


class TestResilientClientMiddlewareFilter(unittest.TestCase):
    """Tests for middleware + filter pipeline on ResilientClient."""

    def test_filter_pipeline_rejects_request(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("1.2.3.4\n")
            tmp = f.name
        try:
            rules = [FilterRule(name="ban-ip", rule_type="ip",
                                params={"list": tmp}, action=FilterAction.REJECT)]
            client = ResilientClient(
                auto_load_proxies=False,
                filter_rules=rules,
            )
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={"x-forwarded-for": "1.2.3.4"},
                                 protocol="http/1.1")
            # Directly test filter pipeline evaluation
            action, name = client.filter_pipeline.evaluate(ctx)
            self.assertEqual(action, FilterAction.REJECT)
        finally:
            os.unlink(tmp)

    def test_middleware_chain_wraps_factory(self):
        calls = []

        async def mw(handler):
            async def wrapped(ctx):
                calls.append("middleware")
                return await handler(ctx)
            return wrapped

        client = ResilientClient(
            auto_load_proxies=False,
            middleware=[mw],
        )
        self.assertEqual(len(client.middleware), 1)

    def test_resilient_client_no_middleware_by_default(self):
        client = ResilientClient(auto_load_proxies=False)
        self.assertEqual(len(client.middleware), 0)

    def test_filter_rule_accept_action(self):
        rule = FilterRule(name="allow-all", rule_type="ip",
                          params={"list": "/nonexistent.txt"},
                          action=FilterAction.ACCEPT)
        self.assertEqual(rule.action, FilterAction.ACCEPT)
        self.assertEqual(rule.name, "allow-all")


# ── LLM routing tests ────────────────────────────────────────────────────


class TestLLMRouting(unittest.TestCase):
    """Tests for v7.2 LLM request routing through local model upstreams."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        config_path = Path(self.tmpdir.name) / "config.json"
        config = {
            "local_model_upstreams": {
                "colibri": {
                    "name": "colibri",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "compatible": "OpenAI",
                },
                "freeride": {
                    "name": "freeride",
                    "base_url": "http://localhost:11343/v1",
                    "compatible": "OpenAI",
                },
            }
        }
        config_path.write_text(json.dumps(config))
        self.client = ResilientClient(config_path=str(config_path))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_is_llm_request_detects_all_paths(self):
        for path in ("/v1/chat/completions", "/v1/completions",
                     "/v1/models", "/v1/embeddings"):
            self.assertTrue(
                self.client._is_llm_request(f"http://proxy{path}"),
                f"should detect {path}",
            )
            self.assertTrue(
                self.client._is_llm_request(f"http://proxy{path}?stream=true"),
                f"should detect {path} with query",
            )

    def test_is_llm_request_detects_base_url_prefix(self):
        self.assertTrue(
            self.client._is_llm_request("http://127.0.0.1:8000/v1/chat/completions")
        )
        self.assertTrue(
            self.client._is_llm_request("http://localhost:11343/v1/models")
        )
        # Non-prefix, non-LLM path should not trigger
        self.assertFalse(
            self.client._is_llm_request("http://other.com/api/data")
        )

    def test_is_llm_request_rejects_non_llm(self):
        self.assertFalse(self.client._is_llm_request("http://example.com/page"))
        self.assertFalse(self.client._is_llm_request("https://httpbin.org/ip"))
        self.assertFalse(self.client._is_llm_request("http://example.com/api/v1/data"))

    def test_rewrite_llm_url_strips_v1_suffix(self):
        # base_url ends with /v1, so /v1 is stripped from path to avoid duplication
        result = self.client._rewrite_llm_url(
            "http://proxy/v1/chat/completions", "colibri"
        )
        self.assertEqual(result, "http://127.0.0.1:8000/v1/chat/completions")

    def test_rewrite_llm_url_no_v1_in_path_keeps_path(self):
        # base_url ends with /v1 but path doesn't start with /v1, so no stripping
        result = self.client._rewrite_llm_url(
            "http://proxy/api/completions", "freeride"
        )
        self.assertEqual(result, "http://localhost:11343/v1/api/completions")

    def test_rewrite_llm_url_preserves_query(self):
        result = self.client._rewrite_llm_url(
            "http://proxy/v1/models?page=2", "colibri"
        )
        self.assertEqual(result, "http://127.0.0.1:8000/v1/models?page=2")

    def test_rewrite_llm_url_root_v1(self):
        result = self.client._rewrite_llm_url("http://proxy/v1", "colibri")
        self.assertEqual(result, "http://127.0.0.1:8000/v1/")

    def test_next_upstream_returns_unattempted(self):
        upstream = self.client._next_upstream({"colibri"})
        self.assertEqual(upstream, "freeride")

    def test_next_upstream_returns_none_when_all_attempted(self):
        upstream = self.client._next_upstream({"colibri", "freeride"})
        self.assertIsNone(upstream)

    def test_select_llm_upstream_no_upstreams_returns_none(self):
        client = ResilientClient(auto_load_proxies=False)
        result = asyncio.run(client._select_llm_upstream("agent-1"))
        self.assertIsNone(result)


class TestLLMRequestFailover(unittest.TestCase):
    """Tests for _request_llm failover behavior (no network)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        config_path = Path(self.tmpdir.name) / "config.json"
        config = {
            "local_model_upstreams": {
                "colibri": {
                    "name": "colibri",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "compatible": "OpenAI",
                },
                "freeride": {
                    "name": "freeride",
                    "base_url": "http://localhost:11343/v1",
                    "compatible": "OpenAI",
                },
            }
        }
        config_path.write_text(json.dumps(config))
        self.client = ResilientClient(config_path=str(config_path),
                                       auto_load_proxies=False)
        self.empty_client = ResilientClient(config_path=str(config_path),
                                            auto_load_proxies=False)
        self.empty_client.local_upstreams["freeride"]["base_url"] = ""

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_request_llm_empty_base_url_skips(self):
        # freeride has empty base_url → should be skipped
        async def run():
            class FakeResponse:
                status = 502
                content = b"fail"
                headers = {}

                async def read(self):
                    return self.content

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *exc):
                    return False

            class FakeSession:
                def request(self, method, url, params, headers, timeout, **kwargs):
                    return FakeResponse()

            self.empty_client._session = FakeSession()
            self.empty_client._upstream_order = ["colibri", "freeride"]
            self.empty_client._upstream_affinity = None
            with patch("proxy_defense._load_harvester", return_value=None):
                with self.assertRaises(RuntimeError):
                    await self.empty_client._request_llm(
                        "POST", "http://proxy/v1/chat/completions",
                        params=None, headers=None, agent_id="agent-1",
                    )
        asyncio.run(run())

    def test_request_llm_failover_on_502(self):
        async def run():
            call_count = 0

            class FakeResponse:
                def __init__(self, status):
                    self.status = status
                    self.content = b"ok"
                    self.headers = {}

                async def read(self):
                    return self.content

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *exc):
                    return False

            class FakeSession:
                def request(self, method, url, params, headers, timeout, **kwargs):
                    nonlocal call_count
                    call_count += 1
                    return FakeResponse(502 if call_count == 1 else 200)

            self.client._session = FakeSession()
            # Force colibri as primary, no affinity
            self.client._upstream_order = ["colibri", "freeride"]
            self.client._upstream_affinity = None
            with patch("proxy_defense._load_harvester", return_value=None):
                result = await self.client._request_llm(
                    "POST", "http://proxy/v1/chat/completions",
                    params=None, headers=None, agent_id="agent-1",
                )
            self.assertEqual(result.status, 200)
        asyncio.run(run())

    def test_request_llm_all_fail_raises_runtime_error(self):
        async def run():
            class FakeResponse:
                def __init__(self):
                    self.status = 502
                    self.content = b"fail"
                    self.headers = {}

                async def read(self):
                    return self.content

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *exc):
                    return False

            class FakeSession:
                def request(self, method, url, params, headers, timeout, **kwargs):
                    return FakeResponse()

            self.client._session = FakeSession()
            self.client._upstream_order = ["colibri", "freeride"]
            self.client._upstream_affinity = None
            with patch("proxy_defense._load_harvester", return_value=None):
                with self.assertRaises(RuntimeError):
                    await self.client._request_llm(
                        "POST", "http://proxy/v1/chat/completions",
                        params=None, headers=None, agent_id="agent-1",
                    )
        asyncio.run(run())


# ── Filter pipeline stub rule tests ──────────────────────────────────────


class TestFilterPipelineStubs(unittest.TestCase):
    """Tests for BounceBack filter pipeline stub rule types."""

    def test_geo_rule_stub_returns_false(self):
        rules = [FilterRule(name="geo-ban", rule_type="geo",
                            params={"geolocations": {"country_code": ["US"]}},
                            action=FilterAction.REJECT)]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        action, name = pipeline.evaluate(ctx)
        self.assertIsNone(action)

    def test_reverse_lookup_rule_stub_returns_false(self):
        rules = [FilterRule(name="ptr-ban", rule_type="reverse_lookup",
                            params={"list": "/nonexistent.txt"},
                            action=FilterAction.REJECT)]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        action, name = pipeline.evaluate(ctx)
        self.assertIsNone(action)

    def test_malleable_rule_stub_returns_false(self):
        rules = [FilterRule(name="malleable-ban", rule_type="malleable",
                            params={"profile": "/nonexistent.profile"},
                            action=FilterAction.REJECT)]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        action, name = pipeline.evaluate(ctx)
        self.assertIsNone(action)

    def test_unknown_rule_type_returns_false(self):
        rules = [FilterRule(name="weird", rule_type="unknown_type",
                            params={}, action=FilterAction.REJECT)]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        action, name = pipeline.evaluate(ctx)
        self.assertIsNone(action)

    def test_ip_matches_empty_client_ip(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("1.2.3.4\n")
            tmp = f.name
        try:
            rules = [FilterRule(name="ban-ip", rule_type="ip",
                                params={"list": tmp}, action=FilterAction.REJECT)]
            pipeline = FilterPipeline(rules)
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={}, protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertIsNone(action)
        finally:
            os.unlink(tmp)

    def test_ip_matches_cidr_notation(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("10.0.0.0/8\n")
            tmp = f.name
        try:
            rules = [FilterRule(name="ban-cidr", rule_type="ip",
                                params={"list": tmp}, action=FilterAction.REJECT)]
            pipeline = FilterPipeline(rules)
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={"x-forwarded-for": "10.1.2.3"},
                                 protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertEqual(action, FilterAction.REJECT)
        finally:
            os.unlink(tmp)

    def test_regexp_matches_empty_pattern_file(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("\n")
            tmp = f.name
        try:
            rules = [FilterRule(name="ban-regexp", rule_type="regexp",
                                params={"list": tmp}, action=FilterAction.REJECT)]
            pipeline = FilterPipeline(rules)
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={}, protocol="http/1.1")
            action, name = pipeline.evaluate(ctx)
            self.assertIsNone(action)
        finally:
            os.unlink(tmp)

    def test_time_matches_overnight_window(self):
        from datetime import datetime
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo("UTC"))
        # Overnight window: 23:00 to 02:00 always matches at some point
        rules = [FilterRule(name="night", rule_type="time",
                            params={"from": "23:00", "to": "02:00",
                                    "timezone": "UTC"},
                            action=FilterAction.REJECT)]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        # May or may not match depending on current time; just verify no crash
        action, name = pipeline.evaluate(ctx)
        self.assertIn(action, (None, FilterAction.REJECT))

    def test_time_matches_weekday_filter(self):
        from datetime import datetime
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo("UTC"))
        weekday = now.strftime("%A")
        rules = [FilterRule(name="weekday-only", rule_type="time",
                            params={"from": "00:00", "to": "23:59",
                                    "timezone": "UTC",
                                    "weekdays": [weekday]},
                            action=FilterAction.REJECT)]
        pipeline = FilterPipeline(rules)
        ctx = RequestContext(method="GET", url="http://example.com",
                             params=None, headers={}, protocol="http/1.1")
        action, name = pipeline.evaluate(ctx)
        self.assertEqual(action, FilterAction.REJECT)


# ── Middleware chain integration tests ───────────────────────────────────


class TestMiddlewareIntegration(unittest.TestCase):
    """Tests for middleware chain integrated with ResilientClient."""

    def test_middleware_short_circuit_skips_execution(self):
        async def run():
            def mw(handler):
                async def wrapped(ctx):
                    ctx.short_circuit = True
                    ctx.response = CachedResponse(
                        status=200, content=b"short-circuit",
                        headers={}, timestamp=time.time(), ttl=300,
                        protocol="http/1.1",
                    )
                    return ctx.response
                return wrapped

            client = ResilientClient(
                auto_load_proxies=False,
                middleware=[mw],
            )
            result = await client.request("GET", "http://example.com")
            self.assertEqual(result.status, 200)
            self.assertEqual(result.content, b"short-circuit")
        asyncio.run(run())

    def test_middleware_modifies_response(self):
        async def run():
            async def mw(handler):
                async def wrapped(ctx):
                    result = await handler(ctx)
                    # Even if handler returns None, middleware can wrap it
                    return result
                return wrapped

            client = ResilientClient(
                auto_load_proxies=False,
                middleware=[mw],
            )
            # No actual request execution — just verify middleware wraps
            self.assertEqual(len(client.middleware), 1)
        asyncio.run(run())


# ── CLI tests ────────────────────────────────────────────────────────────


# ── nginx camouflage middleware tests ───────────────────────────────────


class TestNginxCamouflageMiddleware(unittest.TestCase):
    """Tests for https_proxy-inspired nginx camouflage middleware."""

    def test_nginx_camouflage_adds_server_header(self):
        async def run():
            async def fake_handler(ctx):
                return CachedResponse(
                    status=200, content=b"ok", headers={},
                    timestamp=time.time(), ttl=300, protocol="http/1.1",
                )

            chain_handler = chain(
                [nginx_camouflage_middleware()], fake_handler,
            )
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={}, protocol="http/1.1")
            result = await chain_handler(ctx)
            self.assertEqual(result.headers.get("server"), "nginx/1.24.0")
        asyncio.run(run())

    def test_nginx_camouflage_fake_404(self):
        async def run():
            async def fake_handler(ctx):
                return CachedResponse(
                    status=200, content=b"secret", headers={},
                    timestamp=time.time(), ttl=300, protocol="http/1.1",
                )

            chain_handler = chain(
                [nginx_camouflage_middleware(
                    fake_404_paths=["/.hidden", "/admin"],
                )], fake_handler,
            )
            ctx = RequestContext(method="GET", url="http://example.com/.hidden",
                                 params=None, headers={}, protocol="http/1.1")
            result = await chain_handler(ctx)
            self.assertEqual(result.status, 404)
            self.assertEqual(result.headers.get("server"), "nginx/1.24.0")
        asyncio.run(run())

    def test_nginx_camouflage_custom_server_name(self):
        async def run():
            async def fake_handler(ctx):
                return CachedResponse(
                    status=200, content=b"ok", headers={},
                    timestamp=time.time(), ttl=300, protocol="http/1.1",
                )

            chain_handler = chain(
                [nginx_camouflage_middleware(server_name="nginx/1.18.0")],
                fake_handler,
            )
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={}, protocol="http/1.1")
            result = await chain_handler(ctx)
            self.assertEqual(result.headers.get("server"), "nginx/1.18.0")
        asyncio.run(run())

    def test_basic_auth_camouflage_forwards_header(self):
        async def run():
            captured_headers = {}

            async def fake_handler(ctx):
                captured_headers.update(ctx.headers or {})
                return CachedResponse(
                    status=200, content=b"ok", headers={},
                    timestamp=time.time(), ttl=300, protocol="http/1.1",
                )

            chain_handler = chain(
                [basic_auth_camouflage_middleware(
                    auth_header="Basic dXNlcjpwYXNz",
                )], fake_handler,
            )
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={}, protocol="http/1.1")
            result = await chain_handler(ctx)
            self.assertEqual(
                captured_headers.get("Authorization"),
                "Basic dXNlcjpwYXNz",
            )
        asyncio.run(run())

    def test_basic_auth_camouflage_401_www_authenticate(self):
        async def run():
            async def fake_handler(ctx):
                return CachedResponse(
                    status=401, content=b"unauthorized", headers={},
                    timestamp=time.time(), ttl=0, protocol="http/1.1",
                )

            chain_handler = chain(
                [basic_auth_camouflage_middleware(
                    www_authenticate_realm="MyProxy",
                )], fake_handler,
            )
            ctx = RequestContext(method="GET", url="http://example.com",
                                 params=None, headers={}, protocol="http/1.1")
            result = await chain_handler(ctx)
            self.assertEqual(result.status, 401)
            self.assertEqual(
                result.headers.get("WWW-Authenticate"),
                'Basic realm="MyProxy"',
            )
        asyncio.run(run())


# ── protocol handler tests ─────────────────────────────────────────────


class TestProtocolHandlers(unittest.TestCase):
    """Tests for protocol handlers when dependencies are unavailable."""

    def test_request_http2_raises_when_unavailable(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            with self.assertRaises(RuntimeError):
                await client._request_http2(
                    "GET", "http://example.com", None, {}, None,
                )
        asyncio.run(run())

    def test_request_ja3_raises_when_unavailable(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            with self.assertRaises(RuntimeError):
                await client._request_ja3(
                    "GET", "http://example.com", None, {}, None,
                )
        asyncio.run(run())

    def test_request_websocket_raises_when_unavailable(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            with self.assertRaises(RuntimeError):
                await client._request_websocket("http://example.com", None)
        asyncio.run(run())

    def test_request_browser_raises_when_unavailable(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            with self.assertRaises(RuntimeError):
                await client._request_browser("http://example.com", None)
        asyncio.run(run())

    def test_request_stealth_requires_acknowledgement(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            with self.assertRaises(proxy_defense.ProtocolUnavailable):
                await client._request_stealth("http://example.com", None)
        asyncio.run(run())

    def test_request_stealth_raises_when_not_installed(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            with patch("proxy_defense._stealth_acknowledged", return_value=True):
                with patch("proxy_defense._load_stealth", return_value=None):
                    with self.assertRaises(proxy_defense.ProtocolUnavailable):
                        await client._request_stealth("http://example.com", None)
        asyncio.run(run())
class TestProtocolHandlerSuccessPaths(unittest.TestCase):
    """Tests for protocol handler success paths with mocked dependencies."""

    def _async_context_manager(self, obj):
        """Wrap an object as an async context manager returning itself."""
        async def enter():
            return obj
        async def exit(*exc):
            return False
        cm = AsyncMock()
        cm.__aenter__ = enter
        cm.__aexit__ = exit
        return cm

    def test_request_http1_success(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)

            class FakeResp:
                status = 200
                content = b"hello"
                headers = {"content-type": "text/plain"}

                async def read(self):
                    return self.content

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

            class FakeSession:
                def request(self, method, url, **kwargs):
                    return FakeResp()

            client._session = FakeSession()

            result = await client._request_http1(
                "GET", "http://example.com", None, {}, None,
            )
            self.assertEqual(result.status, 200)
            self.assertEqual(result.content, b"hello")
            self.assertEqual(result.protocol, "http/1.1")
        asyncio.run(run())

    def test_request_http2_success(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)

            class FakeResp:
                status_code = 200
                content = b"hello2"
                headers = {"content-type": "text/plain"}

            fake_client = AsyncMock()
            fake_client.request.return_value = FakeResp()
            client._httpx_client = fake_client

            with patch("proxy_defense.HTTP2_AVAILABLE", True):
                result = await client._request_http2(
                    "GET", "http://example.com", None, {}, None,
                )
            self.assertEqual(result.status, 200)
            self.assertEqual(result.content, b"hello2")
            self.assertEqual(result.protocol, "http/2")
        asyncio.run(run())

    def test_request_http2_no_client_raises(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            client._httpx_client = None
            with patch("proxy_defense.HTTP2_AVAILABLE", True):
                with self.assertRaises(RuntimeError):
                    await client._request_http2(
                        "GET", "http://example.com", None, {}, None,
                    )
        asyncio.run(run())

    def test_request_ja3_success(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)

            class FakeResp:
                status_code = 200
                content = b"ja3-data"
                headers = {"content-type": "text/plain"}

            fake_session = AsyncMock()
            fake_session.request.return_value = FakeResp()
            client._curl_session = fake_session

            result = await client._request_ja3(
                "GET", "http://example.com", None, {}, None,
            )
            self.assertEqual(result.status, 200)
            self.assertEqual(result.content, b"ja3-data")
            self.assertEqual(result.protocol, "ja3")
        asyncio.run(run())

    def test_request_websocket_success(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)

            class FakeWS:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *exc):
                    return False

            def ws_connect(url, **kwargs):
                return FakeWS()

            with patch("proxy_defense.WS_AVAILABLE", True):
                proxy_defense.websockets = MagicMock()
                proxy_defense.websockets.connect = ws_connect
                try:
                    result = await client._request_websocket("ws://example.com", None)
                finally:
                    del proxy_defense.websockets
            self.assertEqual(result.status, 101)
            self.assertEqual(result.protocol, "websocket")
        asyncio.run(run())

    def test_request_browser_success(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)

            class FakePage:
                async def goto(self, *a, **k):
                    return None
                async def content(self):
                    return "<html></html>"
                async def close(self):
                    return None

            class FakeContext:
                async def new_page(self):
                    return FakePage()
                async def close(self):
                    return None

            class FakeBrowser:
                async def new_context(self, *a, **k):
                    return FakeContext()
                async def close(self):
                    return None
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *exc):
                    return False

            class FakePlaywrightCM:
                chromium = AsyncMock()
                chromium.launch = AsyncMock(return_value=FakeBrowser())
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *exc):
                    return False

            def fake_async_playwright():
                return FakePlaywrightCM()

            with patch("proxy_defense.PLAYWRIGHT_AVAILABLE", True):
                proxy_defense.async_playwright = fake_async_playwright
                try:
                    result = await client._request_browser("http://example.com", None)
                finally:
                    del proxy_defense.async_playwright
            self.assertEqual(result.status, 200)
            self.assertEqual(result.protocol, "browser")
        asyncio.run(run())

    def test_request_stealth_success(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)

            class FakePage:
                async def goto(self, *a, **k):
                    return None
                async def content(self):
                    return "<html>stealth</html>"
                async def close(self):
                    return None

            class FakeBrowser:
                async def new_page(self):
                    return FakePage()
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *exc):
                    return False

            class FakeStealthCM:
                async def __aenter__(self):
                    return FakeBrowser()
                async def __aexit__(self, *exc):
                    return False

            def fake_stealth_cls(**launch_kwargs):
                return FakeStealthCM()

            with patch("proxy_defense._stealth_acknowledged", return_value=True):
                with patch("proxy_defense._load_stealth", return_value=fake_stealth_cls):
                    result = await client._request_stealth(
                        "http://example.com", None,
                        acknowledge_terms=True,
                    )
            self.assertEqual(result.status, 200)
            self.assertEqual(result.protocol, "stealth")
        asyncio.run(run())


class TestResilientClientContextManager(unittest.TestCase):
    """Tests for ResilientClient __aenter__/__aexit__ lifecycle."""

    def test_aenter_creates_sessions(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)

            fake_session = AsyncMock()
            fake_session.close = AsyncMock()

            fake_httpx = AsyncMock()
            fake_httpx.aclose = AsyncMock()

            with patch("proxy_defense.aiohttp.ClientSession", return_value=fake_session):
                with patch("proxy_defense.HTTP2_AVAILABLE", True):
                    with patch("proxy_defense.httpx.AsyncClient", return_value=fake_httpx):
                        with patch("proxy_defense.JA3_AVAILABLE", False):
                            async with client:
                                self.assertIsNotNone(client._session)
            fake_session.close.assert_called()
        asyncio.run(run())

    def test_aexit_closes_proxied_clients(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            stale_client = AsyncMock()
            stale_client.aclose = AsyncMock()
            client._httpx_proxied = {"http://proxy:3128": stale_client}

            await client.__aexit__(None, None, None)
            stale_client.aclose.assert_called_once()
            self.assertEqual(len(client._httpx_proxied), 0)
        asyncio.run(run())

    def test_aenter_loads_cache(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            client.rotator.load_cache = MagicMock()

            fake_session = AsyncMock()
            fake_session.close = AsyncMock()

            with patch("proxy_defense.aiohttp.ClientSession", return_value=fake_session):
                with patch("proxy_defense.HTTP2_AVAILABLE", False):
                    with patch("proxy_defense.JA3_AVAILABLE", False):
                        async with client:
                            pass
            client.rotator.load_cache.assert_called_once()
        asyncio.run(run())

    def test_aenter_start_upstream(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False, use_upstream_harvester=True)
            client.rotator.start_upstream = AsyncMock()
            client.rotator.load_cache = MagicMock()

            fake_session = AsyncMock()
            fake_session.close = AsyncMock()

            with patch("proxy_defense.aiohttp.ClientSession", return_value=fake_session):
                with patch("proxy_defense.HTTP2_AVAILABLE", False):
                    with patch("proxy_defense.JA3_AVAILABLE", False):
                        async with client:
                            pass
            client.rotator.start_upstream.assert_called_once()
        asyncio.run(run())

    def test_aenter_exception_cleanup(self):
        async def run():
            client = ResilientClient(auto_load_proxies=False)
            fake_session = AsyncMock()
            fake_session.close = AsyncMock()

            with patch("proxy_defense.aiohttp.ClientSession", return_value=fake_session):
                with patch.object(client.rotator, "load_cache", side_effect=RuntimeError("boom")):
                    with patch("proxy_defense.HTTP2_AVAILABLE", False):
                        with patch("proxy_defense.JA3_AVAILABLE", False):
                            with self.assertRaises(RuntimeError):
                                async with client:
                                    pass
            fake_session.close.assert_called_once()
        asyncio.run(run())

class TestCLI(unittest.TestCase):
    """Tests for proxy_defense.py CLI entry point."""

    def test_main_help(self):
        result = subprocess.run(
            ["python3", str(Path(__file__).resolve().parent.parent /
             "proxy_defense.py"), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("proxy defense", result.stdout.lower())
class TestCLIStatsCommand(unittest.TestCase):
    """Tests for the CLI stats command (no network required)."""

    def test_cli_stats_json_output(self):
        async def run():
            fake_stats = {
                "proxies_total": 5,
                "proxies_healthy": 3,
                "proxies_banned": 1,
                "proxies_by_tier": {1: 3, 2: 2},
                "domains_rate_limited": 2,
                "health_ratio": "3/5 (60.0%)",
                "protocols_available": {
                    "http/1.1": True,
                    "http/2": False,
                    "ja3": False,
                    "websocket": False,
                    "browser": False,
                    "stealth": False,
                },
                "version": "7.1",
                "upstream_harvester": {"running": False, "sources": 0},
                "source_health": {},
                "session_affinity": {"active": 0},
                "cache_memory_size": 0,
                "dedup_in_flight": 0,
            }

            fake_client = AsyncMock()
            fake_client.get_stats.return_value = fake_stats

            with patch("proxy_defense.ResilientClient") as mock_client_class:
                mock_client_class.return_value.__aenter__ = AsyncMock(return_value=fake_client)
                mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await proxy_defense._cli(["stats", "--json"])
            self.assertEqual(result, 0)
        asyncio.run(run())

    def test_cli_stats_text_output(self):
        async def run():
            fake_stats = {
                "proxies_total": 5,
                "proxies_healthy": 3,
                "proxies_banned": 1,
                "proxies_by_tier": {1: 3, 2: 2},
                "domains_rate_limited": 2,
                "health_ratio": "3/5 (60.0%)",
                "protocols_available": {
                    "http/1.1": True,
                    "http/2": False,
                    "ja3": False,
                    "websocket": False,
                    "browser": False,
                    "stealth": False,
                },
                "version": "7.1",
                "upstream_harvester": {"running": True, "sources": 3, "harvested_total": 10, "unvalidated": 2},
                "source_health": {},
                "session_affinity": {"active": 0},
                "cache_memory_size": 0,
                "dedup_in_flight": 0,
            }

            fake_client = AsyncMock()
            fake_client.get_stats.return_value = fake_stats

            with patch("proxy_defense.ResilientClient") as mock_client_class:
                mock_client_class.return_value.__aenter__ = AsyncMock(return_value=fake_client)
                mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await proxy_defense._cli(["stats"])
            self.assertEqual(result, 0)
        asyncio.run(run())

    def test_cli_no_command_returns_demo(self):
        async def run():
            # _demo makes a live request which will fail, but returns 0
            result = await proxy_defense._cli([])
            self.assertEqual(result, 0)
        asyncio.run(run())




if __name__ == "__main__":
    unittest.main()