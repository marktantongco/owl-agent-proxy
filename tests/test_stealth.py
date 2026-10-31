#!/usr/bin/env python3
"""
🦉 OWL-AGENT — stealth browser rung tests (offline, no browser required).

`invisible_playwright` ships a ~550 MB patched Firefox, so these tests exercise
the rung with a fake engine. They assert the contract that matters:

  * the engine is never imported at module load,
  * asking for a protocol this machine cannot run fails loudly and *fast*,
  * the pool's proxy reaches the engine,
  * a missing dependency never gets a healthy proxy banned for it.

The fake engine also stands in for the real one when the library *is* installed,
so the suite behaves the same in both cases.
"""
import asyncio
import subprocess
import sys
import time

import pytest

import proxy_defense as pd


# ── a fake engine with the same async-context-manager shape ────────────────
class FakePage:
    def __init__(self):
        self.goto_url = None
        self.goto_kwargs = {}
        self.closed = False
        self.html = "<html><body>ok</body></html>"

    async def goto(self, url, **kwargs):
        self.goto_url = url
        self.goto_kwargs = kwargs

    async def content(self):
        return self.html

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


class FakeStealth:
    """Records how it was constructed; yields a browser from __aenter__."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.page = FakePage()
        self.exited = False
        FakeStealth.instances.append(self)

    async def __aenter__(self):
        return FakeBrowser(self.page)

    async def __aexit__(self, *exc):
        self.exited = True
        return False


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeStealth.instances = []
    yield
    FakeStealth.instances = []


def _client(**kwargs):
    return pd.ResilientClient(auto_load_proxies=False, **kwargs)


# ── liveness / packaging contract ──────────────────────────────────────────
def test_engine_is_not_imported_at_module_load():
    """The 550 MB engine must stay out of the hot import path."""
    code = (
        "import sys, proxy_defense\n"
        "assert 'invisible_playwright' not in sys.modules, sorted(sys.modules)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_stats_report_stealth_capability():
    async def scenario():
        async with _client() as client:
            return await client.get_stats()

    stats = asyncio.run(scenario())
    assert "stealth" in stats["protocols_available"]
    assert isinstance(stats["protocols_available"]["stealth"], bool)


# ── unavailable: loud, fast, and blameless ─────────────────────────────────
async def test_missing_engine_raises_protocol_unavailable(monkeypatch):
    monkeypatch.setattr(pd, "_load_stealth", lambda: None)
    async with _client() as client:
        with pytest.raises(pd.ProtocolUnavailable) as exc:
            await client._request_stealth("https://example.com", None)

    message = str(exc.value)
    assert "invisible-playwright" in message
    assert "fetch" in message          # the binary step nobody discovers on their own


async def test_missing_engine_is_not_retried(monkeypatch):
    """A missing dependency is a configuration error, not a transient one."""
    monkeypatch.setattr(pd, "_load_stealth", lambda: None)
    client = _client()
    client.max_retries = 5

    started = time.perf_counter()
    with pytest.raises(pd.ProtocolUnavailable):
        await client._execute_with_retry(
            "GET", "https://example.com", {}, {}, "stealth")
    elapsed = time.perf_counter() - started

    # Five retries with exponential backoff would take seconds; failing fast
    # proves the exception short-circuits the loop.
    assert elapsed < 1.0, f"took {elapsed:.2f}s — the retry loop was not bypassed"


async def test_unavailable_protocol_does_not_ban_the_proxy(monkeypatch):
    """The proxy is innocent when the browser engine is missing."""
    monkeypatch.setattr(pd, "_load_stealth", lambda: None)
    entry = pd.ProxyEntry(url="http://198.51.100.9:8080", proxy_type="free",
                          protocol="http", source="test", tier=1)
    client = _client()
    client.rotator.proxies = [entry]

    with pytest.raises(pd.ProtocolUnavailable):
        await client._execute_with_retry(
            "GET", "https://example.com", {}, {}, "stealth")

    assert entry.is_banned() is False and entry.fail_count == 0


async def test_router_refuses_to_downgrade_silently(monkeypatch):
    """Requesting stealth must not quietly return an http/1.1 response."""
    monkeypatch.setattr(pd, "_load_stealth", lambda: None)
    async with _client() as client:
        with pytest.raises(pd.ProtocolUnavailable):
            await client.request("GET", "https://example.com", protocol="stealth")


# ── available: the rung actually drives the engine ─────────────────────────
async def test_engine_receives_the_pool_proxy(monkeypatch):
    monkeypatch.setattr(pd, "_load_stealth", lambda: FakeStealth)
    async with _client() as client:
        response = await client._request_stealth(
            "https://example.com", "http://198.51.100.7:8080")

    launch = FakeStealth.instances[0].kwargs
    assert launch["proxy"] == {"server": "http://198.51.100.7:8080"}
    assert launch["headless"] is True
    assert response.protocol == "stealth"
    assert b"ok" in response.content


async def test_no_proxy_means_no_proxy_config(monkeypatch):
    monkeypatch.setattr(pd, "_load_stealth", lambda: FakeStealth)
    async with _client() as client:
        await client._request_stealth("https://example.com", None)

    assert FakeStealth.instances[0].kwargs["proxy"] is None


async def test_timezone_is_passed_through_when_pinned(monkeypatch):
    monkeypatch.setattr(pd, "_load_stealth", lambda: FakeStealth)
    async with _client() as client:
        await client._request_stealth(
            "https://example.com", None, timezone="Asia/Manila", locale="en-PH")

    launch = FakeStealth.instances[0].kwargs
    assert launch["timezone"] == "Asia/Manila"
    assert launch["locale"] == "en-PH"


async def test_timezone_omitted_leaves_engine_default(monkeypatch):
    monkeypatch.setattr(pd, "_load_stealth", lambda: FakeStealth)
    async with _client() as client:
        await client._request_stealth("https://example.com", None)

    assert "timezone" not in FakeStealth.instances[0].kwargs


async def test_page_is_closed_and_navigation_uses_timeout(monkeypatch):
    monkeypatch.setattr(pd, "_load_stealth", lambda: FakeStealth)
    async with _client() as client:
        await client._request_stealth("https://example.com", None, timeout=7)

    fake = FakeStealth.instances[0]
    assert fake.page.goto_url == "https://example.com"
    assert fake.page.goto_kwargs["timeout"] == 7000
    assert fake.page.closed is True
    assert fake.exited is True       # context manager tore the browser down


async def test_navigation_failure_still_closes_the_page(monkeypatch):
    class Boom(FakeStealth):
        async def __aenter__(self):
            browser = await super().__aenter__()

            async def explode(url, **kwargs):
                raise RuntimeError("net::ERR_TIMED_OUT")

            browser._page.goto = explode
            return browser

    monkeypatch.setattr(pd, "_load_stealth", lambda: Boom)
    async with _client() as client:
        with pytest.raises(RuntimeError, match="ERR_TIMED_OUT"):
            await client._request_stealth("https://example.com", None)

    assert Boom.instances[0].page.closed is True
    assert Boom.instances[0].exited is True
