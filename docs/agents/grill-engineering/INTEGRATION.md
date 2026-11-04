# Grill Engineering Integration — OWL Agent Proxy

## Overview

`grill-engineering` (`agent-run`) is the delivery automation layer that sits at the end of the skills workflow:

```
grill-me / grill-with-docs  →  to-spec  →  to-tickets  →  agent-run (grill-engineering)
     clarify idea                 spec      GitHub tickets   implement + verify + repair
```

After Matt Pocock Skills breaks work into GitHub tickets (via `to-spec` + `to-tickets`), `agent-run` runs Codex to implement the tickets in dependency order, with a separate Codex agent verifying results against requirements. Implementation → verification → fixes runs in a loop until each ticket passes.

## Installed Location

- Source: `tools/grill-engineering/` (cloned from `https://github.com/GRD-Chang/grill-engineering`)
- Python package: `agent-run` (installed via `pip install --no-build-isolation --no-deps .`)
- CLI entry point: `agent-run`

## Prerequisites

`grill-engineering` requires the following on the host:

| Tool | Minimum | Purpose |
|------|---------|---------|
| Python | 3.11+ | Runs the `agent-run` controller |
| Git | 2.40+ | Manages independent clones of the remote |
| GitHub CLI (`gh`) | with `--paginate --slurp --method --header` | GitHub API operations |
| Codex CLI | authenticated (`codex login`) | Development and verification agents |
| bubblewrap (`bwrap`) | — | Isolated workspace sandboxing |
| OpenSSL | — | Cryptographic operations |
| user systemd | — | Transient unit execution |

Install via:

```bash
# From the grill-engineering directory
cd tools/grill-engineering
sh setup.sh   # host preparation (Linux only)
sh install.sh # install agent-run as a Python package
```

## Workflow Integration with OWL Agent Proxy Skills

### Step 1: Clarify and Specify (mattpocock/skills)

Use `grill-with-tail` (with `ponytail` recommendations) or `grill-with-docs` to work through a technical decision. The interview produces:

- `GLOSSARY.md` — shared vocabulary
- ADRs — architecture decision records

### Step 2: Convert to Spec (mattpocock/skills)

Use `to-spec` to synthesize a product-only PRD from the grilling session output.

### Step 3: Convert to Tickets (mattpocock/skills)

Use `to-tickets` to break the PRD into GitHub issues/tickets with dependency ordering.

### Step 4: Implement and Verify (grill-engineering / agent-run)

For each parent issue (the ticket chain root):

```bash
# Discover available runs
agent-run runs --repo marktantongco/owl-agent-proxy

# Start automated delivery for a parent issue
agent-run run <parent-issue-number> --repo marktantongco/owl-agent-proxy

# Check status
agent-run status --parent <parent-issue> --repo marktantongco/owl-agent-proxy --json

# View history
agent-run history --parent <parent-issue> --repo marktantongco/owl-agent-proxy --json

# Resume after a human blocker or failure
agent-run resume --parent <parent-issue> --repo marktantongco/owl-agent-proxy --message "<context>"

# Approve the final PR (only with explicit human approval)
agent-run approve --parent <parent-issue> --repo marktantongco/owl-agent-proxy
```

### Step 5: Complete the Loop

After `agent-run` delivers:

1. Verify tests pass: `python -m pytest tests/ -q`
2. Run CI/CD check: `bash .github/scripts/ci-check.sh`
3. Verify install: `./run.sh verify --no-live`
4. Merge to `main`

## Connection to Existing Skills

| Skill | Role in the Chain |
|-------|-------------------|
| `grill-with-tail` | Design interview with docs + Ponytail recommendations |
| `grill-with-docs` | Stateful grilling (writes GLOSSARY.md + ADRs) |
| `grilling` | Decision-by-decision clarification primitive |
| `domain-modeling` | Product concept, boundary, invariant modeling |
| `to-spec` | PRD synthesis from grilling output |
| `to-tickets` | GitHub issue/ticket breakdown from PRD |
| `agent-run` (grill-engineering) | **Delivery automation** — implement, verify, repair, merge |
| `grill-powers` | Product PRD approval → delegate to `agent-run` for delivery |

## Commands Reference

```bash
# List all runs
agent-run runs --repo marktantongco/owl-agent-proxy

# Start delivery for a parent issue
agent-run run <issue-number> --repo marktantongco/owl-agent-proxy

# Check current status
agent-run status --parent <issue-number> --repo marktantongco/owl-agent-proxy --json

# View full history
agent-run history --parent <issue-number> --repo marktantongco/owl-agent-proxy --json

# Resume after human blocker
agent-run resume --parent <issue-number> --repo marktantongco/owl-agent-proxy --message "<answer>"

# Requeue after requirement change
agent-run requeue --parent <issue-number> --repo marktantongco/owl-agent-proxy

# Approve final PR (human approval required)
agent-run approve --parent <issue-number> --repo marktantongco/owl-agent-proxy

# Stop an active run (preserves work)
agent-run stop --parent <issue-number> --repo marktantongco/owl-agent-proxy

# Doctor check (read-only)
agent-run doctor

# User settings (models, effort, limits)
agent-run settings
agent-run policy
```

## Boundaries

- `agent-run` develops in an **independent clone** of the remote — your local checkout is never modified
- Only pushed content reaches the agent; you update your own files, index, and branches
- Human approval is required for the final PR merge
- When human input is needed, the run pauses and saves its work; use `resume` to continue
- Runs use your Codex account quota; models and repair limits are configurable via `agent-run settings`
