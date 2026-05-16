# 🦉 Protocol Escalation Guide

> Start with `http/1.1`. Escalate only when you hit a specific anti-bot wall.

## The Escalation Ladder

```
Step 0: http/1.1 + cache + dedup + rate limit
        └── Solves 90% of targets
        └── ~100 req/sec, 1 MB memory

Step 1: http/1.1 + proxy rotation (Tier 1 managed free)
        └── 30 IPs, 8 GB/month

Step 2: http/2 (httpx)
        └── Targets that block HTTP/1.1
        └── ~80 req/sec, 1.5 MB memory

Step 3: ja3 (curl_cffi)
        └── Cloudflare, DataDome TLS fingerprinting
        └── ~50 req/sec, 2 MB memory

Step 4: browser (Playwright)
        └── Akamai, Imperva heavy anti-bot
        └── ~10 req/sec, 10 MB memory

Step 5: browser + residential/mobile proxies (Tier 5 paid)
        └── Maximum anti-bot evasion
```

## Code Review Rule

**"Why not http/1.1?" must be answered before `protocol="browser"` is approved.**

Required in PR:
1. What anti-bot wall did http/1.1 hit?
2. What anti-bot system is the target using?
3. Did you try ja3 before browser? (2x vs 10x latency)
4. Benchmark: latency difference vs. http/1.1 baseline
5. Test date and verification status

Template:
```python
# Escalated to browser because:
# - http/1.1 returned 403 with Akamai Bot Manager
# - ja3 returned 403 (JS fingerprinting, not just TLS)
# - Browser latency: 1500ms vs http/1.1: 150ms (10x)
# - Tested on 2026-05-15, confirmed working
protocol="browser"  # APPROVED: Akamai requires full browser
```

## Common Mistakes

| Mistake | Why Wrong | Correct |
|---------|-----------|---------|
| Using `browser` for every target | 10x slower, 10x cost | Start `http/1.1`, escalate when blocked |
| Installing all protocols upfront | Wastes resources, longer install | Install core. Add on demand. |
| Using `ja3` for simple APIs | 2x latency for no benefit | `http/1.1` handles 90% perfectly |
| Ignoring cache layer | Redundant requests waste quota | Cache aggressively. Deduplicate. |
| Rotating proxies every request | Bot fingerprint. Humans persist. | Rotate on error (429/403), not schedule. |
