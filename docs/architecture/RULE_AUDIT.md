# Rule audit — do the 24 declared rules match what the code enforces?

**Date:** 2026-11-12
**Trigger:** PR #48 generated a table of 24 rules from 7 gate headers. Every
description was written by one author reading each gate. Nobody had checked them
against the code. That is this repository's signature failure: documentation that
is confidently wrong.

**Method:** for each rule, read the enforcement path, then try to make the rule
lie. A rule is *accurate* only if the code refuses exactly what the description
claims and its output says so.

---

## Verdict

| # | Rule | Verdict |
|---|------|---------|
| 1 | `skill-frontmatter-valid` | **imprecise** — accurate, but omits two enforced limits |
| 2 | `cited-skills-exist` | accurate |
| 3 | `skill-counts-current` | accurate |
| 4 | `no-blanket-silent-except` | accurate |
| 5 | `dict-chosen-protocol-declared` | accurate |
| 6 | `narrow-handler-allowed` | accurate |
| 7 | `protocol-escalation-justified` | accurate |
| 8 | `proxy-credentials-not-committed` | **FALSE — fixed** |
| 9 | `layer-edges-downward` | accurate |
| 10 | `no-import-cycles` | accurate |
| 11 | `every-module-layered` | **imprecise** — "every shipped module" overclaims |
| 12 | `map-is-current` | accurate |
| 13 | `skills-inventory-current` | accurate |
| 14 | `catalog-matches-source` | accurate |
| 15 | `test-counts-current` | accurate |
| 16 | `gates-declare-rules` | accurate |
| 17 | `seam-state-isolation` | accurate |
| 18 | `probe-separates-tcp-from-http` | **FALSE — fixed** |
| 19 | `harness-proxy-is-pinned` | accurate |
| 20 | `affinity-sticky-then-expires` | accurate |
| 21 | `breaker-opens-then-closes` | accurate |
| 22 | `vendored-files-present` | accurate |
| 23 | `vendored-bytes-match-pin` | accurate |
| 24 | `lock-is-checkable` | accurate |

**Two rules did not do what they said. Both are fixed in this change.**

---

## Rule 8 — `proxy-credentials-not-committed` (false)

**Claimed:** "no hardcoded user:password@ proxy URL *anywhere in the tree*".

**Actual:** matched only `*.py`, `*.js`, `*.ts`, `*.json`, and dropped any hit
whose path contained `test_`.

Probed before the fix:

| File | Result |
|---|---|
| `.py` | caught, exit 1 |
| `.sh` | **passed clean** |
| `.yml` | **passed clean** |
| `proxy_pool.json` | **passed clean** |

The rule claimed the tree; it scanned four extensions. The `grep -v "test_"` was
the worst part: a credential committed in `test_helpers.py` would never be seen,
and the exemption existed for convenience, not because tests are safe.

**Fix:** scan every text format a credential hides in
(`.py .js .ts .json .sh .yml .yaml .toml .cfg .ini`), with **no path-based
exemptions**. Files that legitimately contain fake credentials opt out the way
this repository already does elsewhere:

- obvious placeholders are ignored (`YOUR_USERNAME`, `user1`, `example.com`, `localhost`);
- anything else carries `# cred-ok: <reason>` on the line or the one above.

Re-probed after the fix — five caught, four correctly ignored:

| Input | Expected | Result |
|---|---|---|
| `http://bob:hunter2@10.0.0.1:3128` in `.py` | caught | caught |
| same in `.sh` | caught | caught |
| same in `.yml` | caught | caught |
| same in `.toml` | caught | caught |
| same in `.js` | caught | caught |
| `http://YOUR_USERNAME:YOUR_PASSWORD@p.webshare.io:80` | ignored | ignored |
| `http://user1:pass1@proxy.example.com:8080` | ignored | ignored |
| real-looking cred with `# cred-ok: fixture` | ignored | ignored |
| `https://template:placeholder@proxy.example.org:443` | ignored | ignored |

The detector also matches its own source line, since the script is inside the
tree it scans — handled by `cred-ok` above the pattern, which is exactly the
mechanism being introduced. A rule that cannot exempt itself will be disabled by
whoever hits it first.

---

## Rule 18 — `probe-separates-tcp-from-http` (false)

**Claimed:** "a dead proxy reports TCP failure, not HTTP failure".

**Actual:** asserted `dead is None` and nothing else. It never inspected
`tcp_ms` against `http_ms`, which is the entire distinction `validate_proxy`'s
docstring promises: *"timing is intentionally split so a dead proxy (TCP) is
distinguishable from a proxy that connects but cannot carry an HTTP request."*

Probing showed the two cases really do produce different results:

```
TCP-dead   -> None
TCP-alive, not HTTP -> {'tcp_ms': 0.4, 'http_ms': None, 'ok': False, 'status': None}
```

The distinction exists in the code and was not covered by the rule that claimed
to cover it.

**Fix:** the check now stands up a socket that accepts connections and closes
them (`asyncio.start_server` with a closing handler) and asserts
`tcp_ms is not None and http_ms is None and ok is False`.

---

## Imprecise, not fixed

**Rule 11, `every-module-layered`.** "Every shipped module appears in the layer
table." Discovery is deliberately scoped to top-level modules and `gateway/` —
verified: the 13 discovered modules are exactly the runtime surface, and
`scripts/`, `examples/`, `tests/`, vendored skills are all out of scope by
design. So the rule works; the *wording* promises more than the scope covers.
Rewording it would change the generated table to describe the code accurately,
which is the right fix but a separate, low-risk change.

**Rule 1, `skill-frontmatter-valid`.** Enforces more than its description says:
name ≤ 64 chars, description 20–1024 chars, name matches its directory. All
accurate claims, all unstated.

---

## What this audit does not cover

It checks that each rule **enforces what it claims**. It does not check that each
claimed rule is **worth having** — whether the thing it protects matters, or what
substitutes if it is removed. That is the question the `ci-check.sh` retraction
raised, and 24 accurate descriptions still do not answer it. `[required]` currently
says "don't drop this," not "here is what it catches."

## The pattern, third occurrence

Two of three recommendations retracted on measurement (generator merge, ci-check
deletion) and two of 24 rules found false. In every case the wrong claim was
**written down and trusted** until someone probed it. The generated table made
that cheaper to check — it did not make it automatic. A rule's description is a
claim about code, and it is only as good as the probe behind it.
