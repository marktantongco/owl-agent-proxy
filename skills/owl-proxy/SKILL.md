---
name: owl-proxy
description: Route agent HTTP traffic through the OWL-AGENT proxy defense stack — tier-based proxy rotation, sticky per-agent sessions, response caching, request dedupe, per-domain rate limiting, honeypot/injection detection, and protocol escalation (http/1.1 to HTTP/2 to JA3 to WebSocket to browser). Use when fetching through a proxy pool, diagnosing pool health or yield, or wiring in a paid proxy provider.
---

# OWL-AGENT Proxy Defense Stack

A layered HTTP client for agents: **cache → dedupe → rate limit → proxy select → protocol router**.
Start on `http/1.1`; escalate only when a request is actually blocked.

## When to use this skill

- Outbound fetches must go through rotating proxies instead of your own IP.
- A task needs a **stable** exit IP per `(agent_id, domain)` — sticky sessions, 900 s default.
- You suspect a proxy is tampering with responses and want a honeypot/injection verdict.
- A target returns `403` under `http/1.1` and you need to escalate protocol deliberately.
- You need pool telemetry (per-source yield, latencies, session bindings) before trusting a pool.

## When **not** to use it

- To evade provider **quotas, billing, or access controls**. This stack rotates egress IPs; it does
  not grant unlimited tokens, bypass quotas, or defeat rate limits imposed by a service you use.
  Legitimate headroom comes from caching, dedupe, backoff, and your own paid keys.
- Against a host whose terms forbid automated access. Jurisdiction and ToS are the operator's call —
  the project ships **no compliance advice**.
- As a security boundary. Free proxies are untrusted intermediaries by definition.

## Install (idempotent)

```bash
./install-owl.sh                 # install + full verification (V1–V20)
./install-owl.sh --no-live       # skip network checks, offline-safe
./install-owl.sh --verify-only   # re-run verification on an existing install
./install-owl.sh --rollback      # restore the most recent backup
```

Installs into `$OWL_HOME` (default `~/.owl-agent`): `proxy_defense.py`, `proxy_harvester.py`,
`mcp_proxy_server.py`, `verify_install.py`, a `venv/`, merged `config/config.json`, and a
**generated** `run.sh`. Re-running is safe: it backs up first (keeps the newest 5) and preserves
`config/proxy_cache.json` and `models/`. Requires Python ≥ 3.10.

> `run.sh` is written by the installer and exists only under `$OWL_HOME` — it is not in the repo.

## Operate via the generated launcher

```bash
~/.owl-agent/run.sh                       # demo / smoke test
~/.owl-agent/run.sh stats                 # pool, sources, sessions
~/.owl-agent/run.sh stats --json          # machine-readable
~/.owl-agent/run.sh fetch URL --json      # fetch through the stack
~/.owl-agent/run.sh harvest --seconds 20  # force one upstream sweep, report yield
~/.owl-agent/run.sh validate http://IP:PORT
~/.owl-agent/run.sh verify --no-live      # install verification
~/.owl-agent/run.sh mcp-selftest          # MCP protocol check
```

## Use from Python

```python
import asyncio
from proxy_defense import ResilientClient

async def main():
    async with ResilientClient() as client:          # context manager closes the pool
        resp = await client.request("GET", "https://example.com")
        print(resp.status, resp.protocol)

        if resp.status == 403:                        # escalate deliberately, not blindly
            resp = await client.request("GET", "https://example.com", protocol="ja3")

asyncio.run(main())
```

Sticky sessions: pass `agent_id="job-42"` and keep it stable for the life of a task. Rotating
`agent_id` mid-task makes a target see one user jumping between cities, which is exactly the
pattern detection looks for.

## Add your own proxy source

Free harvested lists are the default and carry **no SLA**. For stable geo-targeted residential
IPs, append a `ProxySource` (lower `tier` = higher trust; `managed=1 … free upstream=4`):

```python
from proxy_harvester import ProxySource, DEFAULT_SOURCES

DEFAULT_SOURCES.append(
    ProxySource(
        "acme_residential",                  # stable name — telemetry keys off it
        "https://provider.example/list.txt",
        format="txt",                        # "txt" | "json"
        protocol_hint="http",                # used when the source omits protocol
        tier=1,
    )
)
```

For a static hand-curated pool instead, start from `config/proxy_pool.template.json`.

## Limits — read before trusting output

| Limit | Consequence |
|---|---|
| Free proxies only by default | Throughput and lifetime unpredictable; no SLA, no throughput guarantee |
| Sticky IP, **static** fingerprint | `SessionAffinityManager` holds the exit IP; TLS/HTTP impersonation is fixed per client instance — **no per-session fingerprint rotation** |
| Honeypot detection is structural, not semantic | Catches redirect/script injection and body tampering vs. a baseline; a proxy rewriting one field without changing shape is **not** detected |
| HTTP/HTTPS only | **No SOCKS validation** |
| Heuristics | Detection is an arms race; behaviour is best-effort, never guaranteed |

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `Proxy Pool: 0` after ~5 min | No egress, or all sources down | `run.sh stats --json` → `.source_health[*].last_error` |
| Everything times out | Pool warming up, or rate limit too tight | `ResilientClient(rate_limit=2.0)`, then `run.sh harvest` |
| `403` persists across protocols | Target fingerprints beyond JA3 | Stop escalating; reduce request rate or reassess intent |
| Installer exits non-zero | Missing/corrupt module | Re-run `./install-owl.sh`, read the failing check, `--rollback` if needed |
