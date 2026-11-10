# Runtime finding — harvester state leaks between instances

**Date:** 2026-11-10
**Found by:** probing what a runtime check could assert, before that check existed
**Severity:** medium — silent; corrupts source ranking and diagnostics, not stored data

---

## What happened

While working out how to build a network-tolerant runtime check, I built a
harvester with one custom source after the default harvester had run in the same
`HOME`:

```python
async with UpstreamHarvester(sources=[ProxySource("mine", "http://127.0.0.1:1/x", "json")]) as h:
    h.health.snapshot()
```

```
declared sources:  ['mine']
health keys:       ['proxyscrape_json', 'maxfeix_txt', 'monosans_txt', 'proxmint_json', 'mine']
```

The instance declared one source and reported five. `snapshot()` is what callers
rank sources by (`health.ranked(self.sources)`), so it handed back sources this
harvester would never fetch.

## Root cause

`load_state()` runs in `__aenter__` and restores the health tracker **verbatim
from disk**:

```python
for name, stats in state.get("health", {}).items():
    entry = self.health._stats[name]      # ← no check against self.sources
```

The state file is per-`HOME`, not per-harvester-configuration, and every
harvester reads it. A one-off diagnostic harvester therefore adopts the four
default sources' decayed stats.

## The fix, and the trap in the obvious version

The obvious fix — skip health rows for sources this instance does not declare —
**introduces a worse bug.** `save_state()` wrote `self.health.snapshot()` over
the whole file, so after `load_state` filtered the foreign rows out, the next
save deleted them from disk permanently:

| Variant | `snapshot()` after load | Default sources' learning on disk |
|---------|------------------------|-----------------------------------|
| pre-fix | 5 sources (wrong) | preserved by accident |
| load filter only | 1 source (right) | **destroyed** |
| load filter + save merge | 1 source (right) | preserved |

That middle row is why this is recorded as a finding rather than a one-line
patch: the two changes are coupled. The filter alone converts a cosmetic
inconsistency into silent state loss for every other source.

Both landed together:

- `load_state()` skips rows for undeclared sources;
- `save_state()` **merges** into the existing file (`seen`, `last`, `health`)
  instead of replacing it, and replaces a corrupt file rather than propagating it.

## Verification

`tests/test_proxy_harvester.py::TestStateIsolation` — three tests, all
`tmp_path`-isolated:

1. `test_declared_sources_do_not_inherit_foreign_health` — **fails pre-fix**
   (`assert 'proxyscrape_json' not in {...}` with the full foreign dict printed),
   passes after.
2. `test_saving_does_not_erase_other_sources_learning` — fails if the merge is
   removed while the filter stays.
3. `test_corrupt_state_file_is_replaced_not_propagated`.

## Why no existing test caught it

Every harvester test builds `UpstreamHarvester(sources=[fake])` and runs in a
`HOME` with no state file, so `load_state()` returns early on
`if not STATE_FILE.exists()`. The persistence tests exercise `save_state` and
`load_state` as a pair — which is exactly the combination that works. The bug
lives in a third combination: **load into an instance whose source list differs
from the file's**. Nothing tested that.

## What this says about coverage

595 tests and seven checks did not catch this, because every one of them
exercised a single component in isolation. The defect is at a seam — `load_state`
× constructor argument × `save_state` — and seams are where current coverage is
thinnest.

## The check this produced

`scripts/runtime-check.py` — six cases driving real components through real
code paths against loopback only:

| Case | What is actually exercised |
|------|---------------------------|
| harvest both live formats | JSON + text parsers, both against a live HTTP endpoint; `is_public_ip` drops a private entry |
| validate through a real proxy | a real forward proxy on `127.0.0.1`; origin records the `X-Owl-Via` hop, so proxying is observed, not assumed |
| state isolation | run A persists, run B declares a different source, disk checked after both |
| session affinity | sticky read, rebind reports the previous proxy, TTL expiry |
| circuit breaker | opens at threshold, closes on success |
| proxy refuses non-loopback | the harness's own forward proxy answers 403 off-loopback; asserted, not assumed |

**It fails on the bug it was built for.** Against `main`'s `proxy_harvester.py`:

```
[FAIL] state isolation holds across instances:
       run B inherited ['rt_a']; disk after B has ['rt_a', 'rt_b']
```

and with the load filter but the merge reverted — the middle row of the table
above — it fails the other way:

```
[FAIL] state isolation holds across instances:
       run B inherited nothing; disk after B has ['rt_b']
```

Both halves of the coupling are caught, `--check` exits 1 either way, and it
passes on the fixed tree. A check that has never failed is a green light with a
test suite attached; this one has been made to fail deliberately.

Two things this cost, both instructive:

- The first draft expected a fresh instance to see its own source in
  `health.snapshot()`. It sees nothing — health rows are created on first fetch.
  Asserting the wrong contract is how a check becomes noise.
- The first fixtures used `10.x` addresses. The parsers dropped every one of
  them, because `is_public_ip` rejects private/loopback/CGNAT at parse time.
  The check now asserts that drop explicitly instead of tripping over it.

## Constraint it imposes

`HOME` is redirected to a temp directory for the whole run and the state file is
deleted between cases, or the check measures a previous run's state: this bug,
one level up. And no egress is used anywhere — the sandbox that found this
reaches none of the four proxy sources, and a check that needs the internet runs
nowhere.
