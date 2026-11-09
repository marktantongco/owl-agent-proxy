# Restructure Plan — Audit → Optimize

**Date:** 2026-11-09
**Branch:** `arena/d1451c82-owl-agent-proxy`
**Mode:** 🦫 Builder (audit + restructure), gated on evidence

---

## 0. Evidence baseline (measured, not assumed)

| Signal | Command | Result |
|--------|---------|--------|
| Test suite | `python -m pytest -q` (with `fastapi` installed) | **571 passed, 0 failed**, 82% coverage |
| Test suite (repo deps only) | `pip install -r requirements.txt -r requirements-dev.txt` | **collection ERROR** — `ModuleNotFoundError: fastapi` |
| Skill packaging | `python .github/scripts/check-skills.py` | **FAIL** — 3 problems (`Caveman`, `freeUnlimited-websearch`) |
| Exception guard | `python .github/scripts/check-swallows.py` | **FAIL** — 6 unexplained `except Exception: pass` |
| Escalation guard | `bash .github/scripts/ci-check.sh` | **FAIL** — 2 false positives in `tests/test_proxy_defense.py:802,806` |
| CI on `main` @ `c5af2b3` | `gh run view 42154787393` | 4 of 8 jobs red (3× Tests, skills, guard) |
| README test claims | `grep -n '484\|507\|407'` | badge `484`, prose `484`, prose `407`, `0 failures` — actual **571** |
| README structure block | `README.md` L667+ | lists 4 test files (actual 10), omits `gateway/`, `reverse_proxy.py`, `agent/`, `.agents/`, `skills/` |

**Root cause of the red CI:** the repo documents a layered design it does not
have, and nothing in CI checks that the documentation matches the tree.

---

## 1. As-is layers (verified by AST import scan)

```
┌────────────────────────────────────────────────────────────────────┐
│ L5  Agent hosts        Claude / Cursor / OpenCode / Codex          │
├────────────────────────────────────────────────────────────────────┤
│ L4  Agent surface      mcp_proxy_server.py (stdio JSON-RPC, 4 tools)│
│                        skills/owl-proxy{,-mcp}/SKILL.md            │
├────────────────────────────────────────────────────────────────────┤
│ L3  Ingress (optional) reverse_proxy.py  (:8080, escalation ladder) │
│                        gateway/ (FastAPI :20128, token plane)       │
├────────────────────────────────────────────────────────────────────┤
│ L2  Egress core        proxy_defense.py (cache, dedupe, ratelimit,  │
│                        pool, protocols, filter, middleware)         │
├────────────────────────────────────────────────────────────────────┤
│ L1  Supply             proxy_harvester.py (harvest, honeypot,       │
│                        affinity, validate_proxy)                    │
└────────────────────────────────────────────────────────────────────┘
```

Import edges are **strictly downward** — verified, no cycles:

```
mcp_proxy_server ──lazy──▶ proxy_defense ──lazy──▶ proxy_harvester
reverse_proxy    ──lazy──▶ proxy_defense
mcp_proxy_server ──lazy──▶ proxy_harvester
gateway/*        ──(isolated app; stdlib + fastapi + httpx only)
```

## 2. Gaps → actions

| # | Gap | Evidence | Action | Risk |
|---|-----|----------|--------|------|
| G1 | CI guard fails on skill names | `check-skills.py` output | `git mv skills/Caveman → skills/caveman`; normalise `freeUnlimited-websearch` → `freeunlimited-websearch`; update doc refs | low |
| G2 | CI guard fails on 6 silent broad excepts | `check-swallows.py` output | add `# swallow: <reason>` or real logging at each site | low |
| G3 | Escalation guard false-positives on cache keys | `ci-check.sh` → 802, 806 | narrow the detector to network entry points (exclude cache-key literals), documented in the script | medium — guard semantics |
| G4 | Tests job cannot collect without `fastapi` | `ModuleNotFoundError: fastapi` | add gateway test deps to `requirements-dev.txt` | low |
| G5 | README structure ≠ tree; counts stale | see §0 | regenerate structure block from the tree; correct counts (571 / 82%) | low |
| G6 | No as-is architecture artifact, no drift check | — | `scripts/gen-architecture.py` writes `docs/architecture/MODULE_GRAPH.md`; CI runs `--check` | low |
| G7 | `agent/skills/` is a byte-divergent 585 KB duplicate of `.agents/skills/` | `diff -rq` → 6 files differ; 0 references from code/scripts | `git rm -r agent/skills` | low |
| G8 | 8 legacy skill files undiscoverable (`skills/system/*.md`, `skills/development/*.md`) | `check-skills.py` WARN lines | migrate to `skills/<name>/SKILL.md` with frontmatter; delete empty dirs | medium — content rewrite |

## 3. Order of execution (each gate must pass before the next)

1. **G1–G4** (CI green) → `pytest 571`, `check-skills` 0, `check-swallows` 0, `ci-check` 0.
2. **G7–G8** (structure) → `check-skills` still 0, `pytest` still 571.
3. **G5–G6** (docs) → regenerate the README structure block and the module graph from the tree.
4. **Re-audit** → rerun all four gates + `git diff --stat`.

## 4. Verification commands

```bash
python -m pytest -q                                    # 571 passed
python .github/scripts/check-skills.py                 # exit 0
python .github/scripts/check-swallows.py               # exit 0
bash   .github/scripts/ci-check.sh                     # exit 0
python scripts/gen-architecture.py --check             # exit 0
```

## 5. Out of scope (deliberately)

- PR #22 (10 pipelines) and PR #11 (AgentRouter sidecars) — separate in-flight work.
- Merging `gateway/` (FastAPI) and `reverse_proxy.py` (aiohttp) into one service —
  they are different planes and merging them is a design change, not a restructure.
- Replacing the `skills/` → `.agents/skills/` symlinks with real directories. Flagged
  as a packaging risk in the module graph; not exercised because `check-skills.py`
  resolves them correctly today.

---

## 6. Outcome (measured after the change)

| Gate | Before | After |
|------|--------|-------|
| `python -m pytest -q` | 571 passed (needed an undocumented `pip install fastapi`) | **580 passed**, installable from `requirements*.txt` alone |
| `check-skills.py` | FAIL — 3 problems, 8 undiscoverable files | **PASS — 30 skills valid, 0 flat files** |
| `check-swallows.py` | FAIL — 6 broad handlers silencing errors | **PASS — 0 broad handlers swallowing** |
| `ci-check.sh` | FAIL — 2 false positives | **PASS — 0 errors, 0 warnings** |
| `verify-install.py --no-live` | 18 PASS / 0 FAIL | 18 PASS / 0 FAIL (unchanged) |
| Architecture drift | unmapped, unchecked | `gen-architecture.py --check` in CI, 0 upward edges, 0 cycles |
| Duplicated vendored tree | 62 files / 585 KB in `agent/skills/` | removed; `.agents/skills/` is the single copy |

### Defects found in review of this change (and fixed)

1. **Narrowing a broad handler can hide a real bug.** Replacing
   `except Exception` with `(OSError, ValueError)` in the IP filter dropped the
   `AttributeError` path taken when a `RequestContext` has `headers=None`,
   turning a non-match into a raised exception. Caught by re-reading my own
   diff; now covered by `test_ip_rule_with_no_headers_does_not_raise`, which
   fails with `AttributeError: 'NoneType' object has no attribute 'get'` when
   the clause is removed.
2. **A test runner that collects nothing is not a green light.**
   `python -m unittest tests.test_architecture_check` reported "Ran 0 tests …
   OK". The CI step now runs the file directly, and the runner exits 1 when it
   collects zero tests.
3. **A cross-module import cycle does not exist here.** An earlier reading of
   this repository concluded `proxy_defense` and `proxy_harvester` imported each
   other. The AST graph disproves it: every edge points downward. Recorded
   because stating a false constraint is worse than stating none.
