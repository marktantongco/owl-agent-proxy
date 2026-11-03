#!/usr/bin/env bash
# Install two pinned upstream sidecars alongside OWL, never into OWL's own venv.
set -euo pipefail
umask 077
GO_COMMIT=afa0be17622f95c276d447ab45decb6a049095a7
OPENCODE_COMMIT=cbc6e540a85900e1f50398a8b72885237970702b
ROOT=${OWL_AGENTROUTER_HOME:-"$HOME/.owl-agent/agentrouter"}
PYTHON=${PYTHON:-python3}
GO=${GO:-go}
usage() { echo 'Usage: install-agentrouter-proxies.sh [all|go|opencode]'; }
mode=${1:-all}
[[ $# -le 1 ]] || { usage >&2; exit 2; }
case "$mode" in all|go|opencode) ;; -h|--help) usage; exit 0;; *) usage >&2; exit 2;; esac
command -v git >/dev/null || { echo 'git is required' >&2; exit 1; }
mkdir -p "$ROOT"
ROOT=$(cd "$ROOT" && pwd -P)

install_source() {
  local name=$1 url=$2 rev=$3 dest="$ROOT/$1" tmp
  if [[ -e "$dest" ]]; then
    [[ -d "$dest/.git" ]] || { echo "Refusing to overwrite $dest" >&2; return 1; }
    [[ $(git -C "$dest" rev-parse HEAD) == "$rev" ]] || { echo "Wrong revision in $dest; move it aside manually" >&2; return 1; }
    [[ -z $(git -C "$dest" status --porcelain --untracked-files=no) ]] || { echo "Tracked changes in $dest; move it aside manually" >&2; return 1; }
    return
  fi
  tmp=$(mktemp -d "$ROOT/.install-${name}.XXXXXXXX")
  if ! git clone --quiet --no-checkout "$url" "$tmp" || ! git -C "$tmp" checkout --quiet --detach "$rev"; then
    rm -rf -- "$tmp"
    echo "Unable to fetch $name at pinned revision" >&2
    return 1
  fi
  if ! mv -T -n -- "$tmp" "$dest" || [[ -d "$tmp" ]]; then
    rm -rf -- "$tmp"
    echo "Destination already exists: $dest" >&2
    return 1
  fi
}

if [[ "$mode" == all || "$mode" == go ]]; then
  command -v "$GO" >/dev/null || { echo 'Go 1.26.5+ is required; set GO to its executable' >&2; exit 1; }
  install_source go https://github.com/trefeon/agentrouter-spoof-proxy.git "$GO_COMMIT"
  # Do not replace the running binary until compilation succeeds.
  temp_binary=$(mktemp "$ROOT/.go-proxy.XXXXXXXX")
  if ! (cd "$ROOT/go" && "$GO" build -o "$temp_binary" ./cmd/proxy); then
    rm -f -- "$temp_binary"
    echo 'Go build failed; the prior binary was retained' >&2
    exit 1
  fi
  mv -f -- "$temp_binary" "$ROOT/go-proxy"
fi
if [[ "$mode" == all || "$mode" == opencode ]]; then
  "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
  install_source opencode https://github.com/Goodnessmbakara/agentrouter-opencode-proxy.git "$OPENCODE_COMMIT"
  if [[ ! -x "$ROOT/opencode-venv/bin/python" ]]; then
    "$PYTHON" -m venv "$ROOT/opencode-venv"
  fi
  "$ROOT/opencode-venv/bin/python" -m pip install 'anthropic==0.49.0' 'httpx>=0.27,<0.29' 'fastapi>=0.111,<1' 'uvicorn[standard]>=0.30,<1'
fi
printf '\nInstalled requested upstream project(s) under %s\n' "$ROOT"
echo 'Start each independently with scripts/run-agentrouter-proxy.sh go|opencode; see docs/AGENTROUTER_UPSTREAM_SERVICES.md.'
