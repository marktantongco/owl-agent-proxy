# Stealth browser rung (`protocol="stealth"`)

The top of the escalation ladder. Everything below it — `http/1.1`, `http/2`,
`ja3`, `websocket`, `browser` — is cheaper and should be tried first.

This wraps [invisible_playwright](https://github.com/feder-cr/invisible_playwright),
an MIT-licensed Firefox patched at the C++ source level so the fingerprint is set
inside the engine rather than injected into the page. Input is humanised in the
driver: pointer paths and timing, not a teleporting cursor.

> **Read this first.** Stealth is not invisibility. Every claim below is about
> what the tool is *built* to do; none of it is a guarantee about any particular
> target. Detection is an arms race and the arms change weekly. Whether automated
> access is permitted is decided by the target's terms and your jurisdiction —
> this project ships **no compliance advice**. See [Limits](#limits).

## Install

The engine is optional and never imported at module load, so the stack runs
without it.

```bash
pip install invisible-playwright      # Python >= 3.11
invisible-playwright fetch            # one-time: ~260 MB download, ~550 MB unpacked
```

`pip install 'owl-agent-proxy[stealth]'` does the first step. The second is
required and is easy to miss: the package ships the Python wrapper, not the
browser, so the first launch without a fetch fails at download time.

Python **3.11+** only — the library's floor, above this project's 3.10.
`pip install` on 3.10 will report the extra as unsupported rather than install
something broken.

Verify:

```bash
python -c "import proxy_defense as p; print(p.STEALTH_INSTALLED)"
```

## Use

```python
import asyncio
from proxy_defense import ResilientClient

async def main():
    async with ResilientClient(use_upstream_harvester=True) as client:
        resp = await client.request(
            "GET",
            "https://target.example",
            protocol="stealth",       # after http/1.1 and ja3 have been refused
            timezone="Asia/Manila",   # see below — strongly recommended
            agent_id="job-42",        # keeps the exit IP sticky for this task
        )
        print(resp.status, resp.protocol)

asyncio.run(main())
```

The pool's proxy is handed to the engine as `{"server": "<proxy-url>"}`, so the
browser egresses through the same exit IP as the rest of the request path. The
sticky `(agent_id, domain)` binding applies here too: rotating identity mid-task
is the single most obvious tell.

### Pin a timezone

With no timezone, the engine discovers the egress IP by calling public `checkip`
endpoints **through the proxy** before it can start. That costs a round trip,
fails if the proxy cannot reach those endpoints, and is the first thing to break
behind a TLS-inspecting network — it fails with `GeoTimezoneError` before any
browser launches.

Passing `timezone=` skips that discovery entirely. A timezone that contradicts
the exit IP is its own signal, so pin the target's region, not yours.

Other pass-throughs: `locale`, `seed` (reproducible fingerprint), `humanize`
(bool or float), `timeout` (seconds, default 30).

## Failure behaviour

| Situation | What happens |
|---|---|
| Library not installed | `ProtocolUnavailable` immediately, with the install + `fetch` commands. **Not retried**, and the proxy is **not** marked banned — a missing dependency is not the proxy's fault |
| Requested via `request()` | Raises rather than silently downgrading to `http/1.1`; a downgraded call must not be labelled `stealth` |
| Navigation timeout | Page is closed, browser torn down, error propagates to the retry loop |

Without these rules the retry loop would sleep and retry a configuration error
three times, and ban a healthy proxy for something it did not do.

## Limits

- **Not undetectable.** The engine answers the fingerprint and human-input
  questions well. Any target that fingerprints at a layer nobody has patched
  yet, or that scores behaviour over a session, is out of scope.
- **550 MB and a manual fetch.** Not a dependency you add casually; the rung is
  opt-in for that reason.
- **Some Playwright surfaces are refused on purpose** — tracing, HAR, CDP and
  the API request context raise with an explanation rather than misbehaving
  quietly.
- **No proxy de-anonymisation resistance.** A `ja3`-style fingerprint at the TLS
  layer still depends on the proxy's own TLS behaviour.
- **Terms of service are yours.** Using a stealth browser against a site that
  forbids automated access is a decision this tool cannot make for you.

## What was and was not verified

Verified: package resolution from PyPI, the async API shape
(`InvisiblePlaywright(headless=…, proxy=…, timezone=…)`), lazy import
(`import proxy_defense` does not import the engine), the rung driving a fake
engine end-to-end (proxy passing, page lifecycle, teardown on failure), and the
fail-fast path.

**Not verified: a real browser launch.** The sealed binary downloads from
`release-assets.githubusercontent.com`, which the development sandbox cannot
reach. The first real confirmation will be a manual run on a machine with normal
egress.

---

## Related: `invisible_dots`

[invisible_dots](https://github.com/feder-cr/invisible_dots) is by the same
author and uses this engine for its browser, but it is **not integrated here**,
deliberately.

It is not a library. It is a self-hosted *agent platform*: Node 24 + Go 1.25 +
QEMU/KVM hardware virtualisation, one VM per "Dot", its own web UI, task queue,
Telegram/WhatsApp channels and an OpenRouter key. Vendoring that into a proxy
stack would mean running a second agent runtime beside this one, with no shared
abstraction.

The useful integration runs the other way round: a Dot accepts any MCP server, so
it can consume this project's `owl-proxy-mcp` for its proxy pool —

```json
{
  "command": "/home/YOU/.owl-agent/venv/bin/python",
  "args": ["/home/YOU/.owl-agent/mcp_proxy_server.py"],
  "env": { "OWL_MCP_WARMUP_SEC": "3" }
}
```

— and gets its browser from
[invisible_playwright_mcp](https://github.com/feder-cr/invisible_playwright_mcp).
See [MCP_INTEGRATION.md](MCP_INTEGRATION.md) for host wiring.
