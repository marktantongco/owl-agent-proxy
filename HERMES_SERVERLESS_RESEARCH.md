# HERMES-SERVERLESS-FREE-UNLIMITED — Research & Adoption Analysis

## Repository Summary

| Field | Value |
|-------|-------|
| URL | https://github.com/saad-pie/hermes-serverless-free-unlimited |
| Name | Antigravity AI Gateway |
| Language | Node.js (Express) + vanilla JS frontend |
| License | **None found** (no LICENSE file in repo) |
| Stars | 0 | Forks | 0 | Watchers | 0 |
| Commits | 53 | Last commit | Oct 3, 2026 |
| Deployed at | antigravity-seven-delta.vercel.app |
| Local port | 3000 (`node server.js`) |

## What It Does

A serverless-first OpenAI-compatible LLM proxy that load-balances across multiple free/low-cost providers with in-response failover. Designed for Vercel Edge Runtime but runs locally with `node server.js`.

### Providers Supported

| Provider | Env Keys | Key Pattern | Notes |
|----------|----------|-------------|-------|
| OpenRouter | `OPENROUTER_API_KEY` | single key | Primary stable tier, free models only (`:free` suffix) |
| Google Gemini | `GEMINI_API_KEY`, `GEMINI_KEYS_POOL`, `Key_1`–`Key_100` | up to 100+ keys | Multi-key pool, cycles on 429/403 |
| Unorouter | `Key_101`–`Key_105` | 5 keys | Fallback provider |
| AIHubMix | `Key_106`–`Key_111` | 6 keys | Fallback provider |
| OSAII | `Key_112` | 1 key | Fallback provider |
| Atria | `Key_113` / `ATRIA_API_KEY` | 1 key | Vision + text |
| JankRouter | none | — | No-key provider (`jankrouter.waifly.com`) |
| FreeAIXYZ | none | — | No-key provider (`freeaixyz4all.vercel.app`) |

### Endpoints

- `POST /v1/chat/completions` — OpenAI-compatible chat, with model-based routing + failover
- `GET /v1/models` — Live catalog discovery (refreshes every 3.5 min), reports per-provider live status
- `GET /health` — Health check
- `GET /models`, `/playground`, `/docs` — Static HTML pages

### Routing Behavior

1. Loads live catalog from all providers (3.5 min TTL)
2. Classifies requested model against known patterns
3. Builds ordered target list based on model type (vision → Gemini/Atria; text → provider match order)
4. Tries targets sequentially until one returns 200
5. On total failure: returns HTTP 502 with `error.type: all_upstreams_failed` + attempt trace
6. Sets `X-Antigravity-Target`, `X-Antigravity-Requested-Model`, `X-Antigravity-Attempts` headers

### Honesty Probe

`scripts/honesty-probe.sh` — sends a unique sentinel token to each model, reports OK/SUBSTITUTED/NO_SENTINEL/CANNED_FALLBACK/PARSE_FAIL verdicts. Detects model substitution and proxy drift.

## Constraint Compliance (OWL standing instructions)

| Constraint | Status | Notes |
|------------|--------|-------|
| No autologin/autoclaw | ✅ Pass | No autologin or autoclaw in code |
| No glm/z.ai | ✅ Pass | glm/z.ai not used as provider (glm-5.3-flash appears only in honesty probe test models, not as an upstream) |
| No ai-gateway-complete | ✅ Pass | Different repo entirely |
| Memory-constrained laptop | ⚠️ Partial | Node.js + Express is heavier than OWL's Python stdlib core (~70 npm packages), but runs as a single bare-metal process — no Docker needed |
| Bare metal preferred | ✅ Pass | `node server.js`, no containers |
| No placeholder text | N/A | Research phase — no code written yet |

## Can It Be Merged Into OWL?

**No — not directly.** Reasons:

1. **Language mismatch**: hermes-serverless-free-unlimited is Node.js/Express; OWL is Python. Cannot be vendored into OWL's codebase.
2. **No LICENSE**: No license file means unclear redistribution/merging rights. Adopting code from an unlicensed repo is legally risky.
3. **Architecture mismatch**: OWL is a proxy defense stack (cache→dedupe→ratelimit→proxy-select→protocol-router) with optional LLM routing. hermes-serverless-free-unlimited is a standalone LLM gateway server. They serve different layers.

## How It Can Be Integrated With OWL

**As an external LLM upstream**, not as merged code:

```
OWL ResilientClient (LLM routing)
  ├── colibri:8000/v1 (primary, local, no GPU)
  ├── FreeRide:11343/v1 (failover, free-tier)
  └── hermes-serverless:3000/v1 (optional upstream, multi-key pool)
```

### Integration Points

1. **OWL `local_model_upstreams` config**: Add `hermes-serverless` as an upstream with `base_url: http://localhost:3000/v1`
2. **OWL LLM failover**: If colibri and FreeRide are down, route to hermes-serverless which has its own multi-provider failover (OpenRouter → Gemini → Unorouter → ...)
3. **Multi-key pattern**: OWL could adopt the Key_1–Key_N pooling concept for its own upstream key management
4. **Honesty probe**: OWL could borrow the sentinel-token probe pattern to validate upstream honesty (detect model substitution)

### Values from hermes-serverless-free-unlimited worth borrowing

| Pattern | OWL Application |
|---------|-----------------|
| Multi-key pool (Key_1…Key_100) | OWL upstream key rotation for rate-limit avoidance |
| Live catalog discovery (3.5 min TTL) | OWL upstream health/model refresh |
| In-response failover with attempt tracing | OWL `_request_llm` already does this; could add `X-Attempts`-style header |
| Honesty probe with sentinel tokens | OWL upstream validation / honeypot detection extension |
| Per-provider live status reporting | OWL `get_stats()` already covers this |

## Verdict

**Adapt (do not merge, do not vendor)**

- Use as an **external upstream** for OWL's LLM routing (`localhost:3000/v1`)
- **Borrow patterns**: multi-key pooling, live catalog, honesty probe, attempt tracing headers
- **Do not vendor**: Node.js ≠ Python, no LICENSE, different architectural layer
- **Do not adopt as primary gateway**: OWL already has FreeRide v3 as local upstream and hermes-router as the production gateway reference

## Installation & Usage

```bash
# Clone
git clone https://github.com/saad-pie/hermes-serverless-free-unlimited.git
cd hermes-serverless-free-unlimited

# Install
npm install

# Configure keys (at minimum OPENROUTER_API_KEY or GEMINI_API_KEY)
cp .env.example .env
# Edit .env with your keys

# Run
PORT=3000 node server.js

# Test
curl http://localhost:3000/health
curl http://localhost:3000/v1/models
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"hello"}]}'
```

## Next Steps (if user wants integration)

1. Add `hermes-serverless` to OWL's `local_model_upstreams` config in `~/.owl-agent/config/config.json`
2. Test end-to-end: OWL → hermes-serverless → OpenRouter/Gemini
3. Consider adding a honesty-probe-style validation to OWL's `proxy_validate` tool