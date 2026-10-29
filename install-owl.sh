#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# 🦉 OWL-AGENT v7.1 — installer
# ══════════════════════════════════════════════════════════════════════════════
# Installs the repo's modules into ~/.owl-agent:
#
#   proxy_defense.py       cache → dedupe → rate limit → sticky proxy select
#   proxy_harvester.py     upstream harvest, honeypot detector, session affinity
#   mcp_proxy_server.py    stdlib-only MCP server (4 tools, stdio JSON-RPC)
#   run.sh                 launcher: run.sh [stats|fetch|harvest|validate|mcp]
#
# Additive and idempotent: re-running upgrades code but never overwrites
# config/proxy_pool.json, config/proxy_cache.json, config/config.json values or
# models/. A timestamped backup is taken before every code change.
#
# Usage:
#   ./install-owl.sh                 install + verify
#   ./install-owl.sh --no-live       install + verify without network checks
#   ./install-owl.sh --full          also install h2 / curl_cffi / websockets / redis
#   ./install-owl.sh --verify-only   re-run verification against an existing install
#   ./install-owl.sh --rollback      restore the most recent backup
#   ./install-owl.sh --purge         delete ~/.owl-agent (asks first)
#   OWL_SKIP_VERIFY=1 ./install-owl.sh
#
# Env:
#   OWL_HOME      install root (default ~/.owl-agent)
#   OWL_SOURCE    source directory (default: directory containing this script)
#   PYTHON        interpreter used to build the venv (default python3)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

VERSION="7.1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${OWL_SOURCE:-$SCRIPT_DIR}"
OWL_HOME="${OWL_HOME:-$HOME/.owl-agent}"
VENV="$OWL_HOME/venv"
PY_SYSTEM="${PYTHON:-$(command -v python3 || command -v python || true)}"
LIVE=1
FULL=0
MODE="install"

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[0;33m'
BLU=$'\033[0;34m'; NC=$'\033[0m'
info() { echo -e "${GRN}▶ $*${NC}"; }
warn() { echo -e "${YEL}⚠ $*${NC}"; }
step() { echo -e "\n${BLU}── $* ──${NC}"; }
die()  { echo -e "${RED}❌ $*${NC}" >&2; exit 1; }

usage() {
  sed -n '2,42p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ── arguments ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)      usage; exit 0 ;;
    --full)         FULL=1 ;;
    --no-live)      LIVE=0 ;;
    --verify-only)  MODE="verify" ;;
    --rollback)     MODE="rollback" ;;
    --purge)        MODE="purge" ;;
    --yes|-y)       ASSUME_YES=1 ;;
    *)              die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

if [[ "$MODE" == "purge" ]]; then
  [[ -d "$OWL_HOME" ]] || die "$OWL_HOME does not exist"
  if [[ "${ASSUME_YES:-0}" != "1" ]]; then
    read -rp "Delete $OWL_HOME (config, cache, models, venv)? [y/N] " answer
    [[ "${answer:-n}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
  fi
  rm -rf "$OWL_HOME"
  info "Removed $OWL_HOME"
  exit 0
fi

# ── rollback ─────────────────────────────────────────────────────────────────
if [[ "$MODE" == "rollback" ]]; then
  step "Rollback"
  latest="$( { find "$OWL_HOME/backups" -mindepth 1 -maxdepth 1 -type d 2>/dev/null || true; } | sort | tail -n1 )"
  [[ -n "$latest" ]] || die "no backups found under $OWL_HOME/backups"
  info "Restoring from $latest"
  for file in "$latest"/*; do
    name="$(basename "$file")"
    case "$name" in
      config.json) cp "$file" "$OWL_HOME/config/config.json" ;;
      *)           cp "$file" "$OWL_HOME/$name" ;;
    esac
  done
  info "Restored: $(ls -1 "$latest" | tr '\n' ' ')"
  exit 0
fi

# ── platform detection ───────────────────────────────────────────────────────
# Remediation hints must match the host. "apt install python3-venv" is a dead end
# on Arch, where venv is bundled with `python` and no such package exists.
DISTRO_ID="unknown"
DISTRO_PRETTY="unknown"
OS_RELEASE_FILE="${OWL_OS_RELEASE:-/etc/os-release}"   # overridable so the detection is testable
if [[ -r "$OS_RELEASE_FILE" ]]; then
  DISTRO_ID="$(. "$OS_RELEASE_FILE" 2>/dev/null; printf '%s' "${ID:-unknown}")"
  DISTRO_PRETTY="$(. "$OS_RELEASE_FILE" 2>/dev/null; printf '%s' "${PRETTY_NAME:-${ID:-unknown}}")"
fi

case "$DISTRO_ID" in
  arch|manjaro|endeavouros|cachyos|garuda|artix)
    PKG_MGR="pacman"
    SYS_PY="/usr/bin/python"
    PY_PKG_HINT="sudo pacman -S python"
    VENV_PKG_HINT="venv is bundled with the 'python' package on Arch — no separate package needed" ;;
  debian|ubuntu|linuxmint|pop|raspbian)
    PKG_MGR="apt"
    SYS_PY="/usr/bin/python3"
    PY_PKG_HINT="sudo apt install python3"
    VENV_PKG_HINT="sudo apt install python3-venv" ;;
  fedora|rhel|centos|rocky|almalinux)
    PKG_MGR="dnf"
    SYS_PY="/usr/bin/python3"
    PY_PKG_HINT="sudo dnf install python3"
    VENV_PKG_HINT="venv ships with python3 — reinstall python3" ;;
  alpine)
    PKG_MGR="apk"
    SYS_PY="/usr/bin/python3"
    PY_PKG_HINT="sudo apk add python3"
    VENV_PKG_HINT="venv ships with python3 — reinstall python3" ;;
  opensuse*|sles|sled)
    PKG_MGR="zypper"
    SYS_PY="/usr/bin/python3"
    PY_PKG_HINT="sudo zypper install python3"
    VENV_PKG_HINT="sudo zypper install python3-base" ;;
  *)
    PKG_MGR="unknown"
    SYS_PY="python3"
    PY_PKG_HINT="install Python 3.10+ with your package manager"
    VENV_PKG_HINT="install your distro's Python venv package" ;;
esac

# ── preflight ────────────────────────────────────────────────────────────────
step "Preflight"
info "Platform: $DISTRO_PRETTY (id=$DISTRO_ID, pkg=$PKG_MGR)"
if [[ "$DISTRO_ID" == "arch" ]] && [[ -d /usr/share/omarchy || -d "$HOME/.local/share/omarchy" ]]; then
  info "omArchy detected — Arch + Hyprland"
fi

[[ -n "$PY_SYSTEM" ]] || die "python3 not found — $PY_PKG_HINT"
"$PY_SYSTEM" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' \
  || die "Python ≥ 3.10 required (found $("$PY_SYSTEM" -V 2>&1)) — $PY_PKG_HINT"
PY_VER="$("$PY_SYSTEM" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
info "Python $PY_VER ($PY_SYSTEM)"

# A mise / asdf / pyenv shim ties the venv to one interpreter version: switching
# runtimes later leaves a silently broken venv. omArchy manages runtimes with
# mise, so this is the common case there, not an edge case.
case "$PY_SYSTEM" in
  */mise/*|*/.asdf/*|*/.pyenv/*|*/.rtx/*)
    warn "Python is managed by mise/asdf/pyenv — the venv is pinned to $PY_VER."
    warn "To survive a runtime switch, reinstall with a system interpreter:"
    warn "  PYTHON=$SYS_PY ./install-owl.sh"
    ;;
esac

if [[ "$MODE" == "verify" ]]; then
  [[ -x "$VENV/bin/python" ]] || die "no venv at $VENV — install first"
  exec "$VENV/bin/python" "$OWL_HOME/verify_install.py" --owl-home "$OWL_HOME" \
    $([[ "$LIVE" == "1" ]] || echo --no-live)
fi

for required in proxy_defense.py proxy_harvester.py mcp_proxy_server.py \
                requirements.txt scripts/verify-install.py; do
  [[ -f "$SRC/$required" ]] || die "$required not found in $SRC (set OWL_SOURCE)"
done
info "Source: $SRC"

# ── layout ───────────────────────────────────────────────────────────────────
step "Layout"
mkdir -p "$OWL_HOME"/{config,cache/http,models,plugins,logs,backups}
info "$OWL_HOME ready"

# ── venv ─────────────────────────────────────────────────────────────────────
step "Virtual environment"
if [[ -x "$VENV/bin/python" ]]; then
  VVEN="$("$VENV/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "$VVEN" != "$PY_VER" ]]; then
    warn "venv is $VVEN but system is $PY_VER — recreating venv"
    rm -rf "$VENV"
  fi
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PY_SYSTEM" -m venv --prompt owl-agent "$VENV" \
    || die "venv creation failed — $VENV_PKG_HINT"
  info "created $VENV"
else
  info "reusing $VENV"
fi
PY="$VENV/bin/python"
"$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true

# ── dependencies ─────────────────────────────────────────────────────────────
step "Dependencies"
"$PY" -m pip install -q --upgrade pip setuptools wheel 2>/dev/null || warn "pip self-upgrade skipped"
info "installing core requirements"
if ! "$PY" -m pip install -q -r "$SRC/requirements.txt"; then
  die "core dependencies failed — check your network/pip config, then re-run"
fi
"$PY" -c "import aiohttp, aiofiles, httpx" || die "core imports failed after install"
info "core dependencies installed"

if [[ "$FULL" == "1" ]]; then
  info "installing optional protocols (http/2, ja3, websocket, redis)"
  "$PY" -m pip install -q 'httpx[http2]>=0.28' 'curl_cffi>=0.7' 'websockets>=15' 'redis>=5' \
    || warn "some optional packages failed — the stack still runs on http/1.1"
  "$PY" -c "import h2, curl_cffi, websockets" 2>/dev/null \
    && info "optional protocols available" \
    || warn "optional protocols partially available"
  info "browser automation not installed — 'pip install playwright && playwright install chromium'"
fi

# ── backup ───────────────────────────────────────────────────────────────────
step "Backup"
BACKUP_DIR="$OWL_HOME/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
backed_up=0
for file in proxy_defense.py proxy_harvester.py mcp_proxy_server.py run.sh verify_install.py; do
  if [[ -f "$OWL_HOME/$file" ]]; then
    cp "$OWL_HOME/$file" "$BACKUP_DIR/$file"
    backed_up=$((backed_up + 1))
  fi
done
if [[ -f "$OWL_HOME/config/config.json" ]]; then
  cp "$OWL_HOME/config/config.json" "$BACKUP_DIR/config.json"
  backed_up=$((backed_up + 1))
fi
if [[ "$backed_up" -gt 0 ]]; then
  info "backed up $backed_up file(s) → $BACKUP_DIR"
  # keep the last 5 backups to bound disk use
  { ls -1dt "$OWL_HOME"/backups/*/ 2>/dev/null || true; } | tail -n +6 | xargs -r rm -rf
else
  info "fresh install — nothing to back up"
fi

# ── modules ──────────────────────────────────────────────────────────────────
step "Installing modules"
for file in proxy_defense.py proxy_harvester.py mcp_proxy_server.py; do
  install -m 0644 "$SRC/$file" "$OWL_HOME/$file"
  "$PY" -m py_compile "$OWL_HOME/$file" || die "$file failed to compile"
  info "$file ($(wc -l < "$OWL_HOME/$file") lines)"
done
install -m 0755 "$SRC/scripts/verify-install.py" "$OWL_HOME/verify_install.py"
info "verify_install.py"

cat > "$OWL_HOME/run.sh" <<RUNSH
#!/usr/bin/env bash
# 🦉 OWL-AGENT v${VERSION} launcher
set -euo pipefail
OWL_HOME="\${OWL_HOME:-$OWL_HOME}"
export PYTHONPATH="\$OWL_HOME\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPYCACHEPREFIX="\$OWL_HOME/__pycache__"
export PYTHONUNBUFFERED=1
PY="\$OWL_HOME/venv/bin/python"

case "\${1:-}" in
  mcp)
    shift
    exec "\$PY" -O "\$OWL_HOME/mcp_proxy_server.py" "\$@"
    ;;
  mcp-selftest)
    shift
    OWL_MCP_WARMUP_SEC=0 exec "\$PY" "\$OWL_HOME/mcp_proxy_server.py" --selftest "\$@"
    ;;
  verify)
    shift
    exec "\$PY" "\$OWL_HOME/verify_install.py" --owl-home "\$OWL_HOME" "\$@"
    ;;
  *)
    exec "\$PY" -O "\$OWL_HOME/proxy_defense.py" "\$@"
    ;;
esac
RUNSH
chmod 0755 "$OWL_HOME/run.sh"
info "run.sh"

# ── configuration (merge, never clobber) ─────────────────────────────────────
step "Configuration"
if [[ -f "$OWL_HOME/config/config.json" ]]; then
  "$PY" - "$OWL_HOME/config/config.json" <<'PYMERGE'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
defaults = {
    "cache_ttl": 300,
    "rate_limit": 2.0,
    "max_retries": 2,
    "use_upstream_harvester": True,
    "session_ttl": 900,
    "harvest_interval": 600,
    "honeypot_check": True,
    "max_proxies": 2000,
    "max_per_source": 300,
    "validator_concurrency": 10,
    "validator_timeout": 8,
    "persist_proxy_cache": True,
}
try:
    current = json.loads(path.read_text())
    if not isinstance(current, dict):
        current = {}
except Exception:
    current = {}
added = [key for key in defaults if key not in current]
current.update({k: v for k, v in defaults.items() if k not in current})
path.write_text(json.dumps(current, indent=2) + "\n")
print(f"merged config ({len(added)} new keys)" if added else "config preserved")
PYMERGE
  info "config/config.json merged"
else
  cat > "$OWL_HOME/config/config.json" <<'JSON'
{
  "cache_ttl": 300,
  "rate_limit": 2.0,
  "max_retries": 2,
  "use_upstream_harvester": true,
  "session_ttl": 900,
  "harvest_interval": 600,
  "honeypot_check": true,
  "max_proxies": 2000,
  "max_per_source": 300,
  "validator_concurrency": 10,
  "validator_timeout": 8,
  "persist_proxy_cache": true
}
JSON
  info "config/config.json written"
fi

if [[ ! -f "$OWL_HOME/config/proxy_pool.json" ]]; then
  cp "$SRC/config/proxy_pool.template.json" "$OWL_HOME/config/proxy_pool.json"
  info "config/proxy_pool.json initialised from template"
else
  info "config/proxy_pool.json preserved"
fi

"$PY" -m pip freeze > "$OWL_HOME/requirements.txt" 2>/dev/null || true
"$PY" -m compileall -q "$OWL_HOME" >/dev/null 2>&1 || true

# ── verification ─────────────────────────────────────────────────────────────
if [[ "${OWL_SKIP_VERIFY:-0}" == "1" ]]; then
  warn "OWL_SKIP_VERIFY=1 — skipping verification"
  VERIFY_RC=0
else
  step "Verification"
  VERIFY_ARGS=(--owl-home "$OWL_HOME")
  [[ "$LIVE" == "1" ]] || VERIFY_ARGS+=(--no-live)
  set +e
  "$PY" "$OWL_HOME/verify_install.py" "${VERIFY_ARGS[@]}"
  VERIFY_RC=$?
  set -e
fi

# ── banner ───────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
if [[ "$VERIFY_RC" -ne 0 ]]; then
  echo -e "${RED}❌ OWL-AGENT v${VERSION} installed, but verification FAILED${NC}"
  echo "   Fix the failures above, then re-run: $0 --verify-only"
  echo "   Roll back with: $0 --rollback"
  exit 1
fi
echo -e "${GRN}✅ OWL-AGENT v${VERSION} installed$([[ "${OWL_SKIP_VERIFY:-0}" == "1" ]] || echo ' + verified')${NC}"
echo "   Home   : $OWL_HOME"
echo "   CLI    : $OWL_HOME/run.sh"
echo "   MCP    : $OWL_HOME/mcp_proxy_server.py"
echo "   Config : $OWL_HOME/config/config.json"
echo ""
echo "   Try    : $OWL_HOME/run.sh stats"
echo "   Fetch  : $OWL_HOME/run.sh fetch https://httpbin.org/ip --json"
echo "   Harvest: $OWL_HOME/run.sh harvest --seconds 20"
echo "   MCP    : $OWL_HOME/run.sh mcp-selftest"
echo ""
echo "   Wire an MCP host (Claude Desktop / Cursor / VS Code / Codex / Gemini):"
echo "     python $OWL_HOME/mcp_proxy_server.py      # stdio server"
echo "     docs/MCP_INTEGRATION.md                   # per-host snippets"
echo "════════════════════════════════════════════════════════════"
