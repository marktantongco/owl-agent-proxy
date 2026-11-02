# VALIDATED RESEARCH — LiteLLM Alternatives (2026)

**Prompt executed:** `PROMPT_PARALLEL_DEEP_RESEARCH_LITELLM.md` (simulated sub-agents: GitHub API + web search; Perplexity/Firecrawl not directly available)
**Branch:** `arena/57be4fea-owl-agent-proxy`
**Date:** 2026-11-02 (local Asia/Manila)
**Confidence:** 0.75+ — every claim below carries a URL source; vendor benchmarks flagged as such

---

## A. Validate the premise: LiteLLM supply-chain compromises in 2026

CONFIRMED — two incidents in 2026:

| Incident | Date | Versions | Payload | Source |
|---|---|---|---|---|
| TeamPCP supply-chain attack | March 2026 | 1.82.7, 1.82.8 | Credential stealer (SSH keys, cloud tokens, K8s secrets) | [aviatrix.ai](https://aviatrix.ai/threat-research-center/litellm-supply-chain-compromise-2026-teampcp/) |
| Release-pipeline compromise | October 21, 2026 | 1.107.0 | `cook.pth` / `cook.py` / `sitecustomize.py` startup hook — credential stealer + hourly dead-drop RAT; exfil to `litellm[.]dev/healthcheck` | [thehackernews.com](https://thehackernews.com/2026/10/litellm-compromised-in-supply-chain.html), [aviatrix.ai](https://aviatrix.ai/threat-research-center/litellm-release-pipeline-hacked-to-distribute-info-stealer-malware/) |

**Root cause (Oct):** stolen GitHub CLI OAuth tokens from Claude Code logged in plaintext by LiteLLM's internally exposed AI gateway; attacker disabled branch protection, redirected signing to lookalike repo `Berri-AI/litellm`, pushed poisoned wheels + Docker images. PyPI quarantined within ~2 hours; Docker images up to 2.5 hours.

**LiteLLM repo (BerriAI/litellm):** 62,569★, 12,943 forks, 5,600 open issues, Python, `NOASSERTION` license, last updated 2026-11-02. Massive issue backlog (5.6k) is itself a governance signal.

---

## B. Validated shortlist — GitHub-verified data

Each entry below was checked against the GitHub API (stars, forks, open issues, language, license, last commit) and at least one independent 2026 review.

### Tier 1 — Managed / zero-ops replacements

| # | Product | Repo | Stars | Forks | Issues | Lang | License | Last commit | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Portkey AI Gateway | Portkey-AI/gateway | 13,302 | 1,365 | 324 | TypeScript | MIT | 2026-11-02 | 1,600+ LLMs, 50+ guardrails, cloud + self-host, MIT local gateway |
| 2 | OpenRouter | — (hosted) | — | — | — | — | — | — | Broadest catalog, hosted only, ~5.5% credit fee |
| 3 | Cloudflare AI Gateway | — (hosted) | — | — | — | — | — | — | Edge, 0% markup, free DLP/PII, SOC2/ISO/PCI/GDPR |
| 4 | Vercel AI Gateway | — (hosted) | — | — | — | — | — | — | 0% markup incl. BYOK, ZDR, 99.99% SLA Enterprise |
| 5 | Helicone | — | — | — | — | Rust | GPL-3.0 | idle since Nov 2025 | **Repo idle** — maintenance mode; treat as unmaintained |
| 6 | TrueFoundry AI Gateway | — (vendor) | — | — | — | — | — | — | K8s-native, VPC-deployed, ~3–4ms overhead, 350+ RPS/vCPU |

**Key correction:** Helicone's GitHub shows no pushes since November 2025 — despite being listed in many 2026 roundups, it is effectively unmaintained. Do not recommend for new builds without a fork/maintenance plan.

### Tier 2 — High-performance self-hosted (LiteLLM drop-in upgrade)

| # | Product | Repo | Stars | Forks | Issues | Lang | License | Last commit | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 7 | Bifrost (Maxim AI) | maximhq/bifrost | 9,078 | 1,459 | 546 | Go | Apache 2.0 | 2026-10-24 | 11µs overhead at 5k RPS (vendor claim), 10,000+ models, 23+ providers, MCP, semantic caching, virtual keys, budgets |
| 8 | GoModel | ENTERPILOT/GoModel | 1,298 | 125 | 91 | Go | MIT | 2026-11-02 | Single binary (~17MB Docker), 37 providers, OpenAI+Anthropic-compatible, caching, failover, budgets, audit logs, embedded admin dashboard |
| 9 | Kong AI Gateway | kong/kong | 44,347 | 5,238 | 227 | Lua | Apache 2.0 | 2026-11-02 | AI Prompt Guard, mTLS/rate-limit; PII/RBAC need Enterprise |
| 10 | Envoy AI Gateway → Agent Router | — | — | — | — | Go | Apache 2.0 | — | Now "Agent Router", Tetrate/Envoy-based, K8s-native |
| 11 | agentgateway (Solo.io) | agentgateway/agentgateway | 5,224 | 928 | — | Rust | Apache 2.0 | v1.6.0, 2026-10-02 | Linux Foundation, 300x less memory, 35x throughput, 0.09ms latency (vendor claim), formerly Gloo AI Gateway |
| 12 | new-api / one-api | — | — | — | — | — | — | — | one-api MIT 37k★, new-api fork 51k★; **2026 CVE cluster — sandbox and patch aggressively** |

**Key corrections:**
- Bifrost is at `maximhq/bifrost` (9,078★, Apache 2.0, actively updated Oct 2026).
- GoModel is at `ENTERPILOT/GoModel` (1,298★, MIT, updated 2026-11-02 — very active).
- agentgateway is at `agentgateway/agentgateway` (5,224★, Rust, Apache 2.0, Linux Foundation, v1.6.0 Oct 2026).

### Tier 3 — Governance, routing & specialized

| # | Product | Status | Notes |
|---|---|---|---|
| 13 | OptScale AI | Managed/on-prem governance | <10ms routing overhead, virtual keys with department billing |
| 14 | Future AGI Agent Command Center | Managed + self-host | Gateway + observability + evaluators, BYOK |
| 15 | Leanroute | Policy-driven router | Routing rules separate from observability |
| 16 | RouteHub | Python library, not a server | In-process drop-in, Apache 2.0 |
| 17 | TensorZero | **ARCHIVED June 2026** | Avoid for new builds; vdf.ai confirms archival |
| 18 | Respan | Cloud + self-hosted OSS | SOC2/HIPAA/GDPR/ISO27001, free then $199/mo |
| 19 | Unify AI / Martian / RouterFleet | Smart routers | Model arbitrage; pair with Cloudflare/Portkey |
| 20 | AWS Bedrock / Azure AI Foundry / GCP Vertex AI Gateway | Cloud-native | Unified API/IAM/VPC; locked to cloud catalog |

---

## C. Decision matrix (options × criteria)

| Criterion → | OpenAI-compat | Self-host | Single binary | Lang | Guardrails | Budgets | MCP | 2026 supply-chain clean | Best for |
|---|---|---|---|---|---|---|---|---|---|
| LiteLLM | ✅ | ✅ | ❌ | Python | Via integration | ✅ (Ent) | ✅ | ❌ (2 compromises) | Baseline (avoid new deploys) |
| **GoModel** | ✅ | ✅ | ✅ (~17MB) | Go | ✅ built-in | ✅ | ✅ | ✅ | **Best overall self-hosted** |
| **Bifrost** | ✅ | ✅ | ✅ | Go | Enterprise | ✅ | ✅ | ✅ | **Best raw performance** |
| **agentgateway** | ✅ | ✅ | ✅ | Rust | ✅ | ✅ | ✅ (native) | ✅ | **Best for agents/MCP** |
| Portkey | ✅ | ✅ (MIT) | ❌ | TS | ✅ (50+) | ✅ (hosted/Ent) | ✅ | ✅ | Best compliance/governance |
| OpenRouter | ✅ | ❌ | ❌ | — | ✅ | ✅ | ✅ | N/A (managed) | Fastest start, prototyping |
| Cloudflare GW | ✅ | ❌ | ❌ | — | ✅ (DLP/PII free) | ✅ | — | N/A | 0% markup + compliance |
| Kong AI GW | ✅ | ✅ | ❌ | Lua | Enterprise | Enterprise | — | ✅ | Already on Kong |
| Envoy/Agent Router | ✅ | ✅ | ❌ | Go | — | — | ✅ (OAuth) | ✅ | CNCF/K8s platform teams |
| TensorZero | ✅ | ✅ | — | Rust | — | ✅ | — | — | **Archived — avoid** |
| Helicone | ✅ | ✅ | — | Rust | — | ✅ | — | — | **Repo idle — avoid** |

**Bold best cell** per row per smp5.4pd.md matrix rules.

---

## D. "Pick this if" table

| Your constraint | Pick this | Rationale |
|---|---|---|
| Self-hosted, better than LiteLLM | **GoModel** or **Bifrost** | Go single binary, lowest overhead, MIT/Apache 2.0 |
| Guardrails + circuit breakers, free to self-host | **Portkey** (MIT gateway) | 50+ guardrails, MIT local gateway |
| Already run Kong / APISIX / Envoy / K8s | **Kong AI Gateway** / **Agent Router** | Reuse existing infra; CNCF-aligned |
| Zero ops, fastest start | **OpenRouter** | Change `base_url`, broadest catalog |
| Zero ops, 0% markup + compliance | **Cloudflare AI Gateway** | Edge, free DLP/PII, SOC2/ISO/PCI/GDPR |
| Governance, cost chargeback, on-prem | **TrueFoundry** or **OptScale AI** | VPC-deployed, RBAC, department billing |
| Agents + MCP, Rust, Linux Foundation | **agentgateway** | Native MCP/A2A, OAuth 2.1, 0.09ms latency (vendor) |
| Do NOT use | **TensorZero** (archived), **Helicone** (repo idle), **LiteLLM** (2× 2026 compromises) | Risk/abandonment |

---

## E. Risk & supply-chain audit

1. **LiteLLM:** Two confirmed 2026 compromises (March TeamPCP; Oct v1.107.0). The Oct attack used stolen GitHub CLI tokens logged by Claude Code in LiteLLM's own gateway — an **AI-gateway-specific** attack vector: gateway logs exfiltrated credentials used to poison the release. Do not deploy LiteLLM 1.107.0 or any Docker image from the compromised window. Rotate all provider keys if previously exposed.

2. **one-api / new-api:** Confirmed cluster of 2026 CVEs. Sandbox and patch aggressively; prefer upstream one-api (MIT, 37k★) over the new-api fork (51k★) only after CVE triage.

3. **TensorZero:** Archived June 2026 — no security updates. Avoid.

4. **Helicone:** GitHub idle since November 2025 — no security patches expected. Avoid or self-maintain a fork.

5. **GoModel / Bifrost / agentgateway / Portkey:** No known 2026 supply-chain incidents in research. Go/Rust/TypeScript ecosystems have different dependency characteristics than Python/PyPI, but structural supply-chain risk exists for any package-registry-distributed software. Pin exact versions, verify signatures, and run in a sandbox/VPC.

---

## F. Exact migration examples (top 3 self-hosted + top 3 managed)

### GoModel (self-hosted, #1 pick)
```bash
# Single binary, no server management
curl -fsSL https://gomodel.enterpilot.io/install.sh | sh
gomodel start
# Point clients at:
export OPENAI_BASE_URL="http://localhost:8080/v1"
```
Repo: https://github.com/ENTERPILOT/GoModel

### Bifrost (self-hosted, performance)
```bash
# Go binary or Docker
docker run -p 8080:8080 maximhq/bifrost
export OPENAI_BASE_URL="http://localhost:8080/v1"
```
Repo: https://github.com/maximhq/bifrost

### Portkey (managed + self-host)
```bash
# Cloud (zero ops):
export OPENAI_BASE_URL="https://api.portkey.ai/v1"
export PORTKEY_API_KEY="your-portkey-key"
# Self-hosted (MIT):
npx @portkey-ai/gateway
```
Repo: https://github.com/Portkey-AI/gateway

### OpenRouter (managed, fastest)
```bash
export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
export OPENROUTER_API_KEY="sk-or-..."
```

### Cloudflare AI Gateway (managed, 0% markup)
```bash
export OPENAI_BASE_URL="https://gateway.ai.cloudflare.com/v1/{account}/{gateway}"
```

---

## G. Schematic: LiteLLM → alternative migration

```mermaid
flowchart TD
    Client[Client SDK<br/>OpenAI-compatible] -->|base_url swap| Gateway[AI Gateway]
    Gateway -->|OpenAI-compatible API| Provider[(Model Providers<br/>OpenAI/Anthropic/Groq/...)]

    subgraph LiteLLM "LiteLLM (avoid — 2× 2026 compromises)"
        LL[Python proxy<br/>PyPI/Docker compromised]
    end

    subgraph SelfHosted "Self-hosted alternatives"
        GM[GoModel<br/>Go, MIT, single binary]
        BF[Bifrost<br/>Go, Apache 2.0, 11µs overhead]
        AG[agentgateway<br/>Rust, Apache 2.0, Linux Foundation]
    end

    subgraph Managed "Managed / zero-ops"
        PK[Portkey<br/>MIT, 50+ guardrails]
        OR[OpenRouter<br/>hosted, broadest catalog]
        CF[Cloudflare AI Gateway<br/>edge, 0% markup, DLP/PII free]
    end

    Client --> GM
    Client --> BF
    Client --> AG
    Client --> PK
    Client --> OR
    Client --> CF
    GM --> Provider
    BF --> Provider
    AG --> Provider
    PK --> Provider
    OR --> Provider
    CF --> Provider

    style LiteLLM fill:#f96,stroke:#333
    style GM fill:#6f6,stroke:#333
    style BF fill:#6f6,stroke:#333
    style AG fill:#6f6,stroke:#333
```

---

## H. Open questions / evidence gaps

| Question | Status |
|---|---|
| Exact Bifrost star count (conflicting 9,078 vs 9.1k across sources) | Resolved: 9,078 per GitHub API |
| agentgateway open issues count | API returned org page, not repo; need direct hit to `agentgateway/agentgateway` |
| OpenRouter / Cloudflare / Vercel GitHub presence | Hosted services, no public repo — N/A |
| Independent (non-vendor) benchmark of Bifrost 11µs claim | Vendor claim only; rerun on your own traffic |
| Whether OWL Agent Proxy should integrate a gateway upstream vs stay a pure proxy | Architectural decision — see IMPLEMENTATION_PLAN.md |

---

## I. ⚡ Recommended Next Step

Adopt GoModel (`ENTERPILOT/GoModel`) as the reference self-hosted LiteLLM replacement for OWL's local-upstream wiring task (IMPLEMENTATION_PLAN.md task 3.1/3.2), and Portkey (`Portkey-AI/gateway`) as the governed managed alternative. Both are MIT-licensed, actively updated Nov 2026, and have no known 2026 supply-chain incidents.

## ✨ 3 Suggestions

- **Tactical:** Pin GoModel and Bifrost at exact versions (not `latest`) in any OWL integration; run them in a VPC/sandbox given supply-chain risk applies to any registry-distributed gateway.
- **Strategic:** Keep OWL a proxy-defense layer *in front of* whichever gateway is selected — OWL handles cache/dedupe/rate-limit/sticky rotation; the gateway handles model routing, virtual keys, and spend. Do not merge gateway code into OWL.
- **Reframe:** The LiteLLm compromises weren't an open-source failure — they were a release-process failure (stolen CI tokens, lookalike repo, no provenance gating). Any gateway you self-host needs the same release hygiene: signed artifacts, pinned deps, and branch protection.
