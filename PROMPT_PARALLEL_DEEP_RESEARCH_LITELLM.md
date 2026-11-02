# PROMPT: Parallel-Deep-Research — Top 20 LiteLLM Alternatives (2026)

**Purpose:** One comprehensive prompt to hand to parallel deep-research sub-agents (GitHub, Perplexity, Firecrawl, gap-analysis, dependency-graphing) to exhaustively explore, select, audit, and define every LiteLLM alternative before any implementation code is written.

**Context for the agents:** LiteLLM is the default open-source LLM proxy — one OpenAI-compatible endpoint in front of 100+ providers with virtual keys, spend tracking, load balancing, and fallbacks. Teams are looking for alternatives in 2026 for three reasons: (1) they don't want to run a server at all, (2) they want lower latency, or (3) they want governance built in. LiteLLM suffered two supply-chain compromises in 2026, so the ops bar went up. The starting shortlist (already partially researched) is the tiered list of 20 below; the agents' job is to validate, extend, audit, and sequence it.

---

## Role

You are a parallel deep-research team operating under the smp5.4pd.md operating instructions (Zero fluff. Working code. Alignment > speed. Depth execution > speed. Quality-gated.) Run in **Depth mode 🦉** + **Strategy mode 🦅**. Simulate five sub-agents in parallel:

1. **GitHub sub-agent** — repo archaeology: stars, forks, open issues, license, last commit, release cadence, CVE/advisory history, fork-vs-upstream status, contribution health.
2. **Perplexity/Firecrawl sub-agent** — web research: 2026 roundups, blog posts, benchmark numbers, pricing pages, user reports, supply-chain-incident coverage.
3. **Gap-analysis sub-agent** — compare each candidate against LiteLLM on the decision criteria below; surface what LiteLLM does that the alternative does *not*, and vice versa.
4. **Dependency-graphing sub-agent** — map dependencies, transitive risks, language/runtime, single-binary vs multi-service, GPU/RAM floor, whether a server is required at all.
5. **Synthesis sub-agent** — produce the final tiered shortlist, decision matrix, migration base_url/config examples, and the "who owns patching at 2 a.m." recommendation.

Run all five in parallel, then synthesize. Output format per smp5.4pd.md: Mode | Problem: 1-line | Solution | Reasoning + evidence | Counter | Assumptions | Next Step | 3 Suggestions, plus a compare matrix (Options × criteria, ✅/⚠️/❌) and a Mermaid `flowchart TD` schematic where relevant.

---

## Starting shortlist (the top 20, as given)

**Tier 1 — Managed / zero-ops replacements**
1. Portkey (now Prisma AIRS AI Gateway) — MIT open-source core, cloud + VPC + self-host, guardrails/retries/caching/fallback routing, 200+ providers, free then $49/mo.
2. OpenRouter — ~340 models, auto-failover, BYOK, change `base_url`, ~5.5% credit fee.
3. Cloudflare AI Gateway — edge proxy, 0% markup, free DLP + PII scanning, caching, rate limiting, analytics, dynamic routing, SOC2/ISO/PCI/GDPR, 100% SLA Business+.
4. Vercel AI Gateway — true 0% markup incl. BYOK, ZDR option, 99.99% SLA Enterprise.
5. Helicone — Apache 2.0 observability-first gateway, 100+ providers, one-URL drop-in, usage analytics/caching/rate limits.
6. TrueFoundry AI Gateway — K8s-native enterprise gateway, runs in your VPC, RBAC/budgets/governance, ~3–4ms overhead at 350+ RPS per vCPU.

**Tier 2 — High-performance self-hosted (LiteLLM drop-in upgrade)**
7. Bifrost (Maxim AI) — Go-native, Apache 2.0, 0.62ms added latency vs LiteLLM ~5.83ms, adaptive load balancing, cluster mode, 1000+ models.
8. GoModel — MIT, Go, single binary / one Docker image, secure self-hosted auditable.
9. Kong AI Gateway — Apache 2.0 core, AI Prompt Guard, mTLS/rate-limit plugins; PII/RBAC need Enterprise.
10. Envoy AI Gateway — built on Envoy, native to K8s/Istio, Apache 2.0, multi-provider routing + MCP gateway with OAuth.
11. agentgateway (Solo.io) — Rust, Apache 2.0, for AI agents + MCP servers, imported LiteLLM upstream headers in v1.6.0.
12. new-api / one-api — one-api MIT 37k★, new-api fork 51k★, China-friendly relay panel; **cluster of 2026 CVEs — sandbox and patch aggressively.**

**Tier 3 — Governance, routing & specialized**
13. OptScale AI — managed/on-prem governance, gateway + guardrails + cost attribution + agent control, <10ms routing overhead, virtual keys with department billing.
14. Future AGI Agent Command Center — managed gateway + observability + evaluators, BYOK cloud or self-host.
15. Leanroute — policy-driven router (hosting model, wire format, BYOK, MCP support, guardrails).
16. RouteHub — Python library, not a server; Apache 2.0 in-process drop-in.
17. TensorZero — LLM optimization gateway; **archived June 2026** — flag.
18. Respan — cloud + self-hosted OSS gateway, SOC2/HIPAA/GDPR/ISO27001, free then $199/mo.
19. Unify AI / Martian / RouterFleet — smart routers (cheapest capable model), not full gateways; pair with Cloudflare/Portkey.
20. AWS Bedrock / Azure AI Foundry / GCP Vertex AI Gateway — cloud-native gateways, locked to that cloud's catalog.

---

## Mandatory research questions (every sub-agent must address)

### A. Validate the shortlist
For each of the 20: confirm it still exists and is actively maintained in late 2026; give GitHub stars/forks/open issues/last-commit date; state the license; note any 2026 supply-chain compromise, CVE, or archival status (TensorZero is archived — confirm or correct); flag any fork-vs-upstream ambiguity (e.g. one-api vs new-api).

### B. Decision criteria (score every candidate)

| Criterion | What to measure |
|---|---|
| Server required? | Yes/no — can it run as a library/in-process instead of a proxy? |
| Added latency | ms overhead per request (Bifrost claims 0.62ms vs LiteLLM ~5.83ms — verify) |
| Providers supported | count and which (OpenAI, Anthropic, Groq, Gemini, Ollama, vLLM, local llama.cpp, etc.) |
| OpenAI-compatible? | Does it speak `/v1/chat/completions` so clients only change `base_url`? |
| Virtual keys | per-team/per-user key issuance and rotation |
| Spend tracking | cost attribution, department billing, integer-exact ledger |
| Load balancing / failover | circuit breakers, 429-aware cooldowns, cross-protocol fallback |
| Guardrails | PII/DLP scanning, prompt injection, prompt guard |
| Self-host vs managed | both, one, or neither; VPC-deployable? |
| Governance | RBAC, budgets, audit logs, alerts |
| License | MIT/Apache 2.0 vs proprietary vs open-core with paid features |
| Ops burden | who patches at 2 a.m.; single binary vs multi-service; K8s-native? |
| Security track record | 2026 supply-chain incidents, CVEs, advisories |

### C. Comparative analyses required
1. **Self-hosted showdown:** Bifrost vs GoModel vs Kong AI Gateway vs Envoy AI Gateway vs agentgateway vs Portkey core — on latency, ops burden, license, and governance.
2. **Managed showdown:** OpenRouter vs Cloudflare AI Gateway vs Vercel AI Gateway vs Portkey (Prisma AIRS) vs Helicone — on markup, privacy (DLP/PII), SLA, vendor lock-in.
3. **"No server at all" segment:** RouteHub (Python library), smart routers (Unify/Martian/RouterFleet), and any in-process routing libraries — when is a separate proxy wrong?
4. **Governance showdown:** TrueFoundry vs OptScale AI vs Respan vs Future AGI — on cost chargeback, RBAC, on-prem rights.
5. **Cloud-native:** AWS Bedrock vs Azure AI Foundry vs GCP Vertex AI Gateway — lock-in analysis vs managed third-party.

### D. Risk & supply-chain audit
- Confirm or deny the LiteLLM 2026 supply-chain compromises (two incidents) and their nature.
- For one-api/new-api: document the 2026 CVE cluster and give concrete sandboxing/patching guidance.
- For TensorZero: confirm archival date and whether self-hosted forks exist.
- Flag any candidate whose GitHub shows <1 commit in 90 days or >100 open stale issues.

### E. Output artifacts required from the synthesis sub-agent
1. A validated top-20 (or top-25) tiered list with corrected/updated entries.
2. A decision matrix (Options × criteria, ✅/⚠️/❌, bold best cell).
3. A "pick this if" table mapping constraints → recommendation.
4. Exact `base_url` and config migration examples for the top 3 self-hosted and top 3 managed options.
5. A Mermaid `flowchart TD` schematic: client → LiteLLM → candidate → provider(s), showing where virtual keys, caching, guardrails, and fallbacks sit.
6. A "who owns patching at 2 a.m." recommendation: self-hosted (Bifrost/GoModel/Envoy) vs managed (OpenRouter/Cloudflare/Vercel) with the ops trade-off stated plainly.
7. Open questions remaining after research (evidence gaps).

### F. Confidence & gating (smp5.4pd.md)
- Use internal `confidence_threshold: 0.75`. If below threshold, flag uncertainty and say what evidence is missing — do not fabricate benchmarks or pricing.
- No numeric confidence displayed unless asked.
- Prefer primary sources (GitHub API, official docs, pricing pages) over third-party roundups; cite every claim with URL.
- End with: ⚡ Recommended Next Step (one action, max 2 sentences) and ✨ 3 Suggestions (Tactical | Strategic | Contrarian | Reframe).

---

## Success criteria

The research is complete when a stakeholder can answer, without more research:
- "I want self-hosted but faster than LiteLLM → which one, and what's the base_url?"
- "I want zero ops and compliance → which one?"
- "I want governance + cost chargeback on-prem → which one?"
- "Which of these had 2026 security incidents, and how do I sandbox them?"
- "Do I even need a separate proxy, or an in-process library?"
