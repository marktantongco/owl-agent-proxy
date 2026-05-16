# 🦉 Layered Fallback Architecture

## What If curl_cffi Stops Working?

If Cloudflare patches JA3 detection:
```python
# ja3 returns 403 (was 200 yesterday)
resp = await client.request("GET", "https://cloudflare-site.com", protocol="ja3")
# Status: 403 ❌

# Automatic fallback to browser
resp = await client.request("GET", "https://cloudflare-site.com", protocol="browser")
# Status: 200 ✅ (Playwright bypasses everything)
```

The layered fallback ensures resilience at every level.

## Fallback Ladder

```
Layer 0: http/1.1          → 150ms, 1x cost      → Default
Layer 1: + Proxy Rotation   → 200ms, 1.3x cost    → Rate limited
Layer 2: http/2             → 180ms, 1.2x cost    → HTTP/1.1 blocked
Layer 3: ja3                → 320ms, 2x cost     → TLS fingerprint blocked
Layer 4: browser            → 1500ms, 10x cost   → JS challenge blocked
Layer 5: + Residential      → 2000ms, 13x cost   → Everything blocked
```

## Scenario: Cloudflare Patches JA3 Detection

```python
# Day 1: ja3 works
resp = await client.request("GET", "https://cloudflare-site.com", protocol="ja3")
# Status: 200 ✅

# Day 30: Cloudflare patches
resp = await client.request("GET", "https://cloudflare-site.com", protocol="ja3")
# Status: 403 ❌ (curl_cffi detected)

# Automatic fallback: ResilientClient retries with browser
resp = await client.request("GET", "https://cloudflare-site.com", protocol="browser")
# Status: 200 ✅ (Playwright bypasses everything)

# Documented in git history:
# Escalated to browser because:
# - ja3 stopped working on 2026-06-01 (Cloudflare patch)
# - http/1.1 and http/2 already blocked
# - Browser latency: 1500ms vs ja3: 320ms (5x)
# - Tested on 2026-06-01, confirmed working
```

**Key insight:** The layered fallback means you're never dependent on a single anti-bot technique. If one layer breaks, the next layer activates automatically after `max_retries`.
