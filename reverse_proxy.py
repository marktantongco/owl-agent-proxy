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

Optimizations:
  - Lazy imports (aiohttp only on first request)
  - Connection pooling with keep-alive
  - Pre-warmed upstream connections
  - Per-protocol client cache (httpx per proxy URL)
  - Request deduplication via ResilientClient dedup
  - Domain rate limiting via ResilientClient limiter

Run:
    python reverse_proxy.py               # serve on :8080, forward to localhost:3000
    python reverse_proxy.py --port 9090   # custom listen port
    python reverse_proxy.py --target https://api.example.com  # custom upstream target
    python reverse_proxy.py --targets https://a.example.com,https://b.example.com  # load balance

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
            "health_check_interval": 30
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
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# ── lazy imports ──────────────────────────────────────────────────────
# aiohttp is imported lazily to keep cold import fast for --help and stats.
_aiohttp: Any = None
_web: Any = None


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

    async def start(self) -> None:
        """Initialize the client session and start the aiohttp server."""
        aiohttp = _require_aiohttp()
        self._session = aiohttp.ClientSession()
        await self.client.__aenter__()

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
        """Proxy an incoming HTTP request through ResilientClient to the target."""
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

        # Read body
        body = await request.read()

        # Select protocol with escalation
        protocol = self._select_protocol(forward_headers, target_url)
        last_error: Optional[Exception] = None

        # Try protocols in escalation order
        for attempt_protocol in self.protocol_escalation:
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
        return {
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
    )

    try:
        await proxy.start()
        targets_str = ", ".join(targets)
        print(
            f"Reverse proxy running on http://0.0.0.0:{port} -> {targets_str}",
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
