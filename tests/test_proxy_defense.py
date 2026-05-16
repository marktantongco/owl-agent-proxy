#!/usr/bin/env python3
"""
🦉 OWL-AGENT Proxy Defense Stack — Unit Tests
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from proxy_defense import (
    CachedResponse,
    TokenBucket,
    ProxyEntry,
    HTTPCache,
    RequestDeduplicator,
    DomainRateLimiter,
    ProxyRotator,
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
        asyncio.get_event_loop().run_until_complete(run())


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
        asyncio.get_event_loop().run_until_complete(run())

    def test_cache_miss(self):
        async def run():
            cache = HTTPCache(ttl=300)
            result = await cache.get("GET", "https://example.com")
            self.assertIsNone(result)
        asyncio.get_event_loop().run_until_complete(run())


class TestProxyRotator(unittest.TestCase):
    def test_empty_pool_returns_none(self):
        async def run():
            rotator = ProxyRotator(proxies=[])
            result = await rotator.get_proxy()
            self.assertIsNone(result)
        asyncio.get_event_loop().run_until_complete(run())

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
        asyncio.get_event_loop().run_until_complete(run())


if __name__ == "__main__":
    unittest.main()
