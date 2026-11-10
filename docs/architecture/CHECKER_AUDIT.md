# Checker audit — which of the seven earn their keep

**Date:** 2026-11-09
**Trigger:** a question raised twice and deferred twice — *if you had to keep four, which three go?*
**Method:** for each check, (a) what did it catch in real use, and (b) can it be made to fail on purpose?

A check that has never failed and cannot be induced to fail is not a check, it is
a green light with a test suite attached. That is the failure mode this
repository produced three times in one week.

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
| 7 | pytest + coverage floor (tests matrix) | — | ~15 s |

**1,157 lines** of guard code, plus 21 self-tests across three files.

---

## Real catches

| Check | Caught | Notes |
|-------|--------|-------|
| 1 `ci-check` | **2 real**, plus 4 false positives | genuine unexcused escalations in #38's history; in this session it wrongly blocked 2 cache-key literals — the false positives cost more than the catch |
| 2 `check-skills` | **30** | the whole `skills/` tree was undiscoverable: `Caveman`, `freeUnlimited-websearch`, 8 flat files |
| 3 `check-swallows` | **6** | six `except Exception: pass` swallowing real errors |
| 4 `gen-architecture` | **1** | the documented layer table described a tree that did not exist |
| 5 `gen-docs` | **17** | 14 phantom skills, 3 wrong catalog rows, plus every stale test count |
| 6 `verify-skills-lock` | **1** | the lock had never been checkable — matched nothing, ever |
| 7 pytest | **1** | the suite could not collect from the repo's own requirements |

## Can they fail on purpose? All probed, none assumed

| Check | Probe | Result |
|-------|-------|--------|
| 1 | unjustified `protocol="ja3"` call | ✅ exit 1 |
| 2 | `skills/BadName/SKILL.md` | ✅ exit 1 — `must be lowercase kebab-case` | <!-- skills-ignore -->
| 3 | silent `except Exception: pass` appended to `proxy_harvester.py` | ✅ exit 1 |
| 4 | `import proxy_defense` injected into `proxy_harvester.py` | ✅ exit 1 — reported both the upward edge and the cycle |
| 5 | stale table after adding a test file | ✅ exit 1 (it caught its own author) |
| 6 | one-line append to `you-web`; body edit behind a declared modification | ✅ exit 1 in both modes |
| 7 | — | not probed; a failing pytest is self-evident |

**All seven can fail. None is decorative.** That is the good news, and it is not
the answer to the question asked.

---

## The real problem is what they cost together

**1. Duplicated CI installs.** `requirements.txt + requirements-dev.txt` is
installed three times per PR. This is the second-order cost of generators: a
checker that must *import* the code needs the code's dependencies, so `gen-docs`
added a ~15 s install to a job that previously needed 127 ms and no packages.

**2. Overlapping surfaces.** `check-skills.py`, `gen-docs.py` and
`verify-skills-lock.py` all read `skills/*/SKILL.md`. They cannot contradict each
other today, but nothing enforces that.

**3. Guards can themselves be wrong.** `ci-check.sh` produced 2 false positives
that blocked merges for three days. A wrong check costs more than a missing one:
a missing check fails open and you learn later; a wrong check fails closed and
you learn to bypass it.

## If forced to four

| Priority | Check | Why |
|----------|-------|-----|
| 1 | pytest + coverage | nothing else runs the code |
| 2 | `gen-architecture` | the failure that started this — docs describing a tree that does not exist |
| 3 | `check-skills` | packaging regressions are silent; blast radius is every agent host |
| 4 | `check-swallows` | the only runtime-correctness check; caught 6 real bugs |
| — | `gen-docs` | **merge into `gen-architecture`** — same concept, two scripts, two CI steps |
| — | `verify-skills-lock` | **keep as a step**, not a job; 121 ms |
| — | `ci-check` | **deletion candidate** — 2 real catches vs 4 false positives, and the PR template now covers its ground at review time |

## Recommendation

1. ~~Merge `gen-docs` into `gen-architecture`: one generator, two targets, one CI
   step.~~ **Retracted — measured, see `docs/SKILL_RESOLUTION.md`.** On the same
   tree, `gen-architecture --check` takes **0.11 s** (AST only) and `gen-docs
   --check` takes **3.96 s** (it runs `pytest --collect-only`, so it needs the
   full dependency install). Merging them makes the 0.11 s job pay 3.96 s and a
   pip install to save one YAML step. The 36× is the thing worth keeping
   separate.
2. Delete `ci-check.sh` **only after** the PR template has been in use long
   enough to show reviews carry the justification. Not yet — the template has
   seen two PRs.
3. Do not add an eighth *documentation* check. The next one should be runtime.

**Correction to point 3:** the runtime bug found in
`RUNTIME_FINDING_HARVESTER_STATE.md` existed through all seven checks and 595
tests. It was found in a seam — `load_state` × the constructor argument ×
`save_state` — that no individual test combined. The gap worth closing is
**component seams**, which needs no network at all.
