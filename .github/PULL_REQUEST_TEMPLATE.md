# What this changes

<!-- One or two sentences. If you cannot state it in one, the PR is probably two. -->

## Where it sits in the stack

Do not re-derive the layers from the README. Read the generated map:

- **`docs/architecture/MODULE_GRAPH.md`** — four layers, every first-party
  import edge with its rationale, upward edges, cycles, module sizes.
  Generated from the AST by `scripts/gen-architecture.py`; CI fails if it is stale.

Layers, lowest to highest:

| Layer | Plane | Modules |
|-------|-------|---------|
| 1 | Supply — harvested inventory, trust | `proxy_harvester` |
| 2 | Egress core — cache, dedupe, pool, protocol ladder | `proxy_defense` |
| 3 | Ingress — optional entry points | `reverse_proxy`, `gateway/*` |
| 4 | Agent surface — MCP + skills | `mcp_proxy_server`, `skills/` |

An edge may point down or sideways. **A PR that points an import upward needs to
justify it in `EDGE_NOTES`, not just in this description.**

## Checklist

- [ ] `python -m pytest -q` passes (see the tests badge at the top of the README — do not hardcode a count here)
- [ ] `python scripts/gen-architecture.py --check` passes — regenerate if you changed imports
- [ ] `python scripts/gen-docs.py --check` passes — regenerate if you added a skill, a test file, or a catalog provider
- [ ] `python .github/scripts/check-skills.py` passes — any new skill is `skills/<name>/SKILL.md` with kebab-case `name`
- [ ] `python .github/scripts/check-swallows.py` passes — no silent `except Exception`; log it or add `# swallow: <reason>`
- [ ] `bash .github/scripts/ci-check.sh` passes — an escalation carries a justification in the preceding 5 lines, or `# no-escalation: <reason>`
- [ ] `python .github/scripts/check-skills.py --citations` passes — no doc cites a skill that does not exist, and no doc states a stale skill count

## If this PR adds or changes a check

A check that has never been made to fail is a claim, not a gate. Every new or
materially changed check ships with a **probe**: break the thing on purpose,
confirm the check fails, revert.

- Prefer proving it on a real PR and closing it unmerged (`#45` did this for the
  citation gate, and the job's step-level conclusions are the evidence).
- At minimum, mutate the rule to a no-op locally and record which self-tests go
  red.
- Say what the check **does not** cover. `--citations` reads backticked paths
  only; it does not see prose naming an arbitrary repo file.

Both halves of `ci-check.sh` were probed this way before it was (correctly) kept
rather than deleted — see `docs/architecture/CHECKER_AUDIT.md`.

## Evidence

<!--
Paste the commands and their last line of output. "Tests pass" without output is
the claim that this repository has been burned by before: main was red for three
days while the README said "0 failed".
-->

```
pytest -q                                 ->
gen-architecture.py --check               ->
gen-docs.py --check                       ->
```

## Deliberately not doing

<!-- Scope you chose not to take. An empty section here is a smell. -->
