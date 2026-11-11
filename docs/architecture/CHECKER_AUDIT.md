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
| — | `ci-check` | ~~deletion candidate~~ **retracted — see below.** Half of it is a security control; the catch/false-positive count was never valid for the whole script |

## Recommendation

1. ~~Merge `gen-docs` into `gen-architecture`: one generator, two targets, one CI
   step.~~ **Retracted — measured, see `docs/SKILL_RESOLUTION.md`.** On the same
   tree, `gen-architecture --check` takes **0.11 s** (AST only) and `gen-docs
   --check` takes **3.96 s** (it runs `pytest --collect-only`, so it needs the
   full dependency install). Merging them makes the 0.11 s job pay 3.96 s and a
   pip install to save one YAML step. The 36× is the thing worth keeping
   separate.
2. ~~Delete `ci-check.sh` after the PR template has had another cycle.~~
   **Retracted — the recommendation was wrong on its own terms.** See below.
3. Do not add an eighth *documentation* check. The next one should be runtime.

**Correction to point 3:** the runtime bug found in
`RUNTIME_FINDING_HARVESTER_STATE.md` existed through all seven checks and 595
tests. It was found in a seam — `load_state` × the constructor argument ×
`save_state` — that no individual test combined. The gap worth closing is
**component seams**, which needs no network at all.

---

## Verification: does the citation gate actually block a PR?

**Date:** 2026-11-11
**Question:** `check-skills.py --citations` exits 1 locally. Does it fail CI, or
is this another green light with a test suite attached?
**Method:** break two things on purpose on a real branch, open a real PR, read
the job's step results, revert.

## The two probes

| Probe | What was broken |
|---|---|
| 1 | `PROBE_DOC.md` citing `skills/ghost-skill/SKILL.md` — a skill that does not exist | <!-- skills-ignore -->
| 2 | `AGENTS.md` prose count changed `30` → `31`, **outside** every generated marker |

Probe 2 is the interesting one. It is the same defect class as the four stale
counts this branch already fixed, put back deliberately.

Locally both failed, exit 1, reported precisely:

```
FAILED: 2 problem(s)
  - AGENTS.md:1721: claims '31 skill SKILL.md files' but skills/ has 30 <!-- skills-ignore -->
  - PROBE_DOC.md:3: cites `skills/ghost-skill/SKILL.md` but no such skill exists <!-- skills-ignore -->
```

Also measured in the same run: **`gen-docs.py --check` returned 0** with that
prose drift in place. The generator only owns its marked blocks, so a hand-edited
sentence can disagree with the tree and the release gate says nothing. That is
exactly why `--citations` had to be a separate rule, and it is the strongest
argument against merging the two generators — they check disjoint surfaces.

## Result on CI (PR #45)

Job `Skill packaging`, step-level conclusions:

| Step | Conclusion |
|---|---|
| Validate SKILL.md frontmatter | **success** |
| Cited skills exist and counts are current | **failure** |
| Citation checker self-tests | skipped |
| Vendored skills match skills-lock.json | skipped |

The failing step is the citation step specifically — not a flake, not an
install error, not the workflow. Frontmatter passed, so packaging and citations
are independently gated as designed.

Reverted in `4812430`; PR #45 closed without merging; that branch's tree is
identical to `main` and its checks returned green.

## What this settles, and what it does not

Settled: a phantom citation or a stale prose count **cannot land on `main`**
through a pull request. That was an open question in the previous audit — a check
had never been observed blocking anything.

Not settled: whether the failure is *legible* to whoever hits it. The step name
is clear and the annotation names file and line; nobody has yet been the person
on the other end of it. Until that happens, treat the message quality as unproven.

## Cost of this verification

One PR opened and closed (#45), one commit and one revert, ~6 minutes of CI.
Cheap enough that the question "does this actually block?" should never again be
answered by inference.

---

## Retraction: `ci-check.sh` must not be deleted

**Date:** 2026-11-11
**Original recommendation:** delete it — "2 real catches vs 4 false positives, and
the PR template now covers its ground at review time."
**Why that is wrong:** the script contains **two independent checks with
different risk profiles**, and the catch/false-positive count was recorded
against the script as a whole.

| Check | What it does | Failure if removed |
|---|---|---|
| CHECK 1 | protocol escalation justification | a style/process convention — a reviewer can substitute |
| CHECK 2 | hardcoded proxy credentials (`://user:pass@`) | **nothing substitutes.** A committed proxy credential is a live secret leak |

The PR template can absorb CHECK 1's ground at review time. It cannot absorb
CHECK 2's: review-time attention is not a credential scanner, and this repo
handles proxy pools where such URLs are ordinary working data — exactly the
environment where one gets pasted with a real password.

## Probed, both halves

| Probe | Result |
|---|---|
| `protocol="ja3"` with no justification comment | `[FAIL] Missing justification (score: 0/4)`, merge blocked, exit 1 |
| `POOL = {"http": "http://alice:s3cr3t@proxy.internal:8080"}` | `[FAIL] Hardcoded credentials`, merge blocked, exit 1 |

Both work. The credential probe is the one that matters — it is a real secret
pattern, caught, blocking.

## What this says about the audit method

Counting catches per *script* conflated a process gate with a security control.
The count was also never a sound basis for deletion: a check that has caught
zero of a catastrophic failure class is not therefore worthless, it is
unexercised. "Cheap to remove" and "safe to remove" are different questions, and
the audit only asked the first.

## Also measurable, and uncomfortable

On the current tree, CHECK 1's output is:

| Outcome | Count |
|---|---|
| exempted without scoring | **6** |
| scored by the 4-point heuristic | 3 |

Two thirds of the sites this check inspects reach it through an exemption
(`cache key`, `opted out inline`, `CachedResponse` in a justified handler) —
three separate escape hatches. The check is not wrong here, but its coverage is
thinner than its passing output suggests, and every exemption is a place a real
escalation could sit unflagged.

## Correction on the "trusted, not bypassed" question

An earlier framing claimed `ci-check.sh` blocked merges for three days with false
positives and that the team "learned to route around it." **That cannot be
verified in this checkout:** history is shallow (`git rev-list --count` = 1), so
the events it refers to are not present. The claim is unverified rather than
disproved, and it should not be repeated as established fact until someone has
the full history.

What *is* measurable here is on the other side: after the false-positive episode
the script gained three exemptions and an inline opt-out idiom
(`# no-escalation:`). Three escape hatches added to a check is what happens when
its errors cost more than its catches — a real signal, and a weaker one than
"the team routed around it."

## Revised recommendation

- **Do not delete.** Split instead: keep CHECK 2 as-is, and consider making
  CHECK 1 advisory (warning, not error) — it is the half whose ground the PR
  template genuinely covers, and the half seven of nine sites bypass.
- Any future deletion case for a check must be argued **per rule**, not per
  script, and must say what substitutes if the rule disappears.

### How that is enforced, rather than asked for

Asking for a rule-level argument in a document does nothing; the document is
where the previous recommendation went wrong. So each gate now **declares** its
rules in its own header:

```
# gate: <kebab-case-id>: <what the rule protects> [required]
```

`gen-docs.py` parses those declarations (comment form for shell, docstring form
for Python) and generates a `gates` table in AGENTS.md. The consequences are
mechanical:

| Situation | What happens |
|---|---|
| A rule is deleted | its row disappears from the table — a reviewable diff, not a silent edit |
| A gate is registered with no declarations | `gen-docs.py` **refuses to render** and names the file |
| A registered gate file is missing | same refusal |
| A rule loses `[required]` | it renders italic and marked `advisory`, and the header count changes |

Current state: **7 gates, 24 rules, 23 required**. The one advisory rule is
`narrow-handler-allowed` in `check-swallows.py` — a rule that *permits*
something rather than forbidding it, so "required" would be the wrong word.

Proof it works: 10 self-tests (`tests/test_gate_declarations.py`), mutation-
checked — removing the undeclared-gate guard fails 1 test, ignoring the
`[required]` marker fails 3. The decisive one is
`test_removing_a_rule_changes_the_table`, which asserts the deletion is visible.

