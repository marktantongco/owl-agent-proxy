---
name: owl-proxy-mcp
description: Give any MCP-capable agent a shared proxy pool by wiring the owl-proxy stdio MCP server. Covers host configuration, the four tools (proxy_pick, proxy_stats, proxy_rotate, proxy_validate), the correct pick-fetch-rotate agent loop, stdout purity requirements, and the failure modes that make proxy_pick return null.
---

# owl-proxy MCP server

`mcp_proxy_server.py` exposes the proxy pool over **stdio** using newline-delimited JSON-RPC 2.0
(`Content-Length` framing is also accepted). Protocol `2025-06-18`; `serverInfo`
`{"name": "owl-proxy", "version": "7.1.0"}`.

The protocol layer is **stdlib-only**, and the proxy backend is imported lazily on the first tool
call — so a host's `initialize` handshake answers in milliseconds on a cold machine.

> **Nothing listens on a network port.** The server reads stdin and writes stdout only.
> All diagnostics go to stderr.

## Install first

```bash
./install-owl.sh            # add --no-live on a machine without egress
```

That creates `~/.owl-agent/mcp_proxy_server.py`, `~/.owl-agent/venv/bin/python`, and
`~/.owl-agent/config/config.json` (harvesting / session settings).

## Host wiring

Every host launches the same command; only the config file location and top-level key differ.

```json
{
  "command": "/home/YOU/.owl-agent/venv/bin/python",
  "args": ["/home/YOU/.owl-agent/mcp_proxy_server.py"],
  "env": { "OWL_MCP_WARMUP_SEC": "3" }
}
```

- **Claude Desktop** — macOS `~/Library/Application Support/Claude/claude_desktop_config.json`,
  Windows `%APPDATA%\Claude\claude_desktop_config.json`, under the key `mcpServers`.
- **Others** — same `command`/`args`/`env` object under the host's own key
  (`mcpServers`, `servers`, …). See `docs/MCP_INTEGRATION.md` for the per-host table.

On Windows use the full path to `python.exe` and escape backslashes.

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `proxy_pick` | `domain` **(required)**, `agent_id`, `rotation_mode` = `sticky`\|`random`\|`round_robin` | `{proxy, protocol, tier, source, latency_ms}` — **`proxy: null` while the pool warms** |
| `proxy_stats` | — | pool totals, `source_health`, `session_affinity`, `upstream_harvester`, `protocols_available` |
| `proxy_rotate` | `domain` **(required)**, `agent_id` | `{rotated: true/false}` — drops the sticky binding for that pair |
| `proxy_validate` | `proxy_url` **(required)** | TCP/HTTP timings, `valid`, `trusted`, honeypot `reason` |

`rotation_mode="sticky"` (default) binds one exit IP to `(agent_id, domain)` for `session_ttl`
seconds (default 900). **Keep `agent_id` stable for the life of a task.**

## The correct agent loop

```text
proxy_pick(domain="target.example", agent_id="job-42")
  ├─ proxy != null → fetch through it; keep using it for this task
  └─ proxy == null → fetch directly this time; retry on the next call (pool is warming)

on 403/429 from the target:
proxy_rotate(domain="target.example", agent_id="job-42") → proxy_pick again
```

Never treat `proxy: null` as an error — it is the defined cold-pool signal, and the caller is
expected to fall back to a direct fetch.

## Verify without a host

```bash
~/.owl-agent/run.sh mcp-selftest     # initialize → tools/list → error cases
python mcp_proxy_server.py --selftest
```

The selftest asserts `serverInfo`, the four tool names, `-32601` for unknown methods, and
`-32602` for unknown tools.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `proxy_pick` always `null` | Pool cold or harvesting disabled | `run.sh stats --json` → check `upstream_harvester.running`; wait 1–3 min; confirm `OWL_MCP_HARVEST=1` |
| Garbled / unparsable protocol errors | Something else is writing to **stdout** | Run `run.sh mcp-selftest`; if it passes, the noise is from the host, not the server |
| Host sees no tools | Wrong interpreter path (system python lacks deps) | Point `command` at `~/.owl-agent/venv/bin/python` |
| Handshake hangs | Warmup too long for host timeout | Lower `OWL_MCP_WARMUP_SEC` (e.g. `"0"`) |
| Every pick is `trusted: false` | Free pool degraded | `run.sh harvest --seconds 20`, then `run.sh stats` |

## Environment knobs

| Variable | Effect |
|---|---|
| `OWL_MCP_WARMUP_SEC` | Max seconds to warm the pool during startup |
| `OWL_MCP_HARVEST` | `1` enables upstream harvesting |
| `OWL_HOME` / `OWL_AGENT_HOME` | Install root override |

## Limits

Sticky IP with a **static** TLS/HTTP fingerprint; free proxies only by default (no SLA, no
throughput guarantee); honeypot detection is structural, not semantic; no SOCKS validation.
Rotating `agent_id` mid-task defeats the purpose of sticky sessions.
