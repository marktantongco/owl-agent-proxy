# CommandCode Proxy Compatibility Analysis

**Project:** marktantongco/owl-agent-proxy  
**Branch:** `arena/36744717-owl-agent-proxy`  
**Objective:** Investigate whether commandcode proxy can be placed before the upstream with Hermes and OpenCode, and document findings.

---

## 1. CommandCode Proxy Repos Investigated

| Repo | Description | Protocol | Port | Key Features |
|------|-------------|----------|------|--------------|
| **miku-hermes/commandcode-proxy** | Command Code API → OpenAI/Anthropic compatible reverse proxy | OpenAI + Anthropic | 3050/3000 | Device fingerprint, multi-account pool, smart routing, admin console |
| **thaolaptrinh/commandcode-api-proxy** | Command Code → OpenAI-compatible proxy | OpenAI | 8787 | `--setup-opencode`, model aliases, reasoning effort, Anthropic /v1/messages |
| **wjf1/multi-upstream-gateway** | Multi-upstream AI gateway (CommandCode usable, Freebuff/CodeBuddy roadmap) | OpenAI + Anthropic | - | Multi-upstream, compliance gate, credential encryption |
| **Lythaeon/cmdcode** | 5 protocol frontends → hot-reloadable upstream routing | OpenAI, Anthropic, Gemini, Responses, Ollama | - | command-code adapter with vault auth, taste injection, rate limiting |
| **cwf818/cmc-proxy** | GOAT/commandcode → localhost proxy for Claude Code & Codex | OpenAI, Anthropic, Responses | - | Auto failover rotation, prefix-cache transforms, JSONL logging |

---

## 2. Compatibility with Hermes and OpenCode

### Verdict: YES — CommandCode proxy can be placed before the upstream with both Hermes and OpenCode.

### Evidence

**Hermes Agent compatibility** (from provider setup research):
- Hermes Agent natively supports `commandcode` and `commandcode-anthropic` providers (source: hermes-tutorials.dev/blog/provider-setup/)
- Env var: `COMMANDCODE_API_KEY` maps to provider ID `commandcode`
- Hermes routes through `commandcode-anthropic` for Claude via CommandCode

**OpenCode compatibility** (from commandcode-api-proxy research):
- `commandcode-api-proxy --setup-opencode` generates OpenCode provider config at `~/.config/opencode/opencode.json`
- Config points baseURL at `http://127.0.0.1:8787/v1` with `apiKey: "proxy-managed"`
- OpenCode uses `@ai-sdk/openai-compatible` npm package for the provider

**Placement in the token plane:**
```
Client -> gateway token -> Nginx/Caddy edge -> gateway (:20128)
    -> Tier 1: Free catalog (15 providers)
    -> Tier 2: Paid fallback (Anthropic/OpenAI)
    -> Tier 3: Local Ollama/vLLM
                  ^
                  |
           CommandCode proxy (upstream of tier 3 or standalone tier)
```

The CommandCode proxy acts as an **upstream adapter** that can be inserted:
- **As tier 3 replacement**: Replace Ollama with CommandCode proxy as the free local fallback
- **As an additional tier**: Insert CommandCode between free catalog and paid fallback
- **Alongside Hermes**: Hermes Agent can use `commandcode` provider pointing to the proxy

### Integration pattern

```yaml
# gateway/free_catalog/providers.json — add CommandCode as tier-1 provider
{
  "id": "commandcode",
  "name": "CommandCode",
  "base_url": "http://127.0.0.1:8787/v1",
  "openai_compatible_url": "http://127.0.0.1:8787/v1",
  "api_key_env": "COMMANDCODE_API_KEY",
  "models": [...]
}
```

---

## 3. Five AI Provider Agent Ideas Compatible with the Proxy

### Idea 1: Command Code Router Agent
**Role:** Intelligent router that selects between CommandCode free tier, free catalog providers, and paid fallback based on task complexity and client budget.

**How it works:**
- Sends simple tasks (summarization, extraction) to CommandCode free tier via proxy
- Routes complex reasoning to paid fallback (Anthropic/OpenAI)
- Falls back to local Ollama when all cloud circuits are open
- Logs routing decisions for audit

**Compatible with:** OpenCode v2, Hermes-agent, commandcode-api-proxy

---

### Idea 2: Obsidian Knowledge Agent
**Role:** Autonomous agent that reads/writes Obsidian notes using obsidian-skills, executes tasks via hermes-kanban Kanban boards, and persists results to JSON Canvas.

**How it works:**
- Uses obsidian-skills (50.8k stars) to teach agent Obsidian CLI and open formats (Markdown, Bases, JSON Canvas)
- hermes-kanban (GumbyEnder, 275 stars) turns Hermes into autonomous project executor using Kanban boards inside Obsidian
- Agent reads Kanban board → executes task → writes result back to Obsidian
- All through the governed gateway with provider key isolation

**Compatible with:** obsidian-skills, hermes-kanban, gateway auth + audit

---

### Idea 3: Hermes Web Research Agent
**Role:** Personalized web workbench agent that performs research with memory-aware onboarding and artifact persistence.

**How it works:**
- Uses hermes-for-web (reallygood83, 83 stars) — personalized web workbench for Hermes Agent
- Setup packs, artifacts, memory-aware onboarding
- Agent browses web, synthesizes findings, stores artifacts in Obsidian via hermes-kanban
- Gateway routes web search queries through free catalog (DuckDuckGo, Exa, etc.) with budget enforcement

**Compatible with:** hermes-for-web, hermes-kanban, free catalog (search providers)

---

### Idea 4: Multi-Provider Failover Agent
**Role:** Agent that automatically fails over between providers when circuits open or budgets exhaust, maximizing uptime.

**How it works:**
- Monitors circuit breaker state per provider
- On circuit open: routes to next available provider in tier order
- On budget exhausted: drops to local Ollama/vLLM (tier 3, free)
- On all circuits open: queues request with retry backoff
- Audit log captures all failover decisions

**Compatible with:** gateway circuit breaker, free catalog, paid fallback, local Ollama

---

### Idea 5: Cost-Optimized Coding Agent
**Role:** Coding agent that uses free providers for routine tasks and paid providers only for complex reasoning, minimizing cost.

**How it works:**
- Simple code generation/editing → free catalog (Groq, OpenRouter, Kilo Code)
- Complex architecture/reasoning → paid fallback (Anthropic Claude)
- Local testing/validation → Ollama/vLLM (tier 3)
- Budget alerts when approaching cost ceiling
- Cache hits for repeated queries (Redis cache in gateway)

**Compatible with:** OpenCode v2, free catalog, paid fallback, Redis cache

---

## 4. Obsidian Memory Integration — Structural Design

**Source repos (from image):**
1. **kepano/obsidian-skills** — 50.8k stars — Agent skills for Obsidian: Obsidian CLI, Markdown, Bases, JSON Canvas
2. **GumbyEnder/hermes-kanban** — 275 stars — Obsidian plugin + Hermes skill for autonomous Kanban project execution
3. **reallygood83/hermes-for-web** — 83 stars — Personalized web workbench for Hermes Agent with setup packs, artifacts, memory-aware onboarding

### Integration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Obsidian Vault (Markdown/JSON Canvas)    │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │ obsidian-   │  │ hermes-     │  │ hermes-for-       │   │
│  │ skills      │  │ kanban      │  │ web               │   │
│  │ (CLI/API)   │  │ (Kanban)    │  │ (Workbench)       │   │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘   │
│         │                │                  │               │
│         └────────────────┴──────────────────┘               │
│                           │                                   │
│                    ┌────────▼────────┐                       │
│                    │   Hermes Agent  │                       │
│                    │   (ACP Client)  │                       │
│                    └────────┬────────┘                       │
│                             │                                   │
│                    ┌────────▼────────┐                       │
│                    │  Governed       │                       │
│                    │  Gateway (:20128)│                      │
│                    │  (auth + route   │                       │
│                    │   + cache + bill)│                       │
│                    └─────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

### Structural Memory Layout (Obsidian Vault)

```
vault/
├── .obsidian/
│   ├── plugins/
│   │   ├── hermes-kanban/          # GumbyEnder/hermes-kanban
│   │   └── obsidian-skills/        # kepano/obsidian-skills
│   └── workspace.json
├── agents/
│   ├── hermes/
│   │   ├── skills/                 # Hermes agent skills
│   │   ├── memory/                 # Memory-aware onboarding (hermes-for-web)
│   │   └── config.json             # Hermes agent config
│   ├── tasks/
│   │   ├── kanban.md               # Kanban board (hermes-kanban)
│   │   └── inbox.md                # Task inbox
│   └── research/
│       ├── web/                    # hermes-for-web artifacts
│       ├── findings.md             # Research findings
│       └── cache/                  # Cached research results
├── knowledge/
│   ├── bases/                      # Obsidian Bases (obsidian-skills)
│   ├── canvas/                     # JSON Canvas files
│   └── markdown/                   # Markdown notes
├── gateway/
│   ├── logs/                       # Gateway audit logs (redacted)
│   └── routing-decisions.json      # Route decision history
└── providers/
    ├── commandcode/                # CommandCode proxy config
    └── free-catalog/               # Free catalog provider config
```

### ACP (Agent Control Protocol) Integration Points

| Integration Point | Source Repo | Purpose |
|-------------------|-------------|---------|
| Obsidian CLI access | kepano/obsidian-skills | Teach agent to use Obsidian CLI and open formats |
| Kanban task execution | GumbyEnder/hermes-kanban | Turn Hermes into autonomous project executor |
| Web research workbench | reallygood83/hermes-for-web | Personalized web workbench with memory-aware onboarding |
| Gateway auth | owl-agent-proxy/gateway/auth.py | Bearer token validation, provider key isolation |
| Route logging | owl-agent-proxy/gateway/audit.py | Redacted audit logging of all agent LLM calls |

### Memory Integration Flow

1. **Onboarding** (hermes-for-web): Agent reads setup packs, artifacts, memory-aware onboarding docs from vault
2. **Task intake** (hermes-kanban): Agent reads Kanban board, claims next task, moves to "in progress"
3. **Execution** (obsidian-skills): Agent reads source notes, writes results back to Markdown/JSON Canvas
4. **LLM call** (gateway): Agent sends request through governed gateway with bearer token
5. **Result persistence** (all three): Agent writes LLM response to appropriate vault location
6. **Task completion** (hermes-kanban): Agent moves Kanban card to "done", logs completion

### ACP Provider Config Example

```json
{
  "providers": {
    "obsidian": {
      "name": "Obsidian Knowledge",
      "package": "@opencode/ai/providers/obsidian",
      "settings": {
        "vault_path": "./vault",
        "cli_path": "/usr/local/bin/obsidian",
        "formats": ["markdown", "bases", "json_canvas"]
      }
    },
    "hermes-kanban": {
      "name": "Hermes Kanban",
      "package": "@opencode/ai/providers/hermes-kanban",
      "settings": {
        "board_path": "./vault/agents/tasks/kanban.md",
        "auto_execute": true
      }
    },
    "hermes-for-web": {
      "name": "Hermes Web",
      "package": "@opencode/ai/providers/hermes-for-web",
      "settings": {
        "workbench_path": "./vault/agents/research/web",
        "memory_aware": true
      }
    },
    "gateway": {
      "name": "Governed Gateway",
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "http://127.0.0.1:20128/v1",
        "apiKey_env": "OWL_GATEWAY_TOKEN"
      }
    }
  }
}
```

### Key Integration Benefits

- **Memory persistence**: All agent interactions stored in Obsidian vault (Markdown, Bases, JSON Canvas)
- **Provider key isolation**: Gateway holds all provider keys; agents only present bearer tokens
- **Audit trail**: Every LLM call logged with redacted provider keys
- **Budget governance**: Per-agent token/cost limits enforced at gateway level
- **Failover**: Automatic fallback between free catalog, paid, and local providers
