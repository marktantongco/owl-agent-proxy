# 🦉 OWL-AGENT Proxy Defense Stack v7.1

> **Multi-protocol HTTP defense system** with intelligent caching, request deduplication, domain rate limiting, tier-based proxy rotation, **upstream harvesting**, **honeypot/injection detection**, **sticky per-agent sessions** and an **MCP server** so AI agents can borrow the pool. Start with `http/1.1`, escalate only when justified.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI/CD](https://github.com/marktantongco/owl-agent-proxy/actions/workflows/protocol-check.yml/badge.svg)](https://github.com/marktantongco/owl-agent-proxy/actions/workflows/protocol-check.yml)

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
- [What's new in v7.1](#whats-new-in-v71)
- [System Requirements](#system-requirements)
- [Quick Start (5 minutes)](#quick-start-5-minutes)
- [Complete Installation Guide](#complete-installation-guide)
  - [Phase 1: Core (http/1.1)](#phase-1-core-http11)
  - [Phase 2: HTTP/2](#phase-2-http2)
  - [Phase 3: JA3 Anti-Bot](#phase-3-ja3-anti-bot)
  - [Phase 4: WebSocket](#phase-4-websocket)
  - [Phase 5: Browser Automation](#phase-5-browser-automation)
- [Configuration](#configuration)
  - [Proxy Pool Setup](#proxy-pool-setup)
  - [v7.1 Upstream Configuration](#v71-upstream-configuration)
  - [ResilientClient Parameters](#resilientclient-parameters)
  - [Environment Variables](#environment-variables)
- [Usage](#usage)
  - [Python API](#python-api)
  - [MCP Server (AI agents)](#mcp-server-ai-agents)
  - [CLI Mode](#cli-mode)
  - [Protocol Escalation](#protocol-escalation)
- [CI/CD Pre-Merge Check](#cicd-pre-merge-check)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Protocol Escalation Strategy](#protocol-escalation-strategy)
- [Skills System](#skills-system)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [License](#license)

---

## Architecture

```
Upstream lists ─→ Harvest ─→ Quarantine ─→ Validate ─→ Honeypot ─→ Pool
 (4 sources)      dedupe     tier 4,        TCP+HTTP    structural   tier 1..4
                            healthy=False   probe       hash         │
                                                                     ↓
Request → Cache → Deduplicate → Rate Limit → Sticky Select → Protocol Router → Response
            ↓           ↓            ↓             ↓              ↓
          HIT?      In-flight?   Token Bucket   (agent_id,     http/1.1 | http/2
          Return    Await result   Per-domain   domain) bind    | ja3 | websocket
          cached    same result                  TTL 15 min     | browser
```

### Component Flow

1. **HTTPCache** — SHA-256 keyed in-memory cache with TTL. Protocol-aware.
2. **RequestDeduplicator** — Coalesces in-flight identical requests into one network call.
3. **DomainRateLimiter** — Per-domain token bucket. Configurable rate/capacity.
4. **ProxyRotator** — Tier-sorted pool. Health tracking. Auto-ban on 3 failures.
5. **ProxyRotator** — Tier-sorted selection with sticky per-(agent, domain) bindings, upstream harvesting, validation and honeypot screening.
6. **ProtocolRouter** — Routes to the correct handler based on `protocol` parameter.
7. **ResilientClient** — Context manager orchestrating all components with retry logic.
8. **MCP server** — stdlib-only stdio JSON-RPC exposing the pool as 4 agent tools.

---

## Features

| Feature | Description |
|---------|-------------|
| **5 Protocols** | HTTP/1.1, HTTP/2, JA3 (TLS fingerprint), WebSocket, Browser (Playwright) |
| **Smart Caching** | SHA-256 keyed, TTL-based, protocol-aware, in-memory |
| **Deduplication** | In-flight request coalescing — no duplicate network calls |
| **Rate Limiting** | Per-domain token bucket algorithm |
| **Proxy Rotation** | Tier-based pool with health tracking, auto-ban, latency sorting |
| **Protocol Escalation** | Start `http/1.1`, escalate only when CI/CD-justified |
| **CI/CD Enforcement** | Pre-merge check validates escalation + blocks hardcoded credentials |
| **Retry Logic** | Exponential backoff with jitter, max 3 retries |
| **Upstream Harvesting** | Four free-list sources, tolerant schema parsing, per-source yield learning, on-disk pool persistence |
| **Honeypot Detection** | Structural body hash catches injected redirects, injected scripts and tampered responses |
| **Sticky Sessions** | One exit IP per `(agent_id, domain)` for 15 min — avoids "teleporting user" bot signals |
| **MCP Server** | `proxy_pick` / `proxy_stats` / `proxy_rotate` / `proxy_validate` over stdio for Claude, Cursor, VS Code, Codex, Gemini |

---

## What's new in v7.1

| Area | Before (v3.0) | v7.1 |
|------|---------------|------|
| Proxy inventory | Only what you put in `proxy_pool.json` | Four upstream lists harvested on a timer, quarantined, validated, persisted |
| Source quality | — | `SourceHealthTracker` (0.85 decay) ranks sources by real yield and records last error |
| Trust | — | `HoneypotDetector` rejects proxies that redirect, inject scripts or alter bodies |
| Session model | Per-request rotation | Sticky `(agent_id, domain)` binding, plus `random` / `round_robin` modes |
| Agent access | CLI only | MCP server with 4 tools — see [docs/MCP_INTEGRATION.md](docs/MCP_INTEGRATION.md) |
| Install | Manual pip + copy | `./install-owl.sh` — idempotent, backed up, 20-check verification |
| Tests | 9 | 137 (harvester, MCP protocol, sticky sessions, cache, config) |
| CI | Protocol + credential check | + pytest on 3.10/3.11/3.12 + installer smoke test |

Deep dive: [docs/V7_UPSTREAM.md](docs/V7_UPSTREAM.md).

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **OS** | Linux (Ubuntu 20.04+), macOS 12+, Windows 10+ (WSL2) | Ubuntu 22.04 LTS |
| **Python** | 3.10 | 3.11+ |
| **RAM** | 512 MB (core only) | 2 GB (all protocols) |
| **Disk** | 100 MB (core) | 500 MB (with Playwright browsers) |
| **Network** | Outbound HTTP/HTTPS | Outbound + proxy access |

### Dependency Matrix

| Package | Purpose | Phase | Required |
|---------|---------|-------|----------|
| `aiohttp` | HTTP/1.1 async client | 1 | **Yes** |
| `httpx` | harvester + honeypot probe (HTTP/2 client when `h2` present) | 1 | **Yes** |
| `aiofiles` | Async file I/O | 1 | **Yes** |
| `cachetools` | Cache utilities | 1 | **Yes** |
| `orjson` | Fast JSON serialization | 1 | **Yes** |
| `cryptography` | TLS/crypto operations | 1 | **Yes** |
| `PySocks` | SOCKS proxy support | 1 | **Yes** |
| `tenacity` | Retry logic | 1 | **Yes** |
| `fake-useragent` | User agent rotation | 1 | **Yes** |
| `h2` | enables HTTP/2 for httpx (`pip install httpx[http2]`) | 2 | No |
| `curl_cffi` | JA3/TLS fingerprint spoofing | 3 | No |
| `websockets` | WebSocket client | 4 | No |
| `playwright` | Browser automation | 5 | No |

---

## Quick Start (5 minutes)

### One command (recommended)

```bash
git clone https://github.com/marktantongco/owl-agent-proxy.git
cd owl-agent-proxy
./install-owl.sh              # --no-live if this machine has no egress
```

This builds `~/.owl-agent` (venv, modules, config), preserves any existing
`proxy_pool.json` / `proxy_cache.json` / `models/`, takes a timestamped backup,
and runs the 20-check verification suite. Re-running upgrades code and merges
new config keys without touching your values.

```bash
~/.owl-agent/run.sh stats                  # pool + source + session telemetry
~/.owl-agent/run.sh fetch https://httpbin.org/ip --json
~/.owl-agent/run.sh harvest --seconds 20   # force one upstream sweep
~/.owl-agent/run.sh mcp-selftest           # MCP protocol check
```

### Manual (library only)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# optional protocol layers
pip install 'httpx[http2]' curl_cffi websockets

python proxy_defense.py        # demo / smoke test
```

Expected output:
```
🦉 OWL-AGENT Proxy Defense Stack v7.1
==================================================
Proxy Pool: 0 | Healthy: 0
Protocols: {'http/1.1': True, 'http/2': False, 'ja3': False, 'websocket': False, 'browser': False}

Test: Status 200, Protocol: http/1.1

✅ Defense stack operational.
```

No egress? The demo prints a warning and exits 0 — the stack still initialises.

---

## Complete Installation Guide

> **Shortcut:** `./install-owl.sh` does everything below (venv, dependencies,
> config, launcher, verification) and is idempotent. The manual phases are for
> people who want to compose their own environment or install protocol layers
> individually.

### Phase 1: Core (http/1.1)

**What you get:** HTTP/1.1 async client, caching, deduplication, rate limiting, proxy rotation.

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  (Windows)

# Install core dependencies
pip install -r requirements.txt

# Verify installation
python -c "import aiohttp, aiofiles, httpx, cachetools, orjson, cryptography, socks; print('✅ Core installed')"
```

**Test it:**
```bash
python proxy_defense.py
```

---

### Phase 2: HTTP/2

**What you get:** HTTP/2 multiplexing for concurrent requests to the same domain.

```bash
source venv/bin/activate
pip install httpx[http2]

# Verify
python -c "import httpx; c = httpx.AsyncClient(http2=True); print('✅ HTTP/2 available')"
```

**Usage:**
```python
resp = await client.request("GET", "https://http2.golang.org/reqinfo", protocol="http/2")
```

---

### Phase 3: JA3 Anti-Bot

**What you get:** TLS fingerprint spoofing to bypass Cloudflare, DataDome, Akamai.

```bash
source venv/bin/activate
pip install curl_cffi

# Verify
python -c "from curl_cffi.requests import AsyncSession; print('✅ JA3 available')"
```

**Usage:**
```python
resp = await client.request("GET", "https://cloudflare-protected-site.com", protocol="ja3")
```

---

### Phase 4: WebSocket

**What you get:** Real-time WebSocket connections through proxy rotation.

```bash
source venv/bin/activate
pip install websockets

# Verify
python -c "import websockets; print('✅ WebSocket available')"
```

**Usage:**
```python
resp = await client.request("GET", "wss://echo.websocket.org", protocol="websocket")
```

---

### Phase 5: Browser Automation

**What you get:** Full headless browser for JS-rendered content and CAPTCHA bypass.

```bash
source venv/bin/activate
pip install playwright
playwright install chromium  # ~150 MB download

# Verify
python -c "from playwright.async_api import async_playwright; print('✅ Browser available')"
```

**Usage:**
```python
resp = await client.request("GET", "https://js-heavy-site.com", protocol="browser")
```

---

### One-Command Full Install

```bash
# repo-native installer: core + optional protocols
./install-owl.sh --full

# optional later, if you need JS challenges solved
~/.owl-agent/venv/bin/python -m pip install playwright
~/.owl-agent/venv/bin/python -m playwright install chromium
```

---

## Configuration

### Proxy Pool Setup

1. Copy the template:
```bash
cp config/proxy_pool.template.json config/proxy_pool.json
```

2. Edit with your proxy credentials:
```json
{
  "tier_1_managed_free": {
    "providers": [
      {
        "name": "webshare",
        "proxies": [
          {"url": "http://YOUR_USERNAME:YOUR_PASSWORD@p.webshare.io:80", "type": "datacenter", "protocols": ["HTTP", "SOCKS5"]}
        ]
      }
    ]
  },
  "settings": {
    "health_check_interval": 300,
    "ban_duration": 300,
    "max_retries": 3,
    "backoff_base": 1.5,
    "rotate_on_error_only": true
  }
}
```

3. The `ResilientClient` auto-loads this file on startup when `auto_load_proxies=True`.

### v7.1 Upstream Configuration

`~/.owl-agent/config/config.json` (all keys optional; missing keys fall back to
built-in defaults):

| Key | Default | Meaning |
|-----|---------|---------|
| `use_upstream_harvester` | `false` (library) / `true` (installer) | harvest the four free lists |
| `session_ttl` | `900` | sticky binding lifetime, seconds |
| `harvest_interval` | `600` | seconds between sweeps |
| `honeypot_check` | `true` | verify harvested proxies against a response baseline |
| `max_proxies` | `2000` | pool cap (tier-1 managed proxies always survive) |
| `max_per_source` | `300` | candidates accepted per source per sweep |
| `validator_concurrency` | `10` | parallel validation probes |
| `validator_timeout` | `8` | seconds per probe |
| `persist_proxy_cache` | `true` | write the pool to `config/proxy_cache.json` |

Turn harvesting off without uninstalling:

```json
{ "use_upstream_harvester": false }
```

### ResilientClient Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cache_ttl` | `int` | 300 | Cache time-to-live in seconds |
| `rate_limit` | `float` | 1.0 | Requests per second per domain |
| `max_retries` | `int` | 3 | Maximum retry attempts before raising |
| `auto_load_proxies` | `bool` | True | Auto-load proxy pool from `~/.owl-agent/config/proxy_pool.json` |
| `default_protocol` | `str` | `"http/1.1"` | Default protocol when not specified |
| `use_upstream_harvester` | `bool` | config / False | enable v7.1 harvesting |
| `session_ttl` | `float` | 900 | sticky session lifetime |
| `harvest_interval` | `float` | 600 | seconds between sweeps |
| `honeypot_check` | `bool` | True | body-integrity screening |
| `max_proxies` | `int` | 2000 | pool cap |
| `config_path` | `str` | `~/.owl-agent/config/config.json` | config to merge |

Precedence: explicit argument → `config.json` → built-in default.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OWL_AGENT_HOME` | Base directory for OWL-AGENT | `~/.owl-agent` |
| `OWL_AGENT_CONFIG` | Config directory | `~/.owl-agent/config` |
| `OWL_AGENT_CACHE` | Cache directory | `~/.owl-agent/cache` |
| `OWL_HOME` | Install root used by `install-owl.sh` / `run.sh` | `~/.owl-agent` |
| `OWL_MCP_HARVEST` | `0` disables harvesting inside the MCP server, `1` forces it | unset → `config.json` |
| `OWL_MCP_WARMUP_SEC` | seconds `proxy_pick` waits for a live pool | `3` |
| `HTTP_PROXY` | System-wide HTTP proxy | None |
| `HTTPS_PROXY` | System-wide HTTPS proxy | None |

---

## Usage

### Python API

#### Basic Request
```python
import asyncio
from proxy_defense import ResilientClient

async def main():
    async with ResilientClient() as client:
        resp = await client.request("GET", "https://httpbin.org/get")
        print(f"Status: {resp.status}")
        print(f"Protocol: {resp.protocol}")
        print(f"Content: {resp.content[:100]}")

asyncio.run(main())
```

#### With Custom Headers and Params
```python
async def main():
    async with ResilientClient(rate_limit=2.0) as client:
        resp = await client.request(
            "GET",
            "https://httpbin.org/get",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"key": "value"}
        )
        print(f"Status: {resp.status}")

asyncio.run(main())
```

#### Protocol Escalation
```python
async def main():
    async with ResilientClient() as client:
        # Start with http/1.1
        resp = await client.request("GET", "https://example.com")

        # Escalate to JA3 if blocked
        if resp.status == 403:
            resp = await client.request("GET", "https://example.com", protocol="ja3")

        # Last resort: browser
        if resp.status == 403:
            resp = await client.request("GET", "https://example.com", protocol="browser")

asyncio.run(main())
```

#### Get Statistics
```python
async def main():
    async with ResilientClient() as client:
        stats = await client.get_stats()
        print(f"Proxies: {stats['proxies_healthy']}/{stats['proxies_total']} healthy")
        print(f"Cache entries: {stats['cache_memory_size']}")
        print(f"Protocols: {stats['protocols_available']}")

asyncio.run(main())
```

### Sticky Sessions

```python
async with ResilientClient(use_upstream_harvester=True) as client:
    # same agent + domain → same exit IP for session_ttl (default 15 min)
    a = await client.request("GET", "https://target.example/a", agent_id="job-42")
    b = await client.request("GET", "https://target.example/b", agent_id="job-42")

    # a different agent gets its own binding
    c = await client.request("GET", "https://target.example/c", agent_id="job-43")

    # target started blocking: drop the binding before the next call
    await client.rotator.rotate(agent_id="job-42", domain="target.example")

    # optional: per-call mode
    d = await client.request("GET", "https://target.example/d",
                             rotation_mode="round_robin")
```

### CLI Mode

```bash
~/.owl-agent/run.sh                      # demo / smoke test
~/.owl-agent/run.sh stats                # pool, sources, sessions
~/.owl-agent/run.sh stats --json         # machine-readable
~/.owl-agent/run.sh fetch URL --json     # fetch through the stack
~/.owl-agent/run.sh harvest --seconds 20 # force a sweep, report yield
~/.owl-agent/run.sh validate http://IP:PORT
~/.owl-agent/run.sh mcp-selftest         # MCP protocol check
~/.owl-agent/run.sh verify --no-live     # re-run install verification

# from a repo checkout, without installing:
python proxy_defense.py stats
python proxy_defense.py --harvest harvest --seconds 20
```

Exit codes: `harvest`/`stats` are 0 unless setup is broken; `validate` returns 1
when the proxy is unusable (or is a socks proxy, which the prober does not test).

### MCP Server (AI agents)

```bash
~/.owl-agent/run.sh mcp        # stdio JSON-RPC server
```

Tools: `proxy_pick`, `proxy_stats`, `proxy_rotate`, `proxy_validate`. Host
snippets for Claude Desktop, Claude Code, Cursor, VS Code, Codex, Gemini CLI and
OpenCode: [docs/MCP_INTEGRATION.md](docs/MCP_INTEGRATION.md).

```text
proxy_pick(domain="target.example", agent_id="job-42")
  ├─ proxy != null → use it for the whole task
  └─ proxy == null → fetch directly this once (pool still warming)
```

### Protocol Escalation

| Step | Protocol | When to Use | Latency | Cost |
|------|----------|-------------|---------|------|
| 0 | `http/1.1` | Default baseline | ~100ms | 1x |
| 1 | `http/1.1` + proxy rotation | Rate limited (429) | ~150ms | 1.3x |
| 2 | `http/2` | HTTP/1.1 blocked | ~120ms | 1.2x |
| 3 | `ja3` | TLS fingerprint blocked | ~200ms | 2x |
| 4 | `browser` | JS challenge/CAPTCHA | ~1500ms | 10x |
| 5 | `browser` + residential | Everything blocked | ~2000ms | 13x |

**Rule:** Always answer "Why not http/1.1?" before escalating.

---

## CI/CD Pre-Merge Check

The CI/CD script enforces two rules before code can be merged:

### Check 1: Protocol Escalation Justification

Scans for `protocol="ja3"`, `protocol="browser"`, `protocol="http/2"`, `protocol="websocket"` and requires ≥3/4 justification markers:

| Marker | Keyword |
|--------|---------|
| Baseline | `http/1.1`, `http1`, `baseline` |
| Anti-bot | `cloudflare`, `datadome`, `akamai`, `anti.bot` |
| Performance | `latency`, `ms`, `benchmark`, `tested` |
| Approval | `approved`, `APPROVED` |

### Check 2: Proxy Credential Security

Detects hardcoded credentials (`://user:pass@`) in source files. Excludes `proxy_pool.json` and test files.

### Run Locally

```bash
bash .github/scripts/ci-check.sh
```

### GitHub Actions

`.github/workflows/protocol-check.yml` runs three jobs on PRs (and pushes to
`main`): the escalation/credential guard, `pytest` on Python 3.10/3.11/3.12, and
an installer smoke test that installs into a throwaway `HOME` twice (install +
idempotent re-run) and then re-verifies with `--verify-only --no-live`.

Automatically runs on every PR to `main` or `develop`:

```yaml
# .github/workflows/protocol-check.yml
name: 🦉 OWL-AGENT Protocol Check
on:
  pull_request:
    branches: [main, develop]
jobs:
  protocol-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          chmod +x .github/scripts/ci-check.sh
          .github/scripts/ci-check.sh
```

---

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # 137 tests, offline
python mcp_proxy_server.py --selftest     # MCP protocol
python proxy_defense.py                   # live demo (needs egress)
bash .github/scripts/ci-check.sh          # escalation + credential guard
~/.owl-agent/run.sh verify --no-live      # install verification (V1–V20)
```

### Test Coverage

| File | Tests | Covers |
|------|-------|--------|
| `tests/test_proxy_defense.py` | 9 | TTL, token buckets, bans, cache, rotation |
| `tests/test_proxy_harvester.py` | 59 | ProxyScrape + monosans schemas, IP filtering, source health, text/JSON envelopes, affinity TTL/eviction, honeypot hashing, probe rejection |
| `tests/test_v71_integration.py` | 32 | sticky selection, rotation modes, quarantine, honeypot rejection, trimming, persistence, config merge, dedupe failures |
| `tests/test_mcp_server.py` | 37 | frames (newline + Content-Length), initialize/notifications/batch, all four tools, stdout purity, real stdio subprocess |

Everything above runs offline; live-egress behaviour is covered by the
installer's V19/V20 checks, which SKIP without network.

---

## Project Structure

```
owl-agent-proxy/
├── install-owl.sh                # v7.1 installer (idempotent, backs up, verifies)
├── proxy_defense.py              # Defense stack: cache, dedupe, rate limit, pool, protocols
├── proxy_harvester.py            # Upstream harvest, honeypot detector, session affinity
├── mcp_proxy_server.py           # MCP server (stdlib stdio JSON-RPC, 4 tools)
├── requirements.txt              # Pinned core dependencies
├── requirements-dev.txt          # pytest + pytest-asyncio
├── pytest.ini                    # Test config (async mode, testpaths)
├── .gitignore                    # Git ignore rules
├── README.md                     # This file
├── worklog.md                    # Session worklog template
├── .github/
│   ├── scripts/
│   │   └── ci-check.sh           # Escalation + credential guard
│   └── workflows/
│       └── protocol-check.yml    # CI: guard + pytest (3.10–3.12) + installer smoke
├── config/
│   ├── AGENTS.md                 # Agent system prompt
│   ├── opencode.json             # OpenCode plugin configuration
│   └── proxy_pool.template.json  # Proxy pool template (copy to use)
├── docs/
│   ├── MCP_INTEGRATION.md        # Per-host MCP wiring + tool reference
│   ├── V7_UPSTREAM.md            # Harvesting, honeypot, sticky sessions, runbook
│   ├── PROTOCOL_ESCALATION_GUIDE.md  # When and how to escalate protocols
│   └── LAYERED_FALLBACK.md           # Fallback architecture and resilience
├── examples/
│   └── usage.py                  # Usage examples for all protocols
├── scripts/
│   ├── install-ubuntu.sh         # Ubuntu system install (apt + phases)
│   └── verify-install.py         # V1–V20 install verification
├── skills/
│   ├── development/
│   │   └── code-generation.md    # Code generation skill
│   └── system/
│       ├── audit-optimizer.md    # Performance audit skill
│       ├── brainstorm.md         # Divergent thinking skill
│       ├── compare-a-b.md        # A/B comparison skill
│       ├── decision-tree.md      # Decision tree skill
│       ├── explain-analyzer.md   # SQL EXPLAIN skill
│       ├── research.md           # Research skill
│       └── simulator.md          # Interaction tracing skill
└── tests/
    ├── test_proxy_defense.py     # Core stack unit tests
    ├── test_proxy_harvester.py   # Harvester / affinity / honeypot (offline)
    ├── test_v71_integration.py   # Pool + client integration (offline)
    └── test_mcp_server.py        # MCP protocol + stdio subprocess
```

---

## Protocol Escalation Strategy

### The Golden Rule

> **Start with `http/1.1`. Escalate only when you hit a specific anti-bot wall.**

### Decision Tree

```
Target accessible with http/1.1?
├── Yes → Use http/1.1 + cache. Done.
└── No → What error?
    ├── 429 (Rate Limited) → Add proxy rotation
    ├── 403 (Forbidden) → What anti-bot system?
    │   ├── Cloudflare → Try ja3
    │   ├── DataDome → Try ja3
    │   ├── Akamai → Try browser
    │   └── Unknown → Try ja3 first, then browser
    └── Timeout → Check proxy health, rotate
```

### Code Review Template

```python
# Escalated to browser because:
# - http/1.1 returned 403 with Akamai Bot Manager
# - ja3 returned 403 (JS fingerprinting, not just TLS)
# - Browser latency: 1500ms vs http/1.1: 150ms (10x)
# - Tested on 2026-05-16, confirmed working
protocol="browser"  # APPROVED: Akamai requires full browser
```

---

## Skills System

The `skills/` directory contains reusable agent skills for common workflows. Each skill is a markdown file with context, instructions, constraints, and examples.

| Skill | Purpose | Trigger |
|-------|---------|---------|
| `code-generation` | Production-grade code with tests | Building features, refactoring |
| `audit-optimizer` | Profile → diagnose → fix loops | Performance issues |
| `brainstorm` | Divergent thinking, alternatives | Stuck on single-path solution |
| `compare-a-b` | Weighted A/B comparison | Choosing between options |
| `decision-tree` | Branching logic maps | Routing decisions |
| `explain-analyzer` | SQL EXPLAIN interpretation | Slow database queries |
| `research` | Deep-dive with source validation | Before build decisions |
| `simulator` | End-to-end interaction tracing | Building UI, APIs, workflows |

---

## Limitations

Stated plainly, because these matter more than the feature list:

- **Free proxies only.** The default pool is harvested free lists — no paid
  residential network. Throughput and lifetime are unpredictable; the scoring
  adapts, but there is no SLA. For stable geo-targeted residential IPs, plug a
  paid provider in as a `ProxySource`.
- **Sticky IP, static fingerprint.** `SessionAffinityManager` keeps the exit IP
  coherent per `(agent_id, domain)`, but the TLS/HTTP impersonation profile is
  fixed per client instance. Per-session fingerprint rotation is not implemented.
- **Honeypot detection is structural, not semantic.** It catches redirect
  injection, script injection and body tampering relative to a baseline; a proxy
  that rewrites a single field *without* changing shape or adding markup is not
  detected.
- **No socks validation.** `validate_proxy` probes HTTP/HTTPS proxies only.
- **Detection arms race.** Everything here is a heuristic. Targets change; the
  stack's behaviour is best-effort, not guaranteed.
- **No compliance advice.** Using anonymous proxies has legal and ToS
  implications that vary by jurisdiction and target. The tool is a tool; the
  policy is yours.

---

## Troubleshooting

### Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'aiohttp'` | Dependencies not installed | `pip install -r requirements.txt` |
| `httpx not available` | HTTP/2 not installed | `pip install httpx[http2]` |
| `curl_cffi not available` | JA3 not installed | `pip install curl_cffi` |
| `playwright not available` | Browser not installed | `pip install playwright && playwright install chromium` |
| `Proxy Pool: 0` | No proxy_pool.json | `cp config/proxy_pool.template.json config/proxy_pool.json` and edit |
| `Max retries exceeded` | All proxies banned | Check proxy URLs, increase `ban_duration`, add more proxies |
| `CI/CD check fails` | Missing justification | Add `# APPROVED:` comment with benchmark evidence |
| `Proxy Pool: 0` after 5 min | no egress, or all sources down | `run.sh stats --json` → `.source_health[*].last_error` |
| `proxy_pick` returns `null` | pool still validating | wait ~2 min; check `.upstream_harvester.unvalidated` |
| Honeypot rejections high | baseline mismatch (captive portal / CDN edge) | restart to re-baseline, or set `"honeypot_check": false` |
| `Future exception was never retrieved` (pre-7.1) | dedupe leaked failures | fixed in v7.1 — upgrade |
| Installer stops at verification | a module is missing or corrupt | `./install-owl.sh --verify-only` for detail, `--rollback` to revert |

### Debug Mode

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Verify Installation

```bash
# Check all imports
python -c "
import aiohttp, aiofiles, cachetools, orjson, cryptography, socks
print('✅ Core: OK')
try:
    import httpx; print('✅ HTTP/2: OK')
except: print('⚠️ HTTP/2: not installed')
try:
    from curl_cffi.requests import AsyncSession; print('✅ JA3: OK')
except: print('⚠️ JA3: not installed')
try:
    import websockets; print('✅ WebSocket: OK')
except: print('⚠️ WebSocket: not installed')
try:
    from playwright.async_api import async_playwright; print('✅ Browser: OK')
except: print('⚠️ Browser: not installed')
"
```

---

## Security

- **No hardcoded credentials** — Proxy URLs go in `proxy_pool.json` (gitignored)
- **CI/CD credential scan** — Blocks commits with `://user:pass@` patterns
- **SOCKS5 support** — Encrypted proxy connections via `PySocks`
- **TLS verification** — `certifi` bundle for certificate validation
- **No secret logging** — Logger excludes headers, auth tokens, cookies

### Best Practices

1. Never commit `proxy_pool.json` (contains credentials)
2. Use `proxy_pool.template.json` for sharing structure
3. Rotate proxy credentials regularly
4. Monitor proxy health via `get_stats()`
5. Use `rotate_on_error_only: true` to avoid fingerprinting

---

## License

MIT — See [LICENSE](LICENSE) for details.

## Author

[marktantongco](https://github.com/marktantongco)

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Run CI/CD check locally (`bash .github/scripts/ci-check.sh`)
4. Commit with justification comments for any protocol escalation
5. Push and open a Pull Request

---

*Build it once → it runs forever.*
