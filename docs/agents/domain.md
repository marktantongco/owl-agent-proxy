# Domain Model — OWL Agent Proxy

## Core Concepts

### Proxy
A network intermediary that forwards client requests to target servers. Properties:
- `url`: proxy endpoint (e.g., `http://127.0.0.1:8080`)
- `proxy_type`: `dc` (datacenter), `free`, `residential`
- `protocol`: `http`, `https`, `socks5`
- `source`: where the proxy was harvested from
- `tier`: priority level (1 = highest, external proxies; 4 = lowest)
- `healthy`: whether the proxy passed validation
- `validated`: whether the proxy has been successfully probed
- `latency_ms`: measured response latency
- `p99_latency_ms`: P99 latency for budget-based selection
- `banned`: whether the proxy is currently banned
- `ban_duration`: seconds until ban expires

### Session Affinity
A sticky binding between `(agent_id, domain)` and a proxy URL, with a configurable TTL (default 900 seconds / 15 minutes). Prevents "teleporting user" bot signals by keeping the same exit IP for a given agent+domain pair.

### Token Bucket
Per-domain rate limiter with configurable `rate` (tokens/second) and `capacity` (max tokens). State (`tokens`, `last_update`) is persisted to `~/.owl-agent/config/token_buckets.json` to survive restarts.

### Upstream Source
A free proxy list endpoint harvested on a timer. Each source has:
- `name`: source identifier
- `url`: harvest endpoint
- `format`: `json` or `txt`
- `min_uptime`: minimum uptime percent
- `max_latency_ms`: maximum acceptable latency

## Boundaries

- **Tier 1**: External proxies (BounceBack, https_proxy) — highest priority
- **Tier 2-4**: Harvested free proxies — descending quality
- **Quarantine**: Newly harvested proxies start at tier 4, unhealthy=False
- **Validation**: TCP + HTTP probe to confirm proxy works

## Invariants

- External proxies are attempted before harvested free proxies
- Sticky binding TTL defaults to 900 seconds
- Rate limit defaults to 1.0 token/second per domain
- Max 2000 proxies in pool (tier-1 managed proxies always survive)
- Honeypot check is enabled by default (structural body hash detection)
