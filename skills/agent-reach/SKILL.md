---
name: agent-reach
description: Read and search across Twitter/X, Reddit, YouTube, GitHub, Bilibili, XiaoHongShu, RSS, and any web page — all from a single CLI. Unified internet reachability for agents.
source: panniantong/agent-reach
pipeline_stage: DEFINE
---

# agent-reach

**Pipeline Stage:** DEFINE (Stage 1 – Discover & Research)

**Purpose:** Read and search the internet across 9+ platforms via unified CLI. Provides agent reachability to web content, social media, and documentation sources.

**When to use:** During DEFINE stage for research-heavy pipelines when you need to read content from URLs, search across platforms, or check channel health.

**Process:**
1. Check if agent-reach is installed: `agent-reach doctor`
2. Install if needed: `pip install https://github.com/Panniantong/agent-reach/archive/main.zip`
3. Run `agent-reach install --env=auto` to install dependencies
4. Use `agent-reach` to read URLs or search across platforms

**Supported platforms:** Twitter/X, Reddit, YouTube, GitHub, Bilibili, XiaoHongShu, RSS, any web page

**Triggers:** "search Twitter/Reddit/YouTube", "read this URL", "find posts about"

**Handoff contract:**
- Input: URL or search query
- Output: Content from the target platform
- Handoff to: PLAN stage (writing-plans → executing-plans)

**Source:** https://www.skills.sh/panniantong/agent-reach

**Install commands:**
```bash
pip install https://github.com/Panniantong/agent-reach/archive/main.zip
agent-reach install --env=auto
agent-reach doctor
```
