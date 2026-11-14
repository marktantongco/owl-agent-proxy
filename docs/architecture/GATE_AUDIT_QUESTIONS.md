# Gate Audit Questions

Five consecutive PRs each found a different defect in a gate that was passing.
The defects did not share a root cause, and the questions that found them do not
converge on a single pass/fail state. So this file is not a checklist of things
to confirm — it is a list of questions to *ask*, each of which has already
returned "no" at least once in this repository.

A gate is green when someone last asked it a question it could answer.

## How to use this

Pick a gate. Ask the four questions below in order. Stop at the first "no" and
fix that, because the later questions cannot be answered meaningfully while an
earlier one is open — a rule that never fires cannot be probed, and a rule that
can be switched off does not need a probe.

Record the answers in the table at the bottom. An unanswered question is not a
pass; it is an untested claim.

---

## Q1. Does the rule fire at all?

*Can this gate be shown saying "no"?*

The failure mode: a rule that has never been run against a failing case. It
matches nothing, or matches everything and exempts it, and reports success.

**Ask:** write a file that breaks the rule. Does the gate fail? Then write one
that does not. Does it pass?

**Found this way:** `protocol-escalation-justified` blocked nothing on any input
it could not parse, because a negative `sed` range near the top of a file made
the context empty. Every justified escalation near line 1 scored 0/4.

**Minimum bar:** one positive case and one negative case, both asserted.

---

## Q2. Is there a probe behind the claim?

*If the rule silently stopped working tomorrow, would CI notice?*

The failure mode: the declaration is prose and the behaviour is elsewhere. The
rule is described accurately and nothing checks that the description stays true.

**Ask:** delete the rule's implementation. Does any test fail?

**Found this way:** 24 rules were declared in gate headers with zero probes
behind them. The table was accurate and unenforced — and one declaration
(`lock-is-checkable`) was credited to a test file that had no `--update` case in
it at all, because the filename looked right.

**Minimum bar:** the probe is named in the declaration and runs in CI.

---

## Q3. Can the rule's evidence be faked cheaply?

*What is the least effort that satisfies this gate?*

The failure mode: the gate scores free text, so the text supplies the evidence.
A rule that asks for a justification can be satisfied by a comment that
justifies nothing.

**Ask:** write the most dismissive thing that passes.

**Found this way:** CHECK 1's signals were unbounded regexes. `ms` matched
*systems*, *problems*, *issues*; `approved` matched *unapproved*; `tested`
matched *untested*. `# Approved by ops; this assumes the systems are stable.`
scored 2/4 and passed. `# Not yet approved.` scored an approval point.

**Minimum bar:** a negative case that is textually plausible but substantively
empty, asserted to fail.

---

## Q4. Can the rule be switched off?

*Who holds the exemption, and what do they have to write to use it?*

The failure mode: the gate ships an opt-out that is easier to satisfy than the
gate itself. The opt-out becomes the documented path.

**Ask:** find every marker the gate accepts. Write each one with no reason and
see whether it exempts. Then check how far it reaches.

**Found this way:** all three opt-out markers accepted a bare marker
(`# no-escalation:`, `# cred-ok:`, `# swallow:`) while documentation said
`<reason>`. One of them exempted from five lines away, so a marker written about
one line exempted a different one four lines later.

**Minimum bar:** each marker rejects a bare form, and its reach is pinned by a
test.

---

## What is not on this list

**"Is the rule described accurately?"** — this was the original audit question
and it was the last one to find anything. Two of 24 descriptions were imprecise
and two were confidently false. It is worth asking, but it is the question a
reader can answer by reading, so it produces the least information per unit of
effort.

**"Is the code good?"** — not answerable at this level. Every gate in this
repository turned out, under pressure, to be a comment-matching exercise. That
is a property of static gates over free text, not a defect to be repaired.

---

## State at time of writing

| Gate | Q1 fires | Q2 probed | Q3 prose-proof | Q4 switchable |
|---|---|---|---|---|
| `ci-check.sh` CHECK 1 | ✅ | ✅ | ✅ | ✅ (reach narrowed) |
| `ci-check.sh` CHECK 2 | ✅ | ✅ | n/a | ✅ |
| `check-skills.py` | ✅ | ✅ | ✅ | n/a |
| `check-swallows.py` | ✅ | ✅ | n/a | ✅ |
| `gen-architecture.py` | ✅ | ✅ | n/a | n/a |
| `gen-docs.py` | ✅ | ✅ | n/a | n/a |
| `runtime-check.py` | ✅ | ✅ | n/a | n/a |
| `verify-skills-lock.py` | ✅ | ✅ | n/a | n/a |

`n/a` means the gate has no free-text surface (Q3) or no opt-out (Q4), not that
the question was skipped.

### The honest caveat

Every ✅ above means "asked, and the answer was yes with a test behind it."
None of them means the gate is correct. Q3 in particular has no
satisfying answer for a gate that reads comments — a stricter regex makes the
word game fairer, not sound. The Contrarian option in the final PR of this
series was to delete the marker and the heuristic rather than keep improving
them, and that remains the only proposal here that would settle Q3 instead of
refining it.
