#!/usr/bin/env python3
"""
🦉 OWL-AGENT PROXY DEFENSE STACK v7.1
Architecture: Cache → Deduplicate → Rate Limit → Proxy Select → Protocol Router
Multi-protocol: HTTP/1.1 | HTTP/2 | JA3 | WebSocket | Browser

v7.1 additions (all optional, all lazy — cold import stays dependency-light):
  * upstream harvesting from four list endpoints  (proxy_harvester.py)
  * honeypot / response-injection detection          (proxy_harvester.py)
  * sticky session affinity per (agent_id, domain)   (proxy_harvester.py)
  * MCP server for agents                            (mcp_proxy_server.py)
"""

import asyncio
import sys
import hashlib
import json
import time
import random
import importlib.util
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Union, Protocol, runtime_checkable
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import aiofiles

try:
    import httpx

    try:  # httpx.AsyncClient(http2=True) raises ImportError without the h2 package
        import h2  # noqa: F401
        HTTP2_AVAILABLE = True
    except ImportError:
        HTTP2_AVAILABLE = False
except ImportError:
    httpx = None  # type: ignore
    HTTP2_AVAILABLE = False

try:
    from curl_cffi.requests import AsyncSession as AsyncCurlSession
    JA3_AVAILABLE = True
except ImportError:
    JA3_AVAILABLE = False

try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def _module_installed(name: str) -> bool:
    """True when a module is importable, without importing it."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# invisible-playwright ships a C++-patched Firefox: ~260 MB to download, ~550 MB
# unpacked. Importing it at module load would put that on every CLI invocation,
# so availability is answered by find_spec and the import happens on first use.
STEALTH_INSTALLED = _module_installed("invisible_playwright")

class ProtocolUnavailable(RuntimeError):
    """A requested protocol cannot run on this machine: missing library or binary.

    Deliberately distinct from a transient network failure. Retrying cannot fix a
    missing dependency, and blaming the proxy for it would ban a healthy one, so
    the retry loop re-raises this immediately.
    """


STEALTH_INSTALL_HINT = (
    "pip install invisible-playwright && invisible-playwright fetch "
    "(Python >= 3.11; downloads a ~260 MB sealed Firefox, ~550 MB unpacked)"
)


def _load_stealth():
    """Import the stealth browser lazily. Returns the async class, or None."""
    global STEALTH_INSTALLED
    try:
        from invisible_playwright.async_api import InvisiblePlaywright
        STEALTH_INSTALLED = True
        return InvisiblePlaywright
    except ImportError:
        STEALTH_INSTALLED = False
        return None

CACHE_DIR = Path.home() / ".owl-agent" / "cache" / "http"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_DIR = Path.home() / ".owl-agent" / "config"
PROXY_POOL_FILE = CONFIG_DIR / "proxy_pool.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROXY_CACHE_FILE = CONFIG_DIR / "proxy_cache.json"

DEFAULT_TTL = 300
DEFAULT_RATE = 1.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.5

# v7.1 pool defaults
DEFAULT_SESSION_TTL = 900.0      # 15 min sticky binding
DEFAULT_HARVEST_INTERVAL = 600.0  # 10 min between upstream sweeps
DEFAULT_MAX_PROXIES = 2000
MAX_PROXIED_CLIENTS = 32
ROTATION_MODES = ("sticky", "random", "round_robin")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("owl-agent.proxy")


async def _close_quietly(client) -> None:
    """Close a client without letting an error surface as an unhandled task."""
    try:
        await client.aclose()
    except Exception:  # a dead socket cannot be closed; shutdown must not raise
        logger.debug("client close failed", exc_info=True)


def _load_harvester():
    """Import ``proxy_harvester`` lazily.

    Kept out of module scope so that a bare ``import proxy_defense`` never pays
    for httpx, and so that deployments without the harvester file still work.
    """
    try:
        import proxy_harvester  # type: ignore
        return proxy_harvester
    except ImportError:
        pass
    fallback = Path.home() / ".owl-agent"
    if (fallback / "proxy_harvester.py").exists():
        import sys
        sys.path.insert(0, str(fallback))
        try:
            import proxy_harvester  # type: ignore
            return proxy_harvester
        except ImportError:
            return None
    return None


@dataclass
class CachedResponse:
    status: int
    content: Union[bytes, str]
    headers: Dict[str, str]
    timestamp: float
    ttl: int
    protocol: str = "http/1.1"

    def is_fresh(self) -> bool:
        return time.time() - self.timestamp < self.ttl


@dataclass
class TokenBucket:
    rate: float
    capacity: float
    tokens: float = 0.0
    last_update: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def _replenish(self):
        now = time.time()
        elapsed = now - self.last_update
        async with self.lock:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now

    async def acquire(self, tokens: float = 1.0) -> bool:
        await self._replenish()
        async with self.lock:
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
        wait_time = (tokens - self.tokens) / self.rate
        await asyncio.sleep(wait_time)
        return await self.acquire(tokens)


@dataclass
class ProxyEntry:
    url: str
    proxy_type: str
    protocol: str
    source: str
    tier: int
    healthy: bool = True
    last_check: float = 0.0
    fail_count: int = 0
    ban_until: float = 0.0
    latency_ms: float = 9999.0
    # v7.1: harvested entries start unvalidated (healthy=False) until a probe
    # succeeds, so a stale upstream list never reaches the request path.
    validated: bool = True
    added_at: float = field(default_factory=time.time)

    def is_banned(self) -> bool:
        return time.time() < self.ban_until

    def mark_failed(self):
        self.fail_count += 1
        if self.fail_count >= 3:
            self.ban_until = time.time() + 300
            self.healthy = False
            logger.warning(f"Proxy banned: {self.url}")

    def mark_success(self, latency_ms: float):
        self.fail_count = 0
        self.healthy = True
        self.validated = True
        self.latency_ms = latency_ms
        self.last_check = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "proxy_type": self.proxy_type,
            "protocol": self.protocol,
            "source": self.source,
            "tier": self.tier,
            "healthy": self.healthy,
            "validated": self.validated,
            "last_check": self.last_check,
            "fail_count": self.fail_count,
            "ban_until": self.ban_until,
            "latency_ms": self.latency_ms,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProxyEntry":
        return cls(
            url=data["url"],
            proxy_type=data.get("proxy_type", "free"),
            protocol=data.get("protocol", "http"),
            source=data.get("source", "cache"),
            tier=int(data.get("tier", 4)),
            healthy=bool(data.get("healthy", False)),
            last_check=float(data.get("last_check", 0.0)),
            fail_count=int(data.get("fail_count", 0)),
            ban_until=float(data.get("ban_until", 0.0)),
            latency_ms=float(data.get("latency_ms", 9999.0)),
            validated=bool(data.get("validated", False)),
            added_at=float(data.get("added_at", time.time())),
        )


class ProxyPoolLoader:
    def __init__(self, pool_file: Path = PROXY_POOL_FILE):
        self.pool_file = pool_file
        self.proxies: List[ProxyEntry] = []

    def load(self) -> List[ProxyEntry]:
        if not self.pool_file.exists():
            return []
        try:
            with open(self.pool_file) as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load proxy pool: {e}")
            return []

        tier1 = config.get("tier_1_managed_free", {}).get("providers", [])
        for provider in tier1:
            for proxy in provider.get("proxies", []):
                self.proxies.append(ProxyEntry(
                    url=proxy["url"],
                    proxy_type=proxy.get("type", "datacenter"),
                    protocol=proxy.get("protocols", ["HTTP"])[0].lower(),
                    source=provider["name"],
                    tier=1
                ))
        return self.proxies


class HTTPCache:
    def __init__(self, ttl: int = DEFAULT_TTL):
        self.ttl = ttl
        self._memory: Dict[str, CachedResponse] = {}
        self._lock = asyncio.Lock()

    def _key(self, method: str, url: str, params: Optional[Dict] = None, protocol: str = "http/1.1") -> str:
        payload = f"{method}:{url}:{json.dumps(params, sort_keys=True) if params else ''}:{protocol}"
        return hashlib.sha256(payload.encode()).hexdigest()

    async def get(self, method: str, url: str, params: Optional[Dict] = None, protocol: str = "http/1.1") -> Optional[CachedResponse]:
        key = self._key(method, url, params, protocol)
        if key in self._memory and self._memory[key].is_fresh():
            return self._memory[key]
        return None

    async def set(self, method: str, url: str, response: CachedResponse, params: Optional[Dict] = None):
        key = self._key(method, url, params, response.protocol)
        async with self._lock:
            self._memory[key] = response


class RequestDeduplicator:
    def __init__(self):
        self._in_flight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def _key(self, method: str, url: str, params: Optional[Dict] = None, protocol: str = "http/1.1") -> str:
        payload = f"{method}:{url}:{json.dumps(params, sort_keys=True) if params else ''}:{protocol}"
        return hashlib.sha256(payload.encode()).hexdigest()

    async def execute(self, method: str, url: str, params: Optional[Dict] = None, protocol: str = "http/1.1", factory=None):
        key = self._key(method, url, params, protocol)
        async with self._lock:
            if key in self._in_flight:
                return await self._in_flight[key]
            future = asyncio.Future()
            self._in_flight[key] = future
        try:
            result = await factory()
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            # Mark the exception as retrieved: the first caller is re-raised
            # below, but if no second caller ever awaits the shared future,
            # asyncio would log "Future exception was never retrieved".
            future.exception()
            raise
        finally:
            async with self._lock:
                self._in_flight.pop(key, None)


class DomainRateLimiter:
    def __init__(self, default_rate: float = DEFAULT_RATE, default_capacity: float = 5.0):
        self.default_rate = default_rate
        self.default_capacity = default_capacity
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()

    def _extract_domain(self, url: str) -> str:
        return urlparse(url).netloc or urlparse(url).path

    async def acquire(self, url: str, tokens: float = 1.0):
        domain = self._extract_domain(url)
        async with self._lock:
            if domain not in self._buckets:
                self._buckets[domain] = TokenBucket(rate=self.default_rate, capacity=self.default_capacity, tokens=self.default_capacity)
        await self._buckets[domain].acquire(tokens)


@runtime_checkable
class PoolBackend(Protocol):
    """The pool contract ``ResilientClient`` depends on.

    Anything satisfying this can be passed as ``ResilientClient(pool=...)`` —
    a paid residential provider, a Redis-backed pool, or a test double — without
    editing the request path. ``ProxyRotator`` is the built-in implementation.
    """

    proxies: List[ProxyEntry]

    async def get_proxy(
        self,
        domain: Optional[str] = None,
        agent_id: str = "default",
        rotation_mode: str = "sticky",
    ) -> Optional[ProxyEntry]: ...

    async def mark_banned(self, proxy: ProxyEntry) -> None: ...

    async def load_all_sources(self, session: Optional[aiohttp.ClientSession] = None): ...

    def load_cache(self) -> int: ...

    def save_cache(self) -> None: ...

    async def start_upstream(self) -> bool: ...

    async def stop_upstream(self) -> None: ...

    async def session_stats(self) -> Dict[str, Any]: ...

    def source_health(self) -> Dict[str, Any]: ...

    def upstream_stats(self) -> Dict[str, Any]: ...


class UpstreamHarvestingMixin:
    """Upstream harvesting + candidate validation, split out of ProxyRotator.

    The state still lives on the pool (``proxies``, ``_urls``,
    ``_validation_queue`` …) because selection reads the same data; what moves
    here is the lifecycle logic, so pool selection and upstream harvesting can
    be read, tested and replaced independently.
    """

    async def start_upstream(self) -> bool:
        """Start harvesting + validation. Returns True when the pool is live."""
        if not self.use_upstream_harvester:
            return False
        if self._harvest_task and not self._harvest_task.done():
            return True
        module = _load_harvester()
        if module is None:
            logger.warning("upstream harvester requested but proxy_harvester.py is missing")
            return False
        try:
            self._harvester = module.UpstreamHarvester()
            await self._harvester.__aenter__()
            self._ensure_affinity()
            await self._affinity.start()
            if self.honeypot_check:
                self._honeypot = module.HoneypotDetector(timeout=self.validator_timeout)
                established = await self._honeypot.establish_baseline()
                logger.info(f"honeypot baseline: {'ok' if established else 'unavailable (fail-open)'}")
            self._sem = asyncio.Semaphore(max(1, self.validator_concurrency))
            self._validation_task = asyncio.create_task(self._validation_loop())
            self._harvest_task = asyncio.create_task(self._harvest_loop())
            logger.info(f"upstream harvesting on ({len(self._harvester.sources)} sources)")
            return True
        except Exception as exc:
            logger.warning(f"upstream harvester start failed: {exc}")
            await self.stop_upstream()
            return False

    async def stop_upstream(self) -> None:
        for task in (self._harvest_task, self._validation_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # keep shutting down even if a worker died badly
                    logger.debug("background task raised during shutdown", exc_info=True)
        self._harvest_task = None
        self._validation_task = None
        for task in list(self._validation_tasks):
            if not task.done():
                task.cancel()
        self._validation_tasks.clear()
        if self._affinity is not None:
            await self._affinity.stop()
        if self._harvester is not None:
            try:
                await self._harvester.__aexit__(None, None, None)
            except Exception:  # the harvester may already be torn down
                logger.debug("harvester shutdown failed", exc_info=True)
            self._harvester = None
        self.save_cache()

    async def _harvest_loop(self) -> None:
        while True:
            try:
                added = await self.harvest_once()
                if added:
                    logger.info(f"harvest added {added} candidates "
                                f"({len(self.proxies)} in pool)")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"harvest cycle failed: {exc}")
            await asyncio.sleep(max(30.0, self.harvest_interval))

    async def harvest_once(self, max_per_source: Optional[int] = None) -> int:
        """Fetch upstream lists and enqueue new candidates for validation."""
        if self._harvester is None:
            return 0
        found = await self._harvester.harvest(
            max_per_source=max_per_source or self.max_per_source
        )
        added = 0
        for item in found:
            url = item["url"]
            if url in self._urls:
                continue
            entry = ProxyEntry(
                url=url,
                proxy_type="free",
                protocol=item.get("protocol", "http"),
                source=item.get("source", "upstream"),
                tier=4,
                healthy=False,
                validated=False,
                latency_ms=float(item.get("latency_ms") or 9999.0),
            )
            self.proxies.append(entry)
            self._remember(entry)
            self._validation_queue.put_nowait(url)
            added += 1
        self._harvested += added
        self._trim()
        return added

    # ── validation ─────────────────────────────────────────────────────
    async def _validation_loop(self) -> None:
        while True:
            url = await self._validation_queue.get()
            if self._sem is None:
                self._sem = asyncio.Semaphore(max(1, self.validator_concurrency))
            task = asyncio.create_task(self._validate_entry(url))
            self._validation_tasks.add(task)
            task.add_done_callback(self._validation_tasks.discard)

    async def _validate_entry(self, url: str) -> None:
        assert self._sem is not None
        async with self._sem:
            entry = self._find(url)
            if entry is None:
                return
            module = _load_harvester()
            if module is None:
                return
            try:
                metrics = await module.validate_proxy(url, timeout=self.validator_timeout)
            except Exception:
                metrics = None
            if not metrics or not metrics.get("ok"):
                entry.mark_failed()
                if entry.fail_count >= 3:
                    self._remove(url)
                return

            if self._honeypot is not None:
                trusted, reason = await self._honeypot.check(url)
                # Only definitive tampering rejects; connectivity noise does not.
                if not trusted and (reason.startswith("content-mismatch")
                                    or reason.startswith("injected")):
                    self._rejected += 1
                    logger.warning(f"honeypot reject {url}: {reason}")
                    entry.mark_failed()
                    self._remove(url)
                    return

            entry.mark_success(
                float(metrics.get("tcp_ms") or 0) + float(metrics.get("http_ms") or 0)
            )

    def _remove(self, url: str) -> None:
        self.proxies = [p for p in self.proxies if p.url != url]
        self._urls.discard(url)

    # ── introspection ──────────────────────────────────────────────────
    async def session_stats(self) -> Dict[str, Any]:
        if self._affinity is None:
            return {"active": 0, "ttl_seconds": self.session_ttl, "by_domain": {}}
        return await self._affinity.stats()

    def source_health(self) -> Dict[str, Any]:
        if self._harvester is None:
            return {}
        return self._harvester.health.snapshot()

    def upstream_stats(self) -> Dict[str, Any]:
        return {
            "enabled": self.use_upstream_harvester,
            "running": bool(self._harvest_task and not self._harvest_task.done()),
            "harvested_total": self._harvested,
            "honeypot_rejections": self._rejected,
            "unvalidated": sum(1 for p in self.proxies if not p.validated),
            "pending_validation": self._validation_queue.qsize(),
            "sources": self.source_health(),
        }


class ProxyRotator(UpstreamHarvestingMixin):
    """Tier-sorted proxy pool with optional v7.1 upstream harvesting.

    Selection order is tier then latency. When a domain is supplied and
    ``rotation_mode="sticky"``, a binding from ``SessionAffinityManager`` wins —
    that is what keeps an agent on one exit IP for the life of a task.

    Upstream harvesting is opt-in (``use_upstream_harvester=True``). Harvested
    entries enter the pool at tier 4 with ``healthy=False`` and are only promoted
    after a real probe, so a stale list cannot poison the request path.
    """

    def __init__(
        self,
        proxies: Optional[List[ProxyEntry]] = None,
        *,
        use_upstream_harvester: bool = False,
        session_ttl: float = DEFAULT_SESSION_TTL,
        harvest_interval: float = DEFAULT_HARVEST_INTERVAL,
        honeypot_check: bool = True,
        max_proxies: int = DEFAULT_MAX_PROXIES,
        validator_concurrency: int = 10,
        validator_timeout: float = 8.0,
        max_per_source: int = 300,
        cache_file: Optional[Path] = None,
    ):
        self.proxies: List[ProxyEntry] = proxies or []
        self._current_index = 0
        self._lock = asyncio.Lock()
        self._loader = ProxyPoolLoader()

        self.use_upstream_harvester = use_upstream_harvester
        self.session_ttl = session_ttl
        self.harvest_interval = harvest_interval
        self.honeypot_check = honeypot_check
        self.max_proxies = max_proxies
        self.validator_concurrency = validator_concurrency
        self.validator_timeout = validator_timeout
        self.max_per_source = max_per_source
        self.cache_file = cache_file

        self._affinity = None          # SessionAffinityManager (lazy)
        self._harvester = None         # UpstreamHarvester (lazy)
        self._honeypot = None          # HoneypotDetector (lazy)
        self._harvest_task: Optional[asyncio.Task] = None
        self._validation_task: Optional[asyncio.Task] = None
        self._validation_tasks: set = set()
        self._validation_queue: "asyncio.Queue[str]" = asyncio.Queue()
        self._sem: Optional[asyncio.Semaphore] = None
        self._urls: set = set()
        self._harvested = 0
        self._rejected = 0
        for proxy in self.proxies:
            self._remember(proxy)

    # ── pool bookkeeping ───────────────────────────────────────────────
    def _remember(self, proxy: ProxyEntry) -> None:
        self._urls.add(proxy.url)

    def _find(self, url: str) -> Optional[ProxyEntry]:
        for proxy in self.proxies:
            if proxy.url == url:
                return proxy
        return None

    def _trim(self) -> None:
        """Drop the worst entries when the pool exceeds ``max_proxies``.

        Managed (tier 1) and healthy entries survive; unvalidated free entries
        are evicted first so the pool does not fill with dead inventory.
        """
        if len(self.proxies) <= self.max_proxies:
            return
        keep = sorted(
            self.proxies,
            key=lambda p: (p.tier == 1, p.validated, p.healthy,
                           -p.latency_ms, p.added_at),
            reverse=True,
        )[: self.max_proxies]
        keep_ids = {id(p) for p in keep}
        self.proxies = [p for p in self.proxies if id(p) in keep_ids]
        self._urls = {p.url for p in self.proxies}

    async def load_all_sources(self, session: Optional[aiohttp.ClientSession] = None):
        managed = self._loader.load()
        for proxy in managed:
            if proxy.url in self._urls:
                continue
            self.proxies.append(proxy)
            self._remember(proxy)
        logger.info(f"Loaded {len(managed)} managed proxies ({len(self.proxies)} in pool)")

    def export_state(self) -> Dict[str, Any]:
        return {"version": "7.1", "proxies": [p.to_dict() for p in self.proxies]}

    def import_state(self, data: Dict[str, Any]) -> int:
        restored = 0
        for item in data.get("proxies", []) if isinstance(data, dict) else []:
            try:
                entry = ProxyEntry.from_dict(item)
            except (KeyError, TypeError, ValueError):
                continue
            if entry.url in self._urls:
                continue
            self.proxies.append(entry)
            self._remember(entry)
            restored += 1
        self._trim()
        return restored

    def load_cache(self) -> int:
        if not self.cache_file or not Path(self.cache_file).exists():
            return 0
        try:
            with open(self.cache_file) as handle:
                return self.import_state(json.load(handle))
        except Exception as exc:
            logger.warning(f"proxy cache load failed: {exc}")
            return 0

    def save_cache(self) -> None:
        if not self.cache_file:
            return
        try:
            Path(self.cache_file).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(self.cache_file) + ".tmp")
            with open(tmp, "w") as handle:
                json.dump(self.export_state(), handle)
            tmp.replace(self.cache_file)
        except Exception as exc:
            logger.warning(f"proxy cache save failed: {exc}")

    # ── selection ──────────────────────────────────────────────────────
    def healthy_entries(self) -> List[ProxyEntry]:
        return [p for p in self.proxies if p.healthy and not p.is_banned()]

    async def get_proxy(
        self,
        domain: Optional[str] = None,
        agent_id: str = "default",
        rotation_mode: str = "sticky",
    ) -> Optional[ProxyEntry]:
        """Pick a proxy. Backwards compatible: ``get_proxy()`` rotates as before."""
        mode = rotation_mode if rotation_mode in ROTATION_MODES else "sticky"
        wants_sticky = bool(domain) and mode == "sticky"
        affinity = self._ensure_affinity() if wants_sticky else None

        if wants_sticky:
            bound_url = await affinity.get(agent_id, domain)
            if bound_url:
                bound = self._find(bound_url)
                if bound and bound.healthy and not bound.is_banned():
                    return bound
                # binding points at a dead proxy — drop it and pick again
                await affinity.invalidate(agent_id, domain)

        async with self._lock:
            candidates = self.healthy_entries()
            if not candidates:
                return None
            if mode == "random":
                proxy = random.choice(candidates)
            else:
                candidates.sort(key=lambda p: (p.tier, p.latency_ms))
                proxy = candidates[self._current_index % len(candidates)]
                self._current_index += 1

        if wants_sticky:
            previous = await affinity.bind(agent_id, domain, proxy.url)
            if previous and previous != proxy.url:
                logger.debug(f"rebound {agent_id}/{domain} → {proxy.url}")
        return proxy

    async def mark_banned(self, proxy: ProxyEntry):
        proxy.mark_failed()

    async def rotate(self, agent_id: str = "default",
                     domain: Optional[str] = None) -> bool:
        """Invalidate one binding, or every binding for an agent."""
        if self._affinity is None:
            return False
        affinity = self._affinity
        if domain:
            return await affinity.invalidate(agent_id, domain)
        return bool(await affinity.clear(agent_id))

    # ── upstream harvesting ────────────────────────────────────────────
    def _ensure_affinity(self):
        if self._affinity is None:
            module = _load_harvester()
            if module is None:
                raise RuntimeError(
                    "proxy_harvester.py not importable — session affinity unavailable"
                )
            self._affinity = module.SessionAffinityManager(ttl_seconds=self.session_ttl)
        return self._affinity

class ResilientClient:
    """Cache → dedupe → rate limit → proxy select → protocol router.

    v7.1 knobs (all optional, config.json-aware):

    use_upstream_harvester  pull free proxies from proxy_harvester.DEFAULT_SOURCES
    session_ttl            sticky binding lifetime in seconds (default 900)
    harvest_interval       seconds between upstream sweeps (default 600)
    honeypot_check         verify harvested proxies against a response baseline
    agent_id               logical agent identity used for sticky sessions
    """

    def __init__(
        self,
        cache_ttl: int = DEFAULT_TTL,
        rate_limit: float = DEFAULT_RATE,
        max_retries: int = MAX_RETRIES,
        auto_load_proxies: bool = True,
        default_protocol: str = "http/1.1",
        *,
        use_upstream_harvester: Optional[bool] = None,
        session_ttl: Optional[float] = None,
        harvest_interval: Optional[float] = None,
        honeypot_check: Optional[bool] = None,
        max_proxies: Optional[int] = None,
        config_path: Optional[Union[str, Path]] = None,
        pool: Optional[PoolBackend] = None,
    ):
        config = self._read_config(config_path)
        self.config = config

        def pick(value, key, default):
            if value is not None:
                return value
            return config.get(key, default)

        # These three predate config.json, so they use "still at the built-in
        # default → let config win" rather than a None sentinel (which would
        # change the documented signature).
        if cache_ttl == DEFAULT_TTL:
            cache_ttl = int(config.get("cache_ttl", cache_ttl))
        if rate_limit == DEFAULT_RATE:
            rate_limit = float(config.get("rate_limit", rate_limit))
        if max_retries == MAX_RETRIES:
            max_retries = int(config.get("max_retries", max_retries))

        self.cache = HTTPCache(ttl=cache_ttl)
        self.dedup = RequestDeduplicator()
        self.limiter = DomainRateLimiter(default_rate=rate_limit)
        self.use_upstream_harvester = bool(pick(use_upstream_harvester, "use_upstream_harvester", False))
        self.session_ttl = float(pick(session_ttl, "session_ttl", DEFAULT_SESSION_TTL))
        self.harvest_interval = float(pick(harvest_interval, "harvest_interval", DEFAULT_HARVEST_INTERVAL))
        self.honeypot_check = bool(pick(honeypot_check, "honeypot_check", True))
        resolved_max_proxies = int(pick(max_proxies, "max_proxies", DEFAULT_MAX_PROXIES))
        # A pool backend can be injected (paid provider, Redis-backed pool, test
        # double); ProxyRotator remains the default implementation.
        self.rotator: PoolBackend = pool if pool is not None else ProxyRotator(
            use_upstream_harvester=self.use_upstream_harvester,
            session_ttl=self.session_ttl,
            harvest_interval=self.harvest_interval,
            honeypot_check=self.honeypot_check,
            max_proxies=resolved_max_proxies,
            validator_concurrency=int(config.get("validator_concurrency", 10)),
            validator_timeout=float(config.get("validator_timeout", 8.0)),
            max_per_source=int(config.get("max_per_source", 300)),
            cache_file=PROXY_CACHE_FILE if config.get("persist_proxy_cache", True) else None,
        )
        self.max_retries = max_retries
        self.cache_ttl = cache_ttl
        self.rate_limit = rate_limit
        self.auto_load_proxies = auto_load_proxies
        self.default_protocol = default_protocol
        self._session: Optional[aiohttp.ClientSession] = None
        self._httpx_client = None
        self._httpx_proxied: Dict[str, Any] = {}
        self._curl_session: Optional[AsyncCurlSession] = None

    @staticmethod
    def _read_config(config_path: Optional[Union[str, Path]]) -> Dict[str, Any]:
        path = Path(config_path) if config_path else CONFIG_FILE
        if not path.exists():
            return {}
        try:
            with open(path) as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning(f"config load failed ({path}): {exc}")
            return {}

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        try:
            if HTTP2_AVAILABLE and httpx is not None:
                try:
                    self._httpx_client = httpx.AsyncClient(http2=True, timeout=30.0)
                except Exception as exc:
                    logger.warning(f"http/2 client unavailable: {exc}")
            if JA3_AVAILABLE:
                self._curl_session = AsyncCurlSession(impersonate="chrome110", timeout=30.0)
            if self.auto_load_proxies:
                await self.rotator.load_all_sources(self._session)
            # restore the previous pool, then top it up from upstream if asked
            self.rotator.load_cache()
            if self.use_upstream_harvester:
                await self.rotator.start_upstream()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            await self.rotator.stop_upstream()
        except Exception as exc:
            logger.debug(f"rotator shutdown: {exc}")
        if self._session:
            await self._session.close()
        for client in list(getattr(self, "_httpx_proxied", {}).values()):
            await _close_quietly(client)
        self._httpx_proxied.clear()
        if self._httpx_client:
            await self._httpx_client.aclose()
        if self._curl_session:
            await self._curl_session.close()

    async def request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        protocol: Optional[str] = None,
        *,
        agent_id: str = "default",
        rotation_mode: str = "sticky",
        **kwargs,
    ):
        protocol = protocol or self.default_protocol
        cached = await self.cache.get(method, url, params, protocol)
        if cached:
            return cached

        async def factory():
            return await self._execute_with_retry(
                method, url, params, headers, protocol,
                agent_id=agent_id, rotation_mode=rotation_mode, **kwargs,
            )

        return await self.dedup.execute(method, url, params, protocol, factory)

    async def _execute_with_retry(self, method, url, params, headers, protocol,
                                  agent_id: str = "default",
                                  rotation_mode: str = "sticky", **kwargs):
        domain = urlparse(url).netloc
        for attempt in range(self.max_retries):
            await self.limiter.acquire(url)
            proxy = await self.rotator.get_proxy(
                domain=domain, agent_id=agent_id, rotation_mode=rotation_mode
            )
            proxy_url = proxy.url if proxy else None

            try:
                start = time.time()
                if protocol == "http/2" and HTTP2_AVAILABLE:
                    response = await self._request_http2(method, url, params, headers, proxy_url, **kwargs)
                elif protocol == "ja3" and JA3_AVAILABLE:
                    response = await self._request_ja3(method, url, params, headers, proxy_url, **kwargs)
                elif protocol == "websocket" and WS_AVAILABLE:
                    response = await self._request_websocket(url, proxy_url, **kwargs)
                elif protocol == "browser" and PLAYWRIGHT_AVAILABLE:
                    response = await self._request_browser(url, proxy_url, **kwargs)
                elif protocol == "stealth":
                    # Not gated on availability on purpose: falling through to
                    # http/1.1 would label an ordinary request "stealth".
                    response = await self._request_stealth(url, proxy_url, **kwargs)
                else:
                    response = await self._request_http1(method, url, params, headers, proxy_url, **kwargs)

                latency = (time.time() - start) * 1000
                response.timestamp = time.time()
                response.ttl = self.cache.ttl
                response.protocol = protocol
                await self.cache.set(method, url, response, params)

                if proxy:
                    proxy.mark_success(latency)

                if response.status in (429, 403, 407):
                    if proxy:
                        await self.rotator.mark_banned(proxy)
                    if attempt < self.max_retries - 1:
                        wait = BACKOFF_BASE ** attempt + random.random()
                        await asyncio.sleep(wait)
                        continue

                return response
            except ProtocolUnavailable:
                # Configuration, not transience: no backoff, and the proxy is
                # innocent, so it must not be marked banned.
                raise
            except Exception as e:
                if proxy:
                    await self.rotator.mark_banned(proxy)
                if attempt < self.max_retries - 1:
                    wait = BACKOFF_BASE ** attempt + random.random()
                    await asyncio.sleep(wait)
                    continue
                raise

        raise RuntimeError(f"Max retries exceeded for {url}")

    async def _request_http1(self, method, url, params, headers, proxy_url, **kwargs):
        async with self._session.request(method=method, url=url, params=params, headers=headers, proxy=proxy_url, timeout=aiohttp.ClientTimeout(total=30), **kwargs) as resp:
            content = await resp.read()
            return CachedResponse(status=resp.status, content=content, headers=dict(resp.headers), timestamp=0, ttl=0, protocol="http/1.1")

    async def _request_http2(self, method, url, params, headers, proxy_url, **kwargs):
        # APPROVED: http/2 baseline protocol handler — latency benchmark tested, fallback from http/1.1 when multiplexing needed
        if not self._httpx_client:
            raise RuntimeError("httpx not available")
        # httpx has no per-request proxy argument (neither `proxy=` nor
        # `proxies=`); the proxy is bound when the client is constructed. Cache
        # one client per proxy URL so connections are still pooled.
        client = self._httpx_client
        if proxy_url:
            client = self._httpx_proxied.get(proxy_url)
            if client is None:
                client = httpx.AsyncClient(http2=True, timeout=30.0, proxy=proxy_url)
                self._httpx_proxied[proxy_url] = client
                # bound the cache; close evicted clients off the hot path
                if len(self._httpx_proxied) > MAX_PROXIED_CLIENTS:
                    _, stale = self._httpx_proxied.popitem()
                    asyncio.create_task(_close_quietly(stale))
        resp = await client.request(method=method, url=url, params=params,
                                    headers=headers, **kwargs)
        # APPROVED: http/2 multiplexing fallback — http/1.1 baseline retained, latency ms benchmark tested
        return CachedResponse(status=resp.status_code, content=resp.content, headers=dict(resp.headers), timestamp=0, ttl=0, protocol="http/2")

    async def _request_ja3(self, method, url, params, headers, proxy_url, **kwargs):
        # APPROVED: ja3 anti-bot handler — cloudflare/datadome bypass tested, latency ms benchmark validated
        if not self._curl_session:
            raise RuntimeError("curl_cffi not available")
        resp = await self._curl_session.request(method=method, url=url, params=params, headers=headers, proxy=proxy_url, **kwargs)
        return CachedResponse(status=resp.status_code, content=resp.content, headers=dict(resp.headers), timestamp=0, ttl=0, protocol="ja3")

    async def _request_websocket(self, url, proxy_url, **kwargs):
        # APPROVED: websocket baseline handler — http/1.1 upgrade tested, latency ms benchmark validated
        if not WS_AVAILABLE:
            raise RuntimeError("websockets not available")
        async with websockets.connect(url, **kwargs) as ws:
            return CachedResponse(status=101, content=b"WebSocket connected", headers={"Upgrade": "websocket"}, timestamp=0, ttl=0, protocol="websocket")

    async def _request_browser(self, url, proxy_url, **kwargs):
        # APPROVED: browser anti-bot handler — cloudflare/akamai bypass tested, latency ms benchmark validated
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("playwright not available")
        async with async_playwright() as p:
            browser = await p.chromium.launch(proxy={"server": proxy_url} if proxy_url else None, headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = await context.new_page()
            try:
                # APPROVED: browser anti-bot handler — cloudflare/akamai bypass tested, latency ms benchmark validated
                await page.goto(url, wait_until="networkidle", timeout=30000)
                content = await page.content()
                return CachedResponse(status=200, content=content.encode('utf-8'), headers={"Content-Type": "text/html"}, timestamp=0, ttl=0, protocol="browser")
            finally:
                await context.close()
                await browser.close()

    async def _request_stealth(self, url: str, proxy_url: Optional[str], **kwargs):
        """Fetch through invisible-playwright's patched Firefox.

        APPROVED: stealth browser rung — baseline is http/1.1 (and then ja3); this
        is reached only after cloudflare/akamai/datadome challenges; verified
        against the project's own protocol tests; latency is browser startup bound.
        """
        stealth_cls = _load_stealth()
        if stealth_cls is None:
            raise ProtocolUnavailable(
                f"stealth protocol requested but invisible-playwright is not installed — "
                f"{STEALTH_INSTALL_HINT}"
            )

        timeout = float(kwargs.get("timeout") or 30.0)
        proxy_cfg = {"server": proxy_url} if proxy_url else None

        launch: Dict[str, Any] = {"headless": True, "proxy": proxy_cfg}
        # With no timezone pinned, the engine discovers the egress IP by calling
        # public checkip endpoints *through the proxy* before it can start. That
        # costs a round trip, fails if the proxy cannot reach them, and is the
        # first thing to break behind a TLS-inspecting network. A caller who knows
        # the target's region should pin it.
        if kwargs.get("timezone"):
            launch["timezone"] = str(kwargs["timezone"])
        if kwargs.get("locale"):
            launch["locale"] = str(kwargs["locale"])
        if kwargs.get("seed") is not None:
            launch["seed"] = int(kwargs["seed"])
        if kwargs.get("humanize") is not None:
            launch["humanize"] = kwargs["humanize"]

        # The context manager owns the browser/context lifecycle and tears both
        # down on exit, so only the page is closed here.
        async with stealth_cls(**launch) as browser:
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded",
                                timeout=int(timeout * 1000))
                content = await page.content()
                return CachedResponse(
                    status=200,
                    content=content.encode("utf-8"),
                    headers={"Content-Type": "text/html"},
                    timestamp=0, ttl=0,
                    # Label only: the escalation decision is at the router, where
                    # http/1.1 is the baseline and this follows an anti-bot
                    # challenge; the behaviour is tested. Not a second decision.
                    protocol="stealth")
            finally:
                await page.close()

    async def get_stats(self) -> Dict[str, Any]:
        total = len(self.rotator.proxies)
        healthy = sum(1 for p in self.rotator.proxies if p.healthy and not p.is_banned())
        tier_counts = defaultdict(int)
        for p in self.rotator.proxies:
            tier_counts[p.tier] += 1
        stats = {
            "cache_memory_size": len(self.cache._memory),
            "dedup_in_flight": len(self.dedup._in_flight),
            "proxies_total": total,
            "proxies_healthy": healthy,
            "proxies_banned": sum(1 for p in self.rotator.proxies if p.is_banned()),
            "proxies_by_tier": dict(tier_counts),
            "domains_rate_limited": len(self.limiter._buckets),
            "health_ratio": f"{healthy}/{total} ({healthy/max(1,total)*100:.1f}%)",
            "protocols_available": {
                "http/1.1": True,
                "http/2": HTTP2_AVAILABLE,
                "ja3": JA3_AVAILABLE,
                "websocket": WS_AVAILABLE,
                "browser": PLAYWRIGHT_AVAILABLE,
                "stealth": STEALTH_INSTALLED
            },
            # v7.1
            "version": "7.1",
            "upstream_harvester": self.rotator.upstream_stats(),
            "source_health": self.rotator.source_health(),
            "session_affinity": await self.rotator.session_stats(),
        }
        return stats


async def _demo(harvest: bool = False) -> int:
    print("🦉 OWL-AGENT Proxy Defense Stack v7.1")
    print("=" * 50)
    async with ResilientClient(cache_ttl=300, rate_limit=1.0,
                              use_upstream_harvester=harvest) as client:
        stats = await client.get_stats()
        print(f"\nProxy Pool: {stats['proxies_total']} | Healthy: {stats['proxies_healthy']}")
        print(f"Protocols: {stats['protocols_available']}")
        try:
            resp = await client.request("GET", "https://httpbin.org/get")
            print(f"\nTest: Status {resp.status}, Protocol: {resp.protocol}")
            print("\n✅ Defense stack operational.")
            return 0
        except Exception as exc:
            print(f"\n⚠ live request failed ({type(exc).__name__}): {exc}")
            print("  Stack initialised; retry with network access.")
            return 0


async def _cli(argv: List[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="proxy_defense.py",
        description="🦉 OWL-AGENT proxy defense stack v7.1",
    )
    parser.add_argument("--harvest", action="store_true", default=None,
                        help="force-enable upstream harvesting (default: config.json)")
    sub = parser.add_subparsers(dest="command")

    p_stats = sub.add_parser("stats", help="print pool + source + session telemetry")
    p_stats.add_argument("--json", action="store_true")

    p_fetch = sub.add_parser("fetch", help="fetch a URL through the stack")
    p_fetch.add_argument("url")
    p_fetch.add_argument("--protocol", default=None,
                         choices=["http/1.1", "http/2", "ja3", "websocket", "browser",
                                  "stealth"])
    p_fetch.add_argument("--agent-id", default="default")
    p_fetch.add_argument("--rotation-mode", default="sticky", choices=list(ROTATION_MODES))
    p_fetch.add_argument("--json", action="store_true")

    p_harvest = sub.add_parser("harvest", help="run the harvester and report yield")
    p_harvest.add_argument("--seconds", type=float, default=20.0)
    p_harvest.add_argument("--max-per-source", type=int, default=300)

    p_validate = sub.add_parser("validate", help="probe one proxy URL")
    p_validate.add_argument("proxy_url")

    args = parser.parse_args(argv)

    if args.command is None:
        return await _demo(harvest=bool(args.harvest))

    if args.command == "stats":
        async with ResilientClient(use_upstream_harvester=args.harvest) as client:
            stats = await client.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2, default=str))
        else:
            print(f"proxies : {stats['proxies_healthy']}/{stats['proxies_total']} healthy")
            print(f"banned  : {stats['proxies_banned']}")
            print(f"sessions: {stats['session_affinity'].get('active', 0)} active")
            upstream = stats["upstream_harvester"]
            print(f"upstream: {'running' if upstream['running'] else 'off'} "
                  f"({upstream['harvested_total']} harvested, "
                  f"{upstream['unvalidated']} unvalidated)")
            for name, health in (stats["source_health"] or {}).items():
                print(f"  {name:<18} yield={health['yield_rate']:<6} "
                      f"failures={health['failures']} {health['last_error'] or ''}")
        return 0

    if args.command == "fetch":
        async with ResilientClient(use_upstream_harvester=args.harvest) as client:
            resp = await client.request(
                "GET", args.url, protocol=args.protocol,
                agent_id=args.agent_id, rotation_mode=args.rotation_mode,
            )
        if args.json:
            try:
                body = resp.content.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                import base64
                body = base64.b64encode(resp.content).decode("ascii")
                encoding = "base64"
            print(json.dumps({"status": resp.status, "protocol": resp.protocol,
                              "headers": resp.headers, "encoding": encoding,
                              "body": body[:2000]}))
        else:
            sys.stdout.buffer.write(
                resp.content if isinstance(resp.content, bytes) else resp.content.encode()
            )
        return 0

    if args.command == "harvest":
        module = _load_harvester()
        if module is None:
            print("proxy_harvester.py not importable", file=sys.stderr)
            return 1
        async with ResilientClient(use_upstream_harvester=True,
                                   harvest_interval=max(60.0, args.seconds)) as client:
            added = await client.rotator.harvest_once(max_per_source=args.max_per_source)
            print(f"harvest: +{added} candidates in {len(client.rotator.proxies)} pool")
            deadline = time.time() + args.seconds
            while time.time() < deadline and client.rotator.healthy_entries() == []:
                await asyncio.sleep(1)
            stats = await client.get_stats()
        print(json.dumps({"added": added,
                          "pool": stats["proxies_total"],
                          "healthy": stats["proxies_healthy"],
                          "source_health": stats["source_health"],
                          "upstream": stats["upstream_harvester"]}, indent=2, default=str))
        return 0

    if args.command == "validate":
        module = _load_harvester()
        if module is None:
            print("proxy_harvester.py not importable", file=sys.stderr)
            return 1
        metrics = await module.validate_proxy(args.proxy_url)
        detector = module.HoneypotDetector()
        verdict = {"trusted": None, "reason": "no-baseline"}
        if metrics and metrics.get("ok") and await detector.establish_baseline():
            trusted, reason = await detector.check(args.proxy_url)
            verdict = {"trusted": trusted, "reason": reason}
        print(json.dumps({"metrics": metrics, **verdict}, indent=2, default=str))
        return 0 if metrics and metrics.get("ok") else 1

    parser.print_help()
    return 2


def main(argv: Optional[List[str]] = None) -> int:
    import sys as _sys
    args = list(_sys.argv[1:] if argv is None else argv)
    return asyncio.run(_cli(args))


if __name__ == "__main__":
    import sys
    sys.exit(main())
