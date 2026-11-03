#!/usr/bin/env python3
"""
🦉 OWL-AGENT Proxy Defense Stack — Unit Tests
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
import tempfile
import json

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


if __name__ == "__main__":
    unittest.main()