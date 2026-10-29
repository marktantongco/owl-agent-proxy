#!/usr/bin/env python3
"""
🦉 OWL-AGENT — pool backend seam tests (offline).

The request path depends on the ``PoolBackend`` Protocol, not on
``ProxyRotator`` directly, so a paid provider or a test double can be injected
without editing core. ``ProxyRotator`` remains the default implementation and is
expected to stay small — its upstream lifecycle lives in
``UpstreamHarvestingMixin``.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

import proxy_defense as pd


class FakePool:
    """Minimal in-memory backend satisfying ``PoolBackend``."""

    def __init__(self, proxies: Optional[List[pd.ProxyEntry]] = None) -> None:
        self.proxies = proxies or []
        self.picked: List[str] = []
        self.banned: List[str] = []
        self.started = False
        self.sources_loaded = 0

    async def get_proxy(self, domain=None, agent_id="default", rotation_mode="sticky"):
        self.picked.append(domain or "")
        return self.proxies[0] if self.proxies else None

    async def mark_banned(self, proxy):
        self.banned.append(proxy.url)
        proxy.mark_failed()

    async def load_all_sources(self, session=None):
        self.sources_loaded += 1

    def load_cache(self) -> int:
        return 0

    def save_cache(self) -> None:
        pass

    async def start_upstream(self) -> bool:
        self.started = True
        return True

    async def stop_upstream(self) -> None:
        self.started = False

    async def session_stats(self) -> Dict[str, Any]:
        return {"active": 0, "ttl_seconds": 900, "by_domain": {}}

    def source_health(self) -> Dict[str, Any]:
        return {"fake": {"ok": True}}

    def upstream_stats(self) -> Dict[str, Any]:
        return {"enabled": True, "running": self.started, "harvested_total": 0}


def test_proxy_rotator_satisfies_protocol():
    assert isinstance(pd.ProxyRotator(), pd.PoolBackend)


def test_fake_pool_satisfies_protocol():
    assert isinstance(FakePool(), pd.PoolBackend)


def test_injected_pool_replaces_default_rotator():
    pool = FakePool()
    client = pd.ResilientClient(pool=pool)
    assert client.rotator is pool


def test_default_pool_is_proxy_rotator():
    client = pd.ResilientClient()
    assert isinstance(client.rotator, pd.ProxyRotator)


async def test_stats_come_from_injected_pool():
    pool = FakePool()
    client = pd.ResilientClient(pool=pool)
    stats = await client.get_stats()

    assert stats["proxies_total"] == 0
    assert stats["upstream_harvester"]["running"] is False
    assert stats["source_health"] == {"fake": {"ok": True}}


async def test_injected_pool_selection_and_ban_are_used():
    entry = pd.ProxyEntry(url="http://198.51.100.7:8080", proxy_type="free",
                       protocol="http", source="manual", tier=1)
    pool = FakePool([entry])
    client = pd.ResilientClient(pool=pool)

    picked = await client.rotator.get_proxy(domain="example.com", agent_id="job-1")
    assert picked is entry
    assert pool.picked == ["example.com"]

    await client.rotator.mark_banned(picked)
    assert pool.banned == ["http://198.51.100.7:8080"]


def test_upstream_lifecycle_lives_in_mixin():
    for name in (
        "start_upstream",
        "stop_upstream",
        "harvest_once",
        "_harvest_loop",
        "_validation_loop",
        "_validate_entry",
        "source_health",
        "upstream_stats",
    ):
        assert hasattr(pd.UpstreamHarvestingMixin, name), name
        assert not name in pd.ProxyRotator.__dict__, f"{name} should be inherited, not redefined"


def test_proxy_rotator_body_stays_small():
    source = Path(pd.__file__).read_text().splitlines()
    start = next(i for i, line in enumerate(source) if line.startswith("class ProxyRotator"))
    end = next(i for i, line in enumerate(source) if line.startswith("class ResilientClient:"))
    assert end - start <= 250, f"ProxyRotator is {end - start} lines; keep it under 250"
