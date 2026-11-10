# Checker audit — which of the seven earn their keep

**Date:** 2026-11-09
**Trigger:** the question asked twice and not yet answered — *if you had to keep four, which three go?*
**Method:** for each check, (a) what did it catch in real use, and (b) can it be made to fail on purpose?

A check that has never failed and cannot be induced to fail is not a check, it is
a green light with a test suite attached. That is the failure this repository
produced three times in one week, so both questions get answered with evidence.

---

## The seven

| # | Check | LOC | Runtime |
|---|-------|-----|---------|
| 1 | `ci-check.sh` — escalation + credential guard | 110 | 141 ms |
| 2 | `check-skills.py` — SKILL.md contract | 137 | 231 ms |
| 3 | `check-swallows.py` — silent broad handlers + dict-chosen protocols | 168 | 147 ms |
| 4 | `gen-architecture.py` — layer map drift | 314 | 127 ms |
| 5 | `gen-docs.py` — AGENTS.md table drift | 242 | 89 ms |
| 6 | `verify-skills-lock.py` — vendored provenance | 186 | 121 ms |
| 7 | pytest + coverage floor (in the tests matrix) | — | ~15 s |

Total: **1,157 lines** of guard code, plus 21 self-tests across three files.

---

## Real catches (things that were broken and are not broken now)

| Check | Caught | Notes |
|-------|--------|-------|
| 1 `ci-check` | **2 real**, plus 4 false positives | flagged genuine unexcused escalations in #38's history; in this session it wrongly blocked 2 cache-key literals — the false positives were the bigger cost |
| 2 `check-skills` | **30** | whole `skills/` tree was undiscoverable; `Caveman`, `freeUnlimited-websearch`, 8 flat files |
| 3 `check-swallows` | **6** | six `except Exception: pass` swallowing real errors |
| 4 `gen-architecture` | **1** | the documented layer table described a tree that did not exist |
| 5 `gen-docs` | **17** | 14 phantom skills, 3 wrong catalog rows, plus every stale test count |
| 6 `verify-skills-lock` | **1** | the lock had never been checkable — matched nothing, ever |
| 7 pytest | **1** | the suite could not collect from the repo's own requirements |

## Can they fail on purpose? (probed this session, not assumed)

| Check | Probe | Result |
|-------|-------|--------|
| 1 | unjustified `protocol="ja3"` call | ✅ exit 1 |
| 2 | `skills/BadName/SKILL.md` | ✅ exit 1 — `must be lowercase kebab-case` |
| 3 | silent `except Exception: pass` appended to `proxy_harvester.py` | ✅ exit 1 |
| 4 | `import proxy_defense` injected into `proxy_harvester.py` (upward edge) | ✅ exit 1 — reported both the edge and the cycle |
| 5 | stale table after adding a test file | ✅ exit 1 (it caught its own author) |
| 6 | one-line append to `you-web`; body edit behind a declared modification | ✅ exit 1 in both modes |
| 7 | — | not probed; pytest failing is self-evident |

**All seven can fail. None is decorative.** That is the good news, and it is not
the answer to the question asked.

---

## The actual problem is not which check, but what they cost together

Three costs, measured rather than asserted:

**1. Duplicated CI installs.** `requirements.txt + requirements-dev.txt` is
installed three times per PR (tests matrix ×3, architecture job, installer job).
This is the second-order cost of adding generators: a checker that needs to
*import* the code needs the code's dependencies, so each new generator adds a
~15 s dependency install to a job that previously needed none.

**2. Overlapping surfaces.** Three checks read the same files for different
reasons — `check-skills.py`, `gen-docs.py` and `verify-skills-lock.py` all open
`skills/*/SKILL.md`. They cannot contradict each other today, but nothing
enforces that.

**3. The guards can themselves be wrong.** `ci-check.sh` produced 2 false
positives that blocked a merge for three days. The cost of a wrong check is
higher than the cost of a missing one: a missing check fails open and you find
out later; a wrong check fails closed and you learn to bypass it.

## The answer: keep five, delete one, merge one

If forced to four, in this order:

| Priority | Check | Why |
|----------|-------|-----|
| 1 | pytest + coverage | nothing else runs the code |
| 2 | `gen-architecture` | the failure that started this — docs describing a tree that does not exist |
| 3 | `check-skills` | packaging regressions are silent and the blast radius is every agent host |
| 4 | `check-swallows` | the only check about *runtime* correctness; caught 6 real bugs |
| — | `gen-docs` | **merge into `gen-architecture`.** Both are "generated docs vs source"; two scripts, two CI steps, one concept |
| — | `verify-skills-lock` | **keep as a step, not a job.** 121 ms; it belongs in the skills job, where it already is |
| — | `ci-check` | **the deletion candidate.** 2 real catches vs 4 false positives, and its whole premise — that every escalation needs a written justification — is enforced more cheaply by review with the PR template now in place |

`gen-docs` → `gen-architecture` merges 556 lines into one `gen-docs` command with
two targets, removes one CI step and one dependency install.

---

## What this audit did NOT change

No code. The question was "which would you drop", and the honest answer is that
dropping any of them today would remove a check that has caught something real.
The consolidation above is worth doing and is not urgent.

## Recommendation

1. Merge `gen-docs` into `gen-architecture` — one generator, two targets, one CI step.
2. Delete `ci-check.sh` **only after** the PR template has been in use long
   enough to show reviews actually carry the justification. Not yet: the template
   has seen one PR.
3. Do not add an eighth check for documentation. The next one should be
   runtime: live-egress V19/V20 currently SKIP offline, so nothing in CI has ever
   exercised the proxy path against a real target.
