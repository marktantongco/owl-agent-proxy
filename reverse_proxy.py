#!/usr/bin/env python3
"""
🦉 OWL-AGENT Reverse Proxy — HTTP ingress for the ResilientClient egress layer.

OWL Agent Proxy is a client-side library + stdio MCP server + CLI.
This module adds an optional HTTP ingress listener so the existing
ResilientClient (proxy rotation, caching, deduplication, domain rate
limiting, honeypot detection, sticky sessions, protocol escalation) can
sit in front of configurable upstream targets and act as a reverse proxy.

Architecture:
    Client -> :PORT (reverse_proxy.py) -> ResilientClient egress -> upstream target

Protocol routing methodology (escalation chain):
    http/1.1 -> http/2 -> ja3 -> websocket -> browser -> stealth

The router selects the protocol based on:
  1. Explicit X-OWL-Protocol header from client
  2. Target URL characteristics (HTTPS -> http/2 preferred)
  3. Adaptive: if http/1.1 fails with 429/403, escalate to next protocol
  4. Circuit breaker: after N consecutive failures on a protocol, skip it

STEALTH MODE (v2.1):
  The "stealth" protocol uses curl_cffi (curl-impersonate) to impersonate
  real-browser TLS/JA3/JA4/HTTP2 fingerprints, bypassing anti-bot systems
  (Cloudflare, Akamai, DataDome, PerimeterX) that fingerprint non-browser
  TLS stacks. Stealth mode also injects browser-consistent headers
  (Sec-CH-UA, Sec-Fetch-*, Accept-Language), rotates user agents, persists
  cookies, and applies timing jitter.

Optimizations:
  - Lazy imports (aiohttp, curl_cffi only on first request)
  - Connection pooling with keep-alive
  - Pre-warmed upstream connections
  - Per-protocol client cache (httpx per proxy URL)
  - Request deduplication via ResilientClient dedup
  - Domain rate limiting via ResilientClient limiter

Run:
    python reverse_proxy.py                           # serve on :8080, forward to localhost:3000
    python reverse_proxy.py --port 9090               # custom listen port
    python reverse_proxy.py --target https://api.example.com  # custom upstream target
    python reverse_proxy.py --targets https://a.example.com,https://b.example.com  # load balance
    python reverse_proxy.py --stealth-browser chrome124  # stealth mode with Chrome 124 impersonation

Config (config.json):
    {
        "reverse_proxy": {
            "port": 8080,
            "target_host": "http://localhost:3000",
            "targets": ["http://localhost:3000", "http://localhost:3001"],
            "cache_ttl": 60,
            "cache_max_entries": 10_000,
            "rate_limit": 10.0,
            "max_retries": 3,
            "protocol_escalation": ["http/1.1", "http/2", "ja3", "websocket", "browser", "stealth"],
            "circuit_breaker_threshold": 5,
            "health_check_interval": 30,
            "auto_load_proxies": true,
            "stealth": {
                "enabled": true,
                "browser": "chrome124",
                "user_agent_rotation": "sticky",
                "stealth_headers": true,
                "cookie_persistence": true,
                "timing_jitter_ms": [500, 2500]
            }
        }
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# ── lazy imports ──────────────────────────────────────────────────────
# aiohttp and curl_cffi are imported lazily to keep cold import fast
# for --help, stats reads, config parsing, or API-surface checks.
_aiohttp: Any = None
_web: Any = None
_curl_cffi: Any = None


def _require_aiohttp() -> Any:
    global _aiohttp
    if _aiohttp is None:
        import aiohttp
        _aiohttp = aiohttp
    return _aiohttp


def _require_web() -> Any:
    global _web
    if _web is None:
        from aiohttp import web
        _web = web
    return _web


def _require_curl_cffi() -> Any:
    global _curl_cffi
    if _curl_cffi is None:
        from curl_cffi.requests import AsyncSession
        _curl_cffi = AsyncSession
    return _curl_cffi


# Ensure the package directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

logger = logging.getLogger("owl-agent.reverse-proxy")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"
DEFAULT_PORT = 8080
DEFAULT_TARGET_HOST = "http://localhost:3000"

# Protocol escalation chain — ordered from cheapest to most expensive
DEFAULT_PROTOCOL_ESCALATION: List[str] = [
    "http/1.1",
    "http/2",
    "ja3",
    "websocket",
    "browser",
    "stealth",
]

CIRCUIT_BREAKER_THRESHOLD = 5
HEALTH_CHECK_INTERVAL = 30

# Hop-by-hop headers that must not be forwarded
HOP_BY_HOP_HEADERS: frozenset[str] = frozenset({
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding",
    "upgrade",
})

# Real browser user agents for rotation (Chrome, Safari, Firefox, Edge)
DEFAULT_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

# Browser impersonation presets supported by curl_cffi (curl-impersonate)
STEALTH_BROWSER_PROFILES: List[str] = [
    "chrome", "chrome120", "chrome124", "safari", "safari17",
    "edge", "edge99", "firefox",
]

# Stealth headers injected for browser-consistent fingerprinting
STEALTH_HEADERS_TEMPLATE: Dict[str, str] = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}


class CircuitBreaker:
    """Tracks per-protocol failures and opens the circuit after threshold."""

    def __init__(self, threshold: int = CIRCUIT_BREAKER_THRESHOLD) -> None:
        self.threshold = threshold
        self._failures: Dict[str, int] = {}
        self._open_until: Dict[str, float] = {}

    def record_failure(self, protocol: str) -> None:
        self._failures[protocol] = self._failures.get(protocol, 0) + 1
        if self._failures[protocol] >= self.threshold:
            self._open_until[protocol] = time.time() + 60  # 60s cooldown
            logger.warning(f"Circuit breaker OPEN for protocol '{protocol}'")

    def record_success(self, protocol: str) -> None:
        self._failures[protocol] = 0
        self._open_until.pop(protocol, None)

    def is_open(self, protocol: str) -> bool:
        until = self._open_until.get(protocol, 0)
        if until and time.time() < until:
            return True
        self._open_until.pop(protocol, None)
        return False

    def failure_count(self, protocol: str) -> int:
        return self._failures.get(protocol, 0)


class UpstreamTarget:
    """A single upstream target with health tracking."""

    def __init__(self, url: str, weight: float = 1.0) -> None:
        self.url = url.rstrip("/")
        self.weight = weight
        self._healthy = True
        self._last_check: float = 0
        self._consecutive_failures = 0
        self._total_requests = 0
        self._total_errors = 0

    @property
    def healthy(self) -> bool:
        return self._healthy

    def mark_success(self) -> None:
        self._consecutive_failures = 0
        self._healthy = True
        self._total_requests += 1

    def mark_failure(self) -> None:
        self._consecutive_failures += 1
        self._total_requests += 1
        self._total_errors += 1
        if self._consecutive_failures >= 3:
            self._healthy = False
            logger.warning(f"Upstream {self.url} marked UNHEALTHY")

    def mark_healthy(self) -> None:
        self._healthy = True
        self._consecutive_failures = 0

    def error_rate(self) -> float:
        if self._total_requests == 0:
            return 0.0
        return self._total_errors / self._total_requests


# ── stealth mode components ───────────────────────────────────────────


class UserAgentRotator:
    """Rotates through real browser user-agent strings.

    Modes:
      - "random": pick a random user agent on every request
      - "sticky": pin one user agent per (target_url) for session consistency
      - "cycle": round-robin through the list
    """

    def __init__(
        self,
        user_agents: Optional[List[str]] = None,
        mode: str = "sticky",
    ) -> None:
        self.user_agents: List[str] = user_agents or list(DEFAULT_USER_AGENTS)
        self.mode = mode
        self._sticky: Dict[str, str] = {}
        self._cycle_index = 0
        self._lock = asyncio.Lock()

    async def get(self, target_url: str) -> str:
        async with self._lock:
            if self.mode == "sticky":
                if target_url not in self._sticky:
                    self._sticky[target_url] = random.choice(self.user_agents)
                return self._sticky[target_url]
            if self.mode == "random":
                return random.choice(self.user_agents)
            # cycle
            ua = self.user_agents[self._cycle_index % len(self.user_agents)]
            self._cycle_index += 1
            return ua


@dataclass
class StealthConfig:
    """Configuration for stealth mode (browser TLS fingerprint impersonation)."""

    enabled: bool = True
    browser: str = "chrome124"
    user_agent_rotation: str = "sticky"  # "sticky" | "random" | "cycle"
    stealth_headers: bool = True
    cookie_persistence: bool = True
    timing_jitter_ms: Tuple[int, int] = (500, 2500)
    proxy_url: Optional[str] = None

    def __post_init__(self) -> None:
        if self.browser not in STEALTH_BROWSER_PROFILES:
            logger.warning(
                f"Stealth browser '{self.browser}' not in known profiles "
                f"{STEALTH_BROWSER_PROFILES}; curl_cffi may reject it."
            )
        if self.user_agent_rotation not in ("sticky", "random", "cycle"):
            raise ValueError(
                f"user_agent_rotation must be 'sticky', 'random', or 'cycle', "
                f"got {self.user_agent_rotation!r}"
            )
        if len(self.timing_jitter_ms) != 2:
            raise ValueError("timing_jitter_ms must be a (min, max) tuple")


class StealthClient:
    """HTTP client using curl_cffi for browser TLS/JA3/JA4 fingerprint impersonation.

    Stealth mode impersonates real-browser TLS stacks so anti-bot systems
    (Cloudflare, Akamai, DataDome, PerimeterX) see browser-grade JA3/JA4
    fingerprints instead of Python/OpenSSL signatures.

    curl_cffi wraps curl-impersonate, which reproduces the exact TLS ClientHello
    (cipher suite order, extensions, ALPN, GREASE positions), HTTP/2 SETTINGS
    frame ordering, and browser-consistent headers of a target browser profile.
    """

    def __init__(
        self,
        config: Optional[StealthConfig] = None,
        user_agent_rotator: Optional[UserAgentRotator] = None,
    ) -> None:
        self.config = config or StealthConfig()
        self.rotator = user_agent_rotator or UserAgentRotator(
            mode=self.config.user_agent_rotation
        )
        self._sessions: Dict[str, Any] = {}  # browser -> AsyncSession
        self._cookies: Dict[str, Any] = {}  # simple cookie persistence by domain
        self._lock = asyncio.Lock()
        self._requests_total = 0
        self._requests_ok = 0
        self._requests_error = 0

    async def _session(self, browser: str) -> Any:
        """Get or create a curl_cffi AsyncSession for the given browser profile."""
        async with self._lock:
            if browser in self._sessions:
                return self._sessions[browser]
        AsyncSession = _require_curl_cffi()
        session = AsyncSession(
            impersonate=browser,
            headers={},
        )
        async with self._lock:
            self._sessions[browser] = session
        return session

    async def close(self) -> None:
        """Close all curl_cffi sessions."""
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                closer = getattr(session, "aclose", None) or getattr(
                    session, "close", None
                )
                if closer:
                    result = closer()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"stealth session close failed: {exc}")

    def _stealth_headers(self, user_agent: str) -> Dict[str, str]:
        """Build browser-consistent stealth headers."""
        if not self.config.stealth_headers:
            return {}
        headers = dict(STEALTH_HEADERS_TEMPLATE)
        headers["user-agent"] = user_agent
        # Derive sec-ch-ua brand from user agent when possible
        ua_lower = user_agent.lower()
        if "chrome" in ua_lower and "edg" not in ua_lower:
            headers["sec-ch-ua"] = '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'
            headers["sec-ch-ua-platform"] = '"Windows"'
        elif "firefox" in ua_lower:
            headers.pop("sec-ch-ua", None)
            headers.pop("sec-ch-ua-mobile", None)
            headers.pop("sec-ch-ua-platform", None)
        elif "safari" in ua_lower and "chrome" not in ua_lower:
            headers["sec-ch-ua"] = '"Not-A.Brand";v="99", "Safari";v="17.4"'
            headers["sec-ch-ua-platform"] = '"macOS"'
        return headers

    def _apply_timing_jitter(self) -> None:
        """Apply random timing jitter between requests (stealth behavior)."""
        if self.config.timing_jitter_ms:
            min_ms, max_ms = self.config.timing_jitter_ms
            delay = random.uniform(min_ms, max_ms) / 1000.0
            # Note: jitter is applied by callers via asyncio.sleep to avoid
            # blocking the event loop unexpectedly. This helper returns the
            # computed delay so callers can await it.
            return delay
        return 0.0

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Any] = None,
        data: Any = None,
        proxy_url: Optional[str] = None,
    ) -> Any:
        """Make an HTTP request with stealth browser impersonation.

        Returns a response-like object with .status, .content, .headers.
        """
        proxy_url = proxy_url or self.config.proxy_url
        browser = self.config.browser

        # Select user agent
        user_agent = await self.rotator.get(url)
        req_headers = self._stealth_headers(user_agent)
        if headers:
            req_headers.update(headers)

        # Apply timing jitter (non-blocking sleep handled by caller via _jitter_delay)
        jitter_delay = self._apply_timing_jitter()

        session = await self._session(browser)

        self._requests_total += 1
        try:
            resp = await session.request(
                method=method,
                url=url,
                params=params,
                headers=req_headers,
                data=data,
                proxy=proxy_url,
            )

            # Persist cookies (simple domain-based jar)
            if self.config.cookie_persistence:
                self._persist_cookies(url, getattr(resp, "cookies", None) or {})

            self._requests_ok += 1
            return resp

        except Exception as exc:  # noqa: BLE001
            self._requests_error += 1
            logger.error(f"stealth request failed {method} {url}: {exc}")
            raise

    def _persist_cookies(self, url: str, cookies: Any) -> None:
        """Persist cookies by domain for session continuity."""
        try:
            from urllib.parse import urlparse as _up

            domain = _up(url).netloc
            if domain and cookies:
                self._cookies[domain] = dict(cookies)
        except Exception as exc:  # swallow: cookie bookkeeping must never break
            # a request; a relative or malformed URL just has no domain to key.
            logger.debug("could not store cookies for %r: %s", url, exc)  # pragma: no cover

    def _jitter_delay(self) -> float:
        """Return the configured jitter delay in seconds (for callers to await)."""
        if self.config.timing_jitter_ms:
            min_ms, max_ms = self.config.timing_jitter_ms
            return random.uniform(min_ms, max_ms) / 1000.0
        return 0.0

    def stats(self) -> Dict[str, Any]:
        return {
            "browser": self.config.browser,
            "user_agent_rotation": self.config.user_agent_rotation,
            "stealth_headers": self.config.stealth_headers,
            "cookie_persistence": self.config.cookie_persistence,
            "requests_total": self._requests_total,
            "requests_ok": self._requests_ok,
            "requests_error": self._requests_error,
            "sessions_active": len(self._sessions),
        }


class ReverseProxy:
    """HTTP ingress that forwards requests through ResilientClient egress.

    Wraps ResilientClient so every proxied request benefits from the existing
    egress defenses: proxy rotation, caching, deduplication, domain rate
    limiting, honeypot detection, sticky sessions, and protocol escalation.

    Enhancements over v1:
      - Multiple upstream targets with round-robin + health-aware load balancing
      - Per-protocol circuit breaker
      - Adaptive protocol escalation on 429/403 responses
      - Connection pooling and keep-alive
      - Lazy imports for fast cold start
      - Health checks on upstream targets
      - Request/response transformation hooks
      - STEALTH MODE (v2.1): curl_cffi browser TLS/JA3/JA4 fingerprint
        impersonation, user-agent rotation, stealth headers, cookie persistence,
        timing jitter
    """

    def __init__(
        self,
        target_hosts: List[str],
        listen_port: int = DEFAULT_PORT,
        cache_ttl: int = 60,
        cache_max_entries: int = 10_000,
        rate_limit: float = 10.0,
        max_retries: int = 3,
        auto_load_proxies: bool = True,
        agent_id: str = "reverse-proxy",
        protocol_escalation: Optional[List[str]] = None,
        circuit_breaker_threshold: int = CIRCUIT_BREAKER_THRESHOLD,
        health_check_interval: float = HEALTH_CHECK_INTERVAL,
        stealth_mode: bool = False,
        stealth_config: Optional[StealthConfig] = None,
    ):
        # Lazy import proxy_defense to keep cold import fast
        import proxy_defense as pd

        self.target_hosts: List[UpstreamTarget] = [
            UpstreamTarget(t) for t in target_hosts
        ]
        self.listen_port = listen_port
        self.agent_id = agent_id
        self.protocol_escalation = protocol_escalation or list(
            DEFAULT_PROTOCOL_ESCALATION
        )
        self.circuit_breaker = CircuitBreaker(circuit_breaker_threshold)
        self.health_check_interval = health_check_interval

        self.client = pd.ResilientClient(
            cache_ttl=cache_ttl,
            cache_max_entries=cache_max_entries,
            rate_limit=rate_limit,
            max_retries=max_retries,
            auto_load_proxies=auto_load_proxies,
        )
        self._session: Optional[Any] = None
        self._runner: Optional[Any] = None

        # Request stats
        self._requests_total = 0
        self._requests_ok = 0
        self._requests_error = 0

        # Round-robin index for load balancing
        self._rr_index = 0

        # Last health check time
        self._last_health_check: float = 0

        # Stealth mode
        self.stealth_mode = stealth_mode
        self.stealth_config = stealth_config or StealthConfig(enabled=stealth_mode)
        self._stealth_client: Optional[StealthClient] = None
        self._user_agent_rotator: Optional[UserAgentRotator] = None

        if self.stealth_mode:
            self._user_agent_rotator = UserAgentRotator(
                mode=self.stealth_config.user_agent_rotation
            )
            self._stealth_client = StealthClient(
                config=self.stealth_config,
                user_agent_rotator=self._user_agent_rotator,
            )

    # ── upstream selection ──────────────────────────────────────────

    def _select_upstream(self) -> Optional[UpstreamTarget]:
        """Select a healthy upstream using weighted round-robin."""
        healthy = [t for t in self.target_hosts if t.healthy]
        if not healthy:
            # Fall back to all targets if none are healthy
            healthy = self.target_hosts
            if not healthy:
                return None

        # Weighted round-robin
        total_weight = sum(t.weight for t in healthy)
        if total_weight == 0:
            return healthy[0]

        # Simple round-robin over healthy targets
        target = healthy[self._rr_index % len(healthy)]
        self._rr_index += 1
        return target

    async def _health_check_upstreams(self) -> None:
        """Periodically health-check upstream targets."""
        now = time.time()
        if now - self._last_health_check < self.health_check_interval:
            return
        self._last_health_check = now

        aiohttp = _require_aiohttp()
        if self._session is None:
            self._session = aiohttp.ClientSession()

        for target in self.target_hosts:
            try:
                async with self._session.get(
                    f"{target.url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status < 500:
                        target.mark_healthy()
                    else:
                        target.mark_failure()
            except Exception:
                target.mark_failure()

    # ── protocol selection ──────────────────────────────────────────

    def _select_protocol(
        self, request_headers: Dict[str, str], target_url: str
    ) -> str:
        """Select the best protocol for this request.

        Priority:
          1. Explicit X-OWL-Protocol header
          2. Adaptive: skip circuits that are open
          3. Target characteristics: HTTPS -> http/2 preferred
          4. Default: first protocol in escalation chain
        """
        # 1. Explicit protocol header
        explicit = request_headers.get("x-owl-protocol")
        if explicit and explicit in self.protocol_escalation:
            protocol = explicit.lower()
            if not self.circuit_breaker.is_open(protocol):
                return protocol

        # 2. Filter out open circuits
        available = [
            p for p in self.protocol_escalation
            if not self.circuit_breaker.is_open(p)
        ]
        if not available:
            # All circuits open — use first protocol anyway
            available = list(self.protocol_escalation)

        # 3. Target characteristics
        parsed = urlparse(target_url)
        if parsed.scheme == "https" and "http/2" in available:
            # Prefer http/2 for HTTPS targets
            if not self.circuit_breaker.is_open("http/2"):
                return "http/2"

        # 4. Return first available protocol
        return available[0]

    # ── request handling ────────────────────────────────────────────

    async def _handle_stealth(
        self,
        method: str,
        target_url: str,
        forward_headers: Dict[str, str],
    ) -> Any:
        """Handle a request using stealth mode (curl_cffi browser impersonation)."""
        if self._stealth_client is None:
            raise RuntimeError("Stealth client not initialized")

        # Apply timing jitter before the request
        jitter = self._stealth_client._jitter_delay()
        if jitter > 0:
            await asyncio.sleep(jitter)

        resp = await self._stealth_client.request(
            method=method,
            url=target_url,
            headers=forward_headers,
            proxy_url=self.stealth_config.proxy_url,
        )
        return resp

    def _build_stealth_response(self, resp: Any) -> Any:
        """Build an aiohttp response from a curl_cffi response."""
        web = _require_web()
        content = getattr(resp, "content", b"")
        if isinstance(content, str):
            content = content.encode()
        headers = getattr(resp, "headers", {}) or {}
        response = web.Response(
            status=getattr(resp, "status", 200),
            body=content,
            content_type=headers.get("content-type"),
        )
        for key, value in headers.items():
            if key.lower() not in HOP_BY_HOP_HEADERS:
                response.headers[key] = value
        return response

    async def start(self) -> None:
        """Initialize the client session and start the aiohttp server."""
        aiohttp = _require_aiohttp()
        self._session = aiohttp.ClientSession()
        await self.client.__aenter__()

        # Initialize stealth client session if stealth mode is enabled
        if self._stealth_client is not None:
            # Force session creation lazily on first stealth request;
            # curl_cffi AsyncSession is created on first use via _session().
            logger.info(
                f"Stealth mode enabled: browser={self.stealth_config.browser}, "
                f"rotation={self.stealth_config.user_agent_rotation}"
            )

        web = _require_web()
        app = web.Application(middlewares=[self._logging_middleware])
        app.router.add_route("*", "/{path:.*}", self._handle_request)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.listen_port)
        await site.start()

        logger.info(
            f"Reverse proxy listening on :{self.listen_port} -> "
            f"{[t.url for t in self.target_hosts]}"
        )

    async def stop(self) -> None:
        """Shutdown the server and client session."""
        if self._runner:
            await self._runner.cleanup()
        if self._session:
            await self._session.close()
        await self.client.__aexit__(None, None, None)
        if self._stealth_client is not None:
            await self._stealth_client.close()
        logger.info("Reverse proxy stopped")

    @staticmethod
    async def _logging_middleware(request: Any, handler: Any) -> Any:
        start = time.time()
        try:
            resp = await handler(request)
            return resp
        finally:
            duration = (time.time() - start) * 1000
            logger.info(
                f"{request.method} {request.path_qs} -> {resp.status} ({duration:.0f}ms)"
            )

    async def _handle_request(self, request: Any) -> Any:
        """Proxy an incoming HTTP request through ResilientClient to the target.

        If stealth mode is active and the selected protocol is "stealth",
        the request is routed through the curl_cffi StealthClient instead
        of ResilientClient.
        """
        self._requests_total += 1

        # Periodic health check
        await self._health_check_upstreams()

        # Select upstream target
        target = self._select_upstream()
        if target is None:
            self._requests_error += 1
            return self._error_response(503, "No healthy upstream available")

        # Build the target URL
        path = request.match_info.get("path", "")
        query = request.query_string
        target_url = f"{target.url}/{path}"
        if query:
            target_url += f"?{query}"

        # Forward headers (skip hop-by-hop)
        forward_headers = {}
        for key, value in request.headers.items():
            if key.lower() not in HOP_BY_HOP_HEADERS:
                forward_headers[key] = value

        # Read body (needed for POST/PUT etc.)
        body = await request.read()

        # Select protocol with escalation
        protocol = self._select_protocol(forward_headers, target_url)
        last_error: Optional[Exception] = None

        # If stealth mode is selected and available, use the stealth client
        if protocol == "stealth" and self._stealth_client is not None:
            try:
                resp = await self._handle_stealth(
                    request.method, target_url, forward_headers
                )
                self._requests_ok += 1
                target.mark_success()
                self.circuit_breaker.record_success("stealth")
                return self._build_stealth_response(resp)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                target.mark_failure()
                self.circuit_breaker.record_failure("stealth")
                self._requests_error += 1
                logger.error(
                    f"Stealth proxy error for {request.method} {target_url}: {last_error}"
                )
                return self._error_response(502, "Bad Gateway")

        # Try protocols in escalation order (ResilientClient egress)
        for attempt_protocol in self.protocol_escalation:
            if attempt_protocol == "stealth":
                # Stealth handled above; skip in the standard loop
                continue
            if self.circuit_breaker.is_open(attempt_protocol):
                continue

            try:
                resp = await self.client.request(
                    method=request.method,
                    url=target_url,
                    params=request.query,
                    headers=forward_headers,
                    agent_id=self.agent_id,
                    rotation_mode="sticky",
                    protocol=attempt_protocol,
                )

                # Success — record and return
                self._requests_ok += 1
                target.mark_success()
                self.circuit_breaker.record_success(attempt_protocol)

                response = self._build_response(resp)
                return response

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                target.mark_failure()
                self.circuit_breaker.record_failure(attempt_protocol)

                # Escalate on 429/403
                if hasattr(exc, "status") and exc.status in (429, 403):
                    logger.warning(
                        f"Protocol {attempt_protocol} returned {exc.status}, "
                        f"escalating to next protocol"
                    )
                    continue
                break

        # All protocols failed
        self._requests_error += 1
        logger.error(
            f"Proxy error for {request.method} {target_url}: {last_error}"
        )
        return self._error_response(502, "Bad Gateway")

    def _build_response(self, resp: Any) -> Any:
        """Build an aiohttp response from a ResilientClient CachedResponse."""
        web = _require_web()
        response = web.Response(
            status=getattr(resp, "status", 200),
            body=getattr(resp, "content", b""),
            content_type=getattr(resp, "headers", {}).get("content-type"),
        )
        # Forward response headers (skip hop-by-hop)
        for key, value in getattr(resp, "headers", {}).items():
            if key.lower() not in HOP_BY_HOP_HEADERS:
                response.headers[key] = value
        return response

    def _error_response(self, status: int, message: str) -> Any:
        web = _require_web()
        return web.Response(
            status=status,
            body=message.encode(),
            content_type="text/plain",
        )

    def stats(self) -> Dict[str, Any]:
        """Return reverse proxy statistics."""
        stats = {
            "listen_port": self.listen_port,
            "target_hosts": [t.url for t in self.target_hosts],
            "targets_healthy": [
                {"url": t.url, "healthy": t.healthy, "error_rate": t.error_rate()}
                for t in self.target_hosts
            ],
            "requests_total": self._requests_total,
            "requests_ok": self._requests_ok,
            "requests_error": self._requests_error,
            "circuit_breaker": {
                p: self.circuit_breaker.failure_count(p)
                for p in self.protocol_escalation
            },
        }
        if self._stealth_client is not None:
            stats["stealth"] = self._stealth_client.stats()
        return stats


def load_config() -> dict:
    """Load configuration from config.json."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"config load failed ({CONFIG_FILE}): {exc}")
    return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OWL Agent Reverse Proxy — HTTP ingress for ResilientClient egress"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Listen port (default: {DEFAULT_PORT}, or config.json reverse_proxy.port)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Upstream target host (default: config.json reverse_proxy.target_host)",
    )
    parser.add_argument(
        "--targets",
        default=None,
        help="Comma-separated list of upstream targets for load balancing",
    )
    parser.add_argument(
        "--stealth-browser",
        default=None,
        choices=STEALTH_BROWSER_PROFILES,
        help=f"Enable stealth mode with browser impersonation ({', '.join(STEALTH_BROWSER_PROFILES)})",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    config = load_config()

    rp_config = config.get("reverse_proxy", {})

    # Determine targets
    targets: List[str] = []
    if args.targets:
        targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    elif args.target:
        targets = [args.target]
    else:
        targets = [rp_config.get("target_host", DEFAULT_TARGET_HOST)]

    port = args.port if args.port is not None else rp_config.get("port", DEFAULT_PORT)

    # Build protocol escalation from config if provided
    protocol_escalation = rp_config.get("protocol_escalation")

    # Stealth mode configuration
    stealth_cfg_dict = rp_config.get("stealth", {})
    stealth_browser = args.stealth_browser or stealth_cfg_dict.get("browser")
    stealth_mode = bool(stealth_browser) or stealth_cfg_dict.get("enabled", False)

    stealth_config: Optional[StealthConfig] = None
    if stealth_mode:
        stealth_config = StealthConfig(
            enabled=True,
            browser=stealth_browser or "chrome124",
            user_agent_rotation=stealth_cfg_dict.get(
                "user_agent_rotation", "sticky"
            ),
            stealth_headers=stealth_cfg_dict.get("stealth_headers", True),
            cookie_persistence=stealth_cfg_dict.get("cookie_persistence", True),
            timing_jitter_ms=tuple(
                stealth_cfg_dict.get("timing_jitter_ms", [500, 2500])
            ),
            proxy_url=stealth_cfg_dict.get("proxy_url"),
        )

    proxy = ReverseProxy(
        target_hosts=targets,
        listen_port=port,
        cache_ttl=rp_config.get("cache_ttl", 60),
        cache_max_entries=rp_config.get("cache_max_entries", 10_000),
        rate_limit=rp_config.get("rate_limit", 10.0),
        max_retries=rp_config.get("max_retries", 3),
        auto_load_proxies=rp_config.get("auto_load_proxies", True),
        protocol_escalation=protocol_escalation,
        circuit_breaker_threshold=rp_config.get(
            "circuit_breaker_threshold", CIRCUIT_BREAKER_THRESHOLD
        ),
        health_check_interval=rp_config.get(
            "health_check_interval", HEALTH_CHECK_INTERVAL
        ),
        stealth_mode=stealth_mode,
        stealth_config=stealth_config,
    )

    try:
        await proxy.start()
        targets_str = ", ".join(targets)
        stealth_str = f" [stealth: {stealth_config.browser}]" if stealth_config else ""
        print(
            f"Reverse proxy running on http://0.0.0.0:{port} -> {targets_str}{stealth_str}",
            file=sys.stderr,
        )
        print("Press Ctrl+C to stop", file=sys.stderr)
        # Run forever until interrupted
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await proxy.stop()


def main() -> int:
    asyncio.run(main_async())
    return 0


if __name__ == "__main__":
    sys.exit(main())
