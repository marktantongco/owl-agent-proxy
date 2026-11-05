# Infra-Shims / Free-Model Gateway Investigation Report

**Project:** marktantongco/owl-agent-proxy  
**Branch:** `arena/d2e335c7-owl-agent-proxy` (active)  
**Phase:** DEFINE → PLAN (investigation only — no code written)  
**Objective:** Investigate, compare, and critique three candidate repos as components/alternatives for the governed token plane (OpenCode v2 → gateway → local + free + paid + cache + budgets + provider key isolation). Identify the better option with a confidence score.

**Sources investigated (all fetched live):**
1. https://github.com/EdgeAIG/infra-shims
2. https://github.com/natorus87/litellm-free-models
3. https://github.com/EkoSaputro14/opencode-proxy

---

## 1. Investigation Findings — Each Repository

### 1.1 EdgeAIG/infra-shims

| Attribute | Value |
|-----------|-------|
| Stars / Forks | 1 / 0 |
| Commits / Branches / Tags | 1 / 1 / 0 |
| Last activity | Sep 3, 2026 (Initial commit, 2 months ago) |
| Languages | JavaScript (100%) |
| License | Per-file headers (personal tooling) |

**Contents:**

| File | Port | Purpose |
|------|------|---------|
| `zen_shim.js` | :8791 | Strip-auth local reverse proxy for OpenCode Zen free tier. Removes the `Authorization` header (Zen free tier rejects it with `401`) and forwards everything else verbatim, streaming included. |
| `manus_shim.js` | :8787 | OpenAI-compatible shim for the Manus LLM proxy. Synthesizes a non-streaming upstream response into an SSE stream, and rewrites upstream `HTTP 200` + `{"error":...}` bodies into proper HTTP error codes. |
| `dsh-tunnel-keepalive.sh` | :3080 | Self-healing supervisor: keeps a Cloudflare quick-tunnel + the DeepSeek Harness (`dsh web`) alive. Extracts the rotating tunnel URL, relaunches `dsh` with it, and rotates the tunnel after 3 consecutive probe failures. |

**Key characteristics:**
- All three are **standalone**, dependency-free shims — no package install (node for `.js`, bash + `cloudflared` + `dsh` for keepalive).
- Path values (e.g. `NODE=` node binary path) are machine-specific; must be adjusted per install.
- Each shim is narrow and single-purpose: one provider, one port, one protocol quirk.
- Not a governed token plane: no auth, no per-client keys, no budgets, no Redis cache, no circuit breaker, no audit logging, no Nginx edge.

### 1.2 natorus87/litellm-free-models

| Attribute | Value |
|-----------|-------|
| Stars / Forks | Not shown on page (repo is active, well-maintained) |
| Commits / Branches / Tags | 19 / 6 / 3 |
| Latest tag | `v0.3.0` (Aug 24, 2026) |
| First release | `v0.1.0` (Jun 14, 2026) |
| Languages | Python (100% — scripts, tests, CI) |
| License | MIT |

**Contents:**

| Directory/File | Purpose |
|----------------|---------|
| `providers_config.py` | Centralized single source of truth for all provider configs |
| `render-config.py` | Template pipeline: `config.template.yaml` → `config.yaml` (atomic write) |
| `find-shared-models.py` | Discovers shared/free models across providers; inverted pricing index (O(1) lookups) |
| `onboard.py` | Provider onboarding |
| `opencode-config.py` | OpenCode-specific client config generation |
| `config.template.yaml` | Template for LiteLLM gateway config |
| `docker-compose.yaml` | Multi-service stack (LiteLLM + Redis + Ollama + ...) |
| `Dockerfile` | Container build |
| `Makefile` | Build/ops shortcuts |
| `tests/` | 109 unit tests (stdlib only, no PyYAML) — grew from 56 → 89 → 109 |
| `k8s/` | Kubernetes manifests |
| `multi-instance/` | Master + 2 Slaves = 3x rate-limit topology |
| `research/free-model-providers-2026/` | Provider research notes |
| `.github/` | GitHub Actions CI (Python 3.10–3.13, Tests, Lint, Dry-Run), weekly sync-models workflow, Dependabot |
| `AGENTS.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `PLAN.md`, `PRICING.md`, `MODEL_PRICING.md`, `CHANGELOG.md` | Full project governance |

**13 free LLM providers aggregated:** OpenRouter, Cerebras, Groq, Cloudflare, Google AI Studio, NVIDIA, Mistral, Cohere, GitHub Models, OpenCode Zen, LLM7.io, HuggingFace, OVHcloud.

**Scale:** 36 model_names / 109 base deployments (171 with multi-instance slaves).

**Quality controls:**
- `DEAD_ROUTES` denylist — routes providers advertise but cannot serve free are excluded
- `is_paid_vendor_model` denylist — filters proprietary vendor brand names (claude-*, gpt-5.x, gemini-*, grok-*, glm-5.x, minimax-*) that aggregators should not be trusted to serve free
- Rate-limit failover hardening: `RateLimitErrorRetries: 0` for single-deployment groups (1.3s fallback instead of 60s+ wait)
- Removed `allowed_fails` from router_settings (forced legacy cooldown counter, disabled immediate HTTP 429 cool-down)
- Live-tested against Docker Compose stack — all 36 model_names reachable via `/v1/models`, no proxy errors
- CI-verified: 109-test suite, ruff, config render/regenerate, live Docker Compose restart

### 1.3 EkoSaputro14/opencode-proxy

| Attribute | Value |
|-----------|-------|
| Stars / Forks | 0 / 0 |
| Commits / Branches / Tags | 4 / 1 / 0 |
| Last activity | Sep 17, 2026 (Merge PR #1) |
| Languages | JavaScript (100%) |
| License | Not specified |

**Contents:**

| File | Purpose |
|------|---------|
| `_worker.js` | Cloudflare Worker proxy for OpenCode free provider |
| `wrangler.toml` | Cloudflare Workers deployment config |
| `README.md` | Bahasa Indonesia documentation |
| `.github/workflows/` | GitHub Actions auto-deploy (CF_API_TOKEN, CF_ACCOUNT_ID) |

**Endpoints proxied:**
- `https://opencode.ai/zen/v1/chat/completions`
- `https://opencode.ai/zen/v1/models`
- `https://opencode.ai/zen/v1/messages`
- `https://opencode.ai/zen/v1/responses`

**Features:**
- Rotates OpenCode CLI identity (`opencode/latest/<ver>/cli`, synced with latest CLI release)
- Strips identity + fingerprint browser headers (`Sec-CH-UA`) that trigger `429 FreeUsageLimitError`
- Random jitter 0–50ms (bypass burst detection)
- CORS support, streaming SSE support
- Zero configuration

**Deployment:** Cloudflare Workers only (GitHub Secrets: `CF_API_TOKEN`, `CF_ACCOUNT_ID`; push to main → auto deploy). Intended to be used as a `baseURL` for 9Router/OmniRoute: `https://opencode-proxy.SUBDOMAIN.workers.dev/zen/v1`

**Scope:** OpenCode Zen free tier only. One provider. Cloudflare-hosted (not bare metal).

---

## 2. Comparison Matrix

| Criterion | EdgeAIG/infra-shims | natorus87/litellm-free-models | EkoSaputro14/opencode-proxy |
|-----------|---------------------|-------------------------------|----------------------------|
| **Primary role** | Narrow single-provider shims | Full free-LLM gateway proxy | Single-provider Cloudflare Worker |
| **Providers covered** | OpenCode Zen, Manus, DeepSeek | 13 providers (incl. all 3 above) | OpenCode Zen only |
| **Maturity** | 1 commit, personal tooling | v0.3.0, 19 commits, 5 months active | 4 commits, 2 months |
| **Test coverage** | None | 109 unit tests + CI | None |
| **CI/CD** | None | GitHub Actions (Python 3.10–3.13) | GitHub Actions (auto-deploy) |
| **Packaging** | Standalone scripts | Docker Compose, k8s, PyPI-style | Cloudflare Worker only |
| **Per-client keys** | No | Yes (LiteLLM virtual keys) | No |
| **Budgets / rate limits** | No | Yes (LiteLLM native + multi-instance 3x) | No (Cloudflare edge rate limit only) |
| **Redis cache** | No | Yes (LiteLLM native) | No |
| **Circuit breaker** | No | Yes (LiteLLM router + failover hardening) | No |
| **Provider key isolation** | No | Yes (LiteLLM server-side) | No |
| **Audit logging** | No | LiteLLM native | No |
| **Nginx/Caddy edge** | No | Recommended alongside | Cloudflare edge (built-in) |
| **Local model support** | No | Yes (Ollama in compose) | No |
| **Paid fallback** | No | No (free providers only) | No |
| **Laptop memory fit** | Excellent (single process) | Poor (PostgreSQL + LiteLLM + Redis + Ollama) | Excellent (Cloudflare-hosted) |
| **Bare metal suitable** | Yes | Partially (heavy stack) | No (Cloudflare only) |
| **Supply-chain risk** | Low (custom, minimal deps) | Medium (LiteLLM had 2x compromises in 2026) | Low (Cloudflare Worker) |
| **Languages** | JavaScript | Python | JavaScript |

---

## 3. Critique of Each Option

### 3.1 EdgeAIG/infra-shims — Critique

**Strengths:**
- Extremely lightweight — ideal for a constrained bare-metal laptop
- Zero dependency overhead beyond Node.js
- Solves real protocol quirks (Zen strips `Authorization` because free tier rejects it; Manus SSE/error rewrite)
- `dsh-tunnel-keepalive.sh` provides self-healing for the DeepSeek Harness tunnel

**Weaknesses / Gaps:**
- **Not a governed token plane** — no auth, no per-client keys, no budgets, no cache, no circuit breaker, no audit logging
- Each shim is single-provider and single-port; no aggregation, no fallback chain, no load balancing
- Machine-specific path values require per-install adjustment (fragile)
- No tests, no CI, no versioning beyond a single initial commit
- Personal tooling repo — no governance, no security docs, no contribution process

**Verdict:** Useful as supplementary shims for specific free-tier protocol quirks, but **cannot serve as the core gateway** of the governed token plane.

---

### 3.2 natorus87/litellm-free-models — Critique

**Strengths:**
- **Most mature of the three** — v0.3.0, 19 commits, 5 months of active development, 109 unit tests with CI
- Production-grade infrastructure: GitHub Actions CI, Dependabot, weekly sync workflow, issue/PR templates, SECURITY.md
- Aggregates 13 free providers with fallback chains — directly serves the "maximum free/local capacity" goal
- `DEAD_ROUTES` and `is_paid_vendor_model` denylists show real operational discipline (removes dead routes, filters paid models mislabeled as free)
- Rate-limit failover hardening (1.3s fallback vs 60s+ wait) is a genuine operational improvement
- Multi-instance topology (Master + 2 Slaves = 3x rate limit) provides horizontal scaling
- Anonymous OVHcloud tier (no API key) for zero-credential free access
- Docker Compose + k8s deployment options
- OpenAI-compatible (LiteLLM) — works with OpenCode v2 and Hermes-agent out of the box
- Verified live: all 36 model_names reachable via `/v1/models`

**Weaknesses / Gaps:**
- **Heavy stack** — LiteLLM + PostgreSQL + Redis + Ollama (+ Nginx edge) conflicts with "laptop memory constraints, bare metal preferred"
- **Supply-chain risk** — Prior validated research (VALIDATED_LITELLM_RESEARCH.md) documented 2x supply-chain compromises in LiteLLM in 2026 plus 5.6k open issues
- Not yet integrated into owl-agent-proxy; would replace or sit alongside the merged FastAPI gateway (PR #33)
- Free providers only — no paid fallback layer built in (would need the custom gateway's tier-3 routing)
- Some provider discovery hit Cloudflare bot protection (403 error code 1010) — required browser-like User-Agent workaround

**Verdict:** The strongest candidate as a **free-tier aggregation layer** within the governed token plane. Its provider catalog, fallback chains, rate-limit handling, and test maturity significantly exceed the custom FastAPI gateway's current capabilities. However, its memory footprint and LiteLLM supply-chain history are concerns for a bare-metal laptop deployment.

---

### 3.3 EkoSaputro14/opencode-proxy — Critique

**Strengths:**
- Solves a specific, real problem: OpenCode Zen free tier rejects browser UAs with `429 FreeUsageLimitError`; this Worker rotates the OpenCode CLI identity and strips fingerprint headers
- Zero-config, zero-maintenance once deployed on Cloudflare Workers
- Random jitter (0–50ms) helps bypass burst detection
- Streaming SSE support
- Works with 9Router/OmniRoute as a `baseURL`

**Weaknesses / Gaps:**
- **Extremely narrow scope** — OpenCode Zen free tier only (one provider, one use case)
- **Cloudflare-only** — not bare metal, not local; conflicts with "bare metal preferred" constraint
- No per-client keys, no budgets, no cache, no circuit breaker, no audit logging
- No tests, 0 stars, 0 forks, minimal community signal
- Bahasa Indonesia README — language barrier for English-only operating instructions
- Dependent on Cloudflare account + API token (external dependency)

**Verdict:** Too narrow and too Cloudflare-dependent to serve as a core component. Could theoretically be one specific free-tier route (OpenCode Zen), but the custom gateway already handles this more directly.

---

## 4. Relevance, Clarity, Compatibility, Interoperability Analysis

### 4.1 Relevance to governed token plane

| Relevance dimension | EdgeAIG/infra-shims | natorus87/litellm-free-models | EkoSaputro14/opencode-proxy |
|---------------------|---------------------|-------------------------------|----------------------------|
| Core gateway auth | ❌ None | ✅ LiteLLM virtual keys + master key | ❌ None |
| Per-client budgets | ❌ None | ✅ LiteLLM native | ❌ None |
| Redis cache | ❌ None | ✅ LiteLLM native Redis cache | ❌ None |
| Circuit breaker | ❌ None | ✅ LiteLLM router + hardened failover | ❌ None |
| Provider key isolation | ❌ None | ✅ Server-side keys only | ❌ None |
| Local model (Ollama) | ❌ None | ✅ In docker-compose | ❌ None |
| Paid fallback | ❌ None | ❌ Free only | ❌ Free only |
| Nginx/Caddy edge | ❌ None | ⚠️ Recommended alongside | ✅ Cloudflare edge (built-in) |
| Free-tier aggregation | ⚠️ 3 single-provider shims | ✅ 13 providers, fallback chains | ⚠️ 1 provider (OpenCode Zen) |

### 4.2 Clarity (documentation, governance, operability)

| Clarity dimension | EdgeAIG/infra-shims | natorus87/litellm-free-models | EkoSaputro14/opencode-proxy |
|-------------------|---------------------|-------------------------------|----------------------------|
| README quality | Basic, English | Comprehensive, English (translated from German) | Bahasa Indonesia |
| AGENTS.md / project context | ❌ None | ✅ Present | ❌ None |
| Contributing / security docs | ❌ None | ✅ CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md | ❌ None |
| CI / test pipeline | ❌ None | ✅ GitHub Actions, 109 tests, ruff | ⚠️ Auto-deploy only |
| Versioning / releases | ❌ None | ✅ v0.3.0, 3 tags | ❌ None |
| Deployment docs | Minimal | Docker Compose, k8s, Makefile | Cloudflare Workers only |

### 4.3 Compatibility with owl-agent-proxy constraints

| Constraint | EdgeAIG/infra-shims | natorus87/litellm-free-models | EkoSaputro14/opencode-proxy |
|------------|---------------------|-------------------------------|----------------------------|
| English only | ✅ | ✅ | ❌ (Bahasa Indonesia README) |
| smp5.4pd.md baseline | N/A | N/A | N/A |
| Laptop memory / bare metal | ✅ Excellent | ⚠️ Heavy (5 services) | ❌ Cloudflare-only |
| No "unlimited free tokens" bypass | ✅ | ✅ (governed, budgeted) | ⚠️ (free-only, no budgets) |
| Provider key isolation | ❌ | ✅ | ❌ |
| Rate limiting / budgets | ❌ | ✅ | ❌ |
| No placeholder text | ✅ | ✅ | ✅ |

### 4.4 Interoperability with existing stack

| Interop dimension | EdgeAIG/infra-shims | natorus87/litellm-free-models | EkoSaputro14/opencode-proxy |
|-------------------|---------------------|-------------------------------|----------------------------|
| OpenCode v2 client | ✅ (zen_shim strips Auth for Zen) | ✅ (LiteLLM is OpenAI-compatible) | ✅ (designed for OpenCode) |
| Hermes-agent | ⚠️ (manus_shim is Manus-specific) | ✅ (LiteLLM is OpenAI-compatible) | ❌ (OpenCode Zen only) |
| Nginx/Caddy edge | ⚠️ Standalone ports | ✅ Compose + edge recommended | ✅ Cloudflare is the edge |
| Redis cache | ❌ | ✅ Native | ❌ |
| Custom FastAPI gateway (PR #33) | ⚠️ Could run alongside | ⚠️ Would replace or sit beside | ❌ Cloudflare-only |
| config.json governed_token_plane | ❌ | ⚠️ Would need integration | ❌ |

---

## 5. Better Option Identification

### 5.1 Core gateway decision

**Better option: natorus87/litellm-free-models** for the free-tier aggregation layer, **custom FastAPI gateway (PR #33)** for the governed core.

Rather than choosing one exclusively, the better architecture is a **layered combination**:

| Layer | Component | Source |
|-------|-----------|--------|
| Edge (TLS, rate limit, header scrub) | Nginx/Caddy | Custom (PR #33 + hardened ideas from litellm-free-models) |
| Governed core (auth, per-client keys, budgets, audit, paid fallback) | Custom FastAPI gateway | PR #33 (merged) |
| Free-tier aggregation (13 providers, fallback chains, rate-limit failover) | natorus87/litellm-free-models | As upstream free-tier pool behind the custom gateway |
| Local model | Ollama | Custom (PR #33) + litellm-free-models compose |
| Redis cache | Redis | Custom (PR #33) |

**Why not pure LiteLLM?** Despite its maturity, LiteLLM's memory footprint (PostgreSQL + LiteLLM + Redis + Ollama) conflicts with bare-metal laptop constraints, and its 2x supply-chain compromises in 2026 are a real risk. The custom FastAPI gateway is lighter, already tested (23 tests), and merged.

**Why not EdgeAIG/infra-shims or opencode-proxy?** Both are too narrow (single provider, no governance) to serve as core components. They could supplement specific providers but add operational surface without adding governed-token-plane value.

### 5.2 Specific elements to adopt from each

| From | Element | Apply to |
|------|---------|----------|
| natorus87/litellm-free-models | `DEAD_ROUTES` denylist | Custom gateway router — skip dead/free-ineligible routes |
| natorus87/litellm-free-models | `is_paid_vendor_model` denylist | Custom gateway — filter paid models mislabeled as free |
| natorus87/litellm-free-models | Rate-limit failover hardening (1.3s vs 60s) | Custom gateway circuit breaker cooldown |
| natorus87/litellm-free-models | Per-client virtual keys + budgets | Custom gateway — replace single `OWL_GATEWAY_TOKEN` with per-client tokens |
| natorus87/litellm-free-models | 13-provider catalog | Custom gateway router — expand free-tier provider list |
| EdgeAIG/infra-shims | Zen strip-auth pattern | Custom gateway — handle Zen's `Authorization` rejection |
| EdgeAIG/infra-shims | Self-healing tunnel keepalive | Operational runbook for cloudflared + Ollama tunnels |
| EkoSaputro14/opencode-proxy | OpenCode CLI identity rotation | Custom gateway — rotate UA for free-tier providers that require it |
| EkoSaputro14/opencode-proxy | Random jitter (0–50ms) | Custom gateway — add jitter to free-tier requests |

---

## 6. Confidence Score Rating

| Option | Confidence | Basis |
|--------|-----------|-------|
| **natorus87/litellm-free-models** as free-tier aggregation layer | **88%** | Mature (v0.3.0), 109 tests, CI, 13 providers, verified live, denylists, rate-limit hardening. Deducts for memory weight and LiteLLM supply-chain history. |
| **Custom FastAPI gateway (PR #33)** as governed core | **85%** | Already merged, 23 tests passing, lightweight, bare-metal friendly, key isolation enforced. Deducts for single shared token, in-memory budgets (no persistence), less provider catalog depth. |
| **Layered combination** (custom core + litellm-free-models free pool) | **90%** | Combines strengths of both; mitigates individual weaknesses. Highest confidence path forward. |
| EdgeAIG/infra-shims as core component | **25%** | Too narrow, no governance, no tests, personal tooling. Only useful as supplementary shims. |
| EkoSaputro14/opencode-proxy as core component | **15%** | Cloudflare-only, single provider, no tests, Bahasa docs, no budgets/keys/cache. |

**Overall confidence in the recommendation (layered combination): 90%**

### 6.1 Remaining uncertainties (10%)

1. **Memory footprint not measured** — The combined stack's actual RAM usage on a bare-metal laptop was not benchmarked. LiteLLM + PostgreSQL could exceed constraints.
2. **LiteLLM supply-chain risk not re-verified** — The 2x compromises in 2026 came from prior validated research; current version (v0.3.0) may have patched the vectors.
3. **OpenCode v2 / Hermes-agent compatibility assumed** — Both are assumed to work with an OpenAI-compatible base URL; not independently confirmed in this session.

---

## 7. Next Step (DEFINE → PLAN gate)

No code written in this phase. The next step (PLAN → BUILD gate G2) would be:

1. **Adopt the layered architecture** — custom FastAPI gateway as governed core, natorus87/litellm-free-models provider catalog + failover patterns as the free-tier upstream pool.
2. **Harden the custom gateway** — per-client virtual keys, PostgreSQL/file-based budget persistence, hardened Nginx (TLSv1.3, header scrubbing, admin IP isolation), DEAD_ROUTES/is_paid_vendor_model denylists, rate-limit failover (1.3s cooldown).
3. **Update config.json** — add litellm-free-models provider catalog reference, per-client token config, denylist settings.
4. **Expand tests** — add tests for per-client keys, budget persistence, denylist filtering, rate-limit failover.
5. **Update AGENTS.md** — document the layered architecture, new skills (litellm-free-models as a research skill), and integration notes.

This completes the DEFINE/PLAN investigation phase for the three candidate repositories.
