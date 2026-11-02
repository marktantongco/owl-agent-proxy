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


if __name__ == "__main__":
    unittest.main()