# 🦉 v7.1 — Upstream Harvesting, Honeypot Detection, Sticky Sessions

v7.1 adds four things to the existing defense stack without changing its
default behaviour. Everything here is opt-in via `config.json` (the installer
turns harvesting on) and disabled automatically when its dependencies or the
network are unavailable.

```
                  ┌─────────────── proxy_harvester.py ───────────────┐
4 list endpoints →│ fetch → tolerant parse → dedupe → source health  │
                  └──────────────────────┬───────────────────────────┘
                                         ↓ quarantine (tier 4, healthy=False)
                          validate (TCP + HTTP probe, N concurrent)
                                         ↓
                             honeypot / injection check
                              ↓ trusted                     ↓ tampered
                    pool entry (tier 4, healthy)      dropped + logged
                                         ↓
  request → cache → dedupe → rate limit → sticky select (agent_id, domain)
                                         → protocol router → response
```

---

## Sources

| Source | Format | Notes |
|--------|--------|-------|
| `proxyscrape_json` | JSON array | richest metadata: `protocols` is a **list**, plus `uptime_percent`, `latency_ms`, `anonymity`, `ssl`, `asn`, `isp` |
| `maxfeix_txt` | text | upstream-screened for honeypots, injection and broken TLS — treated as the highest-trust seed, but still re-validated locally |
| `monosans_txt` | text | fastest-first ordering |
| `proxmint_json` | JSON | re-validated upstream; `score` field |

Free lists are volatile: endpoints move, schemas drift, and availability
depends on your egress. The harvester is written to degrade rather than break:

- a failing source is recorded (`failures`, `last_error`) and does not stop the
  others — `asyncio.gather` never propagates a single source's failure;
- a source that quietly switches from JSON to text is still parsed;
- if no source is reachable, the pool simply stays as it was.

Add or replace sources programmatically:

```python
from proxy_harvester import ProxySource, UpstreamHarvester

sources = [
    ProxySource("my_list", "https://example.com/proxies.txt", "txt",
                protocol_hint="socks5", max_latency_ms=2000),
    ProxySource("paid_pool", "https://example.com/api/all.json", "json",
                min_uptime=80.0),
]
async with UpstreamHarvester(sources=sources) as harvester:
    print(await harvester.harvest())
```

## Tolerant parsing

The four lists do not share a schema, so extraction is alias-based and
unit-aware:

| Field | Accepted aliases | Notes |
|-------|------------------|-------|
| address | `ip`, `host`, `address`, `proxy_ip`, `ip_address` | |
| port | `port`, `proxy_port` | strings accepted |
| protocol | `protocol`, `protocols`, `type`, `scheme` | list or string; `socks5h` → `socks5` |
| country | `country_code`, `country`, `cc`, `iso_code`, … | also nested `geolocation.country.iso_code` |
| uptime | `uptime_percent`, `uptime`, `uptime_pct` | 0–1 ratios are rescaled to percent |
| latency | `latency_ms`, `latency`, `response_time` | `monosans` reports **`timeout` in seconds** → converted |

Entries that can never work are dropped at parse time: private, loopback,
CGNAT, link-local, reserved and unspecified addresses (`networks such as
10/8, 100.64/10, 127/8, 0/8, 240/4`), plus invalid ports. This keeps dead
inventory out of the pool and out of the ban machinery.

## Quarantine + validation

Harvested proxies enter the pool at **tier 4** with `healthy=False` and
`validated=False`. A background validator pulls them off a queue with bounded
concurrency (`validator_concurrency`, default 10) and:

1. opens a TCP connection (dead proxies are rejected without an HTTP round trip);
2. requests a probe URL through the proxy;
3. runs the honeypot check when a baseline exists;
4. promotes on success, bans on failure, removes after three failures.

`get_proxy()` only ever returns healthy, non-banned entries, so a stale list can
never reach the request path. Managed proxies from `config/proxy_pool.json` stay
at tier 1 and are preferred.

## Honeypot / injection detection

`HoneypotDetector` fetches `https://httpbin.org/json` directly once to capture a
**structural hash** (keys + value types, not values), then compares that hash
for the same URL fetched through a candidate proxy. It flags:

- injected redirects (3xx where direct is 200),
- injected markup (a `<script` count where a JSON body is expected),
- replaced/truncated bodies (different structure).

Fail-open by design: if no baseline can be established (offline, endpoint down,
captive portal) the detector returns `no-baseline` instead of rejecting the
whole pool, and an expired baseline is refreshed on the next check. Connectivity
errors (`error:ConnectTimeout`) are also not treated as tampering — only
structural mismatch or injection is.

**Scope limit:** the probe URL is HTTPS, so an HTTP proxy can only tunnel it and
cannot rewrite the body without breaking TLS. What this actually catches is
proxies that intercept or redirect at the CONNECT stage, serve a different
document, or inject markup when asked for a plain-HTTP URL. It is not a general
"detect any malicious proxy" oracle, and a proxy that tampers only with
plain-HTTP traffic to *other* hosts is invisible to it.

## Sticky sessions

`SessionAffinityManager` binds one proxy URL to `(agent_id, domain)` for
`session_ttl` seconds (default 900). Selection is:

| `rotation_mode` | Behaviour |
|-----------------|-----------|
| `sticky` (default) | reuse the binding; re-bind only when the bound proxy dies |
| `random` | pick any healthy proxy, no binding |
| `round_robin` | cycle tier/latency-sorted candidates, no binding |

Why sticky: a target that sees the exit IP change mid-session sees a user
"teleporting between cities", which is itself a strong bot signal. Sticky
bindings are cheap and remove one whole class of suspicion.

**Honest limitation:** this makes the *IP* coherent, not the fingerprint. The
TLS/HTTP impersonation profile is fixed per `ResilientClient` instance
(`curl_cffi` `impersonate="chrome110"` when JA3 is installed), so all sessions in
one process share one TLS fingerprint. Per-session fingerprint rotation needs a
session pool keyed by (proxy, impersonate) and is not implemented.

## Configuration

`~/.owl-agent/config/config.json` (only the v7.1 keys shown):

| Key | Default | Meaning |
|-----|---------|---------|
| `use_upstream_harvester` | `true` (installer) / `false` (library default) | master switch for harvesting |
| `session_ttl` | `900` | sticky binding lifetime, seconds |
| `harvest_interval` | `600` | seconds between sweeps |
| `honeypot_check` | `true` | run the body-integrity check during validation |
| `max_proxies` | `2000` | pool cap; managed tier 1 always survives trimming |
| `max_per_source` | `300` | candidates accepted per source per sweep |
| `validator_concurrency` | `10` | parallel validation probes |
| `validator_timeout` | `8` | seconds per probe |
| `persist_proxy_cache` | `true` | persist the pool to `config/proxy_cache.json` |
| `cache_ttl` / `rate_limit` / `max_retries` | `300` / `1.0` / `3` | pre-v7 keys, still honoured (explicit constructor arguments win) |

Precedence: explicit constructor argument → `config.json` → built-in default.

## Operator runbook

```bash
~/.owl-agent/run.sh stats                       # human summary
~/.owl-agent/run.sh stats --json | jq .         # full telemetry
~/.owl-agent/run.sh harvest --seconds 30        # one sweep + yield report
~/.owl-agent/run.sh validate http://IP:PORT     # probe a single proxy
```

| Signal | Query | Healthy | If it is not |
|--------|-------|---------|--------------|
| Pool size | `.proxies_total` | > 0 within ~2 min of a sweep | check `.source_health[*].last_error` |
| Healthy proxies | `.proxies_healthy` | 5–40 typical | 0 → validators failing or egress blocked |
| Source yield | `.source_health[*].yield_rate` | best source > 0.05 | all ≈ 0 → lists stale; wait or change sources |
| Session bindings | `.session_affinity.active` | grows with agent count | stuck at 1 → `agent_id` not passed by the caller |
| Unvalidated backlog | `.upstream_harvester.unvalidated` | drains between sweeps | growing → slow probes; lower `validator_concurrency` or raise `validator_timeout` |
| Honeypot rejections | `.upstream_harvester.honeypot_rejections` | low | 20 %+ of validations → baseline is broken; restart to re-baseline |

### Kill switch

```json
{ "use_upstream_harvester": false }
```

Restart the host. The stack falls back to `config/proxy_pool.json` plus the
on-disk cache; the MCP server keeps working and `proxy_pick` returns `null`
until the pool has entries.

### Rollback / purge

```bash
./install-owl.sh --rollback   # restore the most recent backup (code + config)
./install-owl.sh --purge      # delete ~/.owl-agent (asks first)
```

## Verification

`install-owl.sh` runs `scripts/verify-install.py` — 18 offline checks plus 2
live ones (V19 live harvest, V20 end-to-end fetch), which report **SKIP** rather
than **FAIL** when there is no egress:

V1 layout · V2 config keys · V3 cold import · V4 API surface · V5 core deps ·
V6 optional protocols · V7 lazy imports · V8 sticky selection · V9 session TTL ·
V10 harvester schemas · V11 source-health ranking · V12 honeypot hash ·
V13 pool persistence · V14 config merge · V15 http/2 guard · V16 CLI stats ·
V17 MCP selftest · V18 MCP stdio handshake · V19 live harvest · V20 e2e fetch

Run it any time with `~/.owl-agent/run.sh verify` (or `--no-live`).

## What v7.1 does not do

- **No per-session fingerprint rotation.** Sticky IP, static TLS profile per
  process.
- **No paid residential pool.** Free lists only; wire a paid provider by
  subclassing/writing a `ProxySource`-shaped loader.
- **No throughput guarantee.** Free proxies are unpredictable; scoring adapts,
  SLAs do not exist.
- **No socks validation.** `validate_proxy` probes HTTP/HTTPS proxies only and
  returns `None` for `socks4`/`socks5` rather than reporting a false verdict.
- **No compliance advice.** Using free proxies carries legal/ToS implications
  that vary by jurisdiction and target. The tool is a tool; policy is yours.
