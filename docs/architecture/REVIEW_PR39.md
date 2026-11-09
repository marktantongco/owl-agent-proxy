# Review — PR #39 (post-merge) and the follow-on work

**Date:** 2026-11-09
**Reviewed:** merge commit `5ee8489` (PR #39, merged 2026-11-09T19:25:05Z)
**Scope:** the merged code, the three review suggestions, and what the review itself found

---

## 1. Was the merge sound?

| Question | Evidence | Verdict |
|----------|----------|---------|
| Did `main` stay green after the merge? | run `42683140043` — 0 failed jobs | ✅ |
| Are the guards still meaningful, or did I weaken them? | planted an unjustified `protocol="ja3"` call → `ci-check` exit 1 | ✅ still blocks |
| Is the generator deterministic across hash seeds? | `PYTHONHASHSEED` 0–5 → identical `MODULE_GRAPH.md` | ✅ |
| Does the generator leave temp files? | `tests/tmp_arch` absent before and after a run | ✅ |

The third-party reviewers were never gates and were never going to be: Qodo is
billing-blocked and CodeRabbit aborted with *"Review failed — the pull request is
closed"* because the merge landed within seconds of the PR opening. Neither
produced a finding. **No review feedback was lost by merging.**

---

## 2. Findings from this review

### F1 — `skills-lock.json` has never matched the files it locks (pre-existing, not fixed)

| Skill | Locked hash | Actual file |
|-------|-------------|-------------|
| `free-search-aggregator` | `db4fc8fe…` | `4d7b8340…` |
| `freeUnlimited-websearch` | `1f7e9614…` | no such path (case) |
| `github-research` | `e2fc4df5…` | `d59a0cf5…` |
| `parallel-deep-research` | `f8d7f91c…` | `6d3523c2…` |
| `parallel-findall` | `779785f4…` | `52ba700d…` |
| `you-web` | `e04ce511…` | `aa84b1e8…` |

**Verified pre-existing:** identical mismatch set at parent `c5af2b3` and at
`HEAD`. The `skillPath` values are repo-relative (`skills/github-research/SKILL.md`)
but the files were vendored under `.agents/skills/<name>/`, and once through a
signing/formatting pass. So the lock has always been decorative.

**Not fixed, deliberately.** Regenerating hashes would make it agree with files
that may themselves be modified forks — that converts a loud inconsistency into a
silent false assurance, which is worse. The correct fix is to re-vendor from
source, which needs network access to six upstream repos and is a supply-chain
decision, not a cleanup.

> Recommended next step: either re-vendor from source and regenerate the lock, or
> delete `skills-lock.json` and say in the README that these skills are forks. Two
> wrong options exist today; both are honest, but doing nothing is not.

### F2 — `AGENTS.md` advertised skills that do not exist (pre-existing, now generated)

The hand-written inventory listed `github-researcher` (the directory is
`github-research`), a capitalised `Caveman`, 14 `find-skills`-era entries that
are not in `skills/` at all, and omitted the 8 reasoning skills and 6 vendored
research skills. Fixed by generating the table (see §3).

### F3 — the free-catalog table disagreed with its own source file (pre-existing, now generated)

| Provider | Table claimed | `providers.json` |
|----------|---------------|------------------|
| Cloudflare Workers AI | 7 named + 55 more | **8** |
| ModelScope | 2 named + more | **3** |
| NVIDIA NIM | 3 named + 92 more | **4** |

3 of 15 rows were wrong. Fixed by generating from the JSON.

### F4 — a dict-chosen protocol walked straight past the escalation guard (pre-existing, now caught)

`ci-check.sh` matches `protocol` + `=` + a quoted escalated value. This passes it
unnoticed:

```python
CONFIG = {"protocol": "browser"}     # dict literal: colon, not equals
client.request("GET", url, **CONFIG)
```

Verified: `ci-check` exit **0** on that file. `check-swallows.py` now also
reports any literal dict whose `protocol` value is an escalated protocol, unless
it carries `# swallow:` or `# no-escalation:`. Verified: exit **1** before the
marker, exit **0** with one.

---

## 3. The three suggestions, executed

### Tactical — point reviewers at the generated map

`.github/PULL_REQUEST_TEMPLATE.md`, which did not exist: the layer table, the
"an upward edge must be justified in `EDGE_NOTES`" rule, a checklist naming all
six gates, and a mandatory **Evidence** block with commands whose output must be
pasted. The repository was burned by exactly the failure this prevents — `main`
red for three days while the README said "0 failed".

### Strategic — generate `AGENTS.md`'s tables and `--check` them in CI

`scripts/gen-docs.py` renders three blocks between `<!-- generated:… -->` markers
and touches nothing outside them:

| Block | Source of truth |
|-------|-----------------|
| skills inventory | `skills/*/SKILL.md` frontmatter |
| free catalog | `gateway/free_catalog/providers.json` |
| test results | `pytest --collect-only` per file |

Idempotent (3 runs → identical hash) and deterministic across hash seeds.
`tests/test_docs_generator.py` proves the check fails on staleness — it caught
the staleness its own addition caused, which is the behaviour wanted.

### Contrarian — not unifying `gateway/` and `reverse_proxy.py`

Unchanged, and still correct: PR #11 is open, and consolidating two HTTP servers
before that lands means merging against a moving target.

---

## 4. Verification

```
pytest -q                              587 passed
check-skills.py                        PASSED: 30 skills valid, 0 flat files
check-swallows.py                      PASSED: 0 broad handlers, 0 dict escalations
ci-check.sh                            ALL CHECKS PASSED
gen-architecture.py --check            OK: map matches the tree
gen-docs.py --check                    OK: AGENTS.md blocks match their sources
tests/test_architecture_check.py       6/6
tests/test_docs_generator.py           7/7
mcp_proxy_server.py --selftest         OK
```

## 5. What this review did not cover

- A live-egress run (V19/V20 are SKIP without network) — the proxy path was not
  exercised against a real target.
- The vendored `free-search-aggregator` sources, beyond their lock hash.
- PR #11 and PR #22, which remain open and are owned elsewhere.

---

## 6. The bug CI caught that local runs could not

The first push of this follow-on failed the architecture job. Worth recording,
because it is the third instance of the same pattern in this repository.

`scripts/gen-docs.py` counts tests with `pytest --collect-only`. On my machine
that worked, because my `.venv` had every dependency. CI installed only plain
`pytest` into a job that had no runtime deps, and two things then went wrong in
sequence:

1. `pytest.ini` sets `--cov=…`; without `pytest-cov`, pytest exited **2** with a
   usage error.
2. `_collect_counts` matched `(\d+) tests? collected` against empty output and
   quietly recorded nothing, so the table rendered `?` for all 11 files.

The generator then compared that degraded table with the committed one and
reported **STALE** — a false failure. But the same silent `?` would have been a
false *pass* if the committed table had also contained `?`. Exit code 2 was the
only signal, and it was being discarded.

Fixes, at both ends:

- `_collect_counts` passes `-o addopts=` (neutralising the ini file) and raises
  `SystemExit` with pytest's own stderr when a count cannot be determined. A
  count is now either a number or a hard failure.
- The CI job installs `requirements.txt` + `requirements-dev.txt`, the same set
  the tests matrix uses, because `--collect-only` imports every test module.

And a second round: even with `pytest-cov` installed, `test_gateway.py` could not
import `fastapi`, so the count failed again — correctly, this time, with the
traceback in the message. That is how the missing-deps problem surfaced instead
of hiding.

`test_collect_counts_fails_loudly_instead_of_returning_question_marks` pins it.

**The pattern, three times over:** "0 tests collected, exit 0" (unittest on the
architecture check), "0 failed, README says 484" (main's red CI), and "? for every
file" here. Every one was a check that reported success while measuring nothing.
That is the failure mode this repository keeps producing, and the reason the
generators raise instead of defaulting.
