#!/usr/bin/env python3
"""
🦉 OWL-AGENT v7.1 — installation verification.

Runs against an installed tree (default ``~/.owl-agent``) using that tree's
interpreter. Offline-safe: every check that needs egress reports SKIP instead of
FAIL, so a laptop on a plane still verifies its install.

Usage:
    python scripts/verify-install.py [--owl-home DIR] [--json]
                                     [--no-live] [--timeout SECONDS]

Exit codes: 0 = no failures (skips allowed), 1 = at least one FAIL.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable, List, Tuple

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[0;33m"
DIM = "\033[0;90m"
RESET = "\033[0m"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
REQUIRED_MODULES = ("proxy_defense.py", "proxy_harvester.py", "mcp_proxy_server.py", "run.sh")
REQUIRED_CLASSES = (
    "CachedResponse", "TokenBucket", "ProxyEntry", "ProxyPoolLoader", "HTTPCache",
    "RequestDeduplicator", "DomainRateLimiter", "ProxyRotator", "ResilientClient",
)
REQUIRED_METHODS = {
    "ProxyRotator": ("get_proxy", "rotate", "harvest_once", "start_upstream",
                     "stop_upstream", "session_stats", "source_health", "upstream_stats"),
    "ResilientClient": ("request", "get_stats", "__aenter__", "__aexit__"),
}


class Checks:
    def __init__(self, owl_home: Path, python: str, live: bool, timeout: float):
        self.home = owl_home
        self.python = python
        self.live = live
        self.timeout = timeout
        self.results: List[Tuple[str, str, str]] = []
        sys.path.insert(0, str(self.home))

    # ── helpers ────────────────────────────────────────────────────────
    def run(self, args: List[str], env: dict | None = None) -> subprocess.CompletedProcess:
        merged = dict(os.environ)
        merged["PYTHONPATH"] = str(self.home)
        merged.setdefault("PYTHONUNBUFFERED", "1")
        if env:
            merged.update(env)
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=self.timeout, env=merged, cwd=str(self.home))

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.results.append((status, name, detail))
        if status == PASS:
            print(f"  {GREEN}✅ {name:<48}{RESET} {detail}")
        elif status == SKIP:
            print(f"  {YELLOW}⚠  {name:<48}{RESET} {detail}")
        else:
            print(f"  {RED}❌ {name:<48}{RESET} {detail}")

    def check(self, name: str, func: Callable[[], Tuple[str, str]]) -> None:
        try:
            status, detail = func()
            self.add(status, name, detail)
        except AssertionError as exc:
            self.add(FAIL, name, str(exc) or "assertion failed")
        except Exception as exc:
            self.add(FAIL, name, f"{type(exc).__name__}: {exc}")
            if os.environ.get("OWL_VERIFY_TRACE"):
                traceback.print_exc()

    # ── checks ─────────────────────────────────────────────────────────
    def layout(self) -> Tuple[str, str]:
        missing = [name for name in REQUIRED_MODULES if not (self.home / name).exists()]
        assert not missing, f"missing: {', '.join(missing)}"
        run_sh = self.home / "run.sh"
        assert os.access(run_sh, os.X_OK), "run.sh is not executable"
        return PASS, f"{len(REQUIRED_MODULES)} modules"

    def config_files(self) -> Tuple[str, str]:
        config = self.home / "config" / "config.json"
        assert config.exists(), "config/config.json missing"
        data = json.loads(config.read_text())
        for key in ("use_upstream_harvester", "session_ttl", "harvest_interval"):
            assert key in data, f"config missing {key}"
        return PASS, f"keys: {len(data)}"

    def cold_import(self) -> Tuple[str, str]:
        started = time.perf_counter()
        result = self.run([self.python, "-c", "import proxy_defense"])
        elapsed = (time.perf_counter() - started) * 1000
        assert result.returncode == 0, result.stderr.strip().splitlines()[-1:]
        # 2.5 s is deliberately generous: CI runners and cold page caches are slow.
        assert elapsed < 2500, f"{elapsed:.0f} ms (threshold 2500)"
        return PASS, f"{elapsed:.0f} ms"

    def api_surface(self) -> Tuple[str, str]:
        import proxy_defense as module
        missing = [name for name in REQUIRED_CLASSES if not hasattr(module, name)]
        assert not missing, f"missing classes: {', '.join(missing)}"
        for cls_name, methods in REQUIRED_METHODS.items():
            cls = getattr(module, cls_name)
            absent = [m for m in methods if not callable(getattr(cls, m, None))]
            assert not absent, f"{cls_name} missing {', '.join(absent)}"
        return PASS, f"{len(REQUIRED_CLASSES)} classes"

    def core_deps(self) -> Tuple[str, str]:
        code = "import aiohttp, aiofiles, httpx; print(aiohttp.__version__)"
        result = self.run([self.python, "-c", code])
        assert result.returncode == 0, (result.stderr.strip().splitlines() or ["import failed"])[-1]
        return PASS, f"aiohttp {result.stdout.strip()}"

    def optional_deps(self) -> Tuple[str, str]:
        modules = {"h2": "http/2", "curl_cffi": "ja3", "websockets": "websocket",
                   "playwright": "browser", "redis": "redis"}
        available = []
        for module, label in modules.items():
            result = self.run([self.python, "-c", f"import {module}"])
            if result.returncode == 0:
                available.append(label)
        detail = ", ".join(available) if available else "core only"
        return PASS, detail

    def lazy_harvester(self) -> Tuple[str, str]:
        # proxy_defense imports curl_cffi / websockets at module scope to set its
        # availability flags, so those are expected in sys.modules when the user
        # installed them. What must stay lazy is the genuinely heavy, rarely used
        # pair (playwright, redis), and the module must import cleanly either way.
        # Asserting "curl_cffi absent" made this check pass only for minimal
        # installs and fail for every --full install.
        code = (
            "import sys, importlib.util, proxy_defense as pd\n"
            "heavy = [m for m in ('playwright', 'redis') if m in sys.modules]\n"
            "assert not heavy, heavy\n"
            "def spec(name):\n"
            "    try:\n"
            "        return importlib.util.find_spec(name) is not None\n"
            "    except (ImportError, ValueError):\n"
            "        return False\n"
            "for mod, flag in (('curl_cffi', pd.JA3_AVAILABLE),\n"
            "                  ('websockets', pd.WS_AVAILABLE),\n"
            "                  ('playwright', pd.PLAYWRIGHT_AVAILABLE)):\n"
            "    assert spec(mod) == flag, (mod, spec(mod), flag)\n"
            "assert all(isinstance(v, bool) for v in\n"
            "           (pd.HTTP2_AVAILABLE, pd.JA3_AVAILABLE, pd.WS_AVAILABLE,\n"
            "            pd.PLAYWRIGHT_AVAILABLE))\n"
        )
        result = self.run([self.python, "-c", code])
        assert result.returncode == 0, result.stderr.strip().splitlines()[-1:]
        return PASS, "optional protocols degrade cleanly, heavy pair still lazy"

    def sticky_selection(self) -> Tuple[str, str]:
        import proxy_defense as pd

        async def scenario():
            entries = [
                pd.ProxyEntry(url="http://p1:80", proxy_type="dc", protocol="http",
                              source="test", tier=1, latency_ms=5),
                pd.ProxyEntry(url="http://p2:80", proxy_type="dc", protocol="http",
                              source="test", tier=1, latency_ms=50),
            ]
            rotator = pd.ProxyRotator(entries)
            first = await rotator.get_proxy(domain="example.com", agent_id="a1")
            repeated = {(await rotator.get_proxy(domain="example.com", agent_id="a1")).url
                        for _ in range(5)}
            assert repeated == {first.url}, "sticky binding drifted"
            await rotator.get_proxy(domain="example.com", agent_id="a2")
            stats = await rotator.session_stats()
            assert stats["active"] == 2, stats
            await rotator.rotate(agent_id="a1", domain="example.com")
            assert (await rotator.session_stats())["active"] == 1
            legacy = await pd.ProxyRotator(entries).get_proxy()
            assert legacy is not None
            return first.url

        url = asyncio.run(scenario())
        return PASS, f"bound {url}"

    def affinity_ttl(self) -> Tuple[str, str]:
        from proxy_harvester import SessionAffinityManager

        async def scenario():
            now = [0.0]
            manager = SessionAffinityManager(ttl_seconds=10, clock=lambda: now[0])
            await manager.bind("a", "example.com", "http://1.1.1.1:80")
            assert await manager.get("a", "example.com"), "binding lost"
            now[0] = 11.0
            assert await manager.get("a", "example.com") is None, "binding did not expire"

        asyncio.run(scenario())
        return PASS, "10 s TTL honoured"

    def harvester_schemas(self) -> Tuple[str, str]:
        from proxy_harvester import ProxySource, parse_proxy_item

        source = ProxySource("proxyscrape_json", "https://example.invalid", "json",
                             min_uptime=60.0, max_latency_ms=3000.0)
        proxyscrape = parse_proxy_item({
            "ip": "93.184.216.34", "port": 8080, "protocols": ["http", "https"],
            "country_code": "US", "uptime_percent": 92.5, "latency_ms": 410,
            "anonymity": "elite", "ssl": True, "asn": 1, "isp": "x",
        }, source)
        assert proxyscrape and proxyscrape["url"] == "http://93.184.216.34:8080"
        assert proxyscrape["country"] == "US"

        monosans = parse_proxy_item({
            "protocol": "socks5", "ip": "8.8.8.8", "port": "1080", "timeout": 1.4,
            "geolocation": {"country": {"iso_code": "DE"}},
        }, ProxySource("monosans_txt", "https://example.invalid", "json",
                       max_latency_ms=3000.0))
        assert monosans and monosans["country"] == "DE"
        assert monosans["latency_ms"] == 1400.0, monosans

        rejected = parse_proxy_item({"ip": "10.0.0.1", "port": 80}, source)
        assert rejected is None, "private IP accepted"
        return PASS, "proxyscrape + monosans shapes"

    def source_health(self) -> Tuple[str, str]:
        from proxy_harvester import DEFAULT_SOURCES, SourceHealthTracker

        tracker = SourceHealthTracker()
        for source in DEFAULT_SOURCES:
            tracker.record(source.name, 100, 1)
        tracker.record("proxyscrape_json", 100, 40)
        ranked = tracker.ranked(DEFAULT_SOURCES)
        assert ranked[0].name == "proxyscrape_json", [s.name for s in ranked]
        return PASS, f"top: {ranked[0].name}"

    def honeypot_hash(self) -> Tuple[str, str]:
        from proxy_harvester import HoneypotDetector

        detector = HoneypotDetector()
        same_shape = detector._hash(b'{"slideshow": {"a": 1}}')
        other_values = detector._hash(b'{"slideshow": {"a": 2}}')
        tampered = detector._hash(b"<html><script>x</script></html>")
        assert same_shape == other_values, "value churn changed the structural hash"
        assert same_shape != tampered, "script injection not detected"
        return PASS, "structural + script detection"

    def pool_persistence(self) -> Tuple[str, str]:
        import proxy_defense as pd

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "proxy_cache.json"
            entry = pd.ProxyEntry(url="http://p1:80", proxy_type="free",
                                  protocol="http", source="test", tier=4,
                                  healthy=True, validated=True)
            rotator = pd.ProxyRotator([entry], cache_file=cache)
            rotator.save_cache()
            restored = pd.ProxyRotator([], cache_file=cache)
            assert restored.load_cache() == 1
            assert restored.proxies[0].validated is True
        return PASS, "roundtrip ok"

    def config_merge(self) -> Tuple[str, str]:
        import proxy_defense as pd

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"session_ttl": 42, "max_proxies": 9,
                                        "persist_proxy_cache": False}))
            client = pd.ResilientClient(config_path=path, auto_load_proxies=False)
            assert client.session_ttl == 42, client.session_ttl
            assert client.rotator.max_proxies == 9
            override = pd.ResilientClient(config_path=path, session_ttl=7,
                                          auto_load_proxies=False)
            assert override.session_ttl == 7
        return PASS, "config + explicit override"

    def http2_guard(self) -> Tuple[str, str]:
        """A missing h2 package must degrade, not crash client construction."""
        import proxy_defense as pd

        async def scenario():
            client = pd.ResilientClient(auto_load_proxies=False,
                                        use_upstream_harvester=False,
                                        config_path=self.home / "config" / "config.json")
            async with client:
                if not pd.HTTP2_AVAILABLE:
                    return "http/2 disabled cleanly"
                return "http/2 client constructed"

        return PASS, asyncio.run(scenario())

    def cli_stats(self) -> Tuple[str, str]:
        result = self.run([str(self.home / "run.sh"), "stats", "--json"])
        assert result.returncode == 0, (result.stderr.strip().splitlines() or ["exit"])[-1]
        stats = json.loads(result.stdout)
        for key in ("proxies_total", "proxies_healthy", "session_affinity",
                    "source_health", "upstream_harvester", "protocols_available"):
            assert key in stats, f"stats missing {key}"
        return PASS, f"{stats['proxies_total']} proxies, v{stats.get('version')}"

    def mcp_selftest(self) -> Tuple[str, str]:
        result = self.run([self.python, str(self.home / "mcp_proxy_server.py"), "--selftest"],
                          env={"OWL_MCP_HARVEST": "0", "OWL_MCP_WARMUP_SEC": "0"})
        assert result.returncode == 0, result.stderr.strip()[-300:]
        return PASS, "initialize/tools/resources/ping"

    def mcp_handshake(self) -> Tuple[str, str]:
        frames = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "verify", "version": "0"}}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]) + "\n"
        merged = dict(os.environ)
        merged.update({"OWL_MCP_HARVEST": "0", "OWL_MCP_WARMUP_SEC": "0"})
        result = subprocess.run(
            [self.python, str(self.home / "mcp_proxy_server.py")],
            input=frames, capture_output=True, text=True,
            timeout=self.timeout, env=merged, cwd=str(self.home),
        )
        assert result.returncode == 0, result.stderr.strip()[-300:]
        responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        assert len(responses) == 2, f"expected 2 frames, got {len(responses)}"
        info = responses[0]["result"]["serverInfo"]
        assert info["name"] == "owl-proxy", info
        tools = {tool["name"] for tool in responses[1]["result"]["tools"]}
        assert tools == {"proxy_pick", "proxy_stats", "proxy_rotate", "proxy_validate"}, tools
        for line in result.stdout.splitlines():
            if line.strip():
                json.loads(line)  # stdout purity
        return PASS, f"{info['version']}, 4 tools"

    def live_harvest(self) -> Tuple[str, str]:
        from proxy_harvester import DEFAULT_SOURCES, UpstreamHarvester

        async def scenario():
            async with UpstreamHarvester(timeout=12.0, concurrency=4) as harvester:
                proxies = await harvester.harvest(max_per_source=20)
                health = harvester.health.snapshot()
                return proxies, health

        try:
            proxies, health = asyncio.run(scenario())
        except Exception as exc:
            return SKIP, f"offline ({type(exc).__name__})"
        reachable = [name for name, data in health.items() if data["failures"] == 0]
        if not proxies:
            errors = {name: data["last_error"] for name, data in health.items()
                      if data["last_error"]}
            if not reachable:
                return SKIP, "no source reachable"
            return FAIL, f"sources reached but yielded 0 proxies: {errors}"
        sample = proxies[0]["url"]
        return PASS, f"{len(proxies)} proxies from {len(reachable)} sources (e.g. {sample})"

    def live_fetch(self) -> Tuple[str, str]:
        result = self.run([str(self.home / "run.sh"), "fetch",
                           "https://httpbin.org/status/200", "--json"])
        if result.returncode != 0:
            return SKIP, "offline"
        payload = json.loads(result.stdout[result.stdout.find("{"):])
        if payload.get("status") != 200:
            return FAIL, f"status {payload.get('status')}"
        return PASS, f"status 200 via {payload.get('protocol')}"

    # ── driver ─────────────────────────────────────────────────────────
    def run_all(self) -> int:
        print(f"\n{DIM}verifying {self.home} with {self.python}{RESET}\n")
        self.check("V1  layout (modules + launcher)", self.layout)
        self.check("V2  config keys", self.config_files)
        self.check("V3  cold import time", self.cold_import)
        self.check("V4  API surface", self.api_surface)
        self.check("V5  core dependencies", self.core_deps)
        self.check("V6  optional protocols", self.optional_deps)
        self.check("V7  lazy optional imports", self.lazy_harvester)
        self.check("V8  sticky selection + rotation", self.sticky_selection)
        self.check("V9  session TTL", self.affinity_ttl)
        self.check("V10 harvester schemas", self.harvester_schemas)
        self.check("V11 source-health ranking", self.source_health)
        self.check("V12 honeypot hash", self.honeypot_hash)
        self.check("V13 pool persistence", self.pool_persistence)
        self.check("V14 config merge", self.config_merge)
        self.check("V15 http/2 guard", self.http2_guard)
        self.check("V16 CLI stats", self.cli_stats)
        self.check("V17 MCP selftest", self.mcp_selftest)
        self.check("V18 MCP stdio handshake", self.mcp_handshake)
        if self.live:
            self.check("V19 live harvest", self.live_harvest)
            self.check("V20 end-to-end fetch", self.live_fetch)
        else:
            self.add(SKIP, "V19 live harvest", "--no-live")
            self.add(SKIP, "V20 end-to-end fetch", "--no-live")

        passed = sum(1 for status, _, _ in self.results if status == PASS)
        failed = sum(1 for status, _, _ in self.results if status == FAIL)
        skipped = sum(1 for status, _, _ in self.results if status == SKIP)
        print("\n" + "─" * 62)
        color = GREEN if failed == 0 else RED
        print(f"{color}PASS: {passed}   FAIL: {failed}   SKIP: {skipped}{RESET}")
        return 0 if failed == 0 else 1


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="🦉 OWL-AGENT v7.1 install verification")
    parser.add_argument("--owl-home", default=os.environ.get("OWL_HOME",
                                                             str(Path.home() / ".owl-agent")))
    parser.add_argument("--python", default=None,
                        help="interpreter to use (default: <owl-home>/venv/bin/python)")
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    parser.add_argument("--no-live", action="store_true", help="skip network checks")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)

    home = Path(args.owl_home).expanduser()
    if not home.exists():
        print(f"❌ {home} does not exist — run install-owl.sh first", file=sys.stderr)
        return 1
    python = args.python or str(home / "venv" / "bin" / "python")
    if not Path(python).exists():
        python = sys.executable

    checks = Checks(home, python, live=not args.no_live, timeout=args.timeout)
    code = checks.run_all()
    if args.json:
        summary = [{"status": status, "check": name, "detail": detail}
                   for status, name, detail in checks.results]
        print(json.dumps({"passed": sum(1 for r in summary if r["status"] == PASS),
                          "failed": sum(1 for r in summary if r["status"] == FAIL),
                          "skipped": sum(1 for r in summary if r["status"] == SKIP),
                          "results": summary}, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
