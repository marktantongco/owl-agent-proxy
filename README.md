# 🦉 OWL-AGENT Proxy Defense Stack v3.0

> **Multi-protocol HTTP defense system** with intelligent caching, request deduplication, domain rate limiting, and tier-based proxy rotation. Start with `http/1.1`, escalate only when justified.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI/CD](https://github.com/marktantongco/owl-agent-proxy/actions/workflows/protocol-check.yml/badge.svg)](https://github.com/marktantongco/owl-agent-proxy/actions/workflows/protocol-check.yml)

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
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
  - [ResilientClient Parameters](#resilientclient-parameters)
  - [Environment Variables](#environment-variables)
- [Usage](#usage)
  - [Python API](#python-api)
  - [CLI Mode](#cli-mode)
  - [Protocol Escalation](#protocol-escalation)
- [CI/CD Pre-Merge Check](#cicd-pre-merge-check)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Protocol Escalation Strategy](#protocol-escalation-strategy)
- [Skills System](#skills-system)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [License](#license)

---

## Architecture

```
Request → Cache → Deduplicate → Rate Limit → Proxy Rotate → Protocol Router → Response
            ↓           ↓            ↓             ↓              ↓
          HIT?      In-flight?   Token Bucket   Tier-sorted   http/1.1 | http/2
          Return    Await result   Per-domain   by latency    | ja3 | websocket
          cached    same result                  health       | browser
```

### Component Flow

1. **HTTPCache** — SHA-256 keyed in-memory cache with TTL. Protocol-aware.
2. **RequestDeduplicator** — Coalesces in-flight identical requests into one network call.
3. **DomainRateLimiter** — Per-domain token bucket. Configurable rate/capacity.
4. **ProxyRotator** — Tier-sorted pool. Health tracking. Auto-ban on 3 failures.
5. **ProtocolRouter** — Routes to the correct handler based on `protocol` parameter.
6. **ResilientClient** — Context manager orchestrating all components with retry logic.

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
| `aiofiles` | Async file I/O | 1 | **Yes** |
| `cachetools` | Cache utilities | 1 | **Yes** |
| `orjson` | Fast JSON serialization | 1 | **Yes** |
| `cryptography` | TLS/crypto operations | 1 | **Yes** |
| `PySocks` | SOCKS proxy support | 1 | **Yes** |
| `tenacity` | Retry logic | 1 | **Yes** |
| `fake-useragent` | User agent rotation | 1 | **Yes** |
| `httpx[http2]` | HTTP/2 async client | 2 | No |
| `curl_cffi` | JA3/TLS fingerprint spoofing | 3 | No |
| `websockets` | WebSocket client | 4 | No |
| `playwright` | Browser automation | 5 | No |

---

## Quick Start (5 minutes)

```bash
# 1. Clone
git clone https://github.com/marktantongco/owl-agent-proxy.git
cd owl-agent-proxy

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install core dependencies
pip install -r requirements.txt

# 4. Run built-in test
python proxy_defense.py
```

Expected output:
```
🦉 OWL-AGENT Proxy Defense Stack v3.0
==================================================
Proxy Pool: 0 | Healthy: 0
Protocols: {'http/1.1': True, 'http/2': False, 'ja3': False, 'websocket': False, 'browser': False}

Test: Status 200, Protocol: http/1.1

✅ Defense stack operational.
```

---

## Complete Installation Guide

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
python -c "import aiohttp, aiofiles, cachetools, orjson, cryptography, socks; print('✅ Core installed')"
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
# Install everything at once (not recommended for production)
pip install -r requirements.txt httpx[http2] curl_cffi websockets playwright
playwright install chromium
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

### ResilientClient Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cache_ttl` | `int` | 300 | Cache time-to-live in seconds |
| `rate_limit` | `float` | 1.0 | Requests per second per domain |
| `max_retries` | `int` | 3 | Maximum retry attempts before raising |
| `auto_load_proxies` | `bool` | True | Auto-load proxy pool from `~/.owl-agent/config/proxy_pool.json` |
| `default_protocol` | `str` | `"http/1.1"` | Default protocol when not specified |

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OWL_AGENT_HOME` | Base directory for OWL-AGENT | `~/.owl-agent` |
| `OWL_AGENT_CONFIG` | Config directory | `~/.owl-agent/config` |
| `OWL_AGENT_CACHE` | Cache directory | `~/.owl-agent/cache` |
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

### CLI Mode

```bash
# Run built-in test (makes real HTTP request to httpbin.org)
python proxy_defense.py

# Run CI/CD pre-merge check
bash .github/scripts/ci-check.sh

# Run tests
python -m pytest tests/ -v
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
# Unit tests
python -m pytest tests/ -v

# Integration test (real HTTP request)
python proxy_defense.py

# CI/CD check
bash .github/scripts/ci-check.sh
```

### Test Coverage

| Component | Tests |
|-----------|-------|
| `CachedResponse` | TTL freshness, expiry |
| `TokenBucket` | Token acquisition, replenishment |
| `ProxyEntry` | Failure counting, ban logic, success reset |
| `HTTPCache` | Set/get, cache miss, protocol-aware keys |
| `ProxyRotator` | Empty pool, rotation order |

---

## Project Structure

```
owl-agent-proxy/
├── proxy_defense.py              # Main defense stack (v3.0) — 425 lines
├── requirements.txt              # Pinned core dependencies
├── .gitignore                    # Git ignore rules
├── README.md                     # This file
├── worklog.md                    # Session worklog template
├── .github/
│   ├── scripts/
│   │   └── ci-check.sh           # CI/CD pre-merge check (70 lines)
│   └── workflows/
│       └── protocol-check.yml    # GitHub Actions workflow
├── config/
│   ├── AGENTS.md                 # Agent system prompt
│   ├── opencode.json             # OpenCode plugin configuration
│   └── proxy_pool.template.json  # Proxy pool template (copy to use)
├── docs/
│   ├── PROTOCOL_ESCALATION_GUIDE.md  # When and how to escalate protocols
│   └── LAYERED_FALLBACK.md           # Fallback architecture and resilience
├── examples/
│   └── usage.py                  # Usage examples for all protocols
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
    └── test_proxy_defense.py     # Unit tests
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
