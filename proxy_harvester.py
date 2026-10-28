#!/usr/bin/env python3
"""
🦉 OWL-AGENT v7.1 — upstream proxy harvester, honeypot detector, session affinity.

This module is deliberately dependency-light: ``httpx`` is imported lazily so that
the pure parsing / affinity / hashing helpers can be imported and unit-tested on a
machine with no third-party packages installed at all.

Public surface
--------------
ProxySource, DEFAULT_SOURCES      source registry
parse_text, parse_json, parse_payload, parse_proxy_item
SourceHealthTracker               per-source yield learning (0.85 decay)
UpstreamHarvester                 async fetch + dedupe across sources
HoneypotDetector                  structural-hash body-integrity check
SessionAffinityManager            sticky proxy per (agent_id, domain)
validate_proxy                    TCP + HTTP-through-proxy probe

Default sources (all four are plain HTTPS list endpoints):

    proxyscrape_json   JSON array, rich metadata, ``protocols`` is a *list*
    maxfeix_txt        plain text, upstream-screened for honeypots/injection/TLS
    monosans_txt       plain text, fastest-first
    proxmint_json      JSON, re-validated upstream, ``score`` field

Schemas differ between sources, so extraction is field-alias based and tolerant:
unknown extra fields are ignored, missing optional metadata is fine, and items
that cannot be normalised are dropped instead of raising.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("owl-agent.harvester")

DEFAULT_TIMEOUT = 15.0
USER_AGENT = "owl-agent-harvester/7.1"
VALID_PROTOCOLS = ("http", "https", "socks4", "socks5")

# ── field alias tables ──────────────────────────────────────────────────────
_IP_KEYS = ("ip", "host", "address", "proxy_ip", "ip_address", "ipAddress")
_PORT_KEYS = ("port", "proxy_port", "proxyPort")
_PROTO_KEYS = ("protocol", "protocols", "type", "scheme", "proxy_type", "proxyType")
_COUNTRY_KEYS = ("country_code", "country_code_iso", "country", "cc", "iso_code", "countryCode")
_UPTIME_KEYS = ("uptime_percent", "uptime", "uptime_pct", "uptimePercent")
_LATENCY_KEYS = ("latency_ms", "latency", "latencyMs", "response_time", "responseTime")

_RE_LINE = re.compile(
    r"^(?:(?P<scheme>http|https|socks4|socks5)://)?"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{1,5})(?:\s.*)?$",
    re.IGNORECASE,
)


def _first(mapping: Dict[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    """Return the first present, non-None value for any alias in ``keys``."""
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def normalize_protocol(value: Any) -> Optional[str]:
    """Normalise ``protocol``/``protocols``/``type`` into one of VALID_PROTOCOLS.

    Sources differ: ProxyScrape emits a *list* (``["http", "https"]``), monosans
    emits a string, some lists emit ``"HTTP"`` or ``"socks5"``. The first usable
    entry wins.
    """
    if isinstance(value, (list, tuple, set)):
        for item in value:
            normalised = normalize_protocol(item)
            if normalised:
                return normalised
        return None
    if not isinstance(value, str):
        return None
    protocol = value.strip().lower()
    if protocol in VALID_PROTOCOLS:
        return protocol
    # tolerate "http/https", "socks5h", "HTTP proxy"
    for candidate in VALID_PROTOCOLS:
        if protocol.startswith(candidate):
            return candidate
    return None


def is_public_ip(ip: str) -> bool:
    """True only for globally routable IPv4 addresses.

    Free lists occasionally contain private, loopback, CGNAT or reserved blocks.
    Those can never reach the public internet, so they are dropped at parse time
    rather than becoming permanently "failed" pool entries.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4:
        return False
    return bool(addr.is_global) and not any(
        addr in ipaddress.ip_network(net)
        for net in ("0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "198.18.0.0/15",
                    "240.0.0.0/4")
    )


def _latency_ms(item: Dict[str, Any]) -> Optional[float]:
    """Best-effort latency in milliseconds.

    ``monosans`` reports ``timeout`` in **seconds**; most others report
    ``latency_ms`` already in milliseconds. Explicit millisecond keys win, and a
    bare ``timeout`` is converted.
    """
    value = _first(item, _LATENCY_KEYS)
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    timeout = item.get("timeout")
    if isinstance(timeout, (int, float)):
        try:
            return float(timeout) * 1000.0
        except (TypeError, ValueError):
            return None
    return None


def _uptime_percent(item: Dict[str, Any]) -> Optional[float]:
    value = _first(item, _UPTIME_KEYS)
    if value is None:
        return None
    try:
        uptime = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 < uptime <= 1.0:  # some sources emit a 0-1 ratio
        uptime *= 100.0
    return uptime


def _country(item: Dict[str, Any]) -> Optional[str]:
    value = _first(item, _COUNTRY_KEYS)
    if isinstance(value, dict):
        value = value.get("iso_code") or value.get("code") or next(iter(value.values()), None)
    if not value:
        # monosans nests it: {"geolocation": {"country": {"iso_code": "US"}}}
        geo = item.get("geolocation")
        if isinstance(geo, dict):
            country = geo.get("country")
            if isinstance(country, dict):
                value = country.get("iso_code") or country.get("code")
            else:
                value = country
    if isinstance(value, str) and value.strip():
        return value.strip().upper()[:2] if len(value.strip()) <= 3 else value.strip().upper()
    return None


@dataclass
class ProxySource:
    """One upstream list endpoint."""

    name: str
    url: str
    format: str = "txt"                  # "txt" | "json"
    protocol_hint: Optional[str] = None  # used when the source omits protocol
    min_uptime: float = 0.0
    max_latency_ms: float = 99_999.0
    enabled: bool = True
    tier: int = 4                        # pool tier: managed=1 ... free upstream=4

    def __post_init__(self) -> None:
        if self.format not in ("txt", "json"):
            raise ValueError(f"unsupported source format: {self.format}")
        if self.protocol_hint:
            hint = normalize_protocol(self.protocol_hint)
            if not hint:
                raise ValueError(f"unsupported protocol hint: {self.protocol_hint}")
            self.protocol_hint = hint


# Four live, high-yield sources (v7.1). Names are stable identifiers — the health
# tracker and the MCP ``proxy_stats`` payload key off them.
DEFAULT_SOURCES: List[ProxySource] = [
    ProxySource(
        "proxyscrape_json",
        "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/all/data.json",
        "json",
        min_uptime=60.0,
        max_latency_ms=3000.0,
    ),
    # Upstream-screened for honeypots, injection and broken TLS — treat as the
    # highest-trust seed, but still re-validate locally.
    ProxySource(
        "maxfeix_txt",
        "https://maximilianfeix.github.io/proxy-scraper/all.txt",
        "txt",
    ),
    ProxySource(
        "monosans_txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/all.txt",
        "txt",
    ),
    ProxySource(
        "proxmint_json",
        "https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/all.json",
        "json",
        max_latency_ms=5000.0,
    ),
]


# ── parsing ────────────────────────────────────────────────────────────────
def parse_proxy_item(item: Any, source: ProxySource) -> Optional[Dict[str, Any]]:
    """Normalise one list item into ``{"url", "protocol", "country", ...}``.

    Returns ``None`` when the item is not a usable public proxy.
    """
    if not isinstance(item, dict):
        return None
    try:
        ip = str(_first(item, _IP_KEYS, "")).strip()
        port = int(str(_first(item, _PORT_KEYS, "")).strip())
    except (TypeError, ValueError):
        return None
    if not is_public_ip(ip) or not (1 <= port <= 65535):
        return None

    protocol = normalize_protocol(_first(item, _PROTO_KEYS)) or source.protocol_hint or "http"

    uptime = _uptime_percent(item)
    if uptime is not None and uptime < source.min_uptime:
        return None

    latency = _latency_ms(item)
    if latency is not None and latency > source.max_latency_ms:
        return None

    proxy = {
        "url": f"{protocol}://{ip}:{port}",
        "protocol": protocol,
        "country": _country(item),
        "source": source.name,
    }
    if uptime is not None:
        proxy["uptime_percent"] = round(uptime, 2)
    if latency is not None:
        proxy["latency_ms"] = round(latency, 1)
    return proxy


def parse_text(text: str, protocol_hint: Optional[str] = None,
               source_name: str = "txt") -> List[Dict[str, Any]]:
    """Parse ``ip:port`` lines, with optional ``scheme://`` prefix and trailing comments."""
    hint = normalize_protocol(protocol_hint) if protocol_hint else None
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _RE_LINE.match(line)
        if not match:
            continue
        ip = match.group("ip")
        port = int(match.group("port"))
        if not is_public_ip(ip) or not (1 <= port <= 65535):
            continue
        protocol = (match.group("scheme") or hint or "http").lower()
        url = f"{protocol}://{ip}:{port}"
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "protocol": protocol, "country": None,
                    "source": source_name})
    return out


def _iter_items(data: Any) -> Iterable[Any]:
    """Yield candidate items from any of the observed JSON envelopes."""
    if isinstance(data, list):
        yield from data
        return
    if not isinstance(data, dict):
        return
    for key in ("proxies", "data", "results", "list", "items", "proxies_list"):
        if isinstance(data.get(key), list):
            yield from data[key]
            return
    # {"1.2.3.4:8080": {...}} style maps
    synthesised = 0
    for key, value in data.items():
        if isinstance(key, str) and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}:\d{1,5}", key):
            ip, _, port = key.partition(":")
            item = dict(value) if isinstance(value, dict) else {}
            item.setdefault("ip", ip)
            item.setdefault("port", port)
            synthesised += 1
            yield item
    if synthesised:
        return
    # {"US": [ ... ], "DE": [ ... ]} style maps
    for value in data.values():
        if isinstance(value, list):
            yield from value


def parse_json(data: Any, source: ProxySource) -> List[Dict[str, Any]]:
    """Parse any observed JSON envelope through ``parse_proxy_item``."""
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in _iter_items(data):
        proxy = parse_proxy_item(item, source)
        if proxy and proxy["url"] not in seen:
            seen.add(proxy["url"])
            out.append(proxy)
    return out


def parse_payload(payload: Any, source: ProxySource) -> List[Dict[str, Any]]:
    """Parse a response body according to ``source.format`` with a txt fallback."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if source.format == "json":
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                # a source that silently switched to text should not kill the harvest
                return parse_text(payload, source.protocol_hint, source.name)
        return parse_json(payload, source)
    if isinstance(payload, (list, dict)):
        return parse_json(payload, source)
    return parse_text(str(payload or ""), source.protocol_hint, source.name)


# ── source health ──────────────────────────────────────────────────────────
@dataclass
class _SourceStats:
    fetched: float = 0.0
    valid: float = 0.0
    failures: float = 0.0
    last_fetch: float = 0.0
    last_error: Optional[str] = None


class SourceHealthTracker:
    """Exponentially-weighted per-source yield, used to rank fetch order.

    ``yield_rate`` is ``valid / fetched`` after decay, so a source that returns
    5,000 entries of which 40 are new/usable scores far higher than one that
    returns 3,000 duplicates. Unknown sources default to 0.5 so they get sampled.
    """

    def __init__(self, decay: float = 0.85) -> None:
        if not (0.0 < decay <= 1.0):
            raise ValueError("decay must be in (0, 1]")
        self._decay = decay
        self._stats: Dict[str, _SourceStats] = defaultdict(_SourceStats)

    def record(self, name: str, fetched: int, valid: int, ok: bool = True,
               error: Optional[str] = None) -> None:
        stats = self._stats[name]
        stats.fetched = stats.fetched * self._decay + max(0, fetched)
        stats.valid = stats.valid * self._decay + max(0, valid)
        stats.last_fetch = time.time()
        if not ok:
            stats.failures += 1
            stats.last_error = (error or "unknown error")[:200]
        else:
            stats.last_error = None

    def yield_rate(self, name: str) -> float:
        stats = self._stats.get(name)
        if not stats or stats.fetched <= 0:
            return 0.5
        return min(1.0, stats.valid / max(1.0, stats.fetched))

    def ranked(self, sources: Sequence[ProxySource]) -> List[ProxySource]:
        """Enabled sources, best-yield first (ties broken by staleness, then name)."""
        return sorted(
            [s for s in sources if s.enabled],
            key=lambda s: (-self.yield_rate(s.name),
                           self._stats[s.name].last_fetch,
                           s.name),
        )

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: {
                "fetched": round(stats.fetched, 2),
                "valid": round(stats.valid, 2),
                "yield_rate": round(self.yield_rate(name), 4),
                "failures": int(stats.failures),
                "last_fetch": stats.last_fetch,
                "last_error": stats.last_error,
            }
            for name, stats in self._stats.items()
        }


# ── harvester ──────────────────────────────────────────────────────────────
class UpstreamHarvester:
    """Fetch every enabled source concurrently, normalise, and dedupe.

    ``harvest()`` only returns proxies never seen by this harvester before, which
    is what the pool wants (new candidates). Pass ``include_seen=True`` for a
    full current snapshot (used by diagnostics).
    """

    def __init__(self, sources: Optional[Sequence[ProxySource]] = None,
                 timeout: float = DEFAULT_TIMEOUT, concurrency: int = 4,
                 client: Any = None) -> None:
        self.sources: List[ProxySource] = list(sources or DEFAULT_SOURCES)
        self.timeout = timeout
        self.concurrency = max(1, int(concurrency))
        self.health = SourceHealthTracker()
        self._client = client
        self._owns_client = client is None
        self._sem = asyncio.Semaphore(self.concurrency)
        self._seen: Set[str] = set()
        self._last: Dict[str, List[Dict[str, Any]]] = {}

    async def __aenter__(self) -> "UpstreamHarvester":
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise RuntimeError("httpx is required for harvesting") from exc
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
            self._owns_client = True
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._owns_client and self._client is not None:
            closer = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
            if closer:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
        self._client = None if self._owns_client else self._client

    async def fetch(self, source: ProxySource) -> Tuple[ProxySource, List[Dict[str, Any]], Optional[str]]:
        """Fetch and parse a single source. Never raises: errors are recorded."""
        if self._client is None:
            raise RuntimeError("UpstreamHarvester must be used as an async context manager")
        async with self._sem:
            try:
                response = await self._client.get(source.url)
                response.raise_for_status()
                if source.format == "json":
                    try:
                        payload: Any = response.json()
                    except Exception:  # some "json" endpoints return text
                        payload = response.text
                else:
                    payload = response.text
                proxies = parse_payload(payload, source)
                return source, proxies, None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("harvest %s failed: %s", source.name, exc)
                return source, [], f"{type(exc).__name__}: {exc}"

    async def harvest(self, max_per_source: int = 300,
                      include_seen: bool = False) -> List[Dict[str, Any]]:
        """Return new proxies across all sources (best source first)."""
        if self._client is None:
            async with self:
                return await self.harvest(max_per_source, include_seen)

        ordered = self.health.ranked(self.sources)
        results = await asyncio.gather(*(self.fetch(src) for src in ordered))

        out: List[Dict[str, Any]] = []
        emitted: Set[str] = set()
        for source, proxies, error in results:
            fresh = [p for p in proxies if include_seen or p["url"] not in self._seen]
            self._last[source.name] = proxies
            # a full snapshot (include_seen=True) says nothing about *new* yield
            self.health.record(source.name, len(proxies),
                               0 if include_seen else len(fresh),
                               ok=error is None, error=error)
            for proxy in fresh[:max_per_source]:
                # the same exit often appears in several lists — first source wins
                if proxy["url"] in emitted:
                    continue
                emitted.add(proxy["url"])
                out.append(proxy)
                # Record exactly what was returned: candidates beyond
                # max_per_source must stay eligible for the next sweep, and a
                # URL dropped here must not be marked seen by a later source.
                if not include_seen:
                    self._seen.add(proxy["url"])

        healthy = sum(1 for _, _, error in results if error is None)
        logger.info("harvested %d new proxies from %d/%d sources",
                    len(out), healthy, len(results))
        return out

    def last_snapshot(self) -> Dict[str, int]:
        """Per-source count from the most recent successful fetch."""
        return {name: len(items) for name, items in self._last.items()}


# ── honeypot / injection detector ─────────────────────────────────────────
class HoneypotDetector:
    """Detect proxies that tamper with response bodies.

    Strategy: fetch ``TEST_URL`` directly to capture a *structural* hash of the
    JSON (keys + value types, not values, so ordinary churn does not trigger),
    then fetch it through a candidate proxy and compare. Catches:

    * injected redirects (3xx where a direct request is 200)
    * injected markup (``<script`` in a JSON body)
    * truncated / replaced bodies (different structure)

    When no baseline can be established (offline, endpoint down) the detector
    fails *open* — returning "no-baseline" — because a missing baseline must not
    silently empty the pool.

    Scope limit worth stating plainly: the probe URL is HTTPS, so an HTTP proxy
    can only tunnel the connection and cannot rewrite the body without breaking
    TLS. In practice this catches proxies that intercept, redirect or MITM at
    the CONNECT stage (surfacing as a status change, a TLS error or a body that
    is not the expected document), and it catches plain-HTTP tampering when
    pointed at an ``http://`` test URL. It is not a general "detect any
    malicious proxy" oracle.
    """

    TEST_URL = "https://httpbin.org/json"
    EXPECTED_KEYS = frozenset({"slideshow"})

    def __init__(self, timeout: float = 8.0, test_url: Optional[str] = None,
                 baseline_ttl: float = 3600.0, verdict_ttl: float = 300.0) -> None:
        self.timeout = timeout
        self.test_url = test_url or self.TEST_URL
        self.baseline_ttl = baseline_ttl
        self.verdict_ttl = verdict_ttl
        self._baseline: Optional[str] = None
        self._baseline_at = 0.0
        self._verdicts: Dict[str, Tuple[float, bool, str]] = {}

    @staticmethod
    def _skeleton(obj: Any) -> Any:
        if isinstance(obj, dict):
            return sorted((str(k), HoneypotDetector._skeleton(v)) for k, v in obj.items())
        if isinstance(obj, list):
            return [HoneypotDetector._skeleton(v) for v in obj[:3]]
        return type(obj).__name__

    def _hash(self, body: bytes) -> str:
        try:
            data = json.loads(body)
            return hashlib.sha256(
                json.dumps(self._skeleton(data), sort_keys=True).encode()
            ).hexdigest()
        except Exception:
            scripts = body.lower().count(b"<script")
            # length is bucketed so trivial dynamic noise does not flip the hash
            return hashlib.sha256(
                f"len:{len(body) // 64}:scripts:{scripts}".encode()
            ).hexdigest()

    @property
    def has_baseline(self) -> bool:
        return self._baseline is not None and (
            self.baseline_ttl <= 0 or time.time() - self._baseline_at < self.baseline_ttl
        )

    async def establish_baseline(self) -> bool:
        if self.has_baseline:
            return True
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.timeout,
                                         follow_redirects=False) as client:
                response = await client.get(self.test_url)
                response.raise_for_status()
                try:
                    keys = set(response.json().keys())
                except Exception:
                    keys = set()
                if not (self.EXPECTED_KEYS & keys):
                    logger.warning("honeypot baseline has unexpected shape: %s", sorted(keys))
                    return False
                self._baseline = self._hash(response.content)
                self._baseline_at = time.time()
                return True
        except Exception as exc:
            logger.warning("honeypot baseline failed: %s", exc)
            return False

    async def check(self, proxy_url: str, use_cache: bool = True) -> Tuple[bool, str]:
        """Return ``(trusted, reason)``. Never raises."""
        cached = self._verdicts.get(proxy_url)
        if use_cache and cached and time.time() - cached[0] < self.verdict_ttl:
            return cached[1], cached[2]
        if not self.has_baseline:
            # A baseline can expire (baseline_ttl) or never have existed; try
            # once more rather than failing open for the rest of the process.
            if not await self.establish_baseline():
                return True, "no-baseline"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.timeout, proxy=proxy_url,
                                         follow_redirects=False) as client:
                response = await client.get(self.test_url)
                verdict: Tuple[bool, str]
                if 300 <= response.status_code < 400:
                    verdict = (False, "injected-redirect")
                elif response.status_code != 200:
                    verdict = (False, f"status-{response.status_code}")
                elif self._hash(response.content) != self._baseline:
                    scripts = response.content.lower().count(b"<script")
                    verdict = (
                        (False, f"content-mismatch-scripts:{scripts}")
                        if scripts
                        else (False, "content-mismatch")
                    )
                else:
                    verdict = (True, "ok")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            name = type(exc).__name__
            verdict = (False, f"error:{name}")
        self._verdicts[proxy_url] = (time.time(), verdict[0], verdict[1])
        return verdict

    def forget(self, proxy_url: Optional[str] = None) -> None:
        if proxy_url is None:
            self._verdicts.clear()
        else:
            self._verdicts.pop(proxy_url, None)


# ── proxy probe (used by MCP proxy_validate and the pool validator) ──────
async def validate_proxy(proxy_url: str, timeout: float = 8.0,
                         probe_url: str = "https://httpbin.org/status/200") -> Optional[Dict[str, Any]]:
    """TCP-connect then fetch ``probe_url`` through ``proxy_url``.

    Returns timing metrics, or ``None`` when the proxy cannot be used. Timing is
    intentionally split so a dead proxy (TCP) is distinguishable from a proxy
    that connects but cannot carry an HTTP request.
    """
    from urllib.parse import urlparse

    parsed = urlparse(proxy_url)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return None
    if parsed.scheme not in ("http", "https"):
        # socks needs an extra dependency; report unsupported instead of lying
        return None

    metrics: Dict[str, Any] = {"url": proxy_url, "protocol": parsed.scheme}
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        metrics["tcp_ms"] = round((time.perf_counter() - started) * 1000, 1)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    except Exception:
        return None

    try:
        import httpx
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_url,
                                     follow_redirects=False) as client:
            response = await client.get(probe_url)
        metrics["http_ms"] = round((time.perf_counter() - started) * 1000, 1)
        metrics["status"] = response.status_code
        metrics["ok"] = 200 <= response.status_code < 400
    except Exception:
        metrics["http_ms"] = None
        metrics["ok"] = False
        metrics["status"] = None
    return metrics


# ── session affinity ───────────────────────────────────────────────────────
@dataclass
class Binding:
    proxy_url: str
    domain: str
    agent_id: str
    expires_at: float
    served: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"proxy": self.proxy_url, "domain": self.domain,
                "agent_id": self.agent_id, "expires_at": self.expires_at,
                "served": self.served}


class SessionAffinityManager:
    """Sticky proxy per ``(agent_id, domain)``.

    Why: a mid-session exit-IP change makes a target site see "a user
    teleporting between cities", which is itself a strong bot signal. Binding one
    proxy to one agent+domain for a TTL is the cheapest way to stay coherent.

    Honest limitation (documented in docs/V7_UPSTREAM.md): this makes the *IP*
    sticky, not the TLS/HTTP fingerprint. Fingerprint coherence is per-client
    static in this stack.
    """

    def __init__(self, ttl_seconds: float = 900.0, sweep_interval: float = 60.0,
                 max_bindings: int = 5000, clock=time.time) -> None:
        self.ttl = max(1.0, float(ttl_seconds))
        self.sweep_interval = max(1.0, float(sweep_interval))
        self.max_bindings = max(1, int(max_bindings))
        self._clock = clock
        self._bindings: Dict[Tuple[str, str], Binding] = {}
        self._lock = asyncio.Lock()
        self._sweeper: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop())

    async def stop(self) -> None:
        if self._sweeper and not self._sweeper.done():
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
        self._sweeper = None

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self.sweep_interval)
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("affinity sweep failed: %s", exc)

    async def sweep(self) -> int:
        now = self._clock()
        async with self._lock:
            expired = [key for key, binding in self._bindings.items()
                       if binding.expires_at <= now]
            for key in expired:
                del self._bindings[key]
            return len(expired)

    async def get(self, agent_id: str, domain: str) -> Optional[str]:
        async with self._lock:
            binding = self._bindings.get((agent_id, domain))
            if binding is None:
                return None
            if binding.expires_at <= self._clock():
                del self._bindings[(agent_id, domain)]
                return None
            binding.served += 1
            return binding.proxy_url

    async def bind(self, agent_id: str, domain: str, proxy_url: str) -> Optional[str]:
        """Bind and return the previously bound proxy (if any)."""
        async with self._lock:
            previous = self._bindings.get((agent_id, domain))
            if len(self._bindings) >= self.max_bindings and (agent_id, domain) not in self._bindings:
                oldest = min(self._bindings, key=lambda k: self._bindings[k].expires_at)
                del self._bindings[oldest]
            self._bindings[(agent_id, domain)] = Binding(
                proxy_url=proxy_url,
                domain=domain,
                agent_id=agent_id,
                expires_at=self._clock() + self.ttl,
            )
            return previous.proxy_url if previous else None

    async def invalidate(self, agent_id: str, domain: str) -> bool:
        async with self._lock:
            return self._bindings.pop((agent_id, domain), None) is not None

    async def clear(self, agent_id: Optional[str] = None) -> int:
        async with self._lock:
            if agent_id is None:
                count = len(self._bindings)
                self._bindings.clear()
                return count
            keys = [key for key in self._bindings if key[0] == agent_id]
            for key in keys:
                del self._bindings[key]
            return len(keys)

    async def bindings(self) -> List[Dict[str, Any]]:
        async with self._lock:
            now = self._clock()
            return [binding.as_dict() for binding in self._bindings.values()
                    if binding.expires_at > now]

    async def stats(self) -> Dict[str, Any]:
        async with self._lock:
            now = self._clock()
            live = [b for b in self._bindings.values() if b.expires_at > now]
            by_domain: Dict[str, int] = defaultdict(int)
            for binding in live:
                by_domain[binding.domain] += 1
            return {
                "active": len(live),
                "ttl_seconds": self.ttl,
                "max_bindings": self.max_bindings,
                "by_domain": dict(by_domain),
                "served": sum(b.served for b in live),
            }

    def __len__(self) -> int:
        return len(self._bindings)
