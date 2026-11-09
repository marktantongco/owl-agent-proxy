# 🦉 OWL-AGENT Proxy Defense Stack v7.1

> **Multi-protocol HTTP defense system** with intelligent caching, request deduplication, domain rate limiting, tier-based proxy rotation, **upstream harvesting**, **honeypot/injection detection**, **sticky per-agent sessions**, an **MCP server** for AI agents, and optional **external proxy** integration (BounceBack, https_proxy). Start with `http/1.1`, escalate only when justified.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/marktantongco/owl-agent-proxy/actions/workflows/protocol-check.yml/badge.svg)](https://github.com/marktantongco/owl-agent-proxy/actions/workflows/protocol-check.yml)
[![Tests](https://img.shields.io/badge/tests-580%20passing-brightgreen.svg)](#testing)

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
  - [External Proxies (BounceBack / https_proxy)](#external-proxies-bounceback--https_proxy)
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
                                                                 | stealth
```

### Component Flow

1. **HTTPCache** — SHA-256 keyed in-memory cache with TTL. Protocol-aware.
2. **RequestDeduplicator** — Coalesces in-flight identical requests into one network call.
3. **DomainRateLimiter** — Per-domain token bucket. Configurable rate/capacity.
4. **ProxyRotator** — Tier-sorted pool. Health tracking. Auto-ban on 3 failures. External proxies (BounceBack/https_proxy) load at tier 1 (highest priority).
5. **FilterPipeline** — WAF filter rules (ip/geo/regexp/time/reverse_lookup/malleable) evaluated before proxy selection; rejects early. Ported from BounceBack.
6. **Middleware chain** — Composable request/response wrappers: nginx camouflage (`Server: nginx/1.24.0`, fake 404s, basic auth WWW-Authenticate) ported from https_proxy; generic middleware pattern ported from go-stealth.
7. **ProtocolRouter** — Routes to the correct handler based on `protocol` parameter.
8. **ResilientClient** — Context manager orchestrating all components with retry logic, LLM routing, and upstream harvesting.
9. **MCP server** — stdlib-only stdio JSON-RPC exposing the pool as 4 agent tools.

---

## Features

| Feature | Description |
|---------|-------------|
| **5 Protocols** | HTTP/1.1, HTTP/2, JA3 (TLS fingerprint), WebSocket, Browser (Playwright) + Stealth (invisible-playwright, last resort) |
| **Smart Caching** | SHA-256 keyed, TTL-based, protocol-aware, in-memory |
| **Deduplication** | In-flight request coalescing — no duplicate network calls |
| **Rate Limiting** | Per-domain token bucket algorithm |
| **Token-Bucket Persistence** | Rate-limit state (`tokens`, `last_update`) serialized to `token_buckets.json`, survives process restart |
| **Config Schema Validation** | 21-key `CONFIG_SCHEMA` with type/min constraints; invalid values logged as warnings (not fatal), unknown keys forward-compatible |
| **Proxy Rotation** | Tier-based pool with health tracking, auto-ban, latency sorting |
| **External Proxies** | BounceBack (Go stealth redirector, port 8080) and https_proxy (Rust stealth HTTPS forward proxy, port 3128) via `external_proxies` config |
| **WAF Filter Pipeline** | BounceBack-inspired rules (ip/geo/regexp/time/and/or/not) evaluated before proxy selection |
| **Nginx Camouflage Middleware** | https_proxy-inspired: `Server: nginx/1.24.0` header, fake 404 for sensitive paths, basic auth `WWW-Authenticate` on 401 |
| **Middleware Chain** | go-stealth-inspired composable request/response wrappers |
| **Protocol Escalation** | Start `http/1.1`, escalate only when CI/CD-justified |
| **LLM Routing** | OpenAI-compatible paths routed through local model upstreams (colibri, FreeRide) with 502 failover |
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
| External proxies | None | BounceBack + https_proxy config, tier 1 priority |
| Filter pipeline | None | WAF filter rules (BounceBack pattern) before proxy selection |
| Middleware chain | None | Composable wrappers (go-stealth pattern); nginx camouflage (https_proxy pattern) |
| LLM routing | None | OpenAI-compatible paths → local model upstreams with failover |
| Source quality | — | `SourceHealthTracker` (0.85 decay) ranks sources by real yield and records last error |
| Trust | — | `HoneypotDetector` rejects proxies that redirect, inject scripts or alter bodies |
| Session model | Per-request rotation | Sticky `(agent_id, domain)` binding, plus `random` / `round_robin` modes |
| Agent access | CLI only | MCP server with 4 tools — see [docs/MCP_INTEGRATION.md](docs/MCP_INTEGRATION.md) |
| Install | Manual pip + copy | `./install-owl.sh` — idempotent, backed up, 20-check verification |
| Tests | 9 | 580 passing, 0 failed |
| Coverage | ~50% | 82% (proxy_defense 83%, mcp_proxy_server 86%, proxy_harvester 78%) |
| CI | Protocol + credential check | + pytest on 3.10/3.11/3.12 + installer smoke test |
| Rate-limit persistence | in-memory only | `token_buckets.json` — state survives restart via `TokenBucket.to_dict()`/`from_dict()`, debounced save every 10 acquires, final persist on `close()` |
| Config validation | `dict.get()` with defaults | `CONFIG_SCHEMA` (21 keys) + `validate_config()` — invalid values logged as warnings, unknown keys forward-compatible |
| Verification suite | V1–V20 checks | `run.sh` CLI wrapper (stats/fetch/harvest/mcp-selftest/verify), `config/config.json` defaults, tool-name prefixes accept `web_`/`github_`/`arxiv_` |

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
| `invisible-playwright` | Stealth Firefox (C++-patched, ~260 MB download) | 6 | No |

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

### External proxy setup (BounceBack / https_proxy)

OWL can route traffic through external stealth proxies at tier 1 (highest
priority). Edit `config/external_proxies.template.json` and point OWL at them:

```json
{
  "external_proxies": [
    "http://127.0.0.1:8080",
    "http://127.0.0.1:3128"
  ]
}
```

| Proxy | Port | Description | Setup |
|-------|------|-------------|-------|
| **BounceBack** | 8080 | Go stealth redirector with WAF filter pipeline | Download linux-amd64 zip from GitHub releases, run `./BounceBack -c config.yml` |
| **https_proxy** | 3128 | Rust stealth HTTPS forward proxy, Let's Encrypt TLS, nginx camouflage | Download linux-amd64 zip from GitHub releases, run `./https_proxy -c config.toml` |

> Binaries are not bundled in this repo — they must be downloaded from the
> respective GitHub releases (SSL may block access in some environments; see
> Limitations below).

### Arch Linux / omArchy

omArchy is Arch Linux + Hyprland, so it uses the same path as any Arch install.
The naive `install-owl.sh` works, but Arch needs two things Ubuntu does not:

- **venv is mandatory, not optional.** Arch marks system Python as
  `EXTERNALLY-MANAGED` (PEP 668), so `pip install` outside a venv is refused.
- **The remediation hint must be right.** There is no `python3-venv` or
  `python3-dev` package on Arch — venv and headers ship inside `python`.

`install-owl.sh` now detects the distro from `/etc/os-release` and prints
`Platform: Arch Linux (id=arch, pkg=pacman)` plus Arch-correct commands. For a
full install including system packages:

```bash
./scripts/install-arch.sh              # sudo: pacman -Syu + packages + install + verify
./scripts/install-arch.sh --minimal    # core http/1.1 only
./scripts/install-arch.sh --user       # skip pacman (no root)
./scripts/install-arch.sh --verify     # verify an existing install
```

Every package name is checked against the pacman database first and **skipped
with a warning** if it no longer exists — `pacman -S` aborts the whole
transaction on one unknown name, and names drift on a rolling release.

> **omArchy + mise:** omArchy manages runtimes with mise. A mise shim on `PATH`
> ties the venv to one interpreter version, and switching versions afterwards
> leaves a silently broken venv. The installer warns when it detects this; pin a
> system interpreter with `PYTHON=/usr/bin/python ./install-owl.sh`.

Verified on every PR in a real `archlinux:latest` container (the `arch` CI job),
not just claimed in a doc.

### Arch package (PKGBUILD)

`packaging/PKGBUILD` builds a real pacman package, so pacman owns install,
upgrade and removal, and the dependency list is declared instead of drifting
with a shell script on a rolling release.

```bash
bash packaging/make-source.sh      # tarball from an exact commit
cd packaging && makepkg -si        # builds and installs
```

It installs `owl-proxy` and `owl-proxy-mcp` on `PATH`, the three modules into
site-packages, docs under `/usr/share/doc/owl-agent-proxy`, and the pool
template under `/usr/share/owl-agent-proxy`.

The package is built and its payload asserted in CI on every PR
(the `pkgbuild` job, inside `archlinux:latest`). Notes:

- **Build outside a virtualenv.** `python -m installer` resolves paths through
  the interpreter it runs under, so a venv-active shell produces a package that
  installs under the venv prefix. The PKGBUILD refuses to build in that case.
- `make-source.sh` archives a **committed** tree — commit before packaging.
- The optional protocol layers (`http2`, `ja3`, `websocket`, `browser`) are
  `optdepends`, not hard dependencies: http/1.1 must keep working without them.

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

### External Proxies (BounceBack / https_proxy)

Copy and edit `config/external_proxies.template.json`:

```json
{
  "external_proxies": [
    "http://127.0.0.1:8080",
    "http://127.0.0.1:3128"
  ]
}
```

OWL attempts external proxies **before** harvested free proxies (tier 1). When an
external proxy is unhealthy or banned, OWL falls through to tier 2+ harvested
entries automatically.

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
| `token_bucket_persist_file` | `~/.owl-agent/config/token_buckets.json` | file for persisting token-bucket rate-limit state across restarts |

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
| `external_proxies` | `List[str]` | None | external proxy URLs (BounceBack/https_proxy) at tier 1 |
| `filter_pipeline` | `FilterPipeline` | None | WAF filter rules evaluated before proxy selection |
| `middleware` | `List[Middleware]` | None | composable middleware wrappers |
| `token_bucket_persist_file` | `str` | `~/.owl-agent/config/token_buckets.json` | path to persist token-bucket rate-limit state |

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

#### With External Proxies and WAF Filter

```python
from proxy_defense import ResilientClient, FilterPipeline, FilterRule, FilterAction, nginx_camouflage_middleware, chain

# WAF: reject requests from blocked IP ranges
pipeline = FilterPipeline([
    FilterRule(name="ban-russia", rule_type="ip",
               params={"list": "blocked_ips.txt"}, action=FilterAction.REJECT),
])

client = ResilientClient(
    external_proxies=["http://127.0.0.1:8080"],
    filter_pipeline=pipeline,
    middleware=[nginx_camouflage_middleware(server_name="nginx/1.24.0")],
)

async with client:
    resp = await client.request("GET", "https://example.com")
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

#### Sticky Sessions

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

#### LLM Routing

OpenAI-compatible paths (`/v1/chat/completions`, `/v1/completions`, `/v1/models`,
`/v1/embeddings`) are routed through local model upstreams instead of the proxy
pool:

```python
async with ResilientClient() as client:
    resp = await client.request(
        "POST", "http://proxy/v1/chat/completions",
        headers={"Authorization": "Bearer sk-..."},
        agent_id="agent-1",
    )
    # routed to colibri (primary) or FreeRide (failover on 502)
```

LLM upstreams are configured in `config.json` under `local_model_upstreams`.

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

---

## CI/CD Pre-Merge Check

The CI/CD script enforces two rules before code can be merged:

### Check 1: Protocol Escalation Justification

Scans for `protocol="ja3"`, `protocol="browser"`, `protocol="stealth"`,
`protocol="http/2"`, `protocol="websocket"` and requires ≥3/4 justification
markers:

| Marker | Keyword |
|--------|---------|
| Baseline | `http/1.1`, `http1`, `baseline` |
| Anti-bot | `cloudflare`, `datadome`, `akamai`, `anti.bot` |
| Performance | `latency`, `ms`, `benchmark`, `tested` |
| Approval | `approved`, `APPROVED` |

### Check 2: Proxy Credential Security

Detects hardcoded credentials (`://user:pass@`) in source files. Excludes
`proxy_pool.json` and test files.

### Run Locally

```bash
bash .github/scripts/ci-check.sh
```

### GitHub Actions

[`.github/workflows/protocol-check.yml`](.github/workflows/protocol-check.yml)
runs on every pull request to `main`/`develop`, on pushes to `main`, and on
demand. Six jobs:

| Job | What it proves |
|-----|----------------|
| `protocol-check` | Every protocol escalation is justified (`# APPROVED:` + evidence) and no proxy credentials are committed |
| `skills` | Every `SKILL.md` is well-formed and discoverable by the `skills` CLI |
| `tests` | `pytest` on Python 3.10, 3.11 and 3.12, plus the MCP protocol selftest |
| `installer` | A fresh install into a throwaway `OWL_HOME`, an idempotent re-run, then `--verify-only --no-live` |
| `arch` | `scripts/install-arch.sh` end-to-end inside `archlinux:latest` — pacman packages, install, idempotent re-run, then verification |
| `pkgbuild` | Builds `packaging/PKGBUILD` with `makepkg` in `archlinux:latest` and asserts the packaged payload |

Run the same checks by hand:

```bash
bash .github/scripts/ci-check.sh                    # escalation + credential guard
python -m pytest -q                                 # 580 tests
python mcp_proxy_server.py --selftest               # MCP protocol
./install-owl.sh --no-live                          # installer + verification
```

> **CodeQL:** this repo uses GitHub's default code-scanning setup. Do not add an
> advanced-configuration `codeql.yml` alongside it — GitHub cannot process that
> SARIF (`CodeQL analyses from advanced configurations cannot be processed when
> the default setup is enabled`), which is what failed `Analyze (actions)` on an
> earlier PR.

---

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # 580 tests, offline + hermetic
python mcp_proxy_server.py --selftest     # MCP protocol
python proxy_defense.py                   # live demo (needs egress)
bash .github/scripts/ci-check.sh          # escalation + credential guard
~/.owl-agent/run.sh verify --no-live      # install verification (V1–V20)
```

### Test Coverage

| File | Tests | Covers |
|------|-------|--------|
| `tests/test_proxy_defense.py` | ~300 | cache, dedupe, rate limit, proxy rotation, LLM routing, filter pipeline, middleware chain, nginx camouflage, protocol handlers, context manager, CLI |
| `tests/test_proxy_harvester.py` | 62 | ProxyScrape + monosans schemas, IP filtering, source health, text/JSON envelopes, affinity TTL/eviction, honeypot hashing, probe rejection |
| `tests/test_v71_integration.py` | 40 | sticky selection, rotation modes, quarantine, honeypot rejection, trimming, persistence, config merge, dedupe failures |
| `tests/test_mcp_server.py` | ~40 | frames (newline + Content-Length), initialize/notifications/batch, all four tools, stdout purity, real stdio subprocess |

Everything above runs offline and hermetically: `tests/conftest.py` blocks
outbound sockets (loopback excepted), so a test can never pass merely because
the runner happened to have — or lack — connectivity. A test that needs the
internet must opt in with `@pytest.mark.allow_network`. Live-egress behaviour is
covered by the installer's V19/V20 checks, which SKIP without network.

### Current Results

| Metric | Value |
|--------|-------|
| Tests passed | 580 |
| Tests failed | 0 |
| Coverage | 82% |
| proxy_defense.py | 83% |
| mcp_proxy_server.py | 86% |
| proxy_harvester.py | 78% |

---

## Project Structure

```
owl-agent-proxy/
├── proxy_defense.py              # L2 egress core: cache, dedupe, rate limit, pool, protocols, filter, middleware, LLM routing
├── proxy_harvester.py            # L1 supply: harvest, honeypot detector, session affinity, validate_proxy
├── reverse_proxy.py              # L3 ingress (optional): HTTP ingress + escalation ladder + circuit breaker
├── mcp_proxy_server.py           # L4 agent surface: stdio JSON-RPC, 4 tools + memory/pool backends
├── gateway/                      # L3 token plane (FastAPI, :20128): never ships with the library
│   ├── app.py                    #   routes, provider calls, request lifecycle
│   ├── auth.py                   #   bearer gateway token (clients never hold provider keys)
│   ├── router.py                 #   free catalog → paid → local fallback chain
│   ├── billing.py                #   token/cost budgets per client
│   ├── cache.py                  #   Redis-backed response cache (degrades off without redis)
│   ├── circuit_breaker.py        #   per-provider breaker
│   ├── audit.py                  #   redacted audit log
│   └── free_catalog/             #   vendored tier-1 provider catalog (providers.json, offline)
├── config/
│   ├── config.json               # Runtime defaults (every key optional)
│   ├── opencode.json             # OpenCode plugin config
│   ├── AGENTS.md                 # Agent system prompt
│   ├── proxy_pool.template.json  # Proxy pool template (copy to use)
│   └── external_proxies.template.json
├── docs/
│   ├── architecture/
│   │   ├── MODULE_GRAPH.md       # GENERATED from the tree — layers, AST import graph, cycles
│   │   └── RESTRUCTURE_PLAN.md   # Audit → optimize plan this layout came from
│   ├── MCP_INTEGRATION.md        # Per-host MCP wiring + tool reference
│   ├── V7_UPSTREAM.md            # Harvesting, honeypot, sticky sessions, runbook
│   ├── PROTOCOL_ESCALATION_GUIDE.md
│   ├── STEALTH_BROWSER.md        # Stealth rung (optional extra, Python 3.11+)
│   ├── LAYERED_FALLBACK.md
│   ├── skills-framework/         # 10 end-to-end pipelines + quick reference
│   └── agents/                   # Domain notes, issue tracker, grill-engineering
├── skills/                       # 30 discoverable skills, each skills/<name>/SKILL.md
│   ├── owl-proxy/                #   install + operate the stack
│   ├── owl-proxy-mcp/            #   wire the MCP server into an agent host
│   ├── research/ brainstorm/ compare-a-b/ decision-tree/ simulator/
│   ├── code-generation/ audit-optimizer/ explain-analyzer/
│   └── free-search-aggregator/ github-research/ parallel-findall/ ...  (vendored, symlinked into .agents/ and .claude/)
├── .agents/skills/               # Canonical location the skill CLIs read
├── .claude/skills/               # Symlinks → ../../.agents/skills/<name>
├── scripts/
│   ├── gen-architecture.py       # Writes/verifies MODULE_GRAPH.md (CI gate: --check)
│   ├── verify-install.py         # V1–V20 install verification
│   ├── install-ubuntu.sh         # Ubuntu system install (apt + phases)
│   ├── install-arch.sh           # Arch / omArchy system install
│   └── smoke-stealth.py          # Live stealth-rung check (needs real networking)
├── tests/                        # 580 tests, all offline + hermetic
│   ├── conftest.py               #   blocks outbound sockets (loopback excepted)
│   ├── test_proxy_defense.py     #   182
│   ├── test_mcp_server.py        #   118
│   ├── test_proxy_harvester.py   #   70
│   ├── test_memory_backend.py    #   46
│   ├── test_reverse_proxy.py     #   41
│   ├── test_v71_integration.py   #   40
│   ├── test_free_catalog.py      #   24
│   ├── test_stealth.py           #   23
│   ├── test_gateway.py           #   22
│   ├── test_pool_backend.py      #   8
│   └── test_architecture_check.py#   6   (proves the drift detector detects)
├── examples/usage.py             # Usage examples for all protocols
├── packaging/                    # PKGBUILD + make-source.sh
├── tools/grill-engineering/      # Review lens used by the pipelines
├── .github/
│   ├── scripts/
│   │   ├── ci-check.sh           #   escalation + credential guard
│   │   ├── check-skills.py       #   SKILL.md contract (fails CI on regression)
│   │   └── check-swallows.py     #   no silent broad excepts
│   └── workflows/protocol-check.yml   # guards + architecture + pytest (3.10–3.12) + installer
├── install-owl.sh                # v7.1 installer (idempotent, backs up, verifies)
├── run.sh                        # CLI wrapper: stats, fetch, harvest, mcp-selftest, verify
├── requirements.txt              # Core deps only (httpx[socks], aiohttp, aiofiles)
├── requirements-dev.txt          # + pytest, fastapi (gateway tests)
├── pyproject.toml                # Build metadata + console scripts
├── pytest.ini                    # Async mode, testpaths, coverage on shipped modules
├── docker-compose.yml            # gateway + Redis + Ollama
├── nginx.conf / Caddyfile        # Edge TLS + rate limiting
└── LICENSE                       # MIT
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
protocol="stealth"  # last resort — see docs/STEALTH_BROWSER.md
```

---

## Skills System

Skills are packaged in the [Agent Skills](https://skills.sh) layout, so the `skills`
CLI can discover them and install them into any supported agent host.

A valid skill is `skills/<name>/SKILL.md` with YAML frontmatter declaring at least
`name` (lowercase kebab-case, matching the directory) and `description`. The CLI
**silently ignores** flat markdown files with no frontmatter — which is why the
legacy files below are listed apart.

| Skill | Purpose |
|-------|---------|
| `owl-proxy` | Install and operate the stack: launcher commands, Python API, adding a `ProxySource`, honest limits |
| `owl-proxy-mcp` | Wire the stdio MCP server into an agent host: tool table, the pick→fetch→rotate loop, failure modes |

```bash
skills add marktantongco/owl-agent-proxy --skill owl-proxy      # install into this project
skills add . --skill '*' -l                                     # list local skills without installing
python .github/scripts/check-skills.py                          # validate packaging (what CI runs)
```

The `skills` CI job fails the build on a malformed or undiscoverable skill, so
packaging cannot regress as skills are added.

### Reasoning skills (migrated from flat prompt files)

These eight used to be flat `skills/system/*.md` files with no frontmatter,
which `skills add` silently ignored — the directory advertised skills that no
agent could discover. They are now `skills/<name>/SKILL.md` and are counted by
`check-skills.py` (30 skills valid, 0 flat files pending). None of them are
vendored from a third party, so unlike the research skills below they are real
files in `skills/` rather than symlinks into `.agents/skills/`.

| Skill | Stage | Purpose | Trigger |
|-------|-------|---------|---------|
| `code-generation` | BUILD | Production-grade code with tests, no placeholders | Building features, refactoring |
| `audit-optimizer` | VERIFY | Baseline → one change → re-measure | Performance issues |
| `brainstorm` | PLAN | Divergent thinking, constraint relaxation | Stuck on single-path solution |
| `compare-a-b` | PLAN | Weighted A/B comparison with the arithmetic shown | Choosing between options |
| `decision-tree` | PLAN | Branching logic maps, every leaf has an action | Routing decisions |
| `explain-analyzer` | VERIFY | SQL EXPLAIN ANALYZE interpretation | Slow database queries |
| `research` | DEFINE | Deep-dive with two-source validation | Before build decisions |
| `simulator` | PLAN | Interaction tracing incl. error + recovery paths | Building UI, APIs, workflows |

### Architecture map (generated, not written)

`docs/architecture/MODULE_GRAPH.md` is produced by `scripts/gen-architecture.py`
from the **AST import graph**, not from prose. It lists the four layers, every
first-party edge with a rationale, any upward edge or import cycle, and each
module's size. CI runs it with `--check`, so the documented layers cannot drift
from the tree again.

```bash
python scripts/gen-architecture.py            # regenerate
python scripts/gen-architecture.py --check    # what CI runs (fails when stale)
```

`AGENTS.md`'s skills inventory, free-catalog table and test counts are generated
the same way, from `skills/*/SKILL.md`, `gateway/free_catalog/providers.json` and
`pytest --collect-only`:

```bash
python scripts/gen-docs.py            # regenerate
python scripts/gen-docs.py --check    # what CI runs (fails when stale)
```

The post-merge review of the restructure, including the two findings left
deliberately unfixed, is in [`docs/architecture/REVIEW_PR39.md`](docs/architecture/REVIEW_PR39.md).

---

## Limitations

Stated plainly, because these matter more than the feature list:

- **Free proxies only.** The default pool is harvested free lists — no paid
  residential network. Throughput and lifetime are unpredictable; the scoring
  adapts, but there is no SLA. For stable geo-targeted residential IPs, plug a
  paid provider in as a `ProxySource`.
- **External proxy binaries not bundled.** BounceBack and https_proxy binaries
  must be downloaded from GitHub releases (SSL may block access in some
  environments). No Go/Rust/Deno toolchain is installed by default, so they
  cannot be built from source in restricted environments.
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