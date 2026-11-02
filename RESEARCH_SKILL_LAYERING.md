# OWL-AGENT PROXY — Parallel Deep-Research Skill Audit & Integration Plan

**Project:** marktantongco/owl-agent-proxy (branch `arena/57be4fea-owl-agent-proxy`)
**Operating instructions adopted:** https://raw.githubusercontent.com/marktantongco/opencode-os/refs/heads/main/profiles/smp5.4pd.md (v5.4 PD Tactical Merge)
**Mode:** 🦉 Depth + 🦅 Strategy
**Confidence:** 0.75+ (all claims sourced from repo inspection, GitHub API metadata, skills.sh/trending, and raw READMEs fetched 2026-11-02)

---

## 1. Silent Layer — what is actually being asked

| Question | Answer |
|---|---|
| **Actual need** | Define, audit, and sequence every skill needed before writing a single line of code for OWL Agent Proxy; layer skills by deployment stage; write one comprehensive parallel-deep-research prompt for the LiteLLM-alternatives landscape; and decide which of ~26 candidate repos to adopt/adapt/merge/skip. |
| **Blind spot** | marktantongco's GitHub org is mostly *forks/mirrors* of upstream projects (colibri←JustVugg/colibri, airllm←lyogavin/airllm, openrelay←romgX/openrelay, cc-switch←farion1231/cc-switch, hermes-router←kjames2001/hermes-router-proxy). Fork staleness and upstream CVE baggage (one-api/new-api 2026 CVEs noted in the user brief) are the real risk, not feature checklists. |
| **Irreducible truth** | Self-hosted vs managed is not about features; it is about who owns patching at 2 a.m. On a memory-constrained laptop, every extra container and every GPU dependency is a tax. OWL already ships an http/1.1-only core that works with zero dependencies — escalation must stay opt-in and justified. |

---

## 2. Mode selection (per smp5.4pd.md)

Stated need ≠ simple answer → **Depth mode** (excavate assumptions, show reasoning) routed through **Strategy mode** (long-term tradeoffs, who owns patching). Sequential workflow per the ops manual: Discovery → Brainstorm → Research → Plan → Execute → Validate → Review → Complete. No code is generated in this phase; this document *is* the plan and the audit gate.

---

## 3. Skills.sh ecosystem recon

Browsed `https://www.skills.sh/trending` (both chunks) and the individual skill pages.

| Skill | Owner | Installs | Stars | Status | Relevance to OWL |
|---|---|---|---|---|---|
| find-skills | vercel-labs/skills | 17.7K | 37.7K | ✅ Published | Skill discovery command — used to find the skills below |
| agent-browser | vercel-labs/agent-browser | 14.8K | — | ✅ Published | Full browser automation (navigate/click/extract/screenshot) — direct input to the stealth-browser decision |
| browser-use | browser-use/browser-use | — | — | ✅ Published | Browser automation with visual understanding — agent-browser alternative |
| brainstorming | obra/superpowers | — | — | ✅ Published | Structured ideation (Stage 1 brainstorming) |
| systematic-debugging | obra/superpowers | — | — | ✅ Published | Hypothesis-driven debug loop (Stage 3) |
| ai-image-generation (superpowers) | skills-shell/superpowers | 30.2K | — | ✅ Published | Not relevant |
| meta-skill | — | — | — | ❌ 404 | Not published on skills.sh |
| parallel-findall | — | — | — | ❌ 404 | Not published on skills.sh |

**Takeaway:** `find-skills` and `agent-browser` are real, installable skills. `meta-skill` and `parallel-findall` do not exist as public skill pages (404) — they must be treated as *concepts* to be implemented inline, not installed packages. The "parallel deep-research sub-agents" (GitHub, Perplexity, Firecrawl, gap-analysis, dependency-graphing) named by the user are likewise concepts; this repo has no Perplexity/Firecrawl tooling, so they are simulated here via parallel GitHub API fetches + web search + README analysis, which is what follows.

---

## 4. LiteLLM top-20 alternatives (from the user brief) — audited

Tiered exactly as provided. OWL-relevant notes added per tier.

### Tier 1 — Managed / zero-ops replacements
1. Portkey (now Prisma AIRS AI Gateway) — MIT open-source core, cloud/VPC/self-host, guardrails/retries/caching/fallback routing, 200+ providers, free then $49/mo.
2. OpenRouter — ~340 models, auto-failover, BYOK, change `base_url`, ~5.5% credit fee. Best for prototyping/model discovery.
3. Cloudflare AI Gateway — edge proxy, 0% markup, free DLP/PII scanning, caching, rate limiting, analytics, dynamic routing, SOC2/ISO/PCI/GDPR, 100% SLA Business+.
4. Vercel AI Gateway — true 0% markup incl. BYOK, ZDR option, 99.99% SLA Enterprise. Best if on Vercel.
5. Helicone — Apache 2.0 observability-first gateway, 100+ providers, one-URL drop-in, analytics/caching/rate limits.
6. TrueFoundry AI Gateway — K8s-native enterprise gateway, runs in your VPC, RBAC/budgets/governance, ~3–4ms overhead at 350+ RPS per vCPU.

### Tier 2 — High-performance self-hosted (LiteLLM drop-in upgrade)
7. **Bifrost (Maxim AI)** — Go-native, Apache 2.0, 0.62ms added latency vs LiteLLM ~5.83ms, adaptive load balancing, cluster mode, 1000+ models. #1 self-hosted speed pick.
8. **GoModel** — MIT, Go, single binary / one Docker image, secure self-hosted auditable. Rated best overall self-hosted in 2026 by several roundups.
9. Kong AI Gateway — if you already run Kong; AI Prompt Guard, mTLS/rate-limit plugins; PII/RBAC need Enterprise.
10. **Envoy AI Gateway** — built on Envoy, native to K8s/Istio, Apache 2.0, multi-provider routing + MCP gateway with OAuth. Best fit for CNCF platform teams.
11. **agentgateway (Solo.io)** — Rust, Apache 2.0, built for AI agents + MCP servers, imported LiteLLM upstream headers in v1.6.0.
12. new-api / one-api — China-friendly relay panel; one-api MIT 37k★, new-api fork 51k★; **cluster of 2026 CVEs — sandbox and patch aggressively.**

### Tier 3 — Governance, routing & specialized
13. OptScale AI — managed/on-prem governance, gateway+guardrails+cost attribution+agent control, <10ms routing overhead, virtual keys with department billing.
14. Future AGI Agent Command Center — managed gateway+observability+evaluators, BYOK cloud or self-host.
15. Leanroute — policy-driven router, compares hosting/wire format/BYOK/MCP/guardrails.
16. RouteHub — Python library, not a server; Apache 2.0 in-process low-overhead drop-in if you don't want a separate proxy.
17. TensorZero — LLM optimization gateway; **archived June 2026** — avoid for new builds.
18. Respan — cloud + self-hosted OSS gateway, SOC2/HIPAA/GDPR/ISO27001, free then $199/mo.
19. Unify AI / Martian / RouterFleet — smart routers (cheapest capable model), not full gateways; pair with Cloudflare/Portkey for 60%+ cost cut via model arbitrage.
20. AWS Bedrock / Azure AI Foundry / GCP Vertex AI Gateway — cloud-native; unified API/IAM/VPC/spend, locked to that cloud's catalog.

### Decision matrix (options × criteria)

| Your constraint | Pick this | Rationale |
|---|---|---|
| Self-hosted, better than LiteLLM | **Bifrost** or **GoModel** | Lowest added latency; Go-native single binary |
| Guardrails + circuit breakers, free to self-host | Portkey Gateway OSS | MIT core, production governance |
| Already run Kong / APISIX / Envoy / K8s | Kong AI Gateway / Envoy AI Gateway | Reuse existing infra; Envoy fits CNCF teams |
| Zero ops, fastest start | OpenRouter | Change base_url, ~340 models |
| Zero ops, 0% markup + compliance | Cloudflare AI Gateway | Edge, DLP/PII free, SOC2/ISO/PCI/GDPR |
| Governance, cost chargeback, on-prem | TrueFoundry or OptScale AI | VPC-deployed, RBAC, department billing |
| Don't want to run a server at all | OpenRouter / Cloudflare / Vercel | Managed, no infra |

**OWL mapping:** OWL Agent Proxy is an outbound HTTP defense/proxy stack (cache → dedupe → rate limit → sticky proxy rotation → honeypot detection → MCP), not an LLM gateway. It does not do model routing, virtual keys, or spend tracking. If the project's next phase adds an LLM-proxy/layer, the self-hosted Tier-2 options (Bifrost, GoModel, Envoy AI Gateway) are the architectural analogues; OpenRouter/Cloudflare are the managed `base_url` targets OWL could front.

---

## 5. Head-to-head comparisons requested

### 5.1 docker-compose.yml vs bare metal — laptop with memory constraints

**Verdict: bare metal (or a single systemd/user service) is better for a memory-constrained laptop; docker-compose is unnecessary overhead here.**

Evidence from the repo and candidates:

- OWL Agent Proxy `pyproject.toml` deliberately ships a **dependency-light** core: `aiohttp`, `httpx`, `aiofiles` only. http/1.1 works with nothing else installed. http2/JA3/websocket/redis/browser/stealth are all *optional extras*. There is **no docker-compose.yml or Dockerfile in the repo** (verified: `find . -name "docker-compose*"` and `Dockerfile*` returned nothing). The installer (`install-owl.sh`) installs into `~/.owl-agent` with a venv and a generated `run.sh` — idempotent, offline-safe with `--no-live`.
- hermes-router (the closest LLM-gateway analogue in the ecosystem) offers **Path A bare-metal installer (recommended)** and only Path B Docker as a "hardened compose profile." Its own docs mark bare metal as the default path.
- browserpilot-enhanced *does* ship a `docker-compose.yml` (searxng + camofox + redis + browserpilot) — four containers. On a RAM-constrained laptop that is a heavy tax; Camofox alone is a full patched Firefox.

**Matrix**

| Criterion | Bare metal (OWL installer / systemd) | docker-compose (browserpilot-style) |
|---|---|---|
| RAM footprint | ~30–80 MB (Python venv, no daemons) | ~600 MB–2 GB+ (4+ containers) |
| CPU at idle | near zero | container runtime + sidecars |
| Disk | tens of MB | several GB images |
| Offline safety | ✅ `--no-live` installer | ❌ needs image pulls |
| Complexity | 1 script, `run.sh` | compose file + engine + networks |
| Best for | memory-constrained laptop | multi-service team / server |

**Recommendation:** Install OWL bare metal via `./install-owl.sh` (or `--no-live` offline). Add optional extras only as needed (`[http2]`, `[ja3]`, `[browser]`, `[stealth]`). If a specific integration *requires* compose (e.g. browserpilot-enhanced's SearXNG/Camofox/Redis tier), run that *one* compose stack separately and point OWL at it via `base_url`, rather than containerizing OWL itself.

### 5.2 Colibri vs AirLLM — local model runner on a memory-constrained laptop

**Verdict: Colibri for a laptop without a discrete NVIDIA GPU; AirLLM only if you have an NVIDIA CUDA GPU.**

| Criterion | Colibri (marktantongco/colibri ← JustVugg/colibri) | AirLLM (marktantongco/airllm ← lyogavin/airllm) |
|---|---|---|
| Engine | Pure C, one file per model family, **zero deps** | Python package, `torch` + `transformers` stack |
| Hardware | **CPU-only optional**, Vulkan/CUDA when available | **Requires GPU (CUDA)** for value; CPU support is secondary |
| Memory model | Streams MoE *experts from disk*; resident working set stays in RAM | Streams model *layers from disk*; keeps a small VRAM footprint |
| RAM/disk floor | 8 GB RAM (16 GB better), 22 GB disk for smallest model | 4 GB GPU VRAM; system RAM for checkpoint cache |
| Best models | GLM-5.2/5.3, Kimi K3, DeepSeek V4 Flash, Qwen3 (incl. Coder), OLMoE, Qwen-Image | Kimi K3 (2.8T), DeepSeek-V3 (671B on ~12 GB VRAM), Qwen3.8-Flash-Next |
| Interface | `coli chat`/`coli serve`; OpenAI base URL `http://127.0.0.1:8000/v1`; MCP server (`coli mcp`) | Python `AutoModel.from_pretrained(...)` API; not a server by default |
| License | Free/OSS (JustVugg) | Apache 2.0 code (note: README shows a BELLE license badge — verify before shipping) |
| Fork status | marktantongco/colibri = fork of JustVugg/colibri | marktantongco/airllm = fork of lyogavin/airllm |

**For a memory-constrained laptop:** Colibri wins because it needs no GPU and fits in 8–16 GB RAM by streaming experts from disk. AirLLM's selling point (70B on a 4GB GPU) is irrelevant on an integrated-graphics laptop and its Python/torch stack is heavier. Both expose an OpenAI-compatible endpoint, so either can sit behind OWL as an upstream (`base_url = http://127.0.0.1:8000/v1`).

### 5.3 OpenRelay vs CC-Switch

**Verdict: OpenRelay for quota discovery + a local endpoint; CC-Switch for provider switching + MCP/skills/prompt management. They are complementary, not substitutes.**

| Criterion | OpenRelay (marktantongco/openrelay ← romgX/openrelay) | CC-Switch (marktantongco/cc-switch ← farion1231/cc-switch) |
|---|---|---|
| Core job | Auto-discover AI quotas from local apps (Claude Desktop, Kiro, Cursor, OpenClaw, etc.) and expose one local endpoint | One-click API provider switching; manage MCP, Skills, Prompts in one place |
| Interface | Web panel `http://localhost:18765` + one-click CLI tool config | Tauri 2 desktop GUI |
| Endpoint | `localhost:18765` (Anthropic/OpenAI-compatible) | Config manager, not primarily a proxy endpoint |
| Providers | 45+ direct API/local providers (Groq, Gemini, DeepSeek, Mistral, OpenRouter, Ollama…) | Switches between configured providers; heavy sponsor/relay linkage (PackyCode, APINebula, AICodeMirror, Pateway, hao.ai, Fenno) |
| License | Open Core: MIT framework + commercial Pro features | Not clearly OSI (sponsor-linked relay ecosystem) |
| Model groups/failover | ✅ Custom model groups with cross-provider auto-failover | Provider switching in one click |
| Best for | "I want my existing paid/free quotas usable by any OpenAI/Anthropic tool" | "I want a desktop UI to switch providers and manage MCP/skills" |

**Integration note:** OpenRelay's local endpoint (`localhost:18765`) is exactly the kind of upstream OWL could rotate through or stick to per `(agent_id, domain)`. CC-Switch is a config UI — useful for operators but adds no network-layer value to OWL.

### 5.4 Hermes-router vs FreeRide — and why

**Verdict: Hermes-router is the production gateway; FreeRide(v3) is the free-tier failover client. Use both at different layers, or pick Hermes-router if you must choose one self-hosted gateway.**

| Criterion | Hermes-router (marktantongco/hermes-router) | FreeRide (Shaivpidadi/FreeRide, v3 gateway) |
|---|---|---|
| Type | Self-hosted LLM gateway | Local free-tier gateway (`localhost:11343`) |
| License | MIT | MIT-0 (1.x), v3 is `freeride-gateway` on uv/pipx |
| Language | Python 3.12+ | Python (`uv tool install freeride-gateway`) |
| Tests | 491 passed + 4 skipped, golden fixtures, docs-as-tests | Watcher/auto-config; less test surface advertised |
| Routing | 5-tier classifier ladder (fastText → SetFit → embeddings → ML surrogate → LLM flash); session-aware, 5-min TTL | Route across free tiers (OpenRouter, Gemini, Groq, Ollama Cloud, Z.ai, NVIDIA NIM, Cloudflare); **fail over inside the same response** on rate limit |
| Budgets | Immutable hash-chained cost ledger, blocking budgets (402 before spend), sliding-window limiters | Free-model ranking by context/capabilities/recency/provider trust |
| Key management | Key pooling, round-robin, 429 cooldown, 401/403 quarantine | Manages OpenRouter free models; optional provider opt-in |
| Ops | Dashboard, Prometheus, 6 alert rules + webhooks, hardened compose, runbook | `freeride bind openclaw`, `freeride rotate` |
| Primary model (per its own README) | `auto` (route by classification) | `openrouter/nvidia/nemotron-3-nano-30b-a3b:free` |
| Fallbacks | Cross-protocol fallback chains | openrouter/free → qwen3-coder → step-3.5 → deepseek → mistral |

**Why:** Hermes-router has a real test gate (491 tests), immutable billing ledger, and alerting — it is the production-hardened choice if you want *governance*. FreeRide's differentiator is *zero-cost uptime*: in-response failover across free tiers means a user never sees a rate-limit error. For OWL, Hermes-router's `http://127.0.0.1:8766/v1` endpoint and OpenAI-compatible adapter make it a natural upstream; FreeRide's `localhost:11343` is a complementary free-tier source.

### 5.5 Best headless stealth browser for this project

**Verdict: Patchright as the default (drop-in Playwright stealth), Camoufox for hardened fingerprinting targets, nodriver as the Python-native alternative. Do not use vanilla Playwright.**

This project's `pyproject.toml` already marks `browser = ["playwright>=1.52"]` as optional and `stealth = ["invisible-playwright>=0.44"]` (C++-patched Firefox, ~260 MB sealed browser, Python ≥3.11). Research (Sendwin 2026-10-12, Scrapfly 2026-10-15, webscraping.cc 2026-07-09, o-mega.ai 2026-09-08) converges:

| Tool | Engine | Stealth approach | Best for | Fit for OWL |
|---|---|---|---|---|
| Patchright | Chromium/Playwright fork | Patches `Runtime.enable`/CDP signals; drop-in import swap | Existing Playwright code | **Best default** — OWL already lists playwright |
| Camoufox | Firefox fork (C++ patches) | Spoofed canvas/WebGL/navigator at engine level | Hard fingerprinting (DataDome, PerimeterX) | High-effort targets |
| nodriver | Python, raw CDP | No WebDriver layer | Python async stealth | Good Python alternative |
| CloakBrowser | Chromium fork, 49 C++ patches | Source-level removal of automation signals | Pixelscan 105/105 | Strong but heavier |
| Vanilla Playwright | Chromium/Firefox/WebKit | None | Baseline only | ❌ Easily detected |

**browserpilot-enhanced** (marktantongco, master branch) is directly relevant: a fusion architecture combining **SearXNG → Camofox → CloakBrowser** 3-tier, FastAPI `:8000`, Redis, Ghost Mode, 105/105 Pixelscan. Its `docker-compose.yml` runs searxng + camofox + redis + browserpilot — four containers, too heavy for a RAM-constrained laptop to run continuously, but valuable as an *on-demand* stealth tier. OWL's `browser` protocol can point at a Patchright- or Camoufox-hardened Playwright instance instead.

---

## 6. Repo-by-repo integration audit (26 candidates)

Each entry: what it is, what code it contributes, and the integration verdict (**Adopt / Adapt / Merge / Skip**) with how it hooks into OWL.

### LLM gateway / routing layer (self-hosted, Tier-2 analogues)

| # | Repo | What it is | Code contribution | Verdict | Hook into OWL |
|---|---|---|---|---|---|
| A | marktantongco/hermes-router | Self-hosted LLM gateway (fork of kjames2001/hermes-router-proxy), MIT, Python 3.12+, port 8766 | Classifier ladder, provider abstraction (OpenAI + Anthropic adapters), key pooling, immutable cost ledger, budgets (402), dashboard/Prometheus, 491 tests | **Adapt** (study patterns; do not vendor wholesale — OWL is a proxy defense stack, not a billing gateway) | As an upstream `base_url` OWL routes through; borrow budget/circuit-breaker patterns into `ResilientClient` |
| B | marktantongco/openrelay | Desktop quota discovery + local endpoint `localhost:18765`, Open Core | Quota auto-discovery from Claude Desktop/Kiro/Cursor/OpenClaw, custom model groups with failover, IDE RPC proxies | **Adapt** | OWL sticky sessions + proxy rotation can rotate through openrelay's local endpoint as one upstream |
| C | marktantongco/cc-switch | Tauri 2 desktop provider switcher + MCP/skills/prompt manager | GUI for switching providers, managing MCP/skills/prompts | **Skip** (for OWL core) | Operator desktop tool only; no network-layer contribution |
| D | Shaivpidadi/FreeRide (+FreeRide v3) | Free-tier manager (v1.x OpenClaw config writer); v3 = local gateway `localhost:11343` with in-response failover across free tiers | Free model ranking, fallback chain (nemotron → openrouter/free → qwen3-coder → step-3.5 → deepseek → mistral), `freeride bind` | **Adapt** (v3 gateway pattern) | Free-tier upstream source for OWL; in-response failover pattern worth borrowing for `ResilientClient` retries |

### Local model runners (for the "run local, no server" user segment)

| # | Repo | What it is | Verdict | Hook |
|---|---|---|---|---|
| E | marktantongco/colibri | Pure C MoE engine, CPU+disk-streaming, OpenAI `:8000/v1`, MCP server | **Adopt** (best for RAM-constrained laptop, no GPU) | Local upstream for OWL; `coli mcp` could feed OWL's MCP tools |
| F | marktantongco/airllm | Python GPU layer-streaming (70B on 4GB GPU) | **Skip** for laptop (needs NVIDIA CUDA) | Only if target machine has a discrete GPU |

### Browser / stealth layer

| # | Repo | What it is | Verdict | Hook |
|---|---|---|---|---|
| G | browserpilot-enhanced | Fusion: SearXNG + Camofox + CloakBrowser 3-tier, FastAPI `:8000`, Ghost Mode, Pixelscan 105/105 | **Adapt** (study the 3-tier stealth pattern; run compose on demand, not resident) | OWL `browser` protocol target; SearXNG as a search upstream for the harvester |
| H | mlc-ai/web-llm-chat | Browser-native LLM chat (WebGPU, private, server-free) | **Skip** (client-side, not a proxy component) | — |

### Auth / autologin / relay ecosystem (user asked to integrate *without* blacklisted pieces)

| # | Repo | What it is | Verdict | Hook |
|---|---|---|---|---|
| I | marktantongco/owl-dns-synergy | OWL-DNS-Synergy v2.0.0, Unified Dual-Channel Resilient Access Engine, AutoClaw synergy | **Adopt** (resilience/DNS dual-channel fits OWL's escalation ladder) | Extends OWL protocol escalation with DNS failover channel |
| J | marktantongco/ai-gateway-complete | Full-stack AI gateway, Grok + Turnstile solving, multi-account | **Skip** — explicitly excluded by user ("without blacklisted AI proxy") | — |
| K | marktantongco/autoclaw-autologin | OpenAI-compatible free LLM proxy with OAuth token harvesting, Google SSO, token rotation | **Adopt without glm/z.ai** — use only the OAuth/SSO rotation pattern, not the glm/z.ai dependency | Auth channel for OWL's upstream credentials |
| L | marktantongco/opencode2dsh | DSH plugin — free OpenCode Zen models for DeepSeek Harness, no API key | **Adapt** | No-key model source for OWL fallbacks |
| M | marktantongco/genspark-claw | Skill pack + CLI for Genspark Claw/OpenClaw/Hermes, 5 SKILL.md skills, Node installer, MCP server | **Adapt** | Skills + MCP patterns for OWL's skills system |
| N | marktantongco/dsh-better-bridge | DeepSeek Harness × Better DeepSeek bridge (free web chat relay) | **Adapt** (cautiously — web-chat relay is fragile) | Free model fallback source |
| O | marktantongco/reason-network | Team coding agents talking to each other | **Adapt** (agent-to-agent bus pattern) | OWL MCP `proxy_pick`/stats could serve agent bus telemetry |

### Hermes ecosystem / memory / skills

| # | Repo | What it is | Verdict | Hook |
|---|---|---|---|---|
| P | robbyczgw-cla/hermes-web-search-plus | Hermes web search: multi-provider search + extraction, optional local key-free DonSeTch | **Adopt** | Search source for OWL's harvester/research mode |
| Q | thvtzy/hermes-unlimited-memory | SQLite + FTS5 MCP server, bypasses 2,200-char limit | **Adopt** | Memory backend for OWL agent sessions |
| R | Devs-Foundation/mnemosyne | Local vault-backed memory for Hermes, zero cloud | **Adopt** (alternative to Q; pick one) | Memory backend |
| S | adi0900/Unlimited-Hermes | 1★, no description, 8 KB | **Skip** (insufficient signal) | — |
| T | QuixThe2nd/chatgpt-chat-api | Free/paid ChatGPT access from Cursor/Hermes/OpenAI-compatible clients | **Adapt** cautiously | OpenAI-compatible upstream source |
| U | reallygood83/hermes-for-web | Personalized web workbench for Hermes Agent | **Skip** (UI workbench, not proxy-layer) | — |
| V | kepano/obsidian-skills | Agent skills for Obsidian CLI (Markdown, Bases, JSON Canvas), 50K★ | **Skip** (Obsidian-specific) | — |
| W | GumbyEnder/hermes-kanban | Obsidian plugin + Hermes skill, Kanban boards | **Skip** (Obsidian-specific) | — |

**Wise to include?** Unlimited-Hermes: no. hermes-unlimited-memory + mnemosyne: yes (pick one memory backend). chatgpt-chat-api: yes with caution (web-chat relay). hermes-for-web / obsidian-skills / hermes-kanban: no — they are Hermes/Obsidian UI layers, not OWL proxy-layer code.

---

## 7. Skill layering by deployment stage

Per the user's requested layering, mapped to real, installable skills (skills.sh) and inline concepts.

### Stage 1 — Discover & Research

| Skill | Source | Status | Purpose |
|---|---|---|---|
| find-skills | vercel-labs/skills | ✅ installable | Discover `npx skills find <query>` / `npx skills add <pkg>` |
| agent-browser | vercel-labs/agent-browser | ✅ installable | Browser automation baseline (navigate, click, extract, screenshot) |
| browser-use | browser-use/browser-use | ✅ installable | Visual-understanding browser automation (stealth-browser alternative research) |
| meta-skill | — | ❌ 404 (not published) | Inline concept: audit which skills are needed before coding |
| parallel-findall | — | ❌ 404 (not published) | Inline concept: fan-out discovery across many repos in parallel |
| feature-research / code-research / research-deep / langchain-parallel | — | concepts | Deep-research sub-agents simulated via GitHub API + web search + README analysis (done in this document) |

### Stage 2 — Plan & Architect

| Skill | Source | Status | Purpose |
|---|---|---|---|
| ralph-prompt-multi-task | — | concept | Multi-task prompt decomposition |
| orchestrate | — | concept | Sequence sub-agents and gates |
| chain-of-thought | — | technique | Step-by-step reasoning (this document) |
| headroom | — | concept | Budget the 2 a.m. patching owner |
| grill-me / devils-advocate | — | techniques | Red-team the integration plan before coding |
| codemap | — | concept | Dependency graph of the 26 repos → OWL |
| parallel-agent-skills / agent-skills | — | concept | Run skill research in parallel |
| mattpocock / pbakaus/impeccable | — | concepts | Audit / impeccable / distill / critique / adapt / optimize / delight / result gates |

### Stage 3 — Execute & Debug

| Skill | Source | Status | Purpose |
|---|---|---|---|
| obra/superpowers (brainstorming, writing-plans, executing-plans, systematic-debugging, orchestrate, superpowers) |obra/superpowers | ✅ installable | Planning + hypothesis-driven debugging loop |
| superpowers | skills-shell/superpowers / bankai-skills / qu-skills / 101-skills / magentos/superpowers | ✅ installable | General execution capabilities |

**Cross-cutting:** `agent-browser` vs `browser-use` — for OWL's optional `browser` protocol, `agent-browser` (vercel-labs, 14.8K installs) is the simpler installable baseline; `browser-use` adds visual understanding at the cost of weight. Start with Patchright-hardened Playwright (already in OWL's `browser` extra); reach for `agent-browser`/`browser-use` only if visual understanding is required.

---

## 8. Recommended stack for a memory-constrained laptop (the "before code" decision)

```
OWL Agent Proxy (bare metal, ./install-owl.sh --no-live)
  └─ http/1.1 core: cache → dedupe → rate limit → sticky proxy rotation → honeypot check
  └─ Optional escalation (opt-in, justified): http/2 → JA3 → WebSocket → browser
  └─ Local upstream: colibri (OpenAI http://127.0.0.1:8000/v1)  [no GPU, 8–16 GB RAM]
  └─ Free-tier upstream: FreeRide v3 (localhost:11343) or OpenRouter (base_url swap)
  └─ Quota discovery: OpenRelay (localhost:18765) on demand
  └─ Stealth on demand: browserpilot-enhanced compose (SearXNG/Camofox/CloakBrowser) — start only when needed
  └─ MCP: mcp_proxy_server (proxy_pick/stats/rotate/validate) + hermes-unlimited-memory or mnemosyne for session memory
  └─ Governance patterns borrowed from hermes-router (budgets, circuit breakers, immutable ledger) — not vendored
```

**Not included:** docker-compose for OWL itself, ai-gateway-complete (blacklisted), Unlimited-Hermes (no signal), obsidian-skills/hermes-kanban (Obsidian UI), airllm (no GPU), TensorZero (archived), one-api/new-api without aggressive patching (2026 CVEs).

---

## 9. ⚡ Next Step

Review this audit, then write the `PROMPT_PARALLEL_DEEP_RESEARCH_LITELLM.md` comprehensive prompt (next file) and run it through the parallel deep-research sub-agents before any implementation code is written.

---

## ✨ 3 Suggestions

- **Tactical:** Run `./install-owl.sh --no-live` on the target laptop and verify `run.sh stats` returns pool/source health before integrating anything else — prove the zero-dependency core works first.
- **Strategic:** Treat OWL as a *proxy defense layer in front of* an LLM gateway (hermes-router pattern) rather than rebuilding gateway features (billing, virtual keys, cost ledger) inside OWL. That keeps OWL's dependency floor low.
- **Reframe:** The question is not "which of these 26 repos do I merge?" It's "which one upstream does OWL rotate through at 2 a.m. when the primary fails?" Design for failover, not fusion.
