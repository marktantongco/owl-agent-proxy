# Stealth Mode Reverse Proxy Upgrade — Plan

## Objective
Upgrade `reverse_proxy.py` v2 to v2.1 with a real **stealth mode** protocol that impersonates
browser TLS/JA3/JA4/HTTP2 fingerprints using `curl_cffi` (curl-impersonate), so anti-bot
systems (Cloudflare, Akamai, DataDome, PerimeterX) see browser-grade traffic instead of
Python/OpenSSL signatures.

## Why (research-backed)
- JA3/JA4 TLS fingerprinting identifies clients independent of IP address (research: proxyhat,
  trustmyip, webdecoy, arxiv 2602.09606)
- Standard Python clients (aiohttp/httpx/requests via OpenSSL) produce non-browser TLS
  signatures that are instantly flagged (research: curl_cffi, tls_client vs curl_cffi)
- curl_cffi reproduces exact browser TLS handshakes: cipher order, extensions, ALPN,
  HTTP/2 SETTINGS, GREASE positions (research: curl_cffi docs, brightdata, proxyhat)
- Stealth requires more than TLS: user-agent rotation, Sec-CH-UA/Sec-Fetch-* headers,
  cookie persistence, timing jitter (research: browserless proxy rotation, node unblocker)

## Current state (reverse_proxy.py v2)
- Protocol escalation chain lists "stealth" but it is just a label — no implementation
- Uses aiohttp server + ResilientClient egress (aiohttp/httpx, no TLS impersonation)
- Circuit breaker, load balancing, health checks all present
- No user-agent rotation, no stealth headers, no cookie jar, no timing jitter

## Design — New components

### 1. UserAgentRotator
Rotates through a list of real browser user-agent strings (Chrome, Safari, Firefox, Edge)
with optional sticky (per-target) or random rotation.

### 2. StealthConfig
Dataclass: browser profile, user_agent_rotation (bool/sticky/random), stealth_headers
(bool), cookie_persistence (bool), timing_jitter (min/max seconds), proxy_url (optional).

### 3. StealthClient
Wraps curl_cffi `AsyncSession` with:
- Lazy curl_cffi import (fast cold start)
- Browser impersonation presets (chrome, chrome120, chrome124, safari, safari17,
  edge, edge99, firefox)
- Per-browser session pool (keep-alive, connection reuse)
- Stealth header injection (Sec-CH-UA, Sec-Fetch-*, Accept-Language, etc.)
- Cookie jar persistence across requests
- Optional proxy support
- HTTP/2 via impersonation preset
- `request()` method mirroring ResilientClient interface

### 4. ReverseProxy integration
- Add `stealth_mode` config flag + `stealth_config` to ReverseProxy constructor
- Add "stealth" as a real protocol in the escalation chain (already listed, now wired)
- When protocol == "stealth", route through StealthClient instead of ResilientClient
- Add `--stealth-browser` CLI flag
- Add `stealth` section to config.json reverse_proxy config

## Config.json additions (reverse_proxy section)
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

## CLI additions
`python reverse_proxy.py --stealth-browser chrome124`
`./run.sh serve --stealth-browser chrome124`

## Tests (tests/test_reverse_proxy.py additions)
- StealthClient init with valid/invalid browser profiles
- UserAgentRotator rotation + sticky behavior
- Stealth header injection verification
- ReverseProxy selects stealth protocol when configured
- curl_cffi lazy import (not imported at module scope)

## Verification
- Full test suite: 598 passed, 0 failed
- verify-install.py: 18 PASS, 0 FAIL, 2 SKIP
- End-to-end: stealth client instantiates with browser impersonation

## Deliverables
- reverse_proxy.py — stealth mode (curl_cffi integration)
- tests/test_reverse_proxy.py — stealth tests
- config.json — stealth section
- run.sh — --stealth-browser flag
- AGENTS.md — stealth mode documentation
- STEALTH_MODE_PLAN.md — this plan
