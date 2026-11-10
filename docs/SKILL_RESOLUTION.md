# Skill resolution — the four skills that "were never found"

**Date:** 2026-11-10
**Question:** four skills were named in the original request and never located.
Were they real, and did the work lose something by not having them?
**Method:** exact-name search on skills.sh, then read the candidate's SKILL.md
before judging it.

---

## Resolution

| Named in request | Status | What it actually is |
|---|---|---|
| `claude-repo-expert` | **name wrong** | no such skill. Closest real match is `repo-expert` (programming-corner/repo-expert, 3 installs) — RepoMind, a "senior tech lead who understands any codebase", routing to bootstrap/consult/requirements/pr-review modes |
| `repo-architect` | **exists, name imprecise** | `agent-repo-architect` (ruvnet/ruflo, 1.2K installs, 81.4K stars). Its own frontmatter `name:` is literally `repo-architect` — multi-repo management and structure optimisation via ruv-swarm |
| `repo-clarity` | **does not exist** | no repo-related skill under any variant. `clarity-audit` (aibtcdev) is **Clarity smart contracts** — Stacks/Bitcoin; `clarity` (addyosmani, 1.6K) is **prose craft**. Both are red herrings. Nearest real capability is `codemap` |
| `module-based-refactor` | **exists, exact** | vamseeachanta/workspace-hub, 27 installs. Description: "reorganize a repository from flat structure to a consistent module-based 5-layer architecture while preserving git history… cleanup of artifacts, runtime data, and hidden folders" |

Two of four exist under exactly-or-nearly the stated name. One is a real skill
with the wrong prefix. One is a name that does not resolve — and both plausible
matches are in unrelated domains.

## The uncomfortable part

`module-based-refactor`'s description is the original request almost word for
word: flat structure → 5-layer architecture, **`git mv` history preservation**,
artifact cleanup. That work was done in PR #39 without the skill.

So did the skill contain something that was missed? Its SKILL.md as rendered
shows a description and metadata, no methodology body. Based on what is
publishable, the answer is **no lost content** — the request was satisfied from
first principles. That is not the same as "the skill was unnecessary," and it
would be dishonest to claim it: a 27-install skill with no visible body cannot
teach anything a careful implementer would not derive. It also cannot be ruled
out that a fetch-invisible body exists.

## What the search did find

A real, live instance of the drift class this repo has been fighting — in its
own docs, unnoticed by seven checks:

```
AGENTS.md:1684  Located at `~/.agents/skills/research-investigation-pipeline/SKILL.md`
                (note: file path may vary — check `find /home/user/.agents/skills ...`)
```

The parenthetical is the tell: a document instructing the reader to go looking
for the thing it just cited. Nothing installs that path — the installer has zero
references to it, and all seven constituent skills it claims to combine exist
individually in `skills/` or `.agents/skills/`. It was a phantom, hedged in the
same sentence that asserted it.

The same section's neighbours had drifted too:

| Claim | Reality |
|---|---|
| "14 skill SKILL.md files" (AGENTS.md:1715) | 30 |
| "10 SKILL.md files" (QUICK_REFERENCE.md:116) | 30 |
| "10 conceptual skill SKILL.md files" (README.md:183, 10-PIPELINES.md:169) | 30 |

AGENTS.md contradicted itself and CI passed: the generated block at line 1579
says `30 skills`, the hand-written prose at 1715 said `14`. Both in one file.

**Root cause: all of these lines sit outside every `<!-- generated: -->` marker.**
The generated blocks cannot drift; the prose around them still can, and does.

## A resolution that costs nothing

`skills/meta-skill` already exists in this repo — "meta-skill for discovering and
installing other skills from the skills.sh ecosystem… the discovery layer."
The named skills were never found because they were never searched *with the
tool the repo already ships*. Skills must be searched by exact name **and**
variants, and the candidate read before it is cited — the same rule the
generators enforce for tables, applied to names.

## Measured: the one consolidation the audit got wrong

The audit recommended merging `gen-docs` into `gen-architecture`. Measured on
this machine, on the same tree:

| Generator | Wall time | Needs `pytest --collect-only` |
|---|---|---|
| `gen-architecture.py --check` | **0.11 s** | no — AST only |
| `gen-docs.py --check` | **3.96 s** | yes |

36×, and the slow one is the one that needs the dependency install. Merging them
drags a dependency-laden 3.96 s into a 0.11 s job to save one CI step. **Do not
merge.** The audit's own rule — "a check that cannot fail is a green light" — has
a companion: a consolidation that makes the fast path pay for the slow path is a
regression whatever it saves in YAML lines.
