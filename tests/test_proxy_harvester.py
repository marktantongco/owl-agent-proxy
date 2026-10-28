#!/usr/bin/env python3
"""
🦉 OWL-AGENT v7.1 — upstream harvester tests.

Everything here runs offline: the four list endpoints and the honeypot probe
endpoint are replaced with fakes. Network-dependent behaviour is covered by the
installer's live checks instead, which skip cleanly when there is no egress.
"""
import asyncio
import ipaddress
import json
import time

import pytest

from proxy_harvester import (
    DEFAULT_SOURCES,
    HoneypotDetector,
    ProxySource,
    SessionAffinityManager,
    SourceHealthTracker,
    UpstreamHarvester,
    is_public_ip,
    normalize_protocol,
    parse_json,
    parse_payload,
    parse_proxy_item,
    parse_text,
    validate_proxy,
)

PROXYSCRAPE_ITEM = {
    "ip": "203.0.113.10",           # documentation range; replaced below with a public IP
    "port": 8080,
    "protocols": ["http", "https"],
    "country_code": "US",
    "uptime_percent": 92.5,
    "latency_ms": 410,
    "anonymity": "elite",
    "ssl": True,
    "asn": 64500,
    "isp": "Example ISP",
    "last_checked": 1700000000,
}

MONOSANS_ITEM = {
    "protocol": "socks5",
    "ip": "8.8.8.8",
    "port": "1080",
    "timeout": 1.4,                       # SECONDS, not milliseconds
    "exit_ip": "8.8.8.8",
    "asn": 15169,
    "geolocation": {"country": {"iso_code": "DE", "name": "Germany"}},
}


def public_item(**overrides):
    item = dict(PROXYSCRAPE_ITEM)
    item["ip"] = "93.184.216.34"          # public, globally routable
    item.update(overrides)
    return item


@pytest.fixture
def proxyscrape_source():
    return ProxySource("proxyscrape_json", "https://example.invalid/a.json", "json",
                       min_uptime=60.0, max_latency_ms=3000.0)


# ── parsing ────────────────────────────────────────────────────────────────
class TestProxyScrapeSchema:
    def test_protocols_list_and_metadata(self, proxyscrape_source):
        proxy = parse_proxy_item(public_item(), proxyscrape_source)
        assert proxy is not None
        assert proxy["url"] == "http://93.184.216.34:8080"
        assert proxy["protocol"] == "http"        # first usable entry wins
        assert proxy["country"] == "US"
        assert proxy["uptime_percent"] == 92.5
        assert proxy["latency_ms"] == 410.0
        assert proxy["source"] == "proxyscrape_json"

    def test_extra_metadata_is_ignored(self, proxyscrape_source):
        item = public_item()
        item.update({"anonymity": "elite", "ssl": True, "asn": 1, "isp": "x",
                     "last_checked": 1, "unknown_future_field": {"nested": True}})
        assert parse_proxy_item(item, proxyscrape_source) is not None

    def test_low_uptime_rejected(self, proxyscrape_source):
        assert parse_proxy_item(public_item(uptime_percent=12.0), proxyscrape_source) is None

    def test_zero_one_uptime_is_rescaled(self, proxyscrape_source):
        proxy = parse_proxy_item(public_item(uptime_percent=0.95), proxyscrape_source)
        assert proxy is not None and proxy["uptime_percent"] == 95.0

    def test_high_latency_rejected(self, proxyscrape_source):
        assert parse_proxy_item(public_item(latency_ms=4500), proxyscrape_source) is None


class TestMonosansSchema:
    def test_nested_geo_and_seconds_timeout(self):
        source = ProxySource("monosans_txt", "https://example.invalid/x.txt", "json",
                             max_latency_ms=3000.0)
        proxy = parse_proxy_item(MONOSANS_ITEM, source)
        assert proxy is not None
        assert proxy["protocol"] == "socks5"
        assert proxy["country"] == "DE"
        assert proxy["latency_ms"] == 1400.0     # 1.4 s → 1400 ms

    def test_seconds_timeout_respects_latency_cap(self):
        source = ProxySource("s", "https://example.invalid/x", "json", max_latency_ms=1000.0)
        assert parse_proxy_item(MONOSANS_ITEM, source) is None


class TestRejectsAndNormalisation:
    @pytest.mark.parametrize("item", [
        {"ip": "10.0.0.5", "port": 80},        # private
        {"ip": "127.0.0.1", "port": 80},       # loopback
        {"ip": "100.64.1.1", "port": 80},      # CGNAT
        {"ip": "0.0.0.0", "port": 80},         # unspecified
        {"ip": "93.184.216.34", "port": 0},
        {"ip": "93.184.216.34", "port": 70000},
        {"ip": "93.184.216.34"},               # no port
        {"ip": "", "port": 8080},
        {"ip": "not-an-ip", "port": 8080},
    ])
    def test_unusable_items_dropped(self, item, proxyscrape_source):
        assert parse_proxy_item(item, proxyscrape_source) is None

    @pytest.mark.parametrize("raw,expected", [
        ("HTTP", "http"),
        ("socks5h", "socks5"),
        (["https"], "https"),
        (["bogus", "socks4"], "socks4"),
        (" ftp ", None),
        (None, None),
        (42, None),
    ])
    def test_normalize_protocol(self, raw, expected):
        assert normalize_protocol(raw) == expected

    def test_is_public_ip(self):
        assert is_public_ip("93.184.216.34")
        assert not is_public_ip("192.168.1.1")
        assert not is_public_ip("::1")

    def test_protocol_hint_used_when_missing(self):
        source = ProxySource("hinted", "https://example.invalid/x", "json",
                             protocol_hint="socks5")
        assert parse_proxy_item({"ip": "93.184.216.34", "port": 1080},
                                source)["protocol"] == "socks5"

    def test_invalid_source_format_rejected(self):
        with pytest.raises(ValueError):
            ProxySource("bad", "https://example.invalid", "xml")


class TestTextParsing:
    def test_plain_and_scheme_lines(self):
        body = """
        # comment
        93.184.216.34:8080
        socks5://8.8.8.8:1080
        http://1.1.1.1:3128  # trailing note
        10.0.0.1:8080
        garbage line
        93.184.216.34:8080
        """
        proxies = parse_text(body)
        urls = [p["url"] for p in proxies]
        assert urls == ["http://93.184.216.34:8080",
                        "socks5://8.8.8.8:1080",
                        "http://1.1.1.1:3128"]

    def test_hint_applied(self):
        proxies = parse_text("8.8.8.8:1080\n", protocol_hint="socks4")
        assert proxies[0]["protocol"] == "socks4"


class TestJsonEnvelopes:
    def test_array(self, proxyscrape_source):
        assert len(parse_json([public_item()], proxyscrape_source)) == 1

    def test_wrapped_proxies_key(self, proxyscrape_source):
        payload = {"proxies": [public_item()], "count": 1}
        assert len(parse_json(payload, proxyscrape_source)) == 1

    def test_map_keyed_by_address(self, proxyscrape_source):
        payload = {"93.184.216.34:8080": {"protocol": "http", "latency_ms": 100}}
        parsed = parse_json(payload, proxyscrape_source)
        assert parsed and parsed[0]["url"] == "http://93.184.216.34:8080"

    def test_country_bucketed_lists(self, proxyscrape_source):
        payload = {"US": [public_item()], "DE": [public_item(ip="1.1.1.1")]}
        assert len(parse_json(payload, proxyscrape_source)) == 2

    def test_json_endpoint_returning_text_falls_back(self, proxyscrape_source):
        payload = "8.8.8.8:3128\n"
        parsed = parse_payload(payload, proxyscrape_source)
        assert parsed and parsed[0]["url"] == "http://8.8.8.8:3128"

    def test_empty_and_none_payloads(self, proxyscrape_source):
        assert parse_payload("", proxyscrape_source) == []
        assert parse_payload([], proxyscrape_source) == []
        assert parse_payload("{}", proxyscrape_source) == []


# ── source health ──────────────────────────────────────────────────────────
class TestSourceHealthTracker:
    def test_ranking_prefers_yield(self):
        tracker = SourceHealthTracker()
        tracker.record("proxyscrape_json", 100, 40)
        tracker.record("monosans_txt", 100, 5)
        tracker.record("maxfeix_txt", 100, 10)
        tracker.record("proxmint_json", 100, 10)
        ranked = tracker.ranked(DEFAULT_SOURCES)
        assert ranked[0].name == "proxyscrape_json"
        assert tracker.yield_rate("proxyscrape_json") > tracker.yield_rate("monosans_txt")

    def test_unknown_source_neutral(self):
        assert SourceHealthTracker().yield_rate("never_seen") == 0.5

    def test_decay_and_failures(self):
        tracker = SourceHealthTracker(decay=0.5)
        tracker.record("s", 100, 100)
        tracker.record("s", 0, 0, ok=False, error="HTTP 503")
        snapshot = tracker.snapshot()["s"]
        assert snapshot["fetched"] == pytest.approx(50.0)
        assert snapshot["failures"] == 1
        assert snapshot["last_error"] == "HTTP 503"
        tracker.record("s", 10, 10, ok=True)
        assert tracker.snapshot()["s"]["last_error"] is None

    def test_disabled_sources_excluded(self):
        sources = [ProxySource("on", "https://example.invalid/a"),
                   ProxySource("off", "https://example.invalid/b", enabled=False)]
        assert [s.name for s in SourceHealthTracker().ranked(sources)] == ["on"]

    def test_invalid_decay(self):
        with pytest.raises(ValueError):
            SourceHealthTracker(decay=0)


# ── harvester ──────────────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload, fmt="json", status=200):
        self._payload = payload
        self._fmt = fmt
        self.status_code = status
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        if self._fmt != "json":
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, responses, errors=()):
        self.responses = responses
        self.errors = set(errors)
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        if url in self.errors:
            raise RuntimeError("connection refused")
        return self.responses[url]


def make_source(name, url, fmt="json"):
    return ProxySource(name, url, fmt)


@pytest.mark.asyncio
class TestUpstreamHarvester:
    async def test_harvest_parses_and_dedupes(self):
        src_a = make_source("a", "https://a.invalid/list.json")
        src_b = make_source("b", "https://b.invalid/list.txt", "txt")
        client = FakeClient({
            src_a.url: FakeResponse([public_item()]),
            src_b.url: FakeResponse("8.8.8.8:1080\n93.184.216.34:8080\n"),
        })
        harvester = UpstreamHarvester(sources=[src_a, src_b], client=client)

        first = await harvester.harvest()
        assert {p["url"] for p in first} == {"http://93.184.216.34:8080",
                                            "http://8.8.8.8:1080"}
        assert {p["source"] for p in first} == {"a", "b"}

        second = await harvester.harvest()
        assert second == []            # already seen

        health = harvester.health.snapshot()
        # decayed: fetched = 0.85*1 + 1, valid = 0.85*1 + 0
        assert health["a"]["yield_rate"] == pytest.approx(0.459, abs=0.01)

        # a full snapshot must not inflate the yield signal
        snapshot = await harvester.harvest(include_seen=True)
        assert len(snapshot) == 2
        assert harvester.health.yield_rate("a") < 0.459

    async def test_one_broken_source_does_not_stop_the_other(self):
        good = make_source("good", "https://good.invalid/a.json")
        bad = make_source("bad", "https://bad.invalid/a.json")
        client = FakeClient({good.url: FakeResponse([public_item()])}, errors={bad.url})
        harvester = UpstreamHarvester(sources=[good, bad], client=client)

        proxies = await harvester.harvest()
        assert len(proxies) == 1
        health = harvester.health.snapshot()
        assert health["bad"]["failures"] == 1
        assert "connection refused" in health["bad"]["last_error"]

    async def test_max_per_source_caps_output(self):
        src = make_source("a", "https://a.invalid/a.json")
        items = [public_item(ip=f"93.184.216.{i}") for i in range(1, 11)]
        harvester = UpstreamHarvester(sources=[src],
                                      client=FakeClient({src.url: FakeResponse(items)}))
        assert len(await harvester.harvest(max_per_source=3)) == 3

    async def test_json_endpoint_returning_text_is_tolerated(self):
        src = make_source("a", "https://a.invalid/a.json")
        response = FakeResponse("8.8.8.8:3128\n", fmt="txt")
        harvester = UpstreamHarvester(sources=[src], client=FakeClient({src.url: response}))
        assert len(await harvester.harvest()) == 1

    async def test_requires_context_without_client(self):
        harvester = UpstreamHarvester()
        assert harvester._client is None


# ── honeypot detector ─────────────────────────────────────────────────────
class TestHoneypotDetector:
    def test_structural_hash_ignores_value_churn(self):
        detector = HoneypotDetector()
        a = detector._hash(b'{"slideshow": {"title": "x", "n": 1}}')
        b = detector._hash(b'{"slideshow": {"title": "y", "n": 2}}')
        assert a == b

    def test_hash_detects_injected_script(self):
        detector = HoneypotDetector()
        clean = detector._hash(b'{"slideshow": {"title": "x"}}')
        tampered = detector._hash(b'<html><script>alert(1)</script></html>')
        assert clean != tampered

    def test_hash_detects_structure_change(self):
        detector = HoneypotDetector()
        assert detector._hash(b'{"slideshow": {}}') != detector._hash(b'{"other": {}}')

    async def test_no_baseline_fails_open(self):
        detector = HoneypotDetector()
        trusted, reason = await detector.check("http://93.184.216.34:8080")
        assert trusted is True and reason == "no-baseline"

    def test_skeleton_types(self):
        skeleton = HoneypotDetector._skeleton({"a": [1, "x", {"b": 2.5}]})
        assert skeleton == [("a", ["int", "str", [("b", "float")]])]


# ── session affinity ──────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestSessionAffinity:
    async def test_bind_get_invalidate(self):
        manager = SessionAffinityManager(ttl_seconds=60)
        assert await manager.get("a1", "example.com") is None
        await manager.bind("a1", "example.com", "http://93.184.216.34:8080")
        assert await manager.get("a1", "example.com") == "http://93.184.216.34:8080"
        assert await manager.get("a1", "other.com") is None
        assert await manager.get("a2", "example.com") is None
        assert await manager.invalidate("a1", "example.com") is True
        assert await manager.get("a1", "example.com") is None

    async def test_ttl_expiry(self):
        now = [1000.0]
        manager = SessionAffinityManager(ttl_seconds=10, clock=lambda: now[0])
        await manager.bind("a1", "example.com", "http://1.2.3.4:80")
        now[0] += 5
        assert await manager.get("a1", "example.com") is not None
        now[0] += 6
        assert await manager.get("a1", "example.com") is None

    async def test_max_bindings_evicts_oldest(self):
        manager = SessionAffinityManager(ttl_seconds=60, max_bindings=2)
        await manager.bind("a", "one.com", "http://1.1.1.1:80")
        await manager.bind("a", "two.com", "http://2.2.2.2:80")
        await manager.bind("a", "three.com", "http://3.3.3.3:80")
        assert len(manager) == 2
        assert await manager.get("a", "one.com") is None
        assert await manager.get("a", "three.com") == "http://3.3.3.3:80"

    async def test_stats_and_clear(self):
        manager = SessionAffinityManager(ttl_seconds=60)
        await manager.bind("a1", "example.com", "http://1.1.1.1:80")
        await manager.bind("a2", "example.com", "http://2.2.2.2:80")
        await manager.get("a1", "example.com")
        stats = await manager.stats()
        assert stats["active"] == 2
        assert stats["by_domain"] == {"example.com": 2}
        assert stats["served"] == 1
        assert await manager.clear("a1") == 1
        assert (await manager.stats())["active"] == 1
        assert await manager.clear() == 1
        assert (await manager.stats())["active"] == 0

    async def test_sweeper_lifecycle(self):
        manager = SessionAffinityManager(ttl_seconds=60, sweep_interval=0.01)
        await manager.start()
        await manager.bind("a", "x.com", "http://1.1.1.1:80")
        assert len(await manager.bindings()) == 1
        await manager.stop()
        assert manager._sweeper is None

    async def test_bind_returns_previous(self):
        manager = SessionAffinityManager(ttl_seconds=60)
        assert await manager.bind("a", "x.com", "http://1.1.1.1:80") is None
        assert await manager.bind("a", "x.com", "http://2.2.2.2:80") == "http://1.1.1.1:80"


# ── probe helper (no network) ─────────────────────────────────────────────
@pytest.mark.asyncio
class TestValidateProxy:
    @pytest.mark.parametrize("url", [
        "not-a-proxy",
        "http://",
        "socks5://93.184.216.34:1080",   # unsupported scheme for this probe
    ])
    async def test_rejects_malformed_or_unsupported(self, url):
        assert await validate_proxy(url) is None

    async def test_unreachable_returns_none_quickly(self):
        started = time.perf_counter()
        assert await validate_proxy("http://127.0.0.1:9", timeout=0.5) is None
        assert time.perf_counter() - started < 3
