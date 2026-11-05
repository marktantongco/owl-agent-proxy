# OWL Agent Proxy — Agent Configuration & Comprehensive Readme

This file is the **single source of truth** for agents working on the OWL Agent Proxy project. It captures every architectural layer, every process step, every installed skill, every URL, every test result, and every installation step required for an AI to fully understand and reproduce the work accomplished.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture Layers (Schematic Diagram)](#architecture-layers-schematic-diagram)
3. [Step-by-Step Process & Layers](#step-by-step-process--layers)
4. [Step-by-Step Installation Guide (for AI Agents)](#step-by-step-installation-guide-for-ai-agents)
5. [Entry Points & CLI](#entry-points--cli)
6. [Reverse Proxy v2 — HTTP Ingress](#reverse-proxy-v2--http-ingress)
7. [Configuration (config.json)](#configuration-configjson)
8. [Test Results & Verification](#test-results--verification)
9. [Skills Inventory (All Installed Skills)](#skills-inventory-all-installed-skills)
10. [Conceptual Skills (14 Stubs in `skills/`)](#conceptual-skills-14-stubs-in-skills)
11. [10 End-to-End Use-Case Pipelines](#10-end-to-end-use-case-pipelines)
12. [Research Investigation Stack](#research-investigation-stack)
13. [Documentation Locations](#documentation-locations)
14. [All URLs Referenced During Development](#all-urls-referenced-during-development)
15. [Conventions](#conventions)

---

## Project Overview

| Field | Value |
|-------|-------|
| **Name** | owl-agent-proxy |
| **Description** | Client-side HTTP defense library + stdio MCP server + CLI with optional reverse proxy ingress. Provides proxy pooling, caching, deduplication, domain rate limiting, tier-based proxy rotation, upstream harvesting, honeypot detection, sticky sessions, and MCP server for AI agents. Core is NOT a reverse proxy — `reverse_proxy.py` adds optional HTTP ingress on a configurable port, forwarding through ResilientClient egress to upstream targets. |
| **Entry point** | `proxy_defense.py` (client library) + `mcp_proxy_server.py` (stdio MCP server) + `run.sh` (CLI) + `reverse_proxy.py` (optional HTTP ingress) |
| **Test command** | `python -m pytest tests/ -q` |
| **Verify command** | `python scripts/verify-install.py --owl-home <path> --no-live` |
| **CLI** | `./run.sh stats \| fetch \| harvest \| mcp-selftest \| serve \| verify` |
| **Version** | v7.1 (core) / v2.1 (reverse proxy with stealth mode) |

**Architecture alignment:**
- Core: client-side library + stdio MCP server + CLI (NOT a reverse proxy by itself)
- `reverse_proxy.py`: optional HTTP ingress layer that wraps ResilientClient egress as a reverse proxy
- Protocol escalation: http/1.1 → http/2 → ja3 → websocket → browser → stealth
- Circuit breaker: per-protocol failure tracking with cooldown
- Load balancing: multiple upstream targets with health-aware round-robin
- STEALTH MODE (v2.1): curl_cffi browser TLS/JA3/JA4 fingerprint impersonation, user-agent rotation,
  stealth headers (Sec-CH-UA, Sec-Fetch-*), cookie persistence, timing jitter
- Trust the tests, not docs prose (version drift: About v3.0 vs README v7.1)

---

## Architecture Layers (Schematic Diagram)

```mermaid
flowchart TD
    %% Client Layer
    C[Client / AI Agent] -->|HTTP Request| RP[reverse_proxy.py :PORT]
    
    %% Reverse Proxy Ingress Layer
    subgraph RP_Ingress [Reverse Proxy Ingress — reverse_proxy.py v2.1]
        RP[HTTP Listener 0.0.0.0:PORT]
        CB[Circuit Breaker — per protocol, threshold 5]
        LB[Load Balancer — weighted round-robin + health-aware]
        PE[Protocol Escalation — http/1.1 → http/2 → ja3 → websocket → browser → stealth]
        HC[Health Check — every 30s on upstream targets]
        SC[Stealth Client — curl_cffi browser impersonation]
        UA[User-Agent Rotator — sticky/random/cycle]
        SH[Stealth Headers — Sec-CH-UA, Sec-Fetch-*]
        CJ[Cookie Jar — persistence by domain]
        TJ[Timing Jitter — random delay between requests]
    end
    
    %% Egress Layer
    subgraph RC_Egress [ResilientClient Egress — proxy_defense.py v7.1]
        PD[proxy_defense.py]
        PR[ProxyRotator — tier-sorted pool + sticky affinity]
        HCache[HTTP Cache — TTL + max entries]
        DD[Request Deduplicator]
        RL[Domain Rate Limiter]
        HD[Honeypot Detector]
        VH[Validation Queue — TCP + HTTP probe]
    end
    
    %% Upstream Harvesting Layer
    subgraph UH_Layer [Upstream Harvesting — proxy_harvester.py]
        UH[UpstreamHarvester — httpx AsyncClient]
        SA[SessionAffinityManager — sticky (agent_id, domain)]
        HD2[Honeypot Detector — structural hash body-integrity]
        VP[validate_proxy — TCP + HTTP probe]
        PS[SourceHealthTracker — 0.85 decay yield learning]
    end
    
    %% Persistence Layer
    subgraph PERS [On-Disk Persistence — ~/.owl-agent/]
        PCJ[proxy_cache.json — ProxyRotator state]
        HSJ[harvester_state.json — UpstreamHarvester state]
        TBJ[token_buckets.json — TokenBucket state]
    end
    
    %% MCP Layer
    subgraph MCP [MCP Server — mcp_proxy_server.py]
        MS[stdio MCP server for AI agents]
    end
    
    %% Upstream Targets
    subgraph UPSTREAM [Upstream Targets]
        T1[http://localhost:3000]
        T2[http://localhost:3001]
        T3[Custom targets via --targets]
    end
    
    %% Data Flow
    RP --> CB
    RP --> LB
    RP --> PE
    RP --> HC
    RP --> SC
    RP --> UA
    RP --> SH
    RP --> CJ
    RP --> TJ
    CB --> RC_Egress
    LB --> RC_Egress
    PE --> RC_Egress
    HC --> RC_Egress
    SC --> RC_Egress
    
    PD --> PR
    PD --> HCache
    PD --> DD
    PD --> RL
    PD --> HD
    PD --> VH
    
    PR --> UH
    PR --> SA
    PR --> HD2
    PR --> VP
    PR --> PS
    
    UH --> PCJ
    UH --> HSJ
    PD --> PCJ
    PD --> TBJ
    
    PD --> MS
    
    RC_Egress --> T1
    RC_Egress --> T2
    RC_Egress --> T3
    
    %% Styling
    classDef ingress fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef stealth fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef egress fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef harvest fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    classDef persist fill:#fff8e1,stroke:#ff6f00,stroke-width:2px
    classDef mcp fill:#fce4ec,stroke:#880e4f,stroke-width:2px
    classDef upstream fill:#ffebee,stroke:#b71c1c,stroke-width:2px
    
    class RP,CB,LB,PE,HC ingress
    class SC,UA,SH,CJ,TJ stealth
    class PD,PR,HCache,DD,RL,HD,VH egress
    class UH,SA,HD2,VP,PS harvest
    class PCJ,HSJ,TBJ persist
    class MS mcp
    class T1,T2,T3 upstream
```

### Layer Descriptions

| Layer | Component | Responsibility |
|-------|-----------|---------------|
| **Ingress** | `reverse_proxy.py` | HTTP listener on `0.0.0.0:PORT`, circuit breaker, load balancing, protocol escalation, health checks, stealth mode |
| **Stealth** | `StealthClient` / `UserAgentRotator` | curl_cffi browser TLS/JA3/JA4 impersonation, UA rotation, stealth headers, cookie jar, timing jitter |
| **Egress** | `proxy_defense.py` | ResilientClient — proxy rotation, caching, dedup, rate limiting, honeypot detection, sticky sessions |
| **Harvesting** | `proxy_harvester.py` | Upstream proxy discovery from 4 list endpoints, honeypot detection, session affinity, validation probe |
| **Persistence** | `~/.owl-agent/` | `proxy_cache.json` (Pool state), `harvester_state.json` (harvest state), `token_buckets.json` (rate limit state) |
| **MCP** | `mcp_proxy_server.py` | stdio MCP server exposing tools/resources to AI agents |
| **Upstream** | Configurable targets | Load-balanced upstream HTTP targets (default `http://localhost:3000`) |

---

## Step-by-Step Process & Layers

The development followed the **DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP** pipeline per `smp5.4pd.md` (Tactical Merge, Mode: 🐜 Systematic).

### Layer 1: DEFINE — Discover & Research

1. **Research skills ecosystem**: Searched skills.sh for available skills — `find-skills` (vercel-labs/skills, 17.9K installs) serves as the meta-skill for discovery.
2. **Identify missing capabilities**: Determined that `meta-skill`, `agent-reach`, `duckduckgo-search`, `exa-web-search-free` were not published as installable skills.
3. **Research upstream proxy harvester**: Confirmed `proxy_harvester.py` is well-built, needs only httpx (0.28.1 available), but on-disk pool persistence lived in `proxy_defense.py` (ProxyRotator), not the harvester.
4. **Confirm "no HTTP server" claim**: `proxy_defense.py` has no `aiohttp.web` — it's a client library (stats|fetch|harvest|validate). Its `ProxyRotator` is a superset (validation queue, honeypot gating, on-disk `proxy_cache.json`, sticky affinity, 3-strike/300s, source health).
5. **Confirm vendoring path**: `_load_harvester()` looks for `proxy_harvester.py` in `~/.owl-agent/` — single-file vendoring is the designed path.
6. **Better answer**: Vendor `proxy_harvester.py`'s pool engine instead of reimplementing adapters.

### Layer 2: PLAN — Plan & Architect

1. **Design reverse proxy v2**: Multiple upstream targets with weighted round-robin + health-aware load balancing, per-protocol circuit breaker, adaptive protocol escalation on 429/403.
2. **Design harvester persistence**: Add `save_state()`/`load_state()` to `UpstreamHarvester` for `_seen`, `_last`, and `SourceHealthTracker` stats.
3. **Design vendoring**: Copy `proxy_harvester.py` to `~/.owl-agent/proxy_harvester.py`.
4. **Update AGENTS.md**: Add conceptual skills table, documentation locations, reverse proxy section.

### Layer 3: BUILD — Execute

1. **Upgrade `reverse_proxy.py` to v2**:
   - `CircuitBreaker` class — per-protocol failure tracking, threshold 5, 60s cooldown
   - `UpstreamTarget` class — health tracking, consecutive failures, error rate
   - `ReverseProxy` class — aiohttp server on configurable port, hop-by-hop header filtering, request stats, `main_async()` with KeyboardInterrupt handling
   - Lazy imports for `aiohttp` (fast cold start)
   - Connection pooling via `ResilientClient`
   - `--targets` flag for comma-separated upstream targets
   - Protocol selection: explicit header → skip open circuits → HTTPS prefers http/2 → first available

2. **Update `run.sh`**: Added `serve [--port N] [--target HOST] [--targets T1,T2]` subcommand with `cmd_serve()` handler.

3. **Update `config.json`**: Full `reverse_proxy` section with `protocol_escalation`, `circuit_breaker_threshold`, `health_check_interval`, `auto_load_proxies`.

4. **Add harvester persistence to `proxy_harvester.py`**:
   - `STATE_FILE = Path.home() / ".owl-agent" / "harvester_state.json"`
   - `save_state()` — atomic write via temp file + replace
   - `load_state()` — restores `_seen`, `_last`, health tracker stats
   - Wired into `__aenter__` (load) and `__aexit__` (save)

5. **Vendor `proxy_harvester.py`**: Copied to `~/.owl-agent/proxy_harvester.py`.

6. **Add 4 conceptual skill stubs**: `meta-skill`, `agent-reach`, `duckduckgo-search`, `exa-web-search-free` in `skills/`.

7. **Expand tests**: `tests/test_reverse_proxy.py` — 30 tests covering CircuitBreaker, UpstreamTarget health, protocol selection, upstream selection, config-driven targets.

### Layer 4: VERIFY — Test & Validate

1. **Installed Python dependencies**: `pytest`, `pytest-asyncio`, `pytest-cov`, `aiohttp`, `aiofiles`, `httpx` via `pip3 install --break-system-packages`.
2. **Ran full test suite**: 507 passed, 0 failed, 82% coverage.
3. **Ran verify-install.py**: 18 PASS, 0 FAIL, 2 SKIP.
4. **End-to-end persistence test**: save → reload → verified `_seen` and health stats restored correctly.
5. **Verified vendored import**: `proxy_harvester.py` imports correctly from `~/.owl-agent/`.

### Layer 5: REVIEW — Challenge & Quality

1. **devils-advocate**: Challenged assumption that harvester needed reimplementation — confirmed vendoring pool engine is the better answer.
2. **impeccable**: Full quality audit — all tests pass, verify script passes, no placeholder text, English only.
3. **AGENTS.md review**: Ensured all skills, URLs, layers, and processes are documented.

### Layer 6: SHIP — Merge & Release

1. **Committed changes** to branch `arena/0edc59d5-owl-agent-proxy`.
2. **Pushed** to `origin arena/0edc59d5-owl-agent-proxy`.
3. **Opened PR #30** on GitHub: "Add on-disk persistence to UpstreamHarvester and vendored pool engine".
4. **Merged PR #30** into `main` via `gh pr merge 30 --merge`.

---

## Step-by-Step Installation Guide (for AI Agents)

Follow these steps exactly to reproduce the complete development environment:

### Step 1: Clone the Repository

```bash
git clone https://github.com/marktantongco/owl-agent-proxy.git
cd owl-agent-proxy
git checkout arena/26f68c45-owl-agent-proxy
```

### Step 2: Install Python Dependencies

```bash
pip3 install --break-system-packages pytest pytest-asyncio pytest-cov aiohttp aiofiles httpx curl_cffi
```

### Step 3: Verify httpx and curl_cffi Installation

```bash
python3 -c "import httpx; print('httpx', httpx.__version__)"
python3 -c "import curl_cffi; print('curl_cffi', curl_cffi.__version__)"
```

Expected: `httpx 0.28.1` and `curl_cffi 0.17.0`

### Step 4: Create the Persistence Directory

```bash
mkdir -p ~/.owl-agent
```

### Step 5: Vendoring — Copy proxy_harvester.py

```bash
cp proxy_harvester.py ~/.owl-agent/proxy_harvester.py
ls -la ~/.owl-agent/
```

Expected output: `proxy_harvester.py` present in `~/.owl-agent/`

### Step 6: Verify Vendored Import

```bash
python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.owl-agent'))
import proxy_harvester
print('Import OK from ~/.owl-agent/')
print('STATE_FILE:', proxy_harvester.STATE_FILE)
print('save_state:', hasattr(proxy_harvester.UpstreamHarvester, 'save_state'))
print('load_state:', hasattr(proxy_harvester.UpstreamHarvester, 'load_state'))
"
```

### Step 7: Run the Test Suite

```bash
python -m pytest tests/ -q
```

Expected: `507 passed in X.XXs`

### Step 8: Run Installation Verification

```bash
python scripts/verify-install.py --owl-home /home/user/owl-agent-proxy --no-live
```

Expected:
```
PASS: 18   FAIL: 0   SKIP: 2
```

### Step 9: Test Harvester Persistence (End-to-End)

```bash
python3 -c "
import asyncio, json
from pathlib import Path
import sys
sys.path.insert(0, '.')
from proxy_harvester import UpstreamHarvester, STATE_FILE

if STATE_FILE.exists():
    STATE_FILE.unlink()

async def main():
    async with UpstreamHarvester() as h:
        h._seen.add('http://1.2.3.4:8080')
        h._seen.add('http://5.6.7.8:3128')
        h._last['test_source'] = [{'url': 'http://1.2.3.4:8080'}]
        h.health.record('test_source', 100, 85, ok=True)
        h.save_state()

    async with UpstreamHarvester() as h2:
        assert len(h2._seen) == 2, 'seen not restored'
        assert h2.health.yield_rate('test_source') == 0.85, 'health not restored'
    print('Persistence test PASSED')

asyncio.run(main())
"
```

### Step 10: Run the Reverse Proxy

```bash
# Default: :8080 -> http://localhost:3000
python reverse_proxy.py

# Custom port
python reverse_proxy.py --port 9090

# Custom single target
python reverse_proxy.py --target https://api.example.com

# Multiple targets with load balancing
python reverse_proxy.py --targets https://a.example.com,https://b.example.com

# Via run.sh
./run.sh serve --port 8080 --targets http://localhost:3000,http://localhost:3001
```

### Step 10a: Run Stealth Mode Reverse Proxy

```bash
# Stealth mode with Chrome 124 TLS fingerprint impersonation
python reverse_proxy.py --stealth-browser chrome124

# Stealth mode via run.sh
./run.sh serve --port 8080 --stealth-browser chrome124

# Stealth mode with Safari 17
python reverse_proxy.py --stealth-browser safari17 --targets https://a.example.com,https://b.example.com
```

Stealth mode uses curl_cffi to impersonate real-browser TLS/JA3/JA4 fingerprints.
Requires outbound network access (sandboxed environments may block TLS).

### Step 11: Run CLI Subcommands

```bash
./run.sh stats
./run.sh fetch https://example.com
./run.sh harvest --seconds 20
./run.sh mcp-selftest
./run.sh serve --port 8080
./run.sh verify --no-live
```

### Step 12: Verify Research Stack Skills

```bash
# parallel-deep-research + parallel-findall
npx skills add parallel-web/parallel-agent-skills --skill parallel-deep-research --skill parallel-findall --agent '*' -y

# github-research
npx skills add lingzhi227/agent-research-skills --skill github-research --agent '*' -y

# free-search-aggregator
npx skills add https://github.com/vulcanusalex/free-search-aggregator --skill free-search-aggregator --agent '*' -y

# freeUnlimited-websearch
npx skills add https://github.com/lngu/openclaw-skill-freeunlimited-websearch --skill freeUnlimited-websearch --agent '*' -y

# you-web
npx skills add https://github.com/youdotcom-oss/agent-skills --skill you-web --agent '*' -y
```

### Step 13: Confirm All 14 Conceptual Skill Stubs

```bash
ls skills/*/SKILL.md
```

Expected 14 stubs: `agent-skills`, `codemap`, `meta-skill`, `agent-reach`, `duckduckgo-search`, `exa-web-search-free`, `ralph-prompt-multi-task`, `orchestrate`, `chain-of-thought`, `headroom`, `Caveman`, `parallel-agent-skills`, `devils-advocate`, `impeccable`.

---

## Entry Points & CLI

| File | Purpose |
|------|---------|
| `proxy_defense.py` | Client-side HTTP defense library (96,560 bytes) — ResilientClient, ProxyRotator, HTTPCache, DomainRateLimiter, RequestDeduplicator, HoneypotDetector, TokenBucket |
| `proxy_harvester.py` | Upstream proxy harvester (38,444 bytes vendored) — UpstreamHarvester, HoneypotDetector, SessionAffinityManager, validate_proxy, SourceHealthTracker |
| `mcp_proxy_server.py` | stdio MCP server for AI agents (41,180 bytes) |
| `run.sh` | CLI wrapper — `stats`, `fetch`, `harvest`, `mcp-selftest`, `serve`, `verify` |
| `reverse_proxy.py` | Optional HTTP ingress v2.1 (20,563 bytes) — ReverseProxy, CircuitBreaker, UpstreamTarget, StealthClient, UserAgentRotator, aiohttp server, curl_cffi (lazy) |
| `config.json` | Configuration — reverse_proxy section + stealth section + core settings |
| `scripts/verify-install.py` | Installation verification |
| `tests/test_reverse_proxy.py` | 41 reverse proxy tests (incl. 19 stealth mode tests) |
| `tests/` | Full test suite |

### CLI Subcommands (`./run.sh`)

```
stats [--json]        Print pool/session/source health
fetch <url> [--json]  Fetch a URL through the proxy pool
harvest [--seconds N] Force one upstream harvest sweep
mcp-selftest          Run MCP server selftest
serve [--port N] [--target HOST] [--targets T1,T2] [--stealth-browser BROWSER]  Run reverse proxy HTTP ingress
verify [--no-live]    Run installation verification suite
```

### Reverse Proxy CLI (`python reverse_proxy.py`)

```
--port N              Listen port (default: 8080, or config.json)
--target HOST         Single upstream target host
--targets T1,T2       Comma-separated upstream targets for load balancing
--stealth-browser BROWSER  Enable stealth mode (chrome, chrome120, chrome124, safari, safari17, edge, edge99, firefox)
```

---

## Reverse Proxy v2 — HTTP Ingress

### Architecture

```
Client -> :PORT (reverse_proxy.py) -> [ResilientClient egress | StealthClient (stealth mode)] -> upstream target
```

### Components

| Component | Purpose |
|-----------|---------|
| `CircuitBreaker` | Per-protocol failure tracking with threshold 5 and 60s cooldown |
| `UpstreamTarget` | Health tracking per target — consecutive failures, error rate, healthy/unhealthy |
| `ReverseProxy` | Main class — aiohttp server, protocol selection, upstream selection, request handling |
| `HOP_BY_HOP_HEADERS` | Filtered headers: connection, keep-alive, proxy-authenticate, proxy-authorization, te, trailers, transfer-encoding, upgrade |
| `StealthClient` | curl_cffi browser TLS/JA3/JA4 fingerprint impersonation (stealth mode) |
| `UserAgentRotator` | Browser user-agent rotation (sticky / random / cycle) |
| `StealthConfig` | Stealth configuration: browser profile, headers, cookies, jitter, proxy |

### Protocol Escalation Chain

```
http/1.1 → http/2 → ja3 → websocket → browser → stealth
```

Selection priority:
1. Explicit `X-OWL-Protocol` header from client
2. Skip circuits that are open (circuit breaker)
3. HTTPS targets → prefer http/2 if available
4. First available protocol in chain

### Circuit Breaker

- Threshold: 5 consecutive failures per protocol
- Cooldown: 60 seconds
- On 429/403 response → escalate to next protocol

### Load Balancing

- Weighted round-robin across healthy upstream targets
- Fallback to all targets if none are healthy
- Health check every 30s on `/health` endpoint

### STEALTH MODE (v2.1)

The `stealth` protocol uses **curl_cffi** (curl-impersonate) to impersonate real-browser
TLS/JA3/JA4/HTTP2 fingerprints, bypassing anti-bot systems (Cloudflare, Akamai, DataDome,
PerimeterX) that fingerprint non-browser TLS stacks.

Stealth mode includes:
- **Browser TLS impersonation** — curl_cffi with presets: chrome, chrome120, chrome124,
  safari, safari17, edge, edge99, firefox
- **User-Agent rotation** — sticky (per-target), random, or cycle rotation
- **Stealth headers** — Sec-CH-UA, Sec-CH-UA-Mobile, Sec-CH-UA-Platform, Sec-Fetch-*,
  Accept-Language, Upgrade-Insecure-Requests
- **Cookie persistence** — domain-based cookie jar for session continuity
- **Timing jitter** — random delay between requests (configurable min/max ms)

Configuration in `config.json`:
```json
"stealth": {
  "enabled": true,
  "browser": "chrome124",
  "user_agent_rotation": "sticky",
  "stealth_headers": true,
  "cookie_persistence": true,
  "timing_jitter_ms": [500, 2500]
}
```

CLI:
```bash
python reverse_proxy.py --stealth-browser chrome124
./run.sh serve --stealth-browser chrome124
```

### Configuration (`config.json` reverse_proxy section)

```json
{
  "reverse_proxy": {
    "port": 8080,
    "target_host": "http://localhost:3000",
    "targets": ["http://localhost:3000"],
    "cache_ttl": 60,
    "cache_max_entries": 10000,
    "rate_limit": 10.0,
    "max_retries": 3,
    "protocol_escalation": ["http/1.1", "http/2", "ja3", "websocket", "browser", "stealth"],
    "circuit_breaker_threshold": 5,
    "health_check_interval": 30,
    "auto_load_proxies": true,
    "stealth": {
      "enabled": false,
      "browser": "chrome124",
      "user_agent_rotation": "sticky",
      "stealth_headers": true,
      "cookie_persistence": true,
      "timing_jitter_ms": [500, 2500]
    }
  }
}
```

### Stats Endpoint

`ReverseProxy.stats()` returns:
- `listen_port`, `target_hosts`, `targets_healthy` (url + healthy + error_rate)
- `requests_total`, `requests_ok`, `requests_error`
- `circuit_breaker` (failure count per protocol)
- `stealth` (when enabled): browser, rotation, headers, cookies, request counts, active sessions

---

## Governed Token Plane (v1.0.0)

**Per Marky's recommendation: do NOT chase "unlimited free tokens" via reverse proxy.**
Instead build a governed token plane: OpenCode v2 → gateway token → Nginx/Caddy edge →
9Router/LiteLLM gateway (`127.0.0.1:20128`) → local models (Ollama/vLLM) + free tiers +
paid fallback + Redis cache + per-user budgets + provider key isolation.

### Architecture

```
Client -> gateway token -> Nginx/Caddy edge (TLS + rate limit)
    -> gateway app.py (auth + route + cache + bill + audit)
    -> local Ollama/vLLM (tier 1, free)
    -> free-tier cloud (tier 2, burst)
    -> paid fallback (tier 3)
```

Clients present only a gateway token. Provider API keys live exclusively in the gateway
environment/secrets manager — never sent to clients, never logged.

### Components

| File | Purpose |
|------|---------|
| `gateway/app.py` | FastAPI gateway — auth, routing, caching, billing, circuit breaker, audit logging |
| `gateway/auth.py` | Bearer token validation — clients authenticate with gateway token, not provider keys |
| `gateway/router.py` | Model routing: local → free cloud → paid fallback, tiered selection |
| `gateway/cache.py` | Redis-backed response cache (exact match, TTL-based) |
| `gateway/billing.py` | Per-client token/cost budgets with kill switch |
| `gateway/circuit_breaker.py` | Per-provider circuit breaker with fallback chain |
| `gateway/audit.py` | Redacted audit logging — no provider keys or secrets in logs |
| `nginx.conf` | Nginx edge proxy: TLS termination, rate limiting, header forwarding |
| `Caddyfile` | Caddy edge proxy (alternative to Nginx) |
| `docker-compose.yml` | Local dev stack: gateway + Redis + Ollama |
| `tests/test_gateway.py` | 23 gateway unit tests |

### Key Design Principles

1. **Provider key isolation** — Provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are read
   from the gateway environment only. Clients never receive them. Audit logs redact all
   sensitive fields.

2. **Local-first routing** — Ollama/vLLM local models are preferred (tier 1, hardware cost
   only). Free-tier cloud is burst capacity. Paid fallback is used only when necessary and
   budget allows.

3. **Budget enforcement** — Per-client token and cost limits with 24-hour windows. Exceeded
   budgets block further requests until reset.

4. **Circuit breaker** — Per-provider failure tracking with configurable threshold and
   cooldown. Failed providers are skipped in favor of the next in the fallback chain.

5. **Redis cache** — Cached responses for repeated prompts, tool schemas, and system
   prompts. Disabled gracefully when Redis is unavailable.

### Configuration (`config.json` governed_token_plane section)

```json
{
  "governed_token_plane": {
    "enabled": true,
    "gateway": {
      "host": "127.0.0.1",
      "port": 20128,
      "token_env": "OWL_GATEWAY_TOKEN",
      "default_token_limit": 100000,
      "default_cost_limit_usd": 10.0,
      "window_seconds": 86400,
      "kill_switch": false,
      "cache_enabled": true,
      "cache_ttl": 3600
    },
    "routing": {
      "strategy": "local_first",
      "tiers": [
        { "tier": 1, "name": "local", "provider": "ollama", "model": "qwen2.5:14b", "cost_per_1k_tokens": 0.0 },
        { "tier": 2, "name": "free_cloud", "provider": "openai", "model": "gpt-4o-mini", "cost_per_1k_tokens": 0.15 },
        { "tier": 3, "name": "paid_fallback", "provider": "anthropic", "model": "claude-3-5-haiku-20241022", "cost_per_1k_tokens": 0.80 }
      ]
    },
    "circuit_breaker": { "threshold": 5, "cooldown_seconds": 60 },
    "edge": {
      "nginx": { "listen": 443, "rate_limit": "10r/s", "burst": 20 },
      "caddy": { "admin_port": 20190 }
    },
    "key_isolation": {
      "provider_keys_in_gateway_env_only": true,
      "clients_receive_gateway_tokens_only": true,
      "no_provider_keys_leaked_to_clients": true
    }
  }
}
```

### Running the Gateway

```bash
# Generate a gateway token (one-time for local dev)
export OWL_GATEWAY_TOKEN=$(python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")

# Run gateway locally (binds to 127.0.0.1:20128 only)
python gateway/app.py

# Or with Docker Compose (gateway + Redis + Ollama)
docker-compose up -d

# Test with curl (gateway token required)
curl -X POST http://127.0.0.1:20128/v1/chat/completions \
  -H "Authorization: Bearer $OWL_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello"}]}'
```

---

## Configuration (config.json)

```json
{
  "reverse_proxy": {
    "port": 8080,
    "target_host": "http://localhost:3000",
    "targets": ["http://localhost:3000"],
    "cache_ttl": 60,
    "cache_max_entries": 10000,
    "rate_limit": 10.0,
    "max_retries": 3,
    "protocol_escalation": ["http/1.1", "http/2", "ja3", "websocket", "browser", "stealth"],
    "circuit_breaker_threshold": 5,
    "health_check_interval": 30,
    "auto_load_proxies": true
  }
}
```

Config precedence: explicit argument → `config.json` → built-in default.

---

## Test Results & Verification

| Check | Result |
|-------|--------|
| Test suite (`pytest tests/ -q`) | **548 passed, 0 failed, 82% coverage** |
| Gateway tests (`tests/test_gateway.py`) | **23 passed** (auth, circuit breaker, cache, billing, router, integration) |
| verify-install.py | **18 PASS, 0 FAIL, 2 SKIP** |
| Harvester persistence test | **PASSED** (save → reload → state restored) |
| Vendored import test | **PASSED** (imports from `~/.owl-agent/`) |

**Total source lines**: 2,351 (proxy_defense.py: 1,285, proxy_harvester.py: 545) + gateway/ (~2,000 lines)
**Uncovered lines**: 418 (18%)

---

## Skills Inventory (All Installed Skills)

### Core Skills (~/.agents/skills/)

| Skill | Source | Pipeline Stage |
|-------|--------|---------------|
| triage | mattpocock/skills | DEFINE |
| diagnosing-bugs | mattpocock/skills | DEFINE |
| grill-with-docs | mattpocock/skills | PLAN |
| grilling | mattpocock/skills | PLAN |
| domain-modeling | mattpocock/skills | PLAN |
| to-spec | mattpocock/skills | PLAN |
| ponytail | DietrichGebert/ponytail | PLAN |
| grill-with-tail | andre-lmarinho/grillwith-tail | PLAN |
| grill-powers | okht/grill-powers | PLAN/SHIP |
| writing-plans | hazikkhatri/superpowers | BUILD |
| subagent-driven-development | hazikkhatri/superpowers | BUILD |
| executing-plans | hazikkhatri/superpowers | BUILD |
| systematic-debugging | hazikkhatri/superpowers | BUILD/VERIFY |
| verification-before-completion | hazikkhatri/superpowers | VERIFY |
| finishing-a-development-branch | hazikkhatri/superpowers | REVIEW/SHIP |
| agent-run | GRD-Chang/grill-engineering | SHIP |

### Research Skills (installed via `npx skills add`)

| Skill | Source | Installs | Pipeline Stage |
|-------|--------|----------|---------------|
| parallel-deep-research | parallel-web/parallel-agent-skills | 14.3K | DEFINE |
| parallel-findall | parallel-web/parallel-agent-skills | 14.3K | DEFINE |
| github-research | lingzhi227/agent-research-skills | 31 skills | DEFINE |
| free-search-aggregator | vulcanusalex/free-search-aggregator | 85 | DEFINE |
| freeUnlimited-websearch | lngu/openclaw-skill-freeunlimited-websearch | 565 | DEFINE |
| you-web | youdotcom-oss/agent-skills | 81 | DEFINE |

### Governed Token Plane Skills (from plan)

| Skill | Source | Pipeline Stage | Purpose |
|-------|--------|---------------|---------|
| find-skills | vercel-labs/skills | DEFINE | #1 meta-skill — discover/install other skills |
| meta-skill | vercel-labs/skills | DEFINE | Conceptual — 404 on skills.sh, find-skills serves this role |
| parallel-findall | parallel-web/parallel-agent-skills | DEFINE | Entity discovery — find providers/models matching criteria |
| impeccable | pbakaus/impeccable | REVIEW | Quality framework: audit, critique, distill, adapt, optimize |
| agent-browser | vercel-labs/agent-browser | DEFINE | Browser automation — stealth verification of gateway endpoints |
| github-researcher | lingzhi227/agent-research-skills | DEFINE | GitHub repo triage — CVEs, staleness, maintenance |
| brainstorming | obra/superpowers | PLAN | Structured ideation for gateway architecture |
| writing-plans | obra/superpowers | PLAN | Detailed implementation plans with checkpoints |
| systematic-debugging | obra/superpowers | BUILD/VERIFY | Hypothesis-driven debug loop for gateway issues |

### Conceptual Skills (14 stubs in `skills/`) — see next section.

---

## Conceptual Skills (14 Stubs in `skills/`)

| # | Skill | Stage | Source | Purpose |
|---|-------|-------|--------|---------|
| 1 | `agent-skills` | DEFINE | `skills/agent-skills/` | Discover/install/manage skills from skills.sh ecosystem |
| 2 | `codemap` | DEFINE | `skills/codemap/` | Map codebase structure — modules, dependencies, entry points, boundaries |
| 3 | `meta-skill` | DEFINE | `skills/meta-skill/` | Discover and install skills when capability is missing |
| 4 | `agent-reach` | DEFINE | `skills/agent-reach/` | Read/search across web platforms (Twitter, Reddit, YouTube, GitHub) |
| 5 | `duckduckgo-search` | DEFINE | `skills/duckduckgo-search/` | Free web search via DuckDuckGo — no API key |
| 6 | `exa-web-search-free` | DEFINE | `skills/exa-web-search-free/` | Free AI neural search via Exa MCP — no API key |
| 7 | `ralph-prompt-multi-task` | PLAN | `skills/ralph-prompt-multi-task/` | Generate phased prompts with sequential milestones |
| 8 | `orchestrate` | PLAN | `skills/orchestrate/` | Meta-orchestrate multi-agent workflow across all pipeline stages |
| 9 | `chain-of-thought` | PLAN | `skills/chain-of-thought/` | Step-by-step reasoning for architecture decisions |
| 10 | `headroom` | PLAN | `skills/headroom/` | Assess capacity, constraints, resource availability before build |
| 11 | `Caveman` | PLAN | `skills/Caveman/` | Simplest solution first — prevent over-engineering during design |
| 12 | `parallel-agent-skills` | BUILD | `skills/parallel-agent-skills/` | Execute multiple agent skills in parallel during implementation |
| 13 | `devils-advocate` | REVIEW | `skills/devils-advocate/` | Challenge assumptions, identify failure modes, stress-test before commit |
| 14 | `impeccable` | REVIEW | `skills/impeccable/` | Quality framework: audit, critique, distill, adapt, optimize, delight, result |

**Skill gaps (not published, custom stubs only):** `meta-skill` (vercel-labs/skills returned 404), `impeccable` (pbakaus/impeccable not found).

---

## 10 End-to-End Use-Case Pipelines

Each pipeline flows: **DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP**

| # | Pipeline | Trigger | DEFINE | PLAN | BUILD | VERIFY | REVIEW | SHIP |
|---|----------|---------|--------|------|-------|--------|--------|------|
| 1 | Bug Fix | Something is broken | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 2 | Feature Development | You want something new | agent-skills, codemap, grill-me, grilling | domain-modeling, to-spec, grill-powers, ralph-prompt-multi-task, chain-of-thought, headroom, Caveman | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 3 | Security Fix | Something isn't safe | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 4 | Performance Optimization | It's too slow | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 5 | Documentation & Spec | People need to understand it | agent-skills, codemap, grill-with-docs | domain-modeling, to-spec, ponytail, ralph-prompt-multi-task, Caveman | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 6 | Incident Response | Something big broke | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 7 | Refactoring | It's messy | agent-skills, codemap, grill-me, grilling | to-spec, chain-of-thought, headroom, Caveman | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 8 | Dependency Update | Tools are old | agent-skills, codemap, agent-browser, find-skills | headroom | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 9 | Architecture Review | You're changing the design | agent-skills, codemap, grill-me, grilling | domain-modeling, to-spec, grill-powers, ralph-prompt-multi-task, chain-of-thought, headroom, Caveman | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 10 | Full Product Delivery | You're making something from scratch | agent-skills, codemap, grill-powers | ralph-prompt-multi-task, orchestrate, chain-of-thought, headroom, Caveman | writing-plans, executing-plans, subagent-driven-development, parallel-agent-skills, systematic-debugging | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | agent-run, finishing-a-development-branch |

### Decision Gates

| Gate | From → To | Condition |
|------|-----------|-----------|
| G1 | DEFINE → PLAN | Requirements clarified, scope agreed |
| G2 | PLAN → BUILD | PRD approved, tasks broken down, headroom confirmed |
| G3 | BUILD → VERIFY | Implementation complete, tests written |
| G4 | VERIFY → REVIEW | All tests pass, evidence captured |
| G5 | REVIEW → SHIP | Code reviewed, devils-advocate challenged, impeccable quality gate passed |
| G6 | SHIP → Complete | Branch merged or PR closed |

---

## Research Investigation Stack

### Stacked Research Skill

Located at `~/.agents/skills/research-investigation-pipeline/SKILL.md` (note: file path may vary — check `find /home/user/.agents/skills -name "SKILL.md"`).

Combines:
- `parallel-deep-research` (parallel-web/parallel-agent-skills)
- `duckduckgo-search` (nousresearch/hermes-agent)
- `exa-web-search-free` (sundial-org/awesome-openclaw-skills)
- `free-search-aggregator` (vulcanusalex/free-search-aggregator)
- `freeUnlimited-websearch` (lngu/openclaw-skill-freeunlimited-websearch)
- `you-web` (youdotcom-oss/agent-skills)
- `agent-reach` (panniantong/agent-reach)

### Research URLs Referenced

- `PROMPT_PARALLEL_DEEP_RESEARCH_LITELLM.md` — Top 20 LiteLLM alternatives research prompt (2026)
- `VALIDATED_LITELLM_RESEARCH.md` — Validated LiteLLM research findings
- `RESEARCH_SKILL_LAYERING.md` — Research skill layering documentation

---

## Documentation Locations

| Document | Path | Purpose |
|----------|------|---------|
| Issue tracker | `docs/agents/issue-tracker.md` | Issue tracking |
| Domain model | `docs/agents/domain.md` | Domain model |
| Architecture docs | `docs/V7_UPSTREAM.md`, `docs/PROTOCOL_ESCALATION_GUIDE.md`, `docs/LAYERED_FALLBACK.md` | Architecture |
| MCP integration | `docs/MCP_INTEGRATION.md`, `docs/STEALTH_BROWSER.md` | MCP + stealth browser |
| Delivery automation | `docs/agents/grill-engineering/INTEGRATION.md` | agent-run integration |
| Skills framework (full) | `docs/skills-framework/README.md` | Full framework with handoff contracts, decision gates |
| 10 pipelines | `docs/skills-framework/10-PIPELINES.md` | 10 use cases with stage mapping |
| Quick reference | `docs/skills-framework/QUICK_REFERENCE.md` | At-a-glance lookup |
| Conceptual skill stubs | `skills/` | 14 skill SKILL.md files |
| Research investigation | `~/.agents/skills/research-investigation-pipeline/SKILL.md` | Stacked research skill |
| Reverse proxy | `reverse_proxy.py` | v2 HTTP ingress |
| Harvester (vendored) | `~/.owl-agent/proxy_harvester.py` | Vendored pool engine |
| Skills lock | `skills-lock.json` | Locked skill sources with hashes |

---

## All URLs Referenced During Development

| URL | Purpose |
|-----|---------|
| https://github.com/marktantongco/owl-agent-proxy | Main repository |
| https://github.com/marktantongco/owl-agent-proxy/pull/30 | PR #30 — harvester persistence + vendoring |
| https://github.com/marktantongco/owl-agent-proxy/pull/29 | PR #29 — AGENTS.md update |
| https://github.com/marktantongco/owl-agent-proxy/pull/28 | PR #28 — reverse proxy v2 + research skills |
| https://github.com/marktantongco/owl-agent-proxy/pull/27 | PR #27 — reverse proxy HTTP ingress |
| https://github.com/GRD-Chang/grill-engineering | agent-run CLI source (no pyproject.toml found) |
| https://github.com/parallel-web/parallel-agent-skills | parallel-deep-research + parallel-findall (14.3K installs) |
| https://github.com/lingzhi227/agent-research-skills | github-research (31 skills) |
| https://github.com/vulcanusalex/free-search-aggregator | free-search-aggregator (85 installs) |
| https://github.com/lngu/openclaw-skill-freeunlimited-websearch | freeUnlimited-websearch (565 installs) |
| https://github.com/youdotcom-oss/agent-skills | you-web (81 installs) |
| https://github.com/panniantong/agent-reach | agent-reach (16.1K installs) |
| https://github.com/nousresearch/hermes-agent | duckduckgo-search |
| https://github.com/sundial-org/awesome-openclaw-skills | exa-web-search-free (2.8K installs) |
| https://github.com/vercel-labs/skills | find-skills / meta-skill (17.9K installs, 404 for meta-skill) |
| https://github.com/adaptationio/skrillz | ralph-prompt-multi-task |
| https://github.com/JuliusBrussee/caveman | Caveman |
| https://lobehub.com/skills/bidodev-devils-advocate-skill-devils-advocate | devils-advocate |
| https://lobehub.com/skills/pluginagentmarketplace-custom-plugin-prompt-engineering-chain-of-thought | chain-of-thought |
| https://skills.sh/trending | Skills leaderboard |
| https://docs.parallel.ai/integrations/agent-skills | Parallel skills installation guide |
| https://parallel.ai/pricing | Parallel AI pricing |
| https://github.com/mattpocock/skills | mattpocock/skills ecosystem |
| https://github.com/DietrichGebert/ponytail | ponytail skill |
| https://github.com/andre-lmarinho/grillwith-tail | grill-with-tail skill |
| https://github.com/okht/grill-powers | grill-powers skill |
| https://github.com/hazikkhatri/superpowers | writing-plans, executing-plans, etc. |
| https://github.com/lexiforest/curl_cffi | curl_cffi — browser TLS/JA3/JA4/HTTP2 fingerprint impersonation (stealth mode) |
| https://brightdata.com/blog/web-data/web-scraping-with-curl-cffi | curl_cffi web scraping guide (2026) |
| https://proxyhat.com/blog/tls-fingerprinting-explained | TLS fingerprinting JA3/JA4 mitigation |
| https://proxyhat.com/blog/tls-impersonation-curl-cffi-guide | curl_cffi TLS impersonation guide |
| https://trustmyip.com/blog/how-to-bypass-proxy-detection | Bypass proxy detection (TLS fingerprint, JA3/JA4) |
| https://webdecoy.com/blog/ja4-fingerprinting-ai-scrapers-practical-guide | JA4 fingerprinting for AI scraper detection |
| https://arxiv.org/html/2602.09606v1 | TLS fingerprinting bot detection research |
| https://github.com/wi1dcard/fingerproxy | Fingerproxy — JA3/JA4/Akamai HTTP2 reverse proxy |

---

## Conventions

- **Language**: English only
- **Adopt smp5.4pd.md** as operating instructions (Tactical Merge, Mode: 🐜 Systematic)
- **No autologin/autoclaw** for owl-dns-synergy
- **No blacklisted AI proxy** for ai-gateway-complete
- **No glm/z.ai** for autoclaw-autologin
- **Laptop memory constraints** — bare metal preferred
- **Plan → validate → execute**
- **Never output placeholder text**
- **Testing**: pytest with `tests/conftest.py` (hermetic, blocks outbound sockets) — 548 tests passing (trust tests over docs prose)
- **CI/CD**: `.github/scripts/ci-check.sh` (protocol escalation + credential guard)
- **Config precedence**: explicit argument → `config.json` → built-in default
- **Version drift note**: Docs disagree (About says v3.0, README says v7.1). Trust the tests (507 passing), not the prose.

---

## Git & PR History

| PR | Title | Status | Merge Commit |
|----|-------|--------|-------------|
| #27 | Add reverse proxy HTTP ingress for ResilientClient egress layer | Merged | `7ea779dbafa95e7b470562d06c924bb128494ca5` |
| #28 | Upgrade reverse proxy with protocol routing, circuit breaker, and research skills | Merged | (via #27 merge) |
| #29 | Update AGENTS.md with conceptual skills, docs locations, and test counts | Merged | (via #30 merge) |
| #30 | Add on-disk persistence to UpstreamHarvester and vendored pool engine | Merged | (merge commit on main) |
| #31 | Stealth mode reverse proxy upgrade (curl_cffi TLS/JA3/JA4 impersonation) | Merged | (via #32 merge) |
| #32 | Stealth mode reverse proxy v2.1 complete | Merged | (merge commit on main) |

**Current branch**: `arena/0866387c-owl-agent-proxy` (active)
**Current work**: Governed token plane (OpenCode v2 → gateway → local + free + paid + cache + budgets, provider key isolation)
