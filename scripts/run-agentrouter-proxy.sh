#!/usr/bin/env bash
# Launch one installed upstream sidecar; no secrets or user configs are written.
set -euo pipefail
ROOT=${OWL_AGENTROUTER_HOME:-"$HOME/.owl-agent/agentrouter"}
[[ $# == 1 ]] || { echo 'Usage: run-agentrouter-proxy.sh go|opencode' >&2; exit 2; }
case "$1" in
  go)
    [[ -x "$ROOT/go-proxy" ]] || { echo 'Go proxy is not installed' >&2; exit 1; }
    # Keep this wrapper loopback-only and avoid the upstream default prompt injection.
    export LISTEN_ADDRESS=127.0.0.1
    export INJECT_SYSTEM_PROMPT="${INJECT_SYSTEM_PROMPT-}"
    exec "$ROOT/go-proxy" ;;
  opencode)
    [[ -x "$ROOT/opencode-venv/bin/python" && -f "$ROOT/opencode/proxy.py" ]] || { echo 'OpenCode proxy is not installed' >&2; exit 1; }
    exec "$ROOT/opencode-venv/bin/python" "$ROOT/opencode/proxy.py" ;;
  *) echo 'Usage: run-agentrouter-proxy.sh go|opencode' >&2; exit 2 ;;
esac
