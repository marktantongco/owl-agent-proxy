---
name: exa-web-search-free
description: Free AI search via Exa MCP. Neural search for web, code, and company research. No API key required. Requires mcporter configured with Exa MCP server.
source: sundial-org/awesome-openclaw-skills
pipeline_stage: DEFINE
---

# exa-web-search-free

**Pipeline Stage:** DEFINE (Stage 1 – Discover & Research)

**Purpose:** Free AI-powered web search via Exa MCP. Provides neural search for web, code, and company research without requiring an API key.

**When to use:** During DEFINE stage for research-heavy pipelines when you need high-quality AI search results, code search, or company research.

**Setup:**
```bash
mcporter list exa
mcporter config add exa https://mcp.exa.ai/mcp
```

**Core tools:**
- `company_research_exa` - Research companies for business info and news
- `web_search_exa` - Search the web
- `deep_search_exa` - Deep research on a topic

**Handoff contract:**
- Input: Search query or research topic
- Output: AI-enriched search results with citations
- Handoff to: PLAN stage (domain-modeling → to-spec)

**Install:**
```bash
npx skills add sundial-org/awesome-openclaw-skills --skill exa-web-search-free --agent '*' -y
```

**Source:** https://www.skills.sh/sundial-org/awesome-openclaw-skills/exa-web-search-free
