# 🦉 OWL-AGENT Proxy Defense Stack v3.0

> Multi-protocol HTTP defense system with intelligent caching, request deduplication, rate limiting, and proxy rotation.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI/CD Pre-Merge](https://img.shields.io/badge/CI%2FCD-Protocol%20Check-orange.svg)](.github/scripts/ci-check.sh)

---

## Architecture

```
Request → Cache → Deduplicate → Rate Limit → Proxy Rotate → Protocol Router → Response
            ↓           ↓            ↓             ↓              ↓
          HIT?      In-flight?   Token Bucket   Tier-sorted   http/1.1 | http/2
          Return    Await result   Per-domain   by latency    | ja3 | websocket
          cached    same result                  health       | browser
```

## Features

- **5 Protocol Support**: HTTP/1.1 (baseline), HTTP/2 (multiplexing), JA3 (anti-bot fingerprint), WebSocket (real-time), Browser (Playwright headless)
- **Intelligent Caching**: SHA-256 keyed cache with TTL, protocol-aware, in-memory
- **Request Deduplication**: In-flight request coalescing prevents duplicate network calls
- **Domain Rate Limiting**: Per-domain token bucket rate limiter
- **Proxy Rotation**: Tier-based proxy pool with health tracking, automatic banning on failure
- **Protocol Escalation**: Start with `http/1.1`, escalate only when justified (enforced by CI/CD)
- **CI/CD Pre-Merge Check**: Validates protocol escalation justification and prevents hardcoded credentials

## Quick Start

### Prerequisites

- Python 3.10+
- Virtual environment (recommended)

### Installation

```bash
# Clone the repository
git clone https://github.com/marktantongco/owl-agent-proxy.git
cd owl-agent-proxy

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install core dependencies (http/1.1 only)
pip install -r requirements.txt

# Optional: install additional protocol support
pip install httpx          # HTTP/2 support
pip install curl_cffi      # JA3/TLS fingerprint support
pip install websockets     # WebSocket support
pip install playwright     # Browser automation
playwright install chromium
```

### Basic Usage

```python
import asyncio
from proxy_defense import ResilientClient

async def main():
    async with ResilientClient(cache_ttl=300, rate_limit=1.0) as client:
        # Simple GET request (defaults to http/1.1)
        resp = await client.request("GET", "https://httpbin.org/get")
        print(f"Status: {resp.status}, Protocol: {resp.protocol}")

        # Escalate to JA3 for anti-bot protection
        resp = await client.request("GET", "https://example.com", protocol="ja3")
        print(f"Status: {resp.status}, Protocol: {resp.protocol}")

        # Get stats
        stats = await client.get_stats()
        print(f"Proxies: {stats['proxies_healthy']}/{stats['proxies_total']} healthy")

asyncio.run(main())
```

### CLI Usage

```bash
# Run the built-in test
python proxy_defense.py

# Run CI/CD pre-merge check
bash .github/scripts/ci-check.sh

# Run tests
python -m pytest tests/
```

## Project Structure

```
owl-agent-proxy/
├── proxy_defense.py              # Main defense stack (v3.0)
├── requirements.txt              # Python dependencies (pinned)
├── .gitignore                    # Git ignore rules
├── README.md                     # This file
├── worklog.md                    # Session worklog template
├── .github/
│   ├── scripts/
│   │   └── ci-check.sh           # CI/CD pre-merge check script
│   └── workflows/
│       └── protocol-check.yml    # GitHub Actions workflow
├── config/
│   ├── AGENTS.md                 # Agent system prompt
│   ├── opencode.json             # OpenCode plugin configuration
│   └── proxy_pool.template.json  # Proxy pool template (copy to proxy_pool.json)
├── docs/
│   ├── PROTOCOL_ESCALATION_GUIDE.md  # Protocol escalation decision guide
│   └── LAYERED_FALLBACK.md           # Layered fallback architecture
├── examples/
│   └── usage.py                  # Usage examples
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

## Protocol Escalation Strategy

| Protocol | Use Case | Dependencies | When to Use |
|----------|----------|--------------|-------------|
| `http/1.1` | Default baseline | `aiohttp` | Always start here |
| `http/2` | Multiplexing, low latency | `httpx` | Multiple concurrent requests to same domain |
| `ja3` | Anti-bot bypass | `curl_cffi` | Cloudflare, DataDome, Akamai blocks |
| `websocket` | Real-time streams | `websockets` | WebSocket endpoints |
| `browser` | Full JS rendering | `playwright` | Dynamic content, CAPTCHA bypass |

**Rule**: Always answer "Why not http/1.1?" before escalating. The CI/CD check enforces this.

## CI/CD Pre-Merge Check

The `ci-check.sh` script runs two checks:

1. **Protocol Escalation Justification**: Scans code for protocol escalation and requires ≥3/4 justification markers:
   - Baseline reference (`http/1.1`, `http1`, `baseline`)
   - Anti-bot context (`cloudflare`, `datadome`, `akamai`, `anti.bot`)
   - Performance evidence (`latency`, `ms`, `benchmark`, `tested`)
   - Approval marker (`approved`, `APPROVED`)

2. **Proxy Credential Security**: Detects hardcoded credentials in source files (excludes `proxy_pool.json` and test files)

```bash
# Run locally
bash .github/scripts/ci-check.sh

# Expected output
🦉 OWL-AGENT CI/CD PRE-MERGE CHECK
CHECK 1: Protocol Escalation Justification
[PASS] ./proxy_defense.py:354 — Justified (score: 3/4)
CHECK 2: Proxy Credential Security
[PASS] No hardcoded proxy credentials
RESULTS: Errors: 0, Warnings: 0
ALL CHECKS PASSED
```

## Configuration

### Proxy Pool

Copy the template and fill in your proxy credentials:

```bash
cp config/proxy_pool.template.json config/proxy_pool.json
# Edit config/proxy_pool.json with your actual proxy URLs
```

```json
{
  "tier_1_managed_free": {
    "providers": [
      {
        "name": "webshare",
        "proxies": [
          {"url": "http://your-proxy:80", "type": "datacenter", "protocols": ["HTTP"]}
        ]
      }
    ]
  }
}
```

### ResilientClient Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `cache_ttl` | 300 | Cache time-to-live in seconds |
| `rate_limit` | 1.0 | Requests per second per domain |
| `max_retries` | 3 | Maximum retry attempts |
| `auto_load_proxies` | True | Auto-load proxy pool on init |
| `default_protocol` | "http/1.1" | Default protocol for requests |

## Skills System

The `skills/` directory contains reusable agent skills for common workflows:

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

## Documentation

- **[PROTOCOL_ESCALATION_GUIDE.md](docs/PROTOCOL_ESCALATION_GUIDE.md)** — When and how to escalate protocols
- **[LAYERED_FALLBACK.md](docs/LAYERED_FALLBACK.md)** — Fallback architecture and resilience strategy
- **[AGENTS.md](config/AGENTS.md)** — Agent system prompt and operating principles

## Dependencies

| Package | Purpose | Required |
|---------|---------|----------|
| `aiohttp` | HTTP/1.1 async client | Yes |
| `aiofiles` | Async file I/O | Yes |
| `cachetools` | Cache utilities | Yes |
| `orjson` | Fast JSON serialization | Yes |
| `cryptography` | TLS/crypto operations | Yes |
| `PySocks` | SOCKS proxy support | Yes |
| `tenacity` | Retry logic | Yes |
| `fake-useragent` | User agent rotation | Yes |
| `httpx` | HTTP/2 async client | No |
| `curl_cffi` | JA3/TLS fingerprint | No |
| `websockets` | WebSocket client | No |
| `playwright` | Browser automation | No |

## Testing

```bash
# Run unit tests
python -m pytest tests/ -v

# Run integration test (makes real HTTP request)
python proxy_defense.py
```

## License

MIT

## Author

[marktantongco](https://github.com/marktantongco)
