# 🦉 MCP Integration — `owl-proxy`

`mcp_proxy_server.py` exposes the proxy pool to any MCP-capable agent over
**stdio**. It speaks newline-delimited JSON-RPC 2.0 (LSP-style `Content-Length`
framing is also accepted), implements `initialize`, `tools/list`, `tools/call`,
`resources/list`, `prompts/list` and `ping`, and ships four tools.

The protocol layer is stdlib-only. The proxy backend (`proxy_defense.py`) is
imported lazily on the first tool call, so a host's `initialize` handshake is
answered in milliseconds even on a cold machine.

> Nothing listens on the network. The server only reads stdin and writes
> stdout; diagnostics go to stderr.

---

## Install first

```bash
cd owl-agent-proxy
./install-owl.sh            # add --no-live on a machine without egress
```

That creates:

| Path | Purpose |
|------|---------|
| `~/.owl-agent/mcp_proxy_server.py` | the server |
| `~/.owl-agent/venv/bin/python` | interpreter with the backend's deps |
| `~/.owl-agent/config/config.json` | harvesting / session settings |

## Tools

| Tool | Arguments | Returns |
|------|-----------|---------|
| `proxy_pick` | `domain` (req), `agent_id`, `rotation_mode` (`sticky`\|`random`\|`round_robin`) | `{proxy, protocol, tier, source, latency_ms}` — `proxy: null` while the pool warms |
| `proxy_stats` | — | pool totals, `source_health`, `session_affinity`, `upstream_harvester`, `protocols_available` |
| `proxy_rotate` | `domain` (req), `agent_id` | `{rotated: true/false}` — drops the sticky binding for that pair |
| `proxy_validate` | `proxy_url` (req) | TCP/HTTP timings, `valid`, `trusted`, honeypot `reason` |

`proxy_pick` with `rotation_mode="sticky"` (the default) binds one exit IP to
`(agent_id, domain)` for `session_ttl` seconds (default 900). Keep the same
`agent_id` for the life of a task; rotating mid-task is what makes a target see
"a user teleporting between cities".

Recommended agent loop:

```text
proxy_pick(domain="target.example", agent_id="job-42")
  ├─ proxy != null → fetch through it, keep using it for this task
  └─ proxy == null → fetch directly this time, try again on the next call

on 403/429 from the target:
proxy_rotate(domain="target.example", agent_id="job-42") → proxy_pick again
```

---

## Host wiring

Every host launches the same command; only the config file location and the
top-level key differ.

```json
{
  "command": "/home/YOU/.owl-agent/venv/bin/python",
  "args": ["/home/YOU/.owl-agent/mcp_proxy_server.py"],
  "env": { "OWL_MCP_WARMUP_SEC": "3" }
}
```

Replace `YOU` with your username (on Windows, use the full path to
`python.exe` and escape backslashes).

### Claude Desktop

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "owl-proxy": {
      "command": "/home/YOU/.owl-agent/venv/bin/python",
      "args": ["/home/YOU/.owl-agent/mcp_proxy_server.py"],
      "env": { "OWL_MCP_WARMUP_SEC": "3" }
    }
  }
}
```

### Claude Code

```bash
claude mcp add owl-proxy -- /home/YOU/.owl-agent/venv/bin/python /home/YOU/.owl-agent/mcp_proxy_server.py
```

or, in project scope, `.mcp.json`:

```json
{
  "mcpServers": {
    "owl-proxy": {
      "type": "stdio",
      "command": "/home/YOU/.owl-agent/venv/bin/python",
      "args": ["/home/YOU/.owl-agent/mcp_proxy_server.py"]
    }
  }
}
```

### Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project):

```json
{
  "mcpServers": {
    "owl-proxy": {
      "command": "/home/YOU/.owl-agent/venv/bin/python",
      "args": ["/home/YOU/.owl-agent/mcp_proxy_server.py"]
    }
  }
}
```

### VS Code (MCP)

`.vscode/mcp.json` in the workspace:

```json
{
  "servers": {
    "owl-proxy": {
      "type": "stdio",
      "command": "/home/YOU/.owl-agent/venv/bin/python",
      "args": ["/home/YOU/.owl-agent/mcp_proxy_server.py"]
    }
  }
}
```

### Codex CLI

```bash
codex --mcp-server "owl-proxy:/home/YOU/.owl-agent/venv/bin/python /home/YOU/.owl-agent/mcp_proxy_server.py"
```

### Gemini CLI

```bash
gemini --mcp-server "owl-proxy:/home/YOU/.owl-agent/venv/bin/python /home/YOU/.owl-agent/mcp_proxy_server.py"
```

### OpenCode

`~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "owl-proxy": {
      "type": "local",
      "command": ["/home/YOU/.owl-agent/venv/bin/python",
                  "/home/YOU/.owl-agent/mcp_proxy_server.py"],
      "enabled": true
    }
  }
}
```

---

## Smoke test

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | OWL_MCP_WARMUP_SEC=0 ~/.owl-agent/venv/bin/python ~/.owl-agent/mcp_proxy_server.py

# or, with no piping at all:
~/.owl-agent/run.sh mcp-selftest
```

Expected: two JSON lines on stdout — `serverInfo` (`owl-proxy`, `7.1.0`) and the
four tool names. Anything else on stdout is a bug: the server redirects stray
backend `print()` output to stderr while a tool runs.

## Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `OWL_AGENT_HOME` | `~/.owl-agent` | where the backend modules live |
| `OWL_MCP_HARVEST` | unset → `config.json` | `0` disables harvesting, `1` forces it (overrides the config kill switch) |
| `OWL_MCP_WARMUP_SEC` | `3` | how long `proxy_pick` waits for the pool to validate before returning `null` |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `proxy_pick` always returns `null` | pool cold or harvesting disabled | `run.sh stats` → check `upstream_harvester.running`; wait 1–3 min; confirm `OWL_MCP_HARVEST=1` |
| Host shows "server exited" immediately | wrong interpreter path | use `~/.owl-agent/venv/bin/python`, not system `python3` |
| `ModuleNotFoundError: proxy_defense` | `OWL_AGENT_HOME` points elsewhere | unset it, or point it at the install root |
| `tools/call` returns `isError: true` with an import error | backend deps missing | `~/.owl-agent/venv/bin/python -m pip install -r ~/.owl-agent/requirements.txt` |
| Host hangs on startup | a host that waits for a warm-up it never requested | set `OWL_MCP_WARMUP_SEC=0` |
| Garbled protocol errors | something else is writing to stdout | run `run.sh mcp-selftest`; if it passes, the noise is from the host, not the server |

Full install verification (including a real stdio handshake):

```bash
~/.owl-agent/run.sh verify            # add --no-live to skip network checks
```
