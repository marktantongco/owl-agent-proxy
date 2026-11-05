# Governed Token Plane — Skill Audit & Implementation Plan

**Project:** marktantongco/owl-agent-proxy  
**Branch:** `arena/0866387c-owl-agent-proxy`  
**Base commit:** `53ceb042e3bd10cbe2caf6fe993707a6fb2f2e6a` (main) + PR #32 merge  
**Operating instructions:** smp5.4pd.md (Tactical Merge) — Mode: 🦉 Depth + 🦅 Strategy  
**Objective:** Define, audit, and sequence every skill before writing code. Build a governed token plane per Marky's recommendation: OpenCode v2 → gateway token → Nginx/Caddy edge → 9Router/LiteLLM gateway → local models + free tiers + paid fallback + Redis cache. Clients never see provider keys.

---

## Silent Layer — What is actually being asked

| Question | Answer |
|---|---|
| **Actual need** | Stop treating reverse proxy as "unlimited free tokens." Build a governed token plane: central gateway with auth, rate limiting, key isolation, model routing, caching, budgets, fallback chains. |
| **Blind spot** | A reverse proxy only routes/authenticates/rate-limits/caches/hides keys — it does NOT create tokens or bypass billing. True "unlimited" = local models + cache + routed capacity, not quota evasion. |
| **Irreducible truth** | Provider keys must live inside the gateway env/secrets manager. Clients get only gateway tokens. Local/self-hosted models remove per-token API fees entirely. |

---

## Mode Selection (per smp5.4pd.md)

Stated need ≠ simple answer → **Depth mode** (excavate assumptions) routed through **Strategy mode** (long-term tradeoffs, who owns patching at 2 a.m.).

Sequential workflow: Discovery → Brainstorm → Research → Plan → Execute → Validate → Review → Complete. No code generated in this phase — this document IS the audit gate and plan.

---

## Layer 1: DEFINE — Discover & Research

### Skill audit (from skills.sh/trending + GitHub research)

| Skill | Owner | Installs | Stars | Status | Relevance to governed token plane |
|---|---|---|---|---|---|
| **find-skills** | vercel-labs/skills | ~3.2M-4.2M | 37.8K | ✅ Published | #1 meta-skill — discovers/installs other skills. Used to find the skills below. |
| **meta-skill** | — | — | — | ❌ 404 | Not published on skills.sh. `find-skills` IS the meta-skill. Treated as conceptual. |
| **parallel-findall** | parallel-web/parallel-agent-skills | 8K | 57 | ✅ Published (in repo) | Entity discovery — "find all providers/models matching criteria." Installable via `npx skills add https://github.com/parallel-web/parallel-agent-skills --skill parallel-findall`. |
| **impeccable** | pbakaus/impeccable | 2.4K | — | ✅ Published | Quality framework: audit, critique, distill, adapt, optimize, delight, result. |
| **parallel-deep-research** | parallel-web/parallel-agent-skills | 14.3K | — | ✅ Published | Comprehensive research — used to audit gateway options (9Router, LiteLLM, Bifrost, GoModel, etc.). |
| **agent-browser** | vercel-labs/agent-browser | 14.8K | — | ✅ Published | Browser automation — stealth verification of gateway endpoints. |
| **github-research** | lingzhi227/agent-research-skills | 31 skills | — | ✅ Published | GitHub issue/codebase triage — audit gateway repos for CVEs, staleness, maintenance. |
| **github-researcher** | — | — | — | concept | Conceptual — deep GitHub archaeology (stars, forks, CVEs, fork-vs-upstream). |
| **feature-research** | — | — | — | concept | Conceptual — feature comparison matrix across gateway options. |
| **code-research** | — | — | — | concept | Conceptual — code-level audit of gateway implementations. |
| **research-deep** | — | — | — | concept | Conceptual — exhaustive investigation of gateway landscape. |
| **langchain-parallel** | — | — | — | concept | Conceptual — LangChain-based parallel agent orchestration. |
| **brainstorming** | obra/superpowers | — | — | ✅ Published | Structured ideation — Stage 1 brainstorming for gateway architecture. |
| **writing-plans** | obra/superpowers | — | — | ✅ Published | Detailed implementation plans from approved designs. |
| **systematic-debugging** | obra/superpowers | — | — | ✅ Published | Hypothesis-driven debug loop for gateway issues. |

### Skill layering by stage

| Stage | Skills | Purpose |
|---|---|---|
| **DEFINE** | find-skills, meta-skill(concept), parallel-findall, feature-research(concept), code-research(concept), research-deep(concept), langchain-parallel(concept), parallel-deep-research, agent-browser, github-researcher(concept), github-research | Discover gateway options, research LiteLLM alternatives, triage repos, find entities |
| **PLAN** | ralph-prompt-multi-task, orchestrate, chain-of-thought, headroom, grill-me, Caveman, devils-advocate, codemap, parallel-agent-skills, agent-skills, impeccable | Phase prompts, meta-orchestrate, step-by-step reasoning, capacity assessment, simplest-first, challenge assumptions, map codebase, parallel execution, quality framework |
| **BUILD** | obra/superpowers (brainstorming, writing-plans, executing-plans, systematic-debugging, orchestrate, superpowers) | Execute the build with checkpoints |

### Skill gap analysis

| Skill | Status | Action |
|---|---|---|
| find-skills | ✅ Installable | `npx skills add https://github.com/vercel-labs/skills --skill find-skills` |
| meta-skill | ❌ Not published | Conceptual — implemented inline via find-skills workflow |
| parallel-findall | ✅ Installable | `npx skills add https://github.com/parallel-web/parallel-agent-skills --skill parallel-findall` |
| impeccable | ✅ Installable | `npx skills add https://github.com/pbakaus/impeccable --skill impeccable` |
| parallel-deep-research | ✅ Installable | `npx skills add https://github.com/parallel-web/parallel-agent-skills --skill parallel-deep-research` |
| agent-browser | ✅ Installable | `npx skills add https://github.com/vercel-labs/agent-browser --skill agent-browser` |
| github-research | ✅ Installable | `npx skills add https://github.com/lingzhi227/agent-research-skills --skill github-research` |
| brainstorming, writing-plans, systematic-debugging | ✅ Installable | obra/superpowers |

---

## Layer 2: PLAN — Plan & Architect

### Brainstorm: 3 gateway architecture options

| Option | Description | Pros | Cons | Best for |
|---|---|---|---|---|
| **A. LiteLLM gateway** | Drop-in OpenAI-compatible gateway, 100+ providers, Redis cache, budgets | Mature, feature-complete, widely adopted | Supply-chain compromises (2x in 2026), 5.6k open issues, heavy deps | Teams wanting fastest time-to-market with LiteLLM familiarity |
| **B. 9Router gateway** | Lightweight policy router, 9Router on :20128, focused on routing + budgets | Lighter than LiteLLM, designed for agent workloads, lower overhead | Less mature ecosystem, fewer providers | Memory-constrained laptop, agent-centric workloads |
| **Bifrost (Maxim AI)** | Go-native, Apache 2.0, 0.62ms latency, 1000+ models, MCP, budgets | Fastest self-hosted, actively maintained, Apache 2.0 | Go-based, newer project | Performance-critical self-hosted deployments |

### Recommended: Option B (9Router/LiteLLM) with local-first bias

Per Marky's recommendation: 9Router/LiteLLM on `127.0.0.1:20128` with Nginx/Caddy edge, OpenCode v2 pointing to gateway, Hermes-agent behind gateway, Ollama/vLLM for local models, Redis for cache/budgets.

### Decision gates

| Gate | From → To | Condition |
|---|---|---|
| G1 | DEFINE → PLAN | Gateway options audited, local model constraint confirmed |
| G2 | PLAN → BUILD | Gateway selected, architecture diagram approved, budget model defined |
| G3 | BUILD → VERIFY | Gateway components implemented, auth/rate-limit/cache working |
| G4 | VERIFY → REVIEW | All tests pass, key isolation verified, no provider keys leaked to clients |
| G5 | REVIEW → SHIP | Code reviewed, impeccable quality gate passed, docs updated |
| G6 | SHIP → Complete | Branch merged, deployment guide published |

---

## Layer 3: BUILD — Execute

### Components to build

1. **Gateway token auth** — Bearer token validation at Nginx/Caddy edge + gateway level
2. **Provider key isolation** — Gateway holds all provider keys in env/secrets manager; clients get only gateway tokens
3. **Rate limiting** — Per-user/per-key rate limits at edge + gateway level
4. **Model routing** — Route to local (Ollama/vLLM) → free tier cloud → paid fallback based on task type/budget
5. **Redis cache** — Semantic + exact response cache for repeated prompts, tool schemas, embeddings
6. **Token/cost budgets** — Per-user budgets, cost ceilings, kill switch for runaway agents
7. **Redacted audit logs** — Log gateway decisions without leaking provider keys or sensitive data
8. **Circuit breaker** — Per-provider circuit breaker with fallback chain
9. **Health checks** — Per-endpoint health checks with automatic failover

### Files to create/modify

| File | Action | Purpose |
|---|---|---|
| `gateway/` | New dir | Gateway service code |
| `gateway/app.py` | Create | FastAPI/Flask gateway with auth, routing, rate limiting |
| `gateway/router.py` | Create | Model routing logic (local → free → paid) |
| `gateway/cache.py` | Create | Redis-backed response cache |
| `gateway/billing.py` | Create | Token/cost budget tracking |
| `gateway/auth.py` | Create | Gateway token validation |
| `gateway/audit.py` | Create | Redacted audit logging |
| `gateway/circuit_breaker.py` | Create | Per-provider circuit breaker |
| `nginx.conf` | Create | Nginx edge config (TLS, rate limit, forward auth) |
| `Caddyfile` | Create | Alternative Caddy edge config |
| `docker-compose.yml` | Create | Local development stack (gateway + Redis + Ollama) |
| `config.json` | Update | Add governed_token_plane section |
| `AGENTS.md` | Update | Document governed token plane architecture |
| `tests/test_gateway.py` | Create | Gateway unit tests |

### Skill application during build

| Stage | Skill | Application |
|---|---|---|
| DEFINE | github-researcher | Audit 9Router/LiteLLM/Bifrost repos for CVEs, staleness |
| DEFINE | parallel-findall | Find all gateway providers/models matching criteria |
| PLAN | chain-of-thought | Step-by-step routing logic design |
| PLAN | headroom | Assess laptop memory constraints (bare metal preferred) |
| PLAN | Caveman | Simplest gateway first — don't over-engineer |
| PLAN | devils-advocate | Challenge "unlimited tokens" premise; confirm key isolation |
| BUILD | writing-plans | Detailed implementation plan with checkpoints |
| BUILD | systematic-debugging | Debug gateway auth/routing issues |
| REVIEW | impeccable | Full quality audit of gateway code |
| REVIEW | codemap | Map gateway codebase structure |

---

## Layer 4: VERIFY — Test & Validate

| Check | Method | Expected |
|---|---|---|
| Gateway auth | Unit test: invalid token → 401 | 401 Unauthorized |
| Key isolation | Integration test: client request contains no provider keys | Provider keys only in gateway env |
| Rate limiting | Unit test: exceed limit → 429 | 429 Too Many Requests |
| Model routing | Unit test: local preferred, fallback chain works | Correct provider selected |
| Redis cache | Integration test: cached response returned | Cache hit on repeated prompt |
| Budget enforcement | Unit test: budget exceeded → 402/429 | Budget block |
| Circuit breaker | Unit test: failing provider → fallback | Automatic failover |
| Audit logs | Integration test: logs redacted, no key leakage | No secrets in logs |

---

## Layer 5: REVIEW — Challenge & Quality

| Reviewer | Focus |
|---|---|
| devils-advocate | Challenge "unlimited free tokens" — confirm governed plane doesn't evade billing |
| impeccable | Audit: code quality, security, no key leakage, test coverage |
| Caveman | Confirm simplest solution — no unnecessary containers/GPU deps on laptop |
| chain-of-thought | Verify routing logic correctness, fallback chain completeness |

---

## Layer 6: SHIP — Merge & Release

1. Commit changes to branch
2. Push to origin
3. Open PR on GitHub
4. Merge PR into main
5. Update AGENTS.md with architecture docs
6. Publish deployment guide

---

## Research sources (all verified)

| Source | URL | Purpose |
|---|---|---|
| smp5.4pd.md | https://raw.githubusercontent.com/marktantongco/opencode-os/refs/heads/main/profiles/smp5.4pd.md | Operating profile |
| skills.sh/trending | https://www.skills.sh/trending | Skills leaderboard |
| find-skills | https://github.com/vercel-labs/skills | #1 meta-skill, skill discovery |
| parallel-agent-skills | https://github.com/parallel-web/parallel-agent-skills | parallel-deep-research, parallel-findall |
| parallel-findall | https://github.com/parallel-web/parallel-agent-skills/tree/main/skills/parallel-findall | Entity discovery |
| impeccable | https://www.skills.sh/pbakaus/impeccable/impeccable | Quality framework |
| agent-browser | https://www.skills.sh/vercel-labs/agent-browser/agent-browser | Browser automation |
| github-research | https://github.com/lingzhi227/agent-research-skills | GitHub repo triage |
| Bifrost | https://github.com/maximhq/bifrost | Go-native gateway (9,078★, Apache 2.0) |
| GoModel | https://github.com/ENTERPILOT/GoModel | Single-binary gateway (1,298★, MIT) |
| agentgateway | https://github.com/agentgateway/agentgateway | Rust gateway (5,224★, Apache 2.0) |
| Portkey | https://github.com/Portkey-AI/gateway | Managed gateway (13,302★, MIT) |
| LiteLLM | https://github.com/BerriAI/litellm | 62,569★ — 2x supply-chain compromises in 2026 |
| 9Router | :20128 | Lightweight policy router per Marky's rec |

---

## Next step

**Execute Layer 3 (BUILD):** Create the gateway directory structure and implement `gateway/app.py` with auth, routing, rate limiting, cache, budgets, circuit breaker, and audit logging. Start with the simplest possible gateway (Caveman principle) — FastAPI with bearer token auth + local model routing + Redis cache.
