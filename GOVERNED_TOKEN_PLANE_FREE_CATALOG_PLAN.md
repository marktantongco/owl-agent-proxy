# Governed Token Plane — Free Catalog Integration Plan (PLAN→BUILD)

**Project:** marktantongco/owl-agent-proxy  
**Branch:** `arena/d2e335c7-owl-agent-proxy` (active)  
**Phase:** PLAN → BUILD (per smp5.4pd.md: DEFINE→PLAN→BUILD→VERIFY→REVIEW→SHIP)  
**Objective:** Integrate `marktantongco/awesome-free-llm-apis` as the free-tier upstream catalog for the governed token plane gateway (custom FastAPI gateway, PR #33, merged to `main`).

**Source investigated:** https://github.com/marktantongco/awesome-free-llm-apis  
- 162 commits, latest Nov 4, 2026 (yesterday), actively maintained
- `data.json`: 38,262 bytes, structured provider+model catalog (base64 via API)
- 15 providers: 5 Provider APIs (vendor-run) + 10 Inference Providers (third-party)
- All OpenAI-compatible base URLs
- English README with rate limits, context windows, modalities, footnotes

---

## Silent Layer — What is actually being asked

| Question | Answer |
|---|---|
| **Actual need** | Populate the gateway's "free cloud" tier (tier 2) with a curated, verified catalog of free LLM APIs instead of hardcoding just OpenAI |
| **Blind spot** | `awesome-free-llm-apis` is a catalog, not a gateway. It provides provider metadata (base URLs, rate limits, models) but no auth, routing, caching, or budget enforcement |
| **Irreducible truth** | The catalog must be vendored + loaded into the gateway router; the gateway still owns provider keys, budgets, circuit breaking, and audit logging |

---

## Mode Selection (per smp5.4pd.md)

**Depth mode** (catalog excavation — 15 providers, rate limits, quirks, footnotes) routed through **Strategy mode** (long-term maintenance: catalog drift, dead routes, provider deprecation).

Sequential workflow: Discovery → Brainstorm → Research → Plan → Execute → Validate → Review → Complete.

---

## Layer 1: DEFINE — Discover & Research

### awesome-free-llm-apis provider catalog

#### Provider APIs (vendor-run, train/fine-tune models)

| # | Provider | Country | Base URL | Rate Limit | Models |
|---|----------|---------|----------|------------|--------|
| 1 | Aion Labs | 🇮🇱 IL | `https://api.aionlabs.ai/v1` | 15 RPM, 20K TPD | aion-2.0, aion-rp-llama-3.1-8b, aion-3.0, aion-3.0-mini |
| 2 | Cohere | 🇨🇦 CA | `https://api.cohere.com/v2` (native) / `https://api.cohere.ai/compatibility/v1` (OpenAI) | 1,000 calls/mo, 20 RPM | Command A+, A, R+, R, R7B, Reasoning, Translate, Vision, Aya Expanse 32B, Aya Vision 32B |
| 3 | Google Gemini | 🇺🇸 US | `https://generativelanguage.googleapis.com/v1beta` (native) / `.../v1beta/openai/` (OpenAI) | No published limits | Gemini 3.8/3.6/3.5/3.1/2.5 Flash, Flash-Lite, Gemma 4 31B, 26B A4B |
| 4 | Mistral AI | 🇫🇷 FR | `https://api.mistral.ai/v1` | ~1 RPS, 500K TPM | Medium 3.5, Small 4, Large 3, Ministral 3 8B/3B/14B, Codestral |
| 5 | Z AI (Zhipu AI) | 🇨🇳 CN | `https://open.bigmodel.cn/api/paas/v4` | 1 concurrent request | GLM-4.7-Flash, GLM-4.5-Flash (retired), GLM-4.6V-Flash |

#### Inference Providers (third-party, open-weight models)

| # | Provider | Country | Base URL | Rate Limit | Notable Models |
|---|----------|---------|----------|------------|---------------|
| 6 | Cloudflare Workers AI | 🇺🇸 US | `https://api.cloudflare.com/client/v4/accounts/{id}/ai/v1` | 10K neurons/day shared | llama-3.3-70b, llama-4-scout, gpt-oss-120b, gemma-4-26b, glm-4.7-flash, mistral-small-3.1, deepseek-r1-distill-qwen-32b + 55 more |
| 7 | Gonka Broker | 🇺🇸 US | `https://proxy.gonkabroker.com/v1` | ~1M tokens/mo shared, phone verification | MiniMax-M2.7, DeepSeek-V4-Flash, GLM-5.3-Flash, BGE-M3 |
| 8 | Groq | 🇺🇸 US | `https://api.groq.com/openai/v1` | 30 RPM, 1,000 RPD | gpt-oss-120b, gpt-oss-20b, qwen3.8-27b |
| 9 | Kilo Code | 🇺🇸 US | `https://api.kilo.ai/api/gateway` | 200 req/hr, no key | nemotron-3-ultra-550b, nemotron-3-nano-omni, north-mini-code, kilo-auto/free router + more |
| 10 | LLM7.io | 🇬🇧 UK | `https://api.llm7.io/v1` | 60 RPM, 250 req/hr (free token) | gpt-oss:20b, mistral-Nemo, nemotron-3-nano:30b, codestral-latest |
| 11 | ModelScope | 🇨🇳 CN | `https://api-inference.modelscope.cn/v1` | 2,000 RPD total, <=500 RPD/model | Qwen3.5-35B-A3B, Qwen3.5-27B + more (real-name verification, mainland China) |
| 12 | NVIDIA NIM | 🇺🇸 US | `https://integrate.api.nvidia.com/v1` | 40 RPM, 10,000 RPD | gemma-4-31b-it, nemotron-3-ultra-550b, gpt-oss-20b + 92 more (NVIDIA Developer Program) |
| 13 | OpenRouter | 🇺🇸 US | `https://openrouter.ai/api/v1` | 20 RPM, 50 RPD (free models) | cohere/north-mini-code:free, google/gemma-4-*:free, liquid/lfm-2.5-2.6b:free, nvidia/nemotron-*:free + 17 free models |
| 14 | OVHcloud AI Endpoints | 🇫🇷 FR | `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1` | 2 RPM anonymous/IP/model | Qwen3.5-397B-A17B, gpt-oss-120b, gpt-oss-20b, Llama-3.3-70B, Qwen3.* variants, Mistral-Small-3.2-24B |
| 15 | SiliconFlow | 🇨🇳 CN | `https://api.siliconflow.cn/v1` | Identity verification (mainland China docs) | Hunyuan-MT-7B, Xing4.0-29B |

### Skill gaps identified vs. catalog

| Skill | Role in this integration | Status |
|-------|-------------------------|--------|
| github-researcher | Audit provider repos for staleness, API changes, rate limit drift | To be applied |
| parallel-deep-research | Verify provider free-tier claims, cross-check rate limits | To be applied |
| brainstorm | Ideate catalog-to-router mapping strategies | To be applied |
| orchestrate | Coordinate multi-stage integration (load → map → route → test) | To be applied |
| deep-analysis | Analyze rate limit patterns, cost estimates, fallback ordering | To be applied |
| deep-dive | Examine provider-specific quirks (auth headers, streaming, error formats) | To be applied |
| review | devils-advocate challenge of catalog assumptions | To be applied |
| validate | Test catalog loading, route selection, rate limit mapping | To be applied |
| test | Unit tests for catalog integration | To be applied |

---

## Layer 2: PLAN — Plan & Architect

### Design decisions

| Decision | Rationale |
|----------|-----------|
| **Vendor the catalog** | Copy `data.json` (or a filtered subset) into the repo as `gateway/free_catalog/providers.json` — avoids runtime network dependency, works on bare metal |
| **Catalog loader module** | `gateway/free_catalog/loader.py` — loads and validates the vendored catalog, converts to `ModelRoute` objects |
| **Tier 2 expansion** | Replace the single hardcoded OpenAI free route with all 15 providers from the catalog, each as a `ModelRoute` with tier=2 |
| **Provider key env vars** | Each provider's API key lives in gateway env (e.g. `OPENROUTER_API_KEY`, `GROQ_API_KEY`) — never sent to clients |
| **Rate limit mapping** | Catalog rate limits (RPM/RPD/TPM) inform the gateway's per-provider circuit breaker thresholds |
| **Dead route filtering** | Apply `is_paid_vendor_model` and `DEAD_ROUTES` concepts from litellm-free-models investigation — filter providers that can't actually serve free |
| **No "unlimited free tokens"** | Catalog is governed: per-provider rate limits, circuit breakers, client budgets still enforced |

### Files to create/modify

| File | Action | Purpose |
|------|--------|---------|
| `gateway/free_catalog/__init__.py` | Create | Package marker |
| `gateway/free_catalog/providers.json` | Create | Vendored catalog (subset of data.json, provider+model metadata) |
| `gateway/free_catalog/loader.py` | Create | Load catalog, validate, convert to `ModelRoute` list |
| `gateway/free_catalog/router_integration.py` | Create | Wire catalog routes into the `Router` class |
| `gateway/router.py` | Modify | Accept catalog routes, tier-2 expansion, per-provider rate limit mapping |
| `config.json` | Modify | Add `free_catalog` section with provider enable/disable, key env var names |
| `tests/test_free_catalog.py` | Create | Unit tests: catalog loading, route conversion, rate limit mapping, provider selection |
| `AGENTS.md` | Modify | Document free catalog integration, provider list, config |

### Router integration design

The existing `Router` class (PR #33) has:
- `routes: Dict[str, List[ModelRoute]]` — task_type → routes
- `route(task_type, client_budget_tokens_remaining, client_cost_remaining_usd, circuit_breaker_available)` → `RouteDecision`
- Default tiers: tier 1 (local Ollama), tier 2 (OpenAI free), tier 3 (Anthropic paid)

**New design:**
- Tier 1: Local Ollama (unchanged, free, hardware cost only)
- Tier 2: Free cloud providers from awesome-free-llm-apis catalog (expanded from 1 to 15 providers)
- Tier 3: Paid fallback (unchanged, Anthropic/OpenAI paid)

**Route selection logic within tier 2:**
1. Filter by circuit breaker availability (skip open circuits)
2. Filter by client cost budget remaining (skip if $0 remaining)
3. Select by cost-per-1K-tokens ascending (cheapest free first)
4. Fall through to tier 3 if all tier 2 circuits are open or budget exhausted

### config.json changes

```json
{
  "governed_token_plane": {
    "free_catalog": {
      "enabled": true,
      "source": "marktantongco/awesome-free-llm-apis",
      "vendored_file": "gateway/free_catalog/providers.json",
      "providers": {
        "openrouter": { "enabled": true, "api_key_env": "OPENROUTER_API_KEY" },
        "groq": { "enabled": true, "api_key_env": "GROQ_API_KEY" },
        "cloudflare_workers_ai": { "enabled": true, "api_key_env": "CLOUDFLARE_API_TOKEN" },
        "ovhcloud": { "enabled": true, "api_key_env": null },
        "llm7": { "enabled": true, "api_key_env": "LLM7_API_KEY" },
        "kilo_code": { "enabled": true, "api_key_env": null },
        "nvidia_nim": { "enabled": true, "api_key_env": "NVIDIA_API_KEY" },
        "mistral": { "enabled": true, "api_key_env": "MISTRAL_API_KEY" },
        "gemini": { "enabled": true, "api_key_env": "GEMINI_API_KEY" },
        "cohere": { "enabled": true, "api_key_env": "COHERE_API_KEY" },
        "aion_labs": { "enabled": true, "api_key_env": "AION_API_KEY" },
        "z_ai": { "enabled": false, "api_key_env": "Z_AI_API_KEY" },
        "gonka_broker": { "enabled": false, "api_key_env": "GONKA_API_KEY" },
        "modelscope": { "enabled": false, "api_key_env": "MODELSCOPE_API_KEY" },
        "siliconflow": { "enabled": false, "api_key_env": "SILICONFLOW_API_KEY" }
      },
      "default_cost_per_1k_tokens": 0.0,
      "dead_routes_denylist": [],
      "is_paid_vendor_model_denylist": ["claude-*", "gpt-5.x", "gemini-*", "grok-*", "glm-5.x", "minimax-*"]
    }
  }
}
```

Rationale for enable/disable:
- **Enabled by default**: openrouter, groq, cloudflare_workers_ai, ovhcloud, llm7, kilo_code, nvidia_nim, mistral, gemini, cohere, aion_labs — no special verification requirements, widely accessible
- **Disabled by default**: z_ai, gonka_broker, modelscope, siliconflow — require phone verification, real-name verification, or mainland-China docs; operator must opt in

### Decision gates

| Gate | From → To | Condition |
|------|-----------|-----------|
| G1 | DEFINE → PLAN | Catalog audited, 15 providers mapped, enable/disable decided |
| G2 | PLAN → BUILD | This plan approved, router integration designed, test cases defined |
| G3 | BUILD → VERIFY | Catalog loader implemented, routes integrated, tests pass |
| G4 | VERIFY → REVIEW | All tests pass, key isolation verified, no provider keys leaked |
| G5 | REVIEW → SHIP | Code reviewed, impeccable quality gate, docs updated |
| G6 | SHIP → Complete | Branch merged, deployment guide updated |

---

## Layer 3: BUILD — Execute (planned, not yet started)

### Implementation order

1. **Create `gateway/free_catalog/` package** — `__init__.py`, `providers.json`, `loader.py`
2. **Implement `loader.py`** — JSON loading, validation, `ModelRoute` conversion
3. **Modify `router.py`** — Accept catalog routes, tier-2 expansion, rate limit mapping to circuit breaker
4. **Create `router_integration.py`** — Wire catalog into `Router.__init__` and `route()`
5. **Update `config.json`** — Add `free_catalog` section
6. **Create `tests/test_free_catalog.py`** — Unit tests for all new functionality
7. **Update `AGENTS.md`** — Document integration

### Skill application during build

| Stage | Skill | Application |
|-------|-------|-------------|
| DEFINE | github-researcher | Audit provider repos for API staleness |
| DEFINE | parallel-deep-research | Verify free-tier claims across providers |
| PLAN | brainstorm | Catalog-to-router mapping strategies |
| PLAN | orchestrate | Coordinate load → map → route → test stages |
| PLAN | deep-analysis | Rate limit patterns, cost estimates, fallback ordering |
| PLAN | deep-dive | Provider-specific quirks (auth, streaming, error formats) |
| BUILD | writing-plans | Detailed implementation with checkpoints |
| BUILD | systematic-debugging | Debug catalog loading/routing issues |
| REVIEW | devils-advocate | Challenge "free catalog" assumptions, dead route risks |
| REVIEW | impeccable | Quality audit of catalog integration code |
| VERIFY | test | Unit tests for catalog loading, route selection |
| VERIFY | systematic-debugging | Debug test failures |

---

## Layer 4: VERIFY — Test & Validate (planned)

| Check | Method | Expected |
|-------|--------|----------|
| Catalog loading | Unit test: `providers.json` parses, 15 providers | All providers loaded, no crashes |
| Route conversion | Unit test: each provider → `ModelRoute` with correct tier/base_url/key_env | Correct field mapping |
| Rate limit mapping | Unit test: catalog RPM/RPD → circuit breaker threshold | Thresholds derived from catalog |
| Provider selection | Unit test: `route()` picks cheapest available tier-2 provider | Correct provider selected |
| Dead route filtering | Unit test: denylisted models excluded from routes | No paid vendor models in routes |
| Budget gating | Unit test: $0 cost remaining → skip non-local tier-2 routes | Falls back to local or tier 3 |
| Key isolation | Integration test: client request contains no provider keys | Keys only in gateway env |
| Full suite | `pytest tests/ -q` | All tests pass, 0 failed |

---

## Layer 5: REVIEW — Challenge & Quality (planned)

| Reviewer | Focus |
|----------|-------|
| devils-advocate | Challenge catalog assumptions: dead routes, rate limit drift, provider TOS changes |
| impeccable | Audit: code quality, no placeholder text, English only, test coverage |
| Caveman | Confirm simplest catalog loader — no unnecessary abstraction |
| deep-dive | Verify provider-specific auth header quirks are handled |

---

## Layer 6: SHIP — Merge & Release (planned)

1. Commit changes to branch
2. Push to origin `arena/d2e335c7-owl-agent-proxy`
3. Open PR on GitHub
4. Merge PR into `main`
5. Update AGENTS.md with architecture docs
6. Publish updated deployment guide

---

## Relevance, Clarity, Compatibility, Interoperability

### Relevance to governed token plane

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Free-tier capacity | High | 15 providers, 100+ free models, directly serves "maximum free/local capacity" |
| Provider key isolation | High | Keys in gateway env only, never sent to clients |
| Budget/governance | High | Catalog rate limits feed circuit breakers; client budgets still enforced |
| Local-first | High | Tier 1 (Ollama) unchanged; catalog is tier 2 (burst only) |

### Clarity

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Documentation | High | English README with rate limits, footnotes, provider details |
| Data structure | High | `data.json` is structured, versioned (last updated 2026-10-25) |
| Governance | Medium | 0 stars/forks, but 162 commits and daily syncs |

### Compatibility with owl-agent-proxy constraints

| Constraint | Rating | Notes |
|------------|--------|-------|
| English only | High | README and data are in English |
| smp5.4pd.md baseline | High | Plan follows DEFINE→PLAN→BUILD→VERIFY→REVIEW→SHIP |
| Laptop memory / bare metal | High | Vendored JSON + Python loader, no extra services |
| No "unlimited free tokens" | High | Catalog is governed, not a bypass |
| Provider key isolation | High | Gateway owns all keys |
| Rate limiting / budgets | High | Catalog limits → circuit breaker thresholds |

### Interoperability with existing stack

| Component | Rating | Notes |
|-----------|--------|-------|
| OpenCode v2 client | High | OpenAI-compatible base URLs from catalog |
| Hermes-agent | High | OpenAI-compatible, works with gateway |
| Nginx/Caddy edge | High | Unchanged, sits in front of gateway |
| Redis cache | High | Unchanged, caches responses regardless of provider |
| Custom FastAPI gateway (PR #33) | High | Router class designed for extensible route tables |
| config.json governed_token_plane | High | New `free_catalog` section added |

---

## Confidence Score Rating

| Option | Confidence | Basis |
|--------|-----------|-------|
| Integrate awesome-free-llm-apis as free-tier catalog | **92%** | Actively maintained (162 commits, Nov 2026), structured data.json, 15 providers, OpenAI-compatible, English docs, bare-metal friendly |
| Use catalog as-is without vendoring | **45%** | Runtime network dependency, catalog drift risk, no offline capability |
| Replace custom gateway with LiteLLM + catalog | **30%** | Memory footprint conflicts with laptop constraints, LiteLLM supply-chain history |

**Overall confidence: 92%** — remaining uncertainty is catalog drift over time (mitigated by vendoring + periodic re-sync) and provider-specific auth quirks (mitigated by deep-dive testing).

---

## Next Step (PLAN → BUILD gate G2)

Execute Layer 3 (BUILD):
1. Create `gateway/free_catalog/` package with `providers.json` (vendored catalog) and `loader.py`
2. Modify `gateway/router.py` for catalog route integration
3. Create `gateway/free_catalog/router_integration.py`
4. Update `config.json` with `free_catalog` section
5. Create `tests/test_free_catalog.py`
6. Update `AGENTS.md`

No code written yet — this document IS the plan gate. Ready for BUILD execution.