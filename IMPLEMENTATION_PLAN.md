# OWL-AGENT PROXY — Implementation Plan (Pre-Code)

**Branch:** `arena/57be4fea-owl-agent-proxy`
**Source:** `RESEARCH_SKILL_LAYERING.md` + `PROMPT_PARALLEL_DEEP_RESEARCH_LITELLM.md`
**Constraint:** No implementation code is written in this phase. This plan defines, sequences, and gates every task. Each task is ≤ 5 minutes and has an explicit verification step.
**Mode per smp5.4pd.md:** Step 4 (Plan) → Step 5 (Execute with checkpoints) → Step 6 (Validate RED-GREEN-REFACTOR)

---

## Phase 0 — Validate the zero-dependency core (prerequisite, before anything else)

| # | Task | Path | Verify |
|---|---|---|---|
| 0.1 | Install OWL offline | `./install-owl.sh --no-live` | Exit code 0; `~/.owl-agent/` created |
| 0.2 | Confirm core imports with no extras | `python3 -c "import proxy_defense, proxy_harvester, mcp_proxy_server"` | No ModuleNotFoundError |
| 0.3 | Run stats | `~/.owl-agent/run.sh stats --json` | JSON pool + source_health present |
| 0.4 | Run verification offline | `~/.owl-agent/run.sh verify --no-live` | All V1–V20 checks pass |

**Gate:** Proceed only if 0.1–0.4 all pass. If any fail, roll back (`--rollback`) and fix before continuing.

---

## Stage 1 — Discover & Research (skills, no code yet)

These are capability definitions, not code changes. Each produces a SKILL.md-style record under `skills/`.

| # | Skill | Source | Verification artifact |
|---|---|---|---|
| 1.1 | find-skills | vercel-labs/skills | `npx skills find <query>` returns results; `skills/owl-proxy/SKILL.md` already exists |
| 1.2 | agent-browser | vercel-labs/agent-browser | Installable via `npx skills add`; compared against browser-use |
| 1.3 | meta-skill (inline concept) | — | This plan document + RESEARCH_SKILL_LAYERING.md serve as the meta-skill output |
| 1.4 | parallel-findall (inline concept) | — | 26-repo GitHub API batch fetch already performed; results in `/tmp/gh_*.json` |

**Gate:** Document each skill's `When to use / When not to use` (pattern after `skills/owl-proxy/SKILL.md`).

---

## Stage 2 — Plan & Architect (design decisions, no code yet)

| # | Decision | Option selected | Rationale | Verification |
|---|---|---|---|---|
| 2.1 | Deployment mode | Bare metal, `install-owl.sh --no-live` | Memory-constrained laptop; no compose overhead | 0.1–0.4 pass |
| 2.2 | Local model runner | Colibri (pure C, CPU+disk-streamed) | Fits 8–16 GB RAM, no GPU; OpenAI `:8000/v1` | colibri README audited |
| 2.3 | Free-tier upstream | FreeRide v3 (`localhost:11343`) | In-response failover across free tiers; OpenAI-compatible | FreeRide README audited |
| 2.4 | Quota discovery | OpenRelay (`localhost:18765`) on demand | Auto-discovers local quotas; not resident | OpenRelay README audited |
| 2.5 | Governed gateway pattern | Hermes-router (study only, not vendored) | 491 tests, cost ledger, budgets, `:8766` | hermes-router README audited |
| 2.6 | Stealth browser | Patchright (default), Camoufox (hardened targets) | Drop-in Playwright stealth; OWL already lists playwright | Stealth research (Sendwin/Scrapfly/CloakBrowser) |
| 2.7 | Repos to adopt | colibri, FreeRide v3, hermes-unlimited-memory or mnemosyne (pick one), opencode2dsh, dsh-better-bridge (cautious) | Each has a clear hook into OWL | 26-repo audit table |
| 2.8 | Repos to skip | ai-gateway-complete, Unlimited-Hermes, obsidian-skills, hermes-kanban, airllm (no GPU), TensorZero (archived), one-api/new-api unpatched | Per audit verdicts | Documented in RESEARCH_SKILL_LAYERING.md |

**Gate:** All 2.1–2.8 decisions recorded (this document). No code written yet.

---

## Stage 3 — Execute & Debug (task sequence, pre-code breakdown)

Each task below is a *planned* unit with inputs, expected output, and verification. Code is written only when the user approves this plan.

### Step 3.1 — Wire colibri as local upstream (read-only configuration)

**Input:** colibri runs at `http://127.0.0.1:8000/v1` (OpenAI-compatible)
**Planned change:** Add `colibri` as a `ProxySource`-style upstream entry in OWL config; document `base_url` mapping
**Verification:** `run.sh fetch http://127.0.0.1:8000/v1/models --json` returns model list (colibri must be running; if not, task is "document only" until colibri is installed separately)
**Time:** ≤ 5 min (config + docs)

### Step 3.2 — Wire FreeRide v3 as free-tier failover upstream

**Input:** FreeRide v3 at `localhost:11343` (OpenAI-compatible)
**Planned change:** Add `freeride` fallback chain to OWL's sticky-session + proxy-rotation logic; document fallback order (nemotron → openrouter/free → qwen3-coder → step-3.5 → deepseek → mistral)
**Verification:** Config parses; fallback chain documented; no runtime test unless FreeRide is running
**Time:** ≤ 5 min (config + docs)

### Step 3.3 — Add memory backend (pick one)

**Options:** hermes-unlimited-memory (SQLite + FTS5 MCP) or mnemosyne (local vault-backed)
**Planned choice:** hermes-unlimited-memory (simpler: SQLite + FTS5, one MCP server)
**Planned change:** Document MCP server command to add to OWL's `mcp` config; map OWL session bindings → memory keys
**Verification:** MCP tool names documented; schema sketch reviewed
**Time:** ≤ 5 min

### Step 3.4 — Add stealth tier (Patchright) as optional browser protocol

**Input:** OWL `browser` protocol already lists `playwright>=1.52` as optional extra
**Planned change:** Document Patchright import-swap pattern (`from patchright.async_api import async_playwright`); add to `stealth` extra docs; note Camoufox for hardened targets
**Verification:** Patchright import pattern documented; no browser launched unless user opts in
**Time:** ≤ 5 min

### Step 3.5 — Borrow hermes-router governance patterns (study only)

**Planned change:** Document the 5-tier classifier ladder, key pooling, immutable cost ledger, budget 402 pattern as *design references* for OWL's `ResilientClient` retries and `SessionAffinityManager`; do NOT vendor hermes-router code
**Verification:** Pattern memo written; no hermes-router dependency added to `pyproject.toml`
**Time:** ≤ 5 min

### Step 3.6 — Integration order (dependency graph)

```
1. Core validation (0.1–0.4) — must pass first
   ↓
2. Skill definitions (1.1–1.4) — documentation only
   ↓
3. Architecture decisions (2.1–2.8) — documentation only
   ↓
4. Colibri upstream wiring (3.1) — depends on 0.x
   ↓
5. FreeRide failover wiring (3.2) — depends on 0.x
   ↓
6. Memory backend (3.3) — depends on 0.x
   ↓
7. Stealth tier docs (3.4) — depends on 0.x
   ↓
8. Governance pattern memo (3.5) — depends on 0.x
```

**Verification gate after each:** run `run.sh stats --json` and confirm no regression in pool health.

---

## Red flags / stop conditions

| Condition | Action |
|---|---|
| `install-owl.sh --no-live` fails | Stop; roll back; do not proceed to Stage 3 |
| Any 2.1–2.8 decision disputed | Revisit Stage 2 before coding |
| A selected upstream (colibri/FreeRide/OpenRelay) is unreachable | Mark task "document only"; do not hardcode a hard dependency |
| User says "write code now" | Move to Step 5 (Execute) with checkpoints; this plan is the task backlog |

---

## ⚡ Recommended Next Step

Review and approve this plan (especially the repo adopt/skip list in 2.7 and the integration order in 3.6). Once approved, the next phase is Step 5 (Execute) — writing code against these pre-defined, gated tasks.

## ✨ 3 Suggestions

- **Tactical:** Run `./install-owl.sh --no-live` and `run.sh stats --json` right now to confirm the zero-dependency core is healthy before any integration task is touched.
- **Strategic:** Keep OWL as a proxy-defense layer *in front of* colibri/FreeRide/hermes-router rather than merging their code in — that preserves OWL's low dependency floor and makes each upstream independently replaceable.
- **Reframe:** The plan above is the complete "before code" specification. If a task can't be verified in ≤ 5 minutes, split it further — that's the smp5.4pd.md atomicity rule.
