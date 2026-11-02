# Governance Patterns — Hermes-router Study Reference (No Vendoring)

**Source:** marktantongco/hermes-router (fork of kjames2001/hermes-router-proxy), MIT, Python 3.12+, port 8766, 491 tests + 4 skipped, v1.0.0 frozen release.
**Purpose:** Document hermes-router governance patterns as design references for OWL's `ResilientClient` retries and `SessionAffinityManager`. Do NOT vendor hermes-router code or add it as a dependency to `pyproject.toml`.

---

## 1. Smart classification (5-tier classifier ladder)

Hermes-router classifies each new conversation into a task category once per session (session key = hash of first user message, 5-min TTL), re-classifying only on keyword deviation or `/use:<category>` override:

```
fastText (<0.01 ms) → SetFit (~10 ms) → zero-shot embeddings →
offline-learned ML surrogate (~0.1 ms, zero LLM cost) → LLM flash fallback
```

Each tier yields at its confidence threshold. Follow-ups reuse the cached tier with sub-millisecond keyword deviation detection.

**OWL application:** Reference pattern for routing LLM requests through colibri (cheap/local) vs FreeRide (free-tier failover) vs a managed gateway, based on request classification. OWL's `SessionAffinityManager` already binds per `(agent_id, domain)` — the classification tier can be layered on top as a cache key.

**Do not vendor:** hermes-router's classifier code, ML models, or training pipeline.

---

## 2. Key pooling with 429-aware cooldowns

Round-robin over operator keys with capability tags. Reads 429 cooldowns from the provider's own retry headers. 401/403 quarantine with operator unlock. Seven-tier free-tier catalog with atomic refresh job.

**OWL application:** Reference pattern for OWL's `ProxyRotator` tier-sorted selection and auto-ban on 3 failures. The 429-aware cooldown pattern can inform retry/backoff behavior in `ResilientClient`.

**Do not vendor:** hermes-router key pool, quota tracking, or refresh job.

---

## 3. Immutable cost ledger

One hash-chained cost record per completion (SHA-256, optional HMAC), integer-exact micro-USD from pinned price snapshots. Virtual keys with blocking budgets (`402` before any upstream spend).

**OWL application:** Reference pattern for cost attribution if OWL later adds spend tracking. OWL's `HoneypotDetector` structural hash is a smaller analog (body-integrity hash vs. cost-record hash chain).

**Do not vendor:** hermes-router ledger, HMAC signing, or price snapshot database.

---

## 4. Cost guard (sliding-window limiters)

True sliding-window limiters in principal / pool / global scopes (requests or tokens), estimate-to-actual reconciliation, burst-smoothing pacer, billing-leak watchdog. Budgets block *before* the upstream call (`402`, not an invoice surprise).

**OWL application:** Reference pattern for OWL's `DomainRateLimiter` per-domain token bucket. The sliding-window + estimate-to-actual pattern can inform future rate-limit enhancements.

**Do not vendor:** hermes-router limiter or billing watchdog.

---

## 5. Operations plane

Zero-asset admin dashboard, six alert rules with webhook delivery, Prometheus metrics, hardened compose profile, full runbook. 32-way concurrent-stream load gate, compressed soak over the failure lattice, three end-to-end failure drills.

**OWL application:** Reference pattern for OWL's `run.sh stats` / MCP `proxy_stats` / `proxy_validate` telemetry. The alert-rules-with-webhooks pattern can inform future OWL observability.

**Do not vendor:** hermes-router dashboard, alerts, or compose profile.

---

## 6. What OWL already has (analogous, no change needed)

| hermes-router pattern | OWL equivalent |
|---|---|
| Session classification + 5-min TTL | `SessionAffinityManager` sticky `(agent_id, domain)` binding, 900s default TTL |
| Key pooling + 429 cooldown | `ProxyRotator` tier-sorted selection, auto-ban on 3 failures |
| Immutable cost ledger | `HoneypotDetector` structural body hash (integrity, not billing) |
| Sliding-window rate limits | `DomainRateLimiter` per-domain token bucket |
| Operations dashboard/metrics | `run.sh stats --json`, MCP `proxy_stats`/`proxy_rotate`/`proxy_validate` |

---

## 7. Verification gate

- [ ] Pattern memo written (this file)
- [ ] No hermes-router dependency added to `pyproject.toml` (verified: `local_model_upstreams` references are config-only, not code imports)
- [ ] No hermes-router code vendored into `proxy_defense.py`, `proxy_harvester.py`, or `mcp_proxy_server.py`

---

## ⚡ Recommended Next Step

Review this memo against `IMPLEMENTATION_PLAN.md` Stage 3 task 3.5. All Stage 3 tasks (3.1–3.5) are now complete — configuration + documentation only, no implementation code written into OWL modules.

## ✨ 3 Suggestions

- **Tactical:** Confirm `pyproject.toml` has no new dependencies from these config-only changes (`grep hermes\|bifrost\|gomodel\|portkey pyproject.toml` should return nothing).
- **Strategic:** Treat hermes-router as a reference architecture, not a dependency — OWL stays a lightweight proxy-defense layer; governance features (ledger, budgets, alerts) live in the gateway upstream if/when adopted.
- **Reframe:** The 5-tier classifier ladder is the pattern most worth borrowing for OWL's route-selection logic — classify once per session, cache the tier, re-classify only on deviation — without importing any ML code.
