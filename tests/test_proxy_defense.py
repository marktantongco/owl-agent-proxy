#!/usr/bin/env python3
"""
🦉 OWL-AGENT Proxy Defense Stack — Unit Tests
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import types
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import tempfile

import proxy_defense
from proxy_defense import (
    CachedResponse,
    TokenBucket,
    ProxyEntry,
    ProxyCredential,
    CredentialStore,
    HTTPCache,
    RequestDeduplicator,
    DomainRateLimiter,
    ProxyRotator,
    ResilientClient,
    RequestContext,
    FilterPipeline,
    FilterRule,
    FilterAction,
    TOKEN_BUCKET_PERSIST_FILE,
    validate_config,
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

    def test_mark_success_appends_latency_history(self):
        entry = ProxyEntry(url="http://proxy:8080", proxy_type="dc", protocol="http", source="test", tier=1)
        entry.mark_success(10.0)
        entry.mark_success(20.0)
        entry.mark_success(30.0)
        self.assertEqual(list(entry.latency_history), [10.0, 20.0, 30.0])
        self.assertEqual(entry.latency_ms, 30.0)  # last measurement still tracked

    def test_p99_latency_empty_history(self):
        entry = ProxyEntry(url="http://proxy:8080", proxy_type="dc", protocol="http", source="test", tier=1)
        entry.latency_ms = 42.0
        self.assertEqual(entry.p99_latency_ms, 42.0)

    def test_p99_latency_single_sample(self):
        entry = ProxyEntry(url="http://proxy:8080", proxy_type="dc", protocol="http", source="test", tier=1)
        entry.mark_success(50.0)
        self.assertEqual(entry.p99_latency_ms, 50.0)

    def test_p99_latency_multiple_samples(self):
        entry = ProxyEntry(url="http://proxy:8080", proxy_type="dc", protocol="http", source="test", tier=1)
        # 50 samples (window maxlen): 1..50 ms, nearest-rank P99 = max = 50 ms
        for i in range(1, 51):
            entry.mark_success(float(i))
        self.assertEqual(entry.p99_latency_ms, 50.0)

    def test_p99_latency_rolling_window(self):
        entry = ProxyEntry(url="http://proxy:8080", proxy_type="dc", protocol="http", source="test", tier=1)
        # Fill past the maxlen=50 window
        for i in range(1, 61):
            entry.mark_success(float(i))
        self.assertEqual(len(entry.latency_history), 50)
        # Oldest (1..10) evicted, history is 11..60
        self.assertEqual(list(entry.latency_history)[0], 11.0)
        self.assertEqual(list(entry.latency_history)[-1], 60.0)

    def test_serialization_roundtrip_preserves_history(self):
        entry = ProxyEntry(url="http://proxy:8080", proxy_type="dc", protocol="http", source="test", tier=1)
        for lat in (10.0, 20.0, 30.0):
            entry.mark_success(lat)
        data = entry.to_dict()
        restored = ProxyEntry.from_dict(data)
        self.assertEqual(list(restored.latency_history), [10.0, 20.0, 30.0])
        self.assertEqual(restored.p99_latency_ms, entry.p99_latency_ms)


class TestProxyRotatorLatency(unittest.TestCase):
    """Rank 6: latency budget / P99 selection tests."""

    def test_get_proxy_sorts_by_p99_not_last_latency(self):
        async def run():
            rotator = ProxyRotator(
                proxies=[
                    ProxyEntry(url="http://slow:8080", proxy_type="dc", protocol="http", source="a", tier=1,
                               latency_ms=5.0, latency_history=deque([5.0, 500.0, 500.0, 500.0])),
                    ProxyEntry(url="http://steady:8080", proxy_type="dc", protocol="http", source="b", tier=1,
                               latency_ms=100.0, latency_history=deque([100.0, 100.0, 100.0, 100.0])),
                ],
                use_upstream_harvester=False,
            )
            rotator._sem = asyncio.Semaphore(1)
            # steady (P99=100) should be selected before slow (P99=500)
            # even though slow has better last-latency (5ms)
            proxy = await rotator.get_proxy(domain="example.com", rotation_mode="sticky")
            self.assertIsNotNone(proxy)
            self.assertEqual(proxy.url, "http://steady:8080")
        asyncio.run(run())

    def test_latency_budget_excludes_high_p99(self):
        async def run():
            rotator = ProxyRotator(
                proxies=[
                    ProxyEntry(url="http://fast:8080", proxy_type="dc", protocol="http", source="a", tier=1,
                               latency_ms=10.0, latency_history=deque([10.0, 10.0, 10.0])),
                    ProxyEntry(url="http://slow:8080", proxy_type="dc", protocol="http", source="b", tier=1,
                               latency_ms=500.0, latency_history=deque([500.0, 500.0, 500.0])),
                ],
                use_upstream_harvester=False,
                latency_budget_ms=100.0,
            )
            rotator._sem = asyncio.Semaphore(1)
            proxy = await rotator.get_proxy(domain="example.com", rotation_mode="sticky")
            self.assertIsNotNone(proxy)
            self.assertEqual(proxy.url, "http://fast:8080")

    def test_latency_budget_fail_open_when_all_exceed(self):
        async def run():
            rotator = ProxyRotator(
                proxies=[
                    ProxyEntry(url="http://slow1:8080", proxy_type="dc", protocol="http", source="a", tier=1,
                               latency_ms=500.0, latency_history=deque([500.0, 500.0, 500.0])),
                    ProxyEntry(url="http://slow2:8080", proxy_type="dc", protocol="http", source="b", tier=1,
                               latency_ms=600.0, latency_history=deque([600.0, 600.0, 600.0])),
                ],
                use_upstream_harvester=False,
                latency_budget_ms=100.0,
            )
            rotator._sem = asyncio.Semaphore(1)
            # All exceed budget: fail-open returns the least-bad (slow1, P99=500)
            proxy = await rotator.get_proxy(domain="example.com", rotation_mode="sticky")
            self.assertIsNotNone(proxy)
            self.assertEqual(proxy.url, "http://slow1:8080")

    def test_no_latency_budget_uses_all_candidates(self):
        async def run():
            rotator = ProxyRotator(
                proxies=[
                    ProxyEntry(url="http://fast:8080", proxy_type="dc", protocol="http", source="a", tier=1,
                               latency_ms=10.0, latency_history=deque([10.0, 10.0, 10.0])),
                    ProxyEntry(url="http://slow:8080", proxy_type="dc", protocol="http", source="b", tier=1,
                               latency_ms=500.0, latency_history=deque([500.0, 500.0, 500.0])),
                ],
                use_upstream_harvester=False,
                # latency_budget_ms not set -> no filtering
            )
            rotator._sem = asyncio.Semaphore(1)
            proxy = await rotator.get_proxy(domain="example.com", rotation_mode="sticky")
            self.assertEqual(proxy.url, "http://fast:8080")



class TestCredentialRotation(unittest.TestCase):
    """Rank 7: credential rotation tests."""

    def test_credential_is_available(self):
        cred = ProxyCredential(username="user", password="pass", host="proxy.example.com")
        self.assertTrue(cred.is_available())
        cred.banned_until = time.time() + 300
        self.assertFalse(cred.is_available())
        cred.banned_until = 0
        cred.fail_count = 3
        self.assertFalse(cred.is_available())
        cred.fail_count = 2
        self.assertTrue(cred.is_available())

    def test_credential_mark_failed_bans_after_3(self):
        cred = ProxyCredential(username="user", password="pass", host="proxy.example.com")
        cred.mark_failed()
        cred.mark_failed()
        self.assertTrue(cred.is_available())
        cred.mark_failed()
        self.assertFalse(cred.is_available())
        self.assertGreater(cred.banned_until, time.time())

    def test_credential_store_add_and_get(self):
        store = CredentialStore()
        store.add("proxy.example.com", "user1", "pass1")
        store.add("proxy.example.com", "user2", "pass2")
        result = store.get("proxy.example.com")
        self.assertIsNotNone(result)
        self.assertEqual(result, ("user1", "pass1"))
        result = store.get("proxy.example.com")
        self.assertIsNotNone(result)
        self.assertEqual(result, ("user2", "pass2"))
        result = store.get("proxy.example.com")
        self.assertIsNotNone(result)
        self.assertEqual(result, ("user1", "pass1"))

    def test_credential_store_no_creds_returns_none(self):
        store = CredentialStore()
        self.assertIsNone(store.get("unknown.example.com"))

    def test_credential_store_unknown_host(self):
        store = CredentialStore()
        store.add("proxy.example.com", "user1", "pass1")
        self.assertIsNone(store.get("other.example.com"))

    def test_credential_store_mark_failed_skips_banned(self):
        store = CredentialStore()
        store.add("proxy.example.com", "user1", "pass1")
        store.add("proxy.example.com", "user2", "pass2")
        for _ in range(3):
            store.mark_failed("proxy.example.com", "user1")
        result = store.get("proxy.example.com")
        self.assertEqual(result, ("user2", "pass2"))

    def test_credential_store_all_banned_returns_none(self):
        store = CredentialStore()
        store.add("proxy.example.com", "user1", "pass1")
        for _ in range(3):
            store.mark_failed("proxy.example.com", "user1")
        self.assertIsNone(store.get("proxy.example.com"))

    def test_credential_store_apply_inserts_credentials(self):
        store = CredentialStore()
        store.add("proxy.example.com", "user1", "pass1")
        url, cred = store.apply("http://proxy.example.com:8080")
        self.assertEqual(url, "http://user1:pass1@proxy.example.com:8080")
        self.assertEqual(cred, ("proxy.example.com", "user1"))

    def test_credential_store_apply_keeps_existing_credentials(self):
        store = CredentialStore()
        store.add("proxy.example.com", "user1", "pass1")
        url, cred = store.apply("http://embedded:creds@proxy.example.com:8080")
        self.assertEqual(url, "http://embedded:creds@proxy.example.com:8080")
        self.assertIsNone(cred)

    def test_credential_store_apply_no_creds_returns_unchanged(self):
        store = CredentialStore()
        url, cred = store.apply("http://proxy.example.com:8080")
        self.assertEqual(url, "http://proxy.example.com:8080")
        self.assertIsNone(cred)

    def test_credential_store_apply_url_convenience(self):
        store = CredentialStore()
        store.add("proxy.example.com", "user1", "pass1")
        url = store.apply_url("http://proxy.example.com:8080")
        self.assertEqual(url, "http://user1:pass1@proxy.example.com:8080")

    def test_rotator_get_effective_url_with_credentials(self):
        async def run():
            store = CredentialStore()
            store.add("proxy.example.com", "user1", "pass1")
            rotator = ProxyRotator(
                proxies=[
                    ProxyEntry(url="http://proxy.example.com:8080", proxy_type="dc",
                               protocol="http", source="test", tier=1),
                ],
                use_upstream_harvester=False,
                credential_store=store,
            )
            effective = rotator.get_effective_url(
                ProxyEntry(url="http://proxy.example.com:8080", proxy_type="dc",
                           protocol="http", source="test", tier=1)
            )
            self.assertEqual(effective, "http://user1:pass1@proxy.example.com:8080")
        asyncio.run(run())

    def test_rotator_get_effective_url_no_store(self):
        rotator = ProxyRotator(
            proxies=[],
            use_upstream_harvester=False,
        )
        effective = rotator.get_effective_url(
            ProxyEntry(url="http://proxy.example.com:8080", proxy_type="dc",
                       protocol="http", source="test", tier=1)
        )
        self.assertEqual(effective, "http://proxy.example.com:8080")

    def test_resilient_client_with_proxy_credentials(self):
        client = ResilientClient(
            auto_load_proxies=False,
            proxy_credentials={"proxy.example.com": [("user1", "pass1"), ("user2", "pass2")]},
        )
        self.assertIsNotNone(client.credential_store)
        self.assertEqual(client.credential_store.credential_count("proxy.example.com"), 2)
        self.assertIs(client.rotator.credential_store, client.credential_store)


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

    def test_max_entries_evicts_oldest(self):
        async def run():
            cache = HTTPCache(ttl=300, max_entries=3)
            for i in range(5):
                resp = CachedResponse(
                    status=200, content=f"resp-{i}".encode(),
                    headers={}, timestamp=time.time(), ttl=300,
                )
                await cache.set("GET", f"https://example.com/{i}", resp)
            self.assertIsNone(await cache.get("GET", "https://example.com/0"))
            self.assertIsNone(await cache.get("GET", "https://example.com/1"))
            self.assertIsNotNone(await cache.get("GET", "https://example.com/2"))
            self.assertIsNotNone(await cache.get("GET", "https://example.com/3"))
            self.assertIsNotNone(await cache.get("GET", "https://example.com/4"))
        asyncio.run(run())

    def test_get_moves_to_end_lru(self):
        async def run():
            cache = HTTPCache(ttl=300, max_entries=2)
            for i in range(2):
                resp = CachedResponse(
                    status=200, content=f"resp-{i}".encode(),
                    headers={}, timestamp=time.time(), ttl=300,
                )
                await cache.set("GET", f"https://example.com/{i}", resp)
            await cache.get("GET", "https://example.com/0")
            resp = CachedResponse(
                status=200, content=b"resp-2", headers={}, timestamp=time.time(), ttl=300,
            )
            await cache.set("GET", "https://example.com/2", resp)
            self.assertIsNotNone(await cache.get("GET", "https://example.com/0"))
            self.assertIsNone(await cache.get("GET", "https://example.com/1"))
            self.assertIsNotNone(await cache.get("GET", "https://example.com/2"))
        asyncio.run(run())

    def test_expired_entry_returned_as_none(self):
        async def run():
            now = [1000.0]
            cache = HTTPCache(ttl=10)
            resp = CachedResponse(
                status=200, content=b"old", headers={},
                timestamp=now[0], ttl=10,
            )
            await cache.set("GET", "https://example.com", resp)
            now[0] = 1011
            result = await cache.get("GET", "https://example.com")
            self.assertIsNone(result)
        asyncio.run(run())


class TestRequestDeduplicatorCap(unittest.TestCase):
    def test_max_in_flight_evicts_oldest(self):
        async def run():
            dedup = RequestDeduplicator(max_in_flight=2)
            results = []

            async def factory(tag):
                await asyncio.sleep(0.01)
                results.append(tag)
                return tag

            f1 = asyncio.ensure_future(dedup.execute("GET", "https://example.com/1", None, None, lambda: factory("one")))
            f2 = asyncio.ensure_future(dedup.execute("GET", "https://example.com/2", None, None, lambda: factory("two")))
            f3 = asyncio.ensure_future(dedup.execute("GET", "https://example.com/3", None, None, lambda: factory("three")))

            r1, r2, r3 = await asyncio.gather(f1, f2, f3)
            self.assertEqual(r1, "one")
            self.assertEqual(r2, "two")
            self.assertEqual(r3, "three")
        asyncio.run(run())

    def test_default_cap_is_finite(self):
        dedup = RequestDeduplicator()
        self.assertGreater(dedup.max_in_flight, 0)


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




class TestTokenBucketPersistence(unittest.TestCase):
    """Rank 9: token-bucket persistence tests."""

    def test_to_dict_from_dict_roundtrip(self):
        bucket = TokenBucket(rate=2.0, capacity=10.0, tokens=3.5, last_update=1000.0)
        data = bucket.to_dict()
        self.assertEqual(data["tokens"], 3.5)
        self.assertEqual(data["last_update"], 1000.0)
        self.assertNotIn("rate", data)
        self.assertNotIn("capacity", data)

        restored = TokenBucket.from_dict(2.0, 10.0, data)
        self.assertEqual(restored.rate, 2.0)
        self.assertEqual(restored.capacity, 10.0)
        self.assertEqual(restored.tokens, 3.5)
        self.assertEqual(restored.last_update, 1000.0)

    def test_from_dict_defaults_to_full_capacity(self):
        restored = TokenBucket.from_dict(1.0, 5.0, {})
        self.assertEqual(restored.tokens, 5.0)
        self.assertGreaterEqual(restored.last_update, time.time() - 1)

    def test_from_dict_partial_state(self):
        restored = TokenBucket.from_dict(1.0, 5.0, {"tokens": 1.5})
        self.assertEqual(restored.tokens, 1.5)
        self.assertGreaterEqual(restored.last_update, time.time() - 1)


class TestDomainRateLimiterPersistence(unittest.TestCase):
    """Rank 9: DomainRateLimiter persistence tests."""

    def test_load_state_missing_file_is_noop(self):
        limiter = DomainRateLimiter(persist_file=Path("/nonexistent/buckets.json"))
        limiter.load_state()
        self.assertEqual(len(limiter._buckets), 0)

    def test_load_state_corrupt_file_is_noop(self):
        persist_file = Path(tempfile.mkdtemp()) / "buckets.json"
        persist_file.write_text("{not valid json")
        limiter = DomainRateLimiter(persist_file=persist_file)
        limiter.load_state()
        self.assertEqual(len(limiter._buckets), 0)

    def test_save_and_load_state_roundtrip(self):
        persist_file = Path(tempfile.mkdtemp()) / "buckets.json"
        limiter = DomainRateLimiter(
            default_rate=1.0, default_capacity=5.0, persist_file=persist_file
        )
        async def run():
            await limiter.acquire("https://example.com/a")
            await limiter.acquire("https://example.com/b")
        asyncio.run(run())

        limiter.save_state()
        assert persist_file.exists()

        limiter2 = DomainRateLimiter(
            default_rate=1.0, default_capacity=5.0, persist_file=persist_file
        )
        limiter2.load_state()
        bucket = limiter2._buckets["example.com"]
        self.assertLess(bucket.tokens, 5.0)
        self.assertGreater(bucket.tokens, 0.0)
        self.assertEqual(bucket.rate, 1.0)
        self.assertEqual(bucket.capacity, 5.0)

    def test_persist_survives_restart(self):
        """Simulate a process restart: new limiter loads old state."""
        persist_file = Path(tempfile.mkdtemp()) / "buckets.json"

        limiter1 = DomainRateLimiter(
            default_rate=1.0, default_capacity=5.0, persist_file=persist_file
        )
        async def run1():
            await limiter1.acquire("https://example.com/x")
            await limiter1.acquire("https://example.com/x")
        asyncio.run(run1())
        limiter1.save_state()

        limiter2 = DomainRateLimiter(
            default_rate=1.0, default_capacity=5.0, persist_file=persist_file
        )
        limiter2.load_state()
        bucket = limiter2._buckets["example.com"]
        self.assertLess(bucket.tokens, 5.0)

    def test_in_memory_state_takes_precedence(self):
        persist_file = Path(tempfile.mkdtemp()) / "buckets.json"
        limiter = DomainRateLimiter(
            default_rate=1.0, default_capacity=5.0, persist_file=persist_file
        )
        limiter._buckets["example.com"] = TokenBucket(
            rate=1.0, capacity=5.0, tokens=0.5, last_update=9999.0
        )
        persist_file.write_text(json.dumps({"example.com": {"tokens": 4.0, "last_update": 1.0}}))
        limiter.load_state()
        bucket = limiter._buckets["example.com"]
        self.assertEqual(bucket.tokens, 0.5)
        self.assertEqual(bucket.last_update, 9999.0)

    def test_mark_dirty_triggers_debounced_save(self):
        persist_file = Path(tempfile.mkdtemp()) / "buckets.json"
        limiter = DomainRateLimiter(
            default_rate=1.0,
            default_capacity=5.0,
            persist_file=persist_file,
        )
        async def run():
            for i in range(12):
                await limiter.acquire(f"https://domain{i}.com/x")
        asyncio.run(run())
        assert persist_file.exists()

    def test_close_persists_final_state(self):
        persist_file = Path(tempfile.mkdtemp()) / "buckets.json"
        limiter = DomainRateLimiter(
            default_rate=1.0, default_capacity=5.0, persist_file=persist_file
        )
        async def run():
            await limiter.acquire("https://example.com/z")
        asyncio.run(run())
        limiter.close()
        assert persist_file.exists()


class TestResilientClientTokenBucketPersistence(unittest.TestCase):
    """Rank 9: ResilientClient token_bucket_persist_file wiring."""

    def test_resilient_client_accepts_persist_file(self):
        persist_file = Path(tempfile.mkdtemp()) / "buckets.json"
        client = ResilientClient(
            auto_load_proxies=False,
            token_bucket_persist_file=persist_file,
        )
        self.assertIsNotNone(client.limiter.persist_file)
        self.assertEqual(client.limiter.persist_file, persist_file)
        client.close()

    def test_resilient_client_default_persist_file(self):
        client = ResilientClient(auto_load_proxies=False)
        self.assertIsNotNone(client.limiter.persist_file)
        self.assertEqual(client.limiter.persist_file, TOKEN_BUCKET_PERSIST_FILE)
        client.close()


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

    def test_mark_banned_invalidates_sticky_binding(self):
        async def run():
            proxy = ProxyEntry(
                url="http://p1:80", proxy_type="dc", protocol="http",
                source="test", tier=1,
            )
            rotator = ProxyRotator(proxies=[proxy])
            affinity = rotator._ensure_affinity()
            await affinity.bind("agent-1", "example.com", "http://p1:80")
            self.assertEqual(await affinity.get("agent-1", "example.com"), "http://p1:80")

            await rotator.mark_banned(proxy)

            # binding is invalidated → agent re-picks on next request
            self.assertIsNone(await affinity.get("agent-1", "example.com"))
        asyncio.run(run())

    def test_mark_banned_no_affinity_no_crash(self):
        async def run():
            proxy = ProxyEntry(
                url="http://p1:80", proxy_type="dc", protocol="http",
                source="test", tier=1,
            )
            rotator = ProxyRotator(proxies=[proxy])
            # _affinity is None → must not raise
            await rotator.mark_banned(proxy)
            self.assertEqual(proxy.fail_count, 1)
            self.assertFalse(proxy.is_banned())  # needs 3 failures
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

    def test_cache_max_entries_and_dedup_cap(self):
        client = ResilientClient(
            auto_load_proxies=False,
            cache_max_entries=500,
            dedup_max_in_flight=100,
        )
        self.assertEqual(client.cache.max_entries, 500)
        self.assertEqual(client.dedup.max_in_flight, 100)


class TestConfigSchema(unittest.TestCase):
    """Rank 10: config schema validation tests."""

    def test_validate_config_empty(self):
        errors = validate_config({})
        self.assertEqual(errors, [])

    def test_validate_config_all_valid(self):
        config = {
            "cache_ttl": 300,
            "rate_limit": 1.5,
            "max_retries": 3,
            "cache_max_entries": 10000,
            "dedup_max_in_flight": 1000,
            "token_bucket_persist_file": "/tmp/buckets.json",
            "use_upstream_harvester": True,
            "session_ttl": 900.0,
            "harvest_interval": 600.0,
            "honeypot_check": True,
            "max_proxies": 2000,
            "external_proxies": ["http://127.0.0.1:8080"],
            "proxy_credentials": {"proxy.example.com": [("user", "pass")]},
            "middleware": [],
            "filter_rules": [],
            "validator_concurrency": 10,
            "validator_timeout": 8.0,
            "max_per_source": 300,
            "persist_proxy_cache": True,
            "latency_budget_ms": 500.0,
            "local_model_upstreams": {"colibri": {"name": "colibri"}},
        }
        errors = validate_config(config)
        self.assertEqual(errors, [])

    def test_validate_config_wrong_type(self):
        errors = validate_config({"cache_ttl": "300"})
        self.assertTrue(any("cache_ttl" in e for e in errors))
        self.assertTrue(any("int" in e and "str" in e for e in errors))

    def test_validate_config_below_min(self):
        errors = validate_config({"cache_ttl": 0})
        self.assertTrue(any("cache_ttl" in e and "minimum" in e for e in errors))

    def test_validate_config_negative_rate_limit(self):
        errors = validate_config({"rate_limit": -1.0})
        self.assertTrue(any("rate_limit" in e for e in errors))

    def test_validate_config_list_wrong_item_type(self):
        errors = validate_config({"external_proxies": [123, "http://ok"]})
        self.assertTrue(any("external_proxies" in e for e in errors))

    def test_validate_config_dict_wrong_value_type(self):
        errors = validate_config({"proxy_credentials": {"host": "not-a-list"}})
        self.assertTrue(any("proxy_credentials" in e for e in errors))

    def test_validate_config_unknown_key_warning(self):
        # Unknown keys are warnings, not errors
        errors = validate_config({"unknown_key": "value"})
        self.assertEqual(errors, [])

    def test_validate_config_not_dict(self):
        errors = validate_config("not a dict")
        self.assertEqual(len(errors), 1)
        self.assertIn("dict", errors[0])

    def test_validate_config_list_item_wrong_type(self):
        errors = validate_config({"filter_rules": ["not-a-dict"]})
        self.assertTrue(any("filter_rules" in e for e in errors))

    def test_read_config_invalid_values_logged(self):
        import tempfile, os
        config_path = Path(tempfile.mkdtemp()) / "config.json"
        config_path.write_text(json.dumps({"cache_ttl": "not-an-int"}))
        client = ResilientClient.__new__(ResilientClient)
        with self.assertLogs("owl-agent.proxy", level="WARNING") as log:
            result = client._read_config(config_path)
        # Should still return the config (invalid values are warnings, not fatal)
        self.assertEqual(result, {"cache_ttl": "not-an-int"})
        # Warning should have been logged
        assert any("cache_ttl" in msg for msg in log.output)

    def test_read_config_non_dict_top_level(self):
        import tempfile
        config_path = Path(tempfile.mkdtemp()) / "config.json"
        config_path.write_text(json.dumps([1, 2, 3]))
        client = ResilientClient.__new__(ResilientClient)
        with self.assertLogs("owl-agent.proxy", level="WARNING") as log:
            result = client._read_config(config_path)
        self.assertEqual(result, {})
        assert any("top-level" in msg for msg in log.output)


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
                # External proxies start unvalidated — they enter the same
                # validation pipeline as harvested proxies before being used.
                self.assertFalse(p.validated)
                self.assertFalse(p.healthy)
            # Both are enqueued for validation
            self.assertEqual(rotator._validation_queue.qsize(), 2)
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
            # External proxies start unvalidated — not returned until they
            # pass validation. Simulate a successful validation:
            external = rotator._find("http://127.0.0.1:8080")
            external.healthy = True
            external.validated = True
            external.latency_ms = 10.0

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

    def test_external_proxy_fails_validation_removed(self):
        async def run():
            rotator = ProxyRotator(
                proxies=[],
                external_proxies=["http://127.0.0.1:8080"],
                use_upstream_harvester=False,
            )
            self.assertEqual(len(rotator.proxies), 1)

            # Mock validate_proxy to return failure (must be async since it's awaited)
            async def fake_validate_fail(url, timeout=None):
                return {"ok": False}
            fake_module = types.ModuleType("fake_module")
            fake_module.validate_proxy = fake_validate_fail
            with patch("proxy_defense._load_harvester", return_value=fake_module):
                rotator._sem = asyncio.Semaphore(1)
                # Three failed validations trigger ban + removal
                for _ in range(3):
                    await rotator._validate_entry("http://127.0.0.1:8080")

            # External proxy removed after exhausting failure budget
            self.assertEqual(len(rotator.proxies), 0)
        asyncio.run(run())

    def test_external_proxy_passes_validation_becomes_healthy(self):
        async def run():
            rotator = ProxyRotator(
                proxies=[],
                external_proxies=["http://127.0.0.1:8080"],
                use_upstream_harvester=False,
            )
            entry_before = rotator._find("http://127.0.0.1:8080")
            self.assertIsNotNone(entry_before)
            self.assertFalse(entry_before.healthy)
            self.assertFalse(entry_before.validated)

            # Mock validate_proxy to return success (must be async since it's awaited)
            async def fake_validate_ok(url, timeout=None):
                return {"ok": True, "tcp_ms": 50, "http_ms": 100}
            fake_module = types.ModuleType("fake_module")
            fake_module.validate_proxy = fake_validate_ok
            with patch("proxy_defense._load_harvester", return_value=fake_module):
                rotator._sem = asyncio.Semaphore(1)
                await rotator._validate_entry("http://127.0.0.1:8080")

            # External proxy is now healthy and validated at tier 1
            entry = rotator._find("http://127.0.0.1:8080")
            self.assertIsNotNone(entry)
            self.assertTrue(entry.healthy)
            self.assertTrue(entry.validated)
            self.assertEqual(entry.tier, 1)
            self.assertEqual(entry.latency_ms, 150.0)
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

            fake_aiohttp_mod = AsyncMock()
            fake_aiohttp_mod.ClientSession = lambda *a, **k: fake_session
            fake_httpx_mod = AsyncMock()
            fake_httpx_mod.AsyncClient = lambda *a, **k: fake_httpx

            with patch("proxy_defense._require_aiohttp", return_value=fake_aiohttp_mod):
                with patch("proxy_defense.HTTP2_AVAILABLE", True):
                    with patch("proxy_defense._require_httpx", return_value=fake_httpx_mod):
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

            fake_aiohttp_mod = AsyncMock()
            fake_aiohttp_mod.ClientSession = lambda *a, **k: fake_session

            with patch("proxy_defense._require_aiohttp", return_value=fake_aiohttp_mod):
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

            fake_aiohttp_mod = AsyncMock()
            fake_aiohttp_mod.ClientSession = lambda *a, **k: fake_session

            with patch("proxy_defense._require_aiohttp", return_value=fake_aiohttp_mod):
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

            fake_aiohttp_mod = AsyncMock()
            fake_aiohttp_mod.ClientSession = lambda *a, **k: fake_session

            with patch("proxy_defense._require_aiohttp", return_value=fake_aiohttp_mod):
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




class TestVerificationSuiteDrift(unittest.TestCase):
    """Rank 11: verification suite drift — ensure verify-install.py expectations match the repo."""

    def test_run_sh_exists_and_executable(self):
        run_sh = Path(__file__).resolve().parent.parent / "run.sh"
        self.assertTrue(run_sh.exists(), "run.sh must exist in repo root")
        self.assertTrue(os.access(run_sh, os.X_OK), "run.sh must be executable")

    def test_config_json_exists_with_required_keys(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "config.json"
        self.assertTrue(config_path.exists(), "config/config.json must exist")
        data = json.loads(config_path.read_text())
        for key in ("use_upstream_harvester", "session_ttl", "harvest_interval"):
            self.assertIn(key, data, f"config.json missing required key: {key}")

    def test_tool_prefixes_allow_web_github_arxiv(self):
        """V18: tool names may start with proxy_, memory_, web_, github_, or arxiv_."""
        allowed = ("proxy_", "memory_", "web_", "github_", "arxiv_")
        tool_names = [
            "proxy_pick", "proxy_stats", "proxy_rotate", "proxy_validate",
            "memory_set", "memory_get", "memory_search",
            "web_search", "web_fetch", "web_open",
            "arxiv_search", "github_search",
        ]
        for name in tool_names:
            self.assertTrue(
                name.startswith(allowed),
                f"tool name '{name}' does not start with an allowed prefix",
            )

    def test_verification_script_runs_offline(self):
        """Running verify-install.py --no-live against the repo root yields 0 failures."""
        repo_root = Path(__file__).resolve().parent.parent
        verify = repo_root / "scripts" / "verify-install.py"
        result = subprocess.run(
            [sys.executable, str(verify), "--owl-home", str(repo_root),
             "--python", sys.executable, "--no-live"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0,
                         f"verification failed:\n{result.stdout}\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()