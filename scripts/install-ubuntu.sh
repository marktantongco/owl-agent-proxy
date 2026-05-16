#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# 🦉 OWL-AGENT PROXY DEFENSE STACK v3.0 — Ubuntu Installer
# ═══════════════════════════════════════════════════════════════════════════════
# Usage:
#   chmod +x scripts/install-ubuntu.sh
#   sudo ./scripts/install-ubuntu.sh              # full system install
#   ./scripts/install-ubuntu.sh --user            # user-only (no sudo)
#   ./scripts/install-ubuntu.sh --minimal         # Phase 1 only (http/1.1)
#   ./scripts/install-ubuntu.sh --verify          # verify existing install
# ═══════════════════════════════════════════════════════════════════════════════

REPO_URL="https://github.com/marktantongco/owl-agent-proxy.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/owl-agent-proxy}"
PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-$HOME/.owl-agent/venv}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.owl-agent/config}"
CACHE_DIR="${CACHE_DIR:-$HOME/.owl-agent/cache}"
LOG_DIR="${LOG_DIR:-$HOME/.owl-agent/logs}"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.owl-agent/skills}"
WORKSPACE_DIR="${WORKSPACE_DIR:-$HOME/.owl-agent/workspace}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${BLUE}→${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
header() { echo -e "\n${BLUE}═ $1 ${NC}${BLUE}${NC}"; }

MIN_PYTHON="3.10"
UBUNTU_MIN="20.04"
ERRORS=0

check_root() {
    if [[ $EUID -ne 0 ]] && [[ "${1:-}" != "--user" ]]; then
        warn "Not running as root. Some system packages may not install."
        warn "Re-run with 'sudo ./scripts/install-ubuntu.sh' for full system install."
        echo ""
        read -rp "Continue as user-only? [Y/n] " choice
        if [[ "${choice:-Y}" =~ ^[Nn] ]]; then
            echo "Aborted."
            exit 1
        fi
    fi
}

check_ubuntu() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        if [[ "$ID" != "ubuntu" ]]; then
            warn "This script is optimized for Ubuntu. Detected: $ID $VERSION_ID"
            warn "Continuing anyway — dependencies may differ."
        else
            pass "Ubuntu $VERSION_ID detected"
        fi
    fi
}

check_python() {
    if ! command -v "$PYTHON" &>/dev/null; then
        fail "Python3 not found. Install it: sudo apt install python3 python3-pip python3-venv"
        return 1
    fi
    local ver
    ver=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if [[ "$(printf '%s\n' "$MIN_PYTHON" "$ver" | sort -V | head -n1)" != "$MIN_PYTHON" ]]; then
        fail "Python $ver detected. Need >= $MIN_PYTHON"
        return 1
    fi
    pass "Python $ver detected"
}

install_system_deps() {
    header "System Dependencies"
    if [[ $EUID -eq 0 ]]; then
        info "Installing build-essential, python3-dev, libssl-dev, curl, git..."
        apt-get update -qq
        apt-get install -y -qq \
            build-essential \
            python3-dev \
            python3-pip \
            python3-venv \
            libssl-dev \
            libffi-dev \
            curl \
            git \
            wget \
            ca-certificates \
            2>&1 | tail -1
        pass "System dependencies installed"
    else
        warn "Skipping system packages (not root)"
        warn "If builds fail, run: sudo apt install build-essential python3-dev libssl-dev"
    fi
}

clone_repo() {
    header "Cloning Repository"
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Repository already exists at $INSTALL_DIR — pulling latest"
        git -C "$INSTALL_DIR" pull --ff-only 2>&1 | tail -1
    else
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone "$REPO_URL" "$INSTALL_DIR" 2>&1 | tail -1
    fi
    pass "Repository at $INSTALL_DIR"
}

setup_venv() {
    header "Python Virtual Environment"
    mkdir -p "$(dirname "$VENV_DIR")"
    if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
        info "Creating virtual environment at $VENV_DIR..."
        "$PYTHON" -m venv "$VENV_DIR"
        pass "Virtual environment created"
    else
        info "Virtual environment already exists"
    fi
    source "$VENV_DIR/bin/activate"
    pass "Virtual environment activated"
    info "Upgrading pip..."
    pip install --quiet --upgrade pip setuptools wheel 2>&1 | tail -1
}

install_phase1_core() {
    header "Phase 1: Core (http/1.1)"
    source "$VENV_DIR/bin/activate"
    info "Installing core dependencies..."
    pip install --quiet \
        aiohttp>=3.11.0 \
        aiofiles>=24.1.0 \
        cachetools>=5.5.0 \
        orjson>=3.10.0 \
        cryptography>=44.0.0 \
        PySocks>=1.7.1 \
        requests>=2.32.0 \
        urllib3>=2.4.0 \
        PyYAML>=6.0.2 \
        tenacity>=9.1.0 \
        fake-useragent>=2.2.0 \
        aiohttp-socks>=0.10.0 \
        certifi>=2025.0.0 \
        python-dateutil>=2.9.0 \
        2>&1 | tail -1
    pass "Core dependencies installed"
    $PYTHON -c "import aiohttp, aiofiles, cachetools, orjson, cryptography, socks; print('    ✓ Imports verified')" 2>&1 || { fail "Core import check failed"; ((ERRORS++)); }
}

install_phase2_http2() {
    header "Phase 2: HTTP/2"
    source "$VENV_DIR/bin/activate"
    info "Installing httpx with HTTP/2 support..."
    pip install --quiet 'httpx[http2]>=0.28.0' 2>&1 | tail -1
    $PYTHON -c "import httpx; c=httpx.AsyncClient(http2=True); print('    ✓ HTTP/2 available')" 2>&1 || warn "HTTP/2 import failed (non-fatal)"
    pass "HTTP/2 installed"
}

install_phase3_ja3() {
    header "Phase 3: JA3 / TLS Fingerprint"
    source "$VENV_DIR/bin/activate"
    info "Installing curl_cffi..."
    pip install --quiet curl-cffi>=0.10.0 2>&1 | tail -1
    $PYTHON -c "from curl_cffi.requests import AsyncSession; print('    ✓ JA3 available')" 2>&1 || warn "curl_cffi import failed (non-fatal)"
    pass "JA3 installed"
}

install_phase4_websocket() {
    header "Phase 4: WebSocket"
    source "$VENV_DIR/bin/activate"
    info "Installing websockets..."
    pip install --quiet websockets>=15.0.0 2>&1 | tail -1
    $PYTHON -c "import websockets; print('    ✓ WebSocket available')" 2>&1 || warn "websockets import failed (non-fatal)"
    pass "WebSocket installed"
}

install_phase5_browser() {
    header "Phase 5: Browser Automation"
    source "$VENV_DIR/bin/activate"
    info "Installing Playwright..."
    pip install --quiet playwright>=1.52.0 2>&1 | tail -1
    info "Installing Chromium browser (~150 MB)..."
    $PYTHON -m playwright install chromium 2>&1 | tail -1
    $PYTHON -c "from playwright.async_api import async_playwright; print('    ✓ Browser available')" 2>&1 || warn "playwright import failed (non-fatal)"
    pass "Browser automation installed"
}

setup_directories() {
    header "Directory Structure"
    for dir in "$CONFIG_DIR" "$CACHE_DIR/http" "$CACHE_DIR/dedup" "$CACHE_DIR/proxies" "$LOG_DIR" "$SKILLS_DIR/development" "$SKILLS_DIR/system" "$WORKSPACE_DIR/projects" "$WORKSPACE_DIR/worklogs"; do
        mkdir -p "$dir"
    done
    pass "Directory structure created"
}

setup_config() {
    header "Configuration"
    if [[ ! -f "$CONFIG_DIR/proxy_pool.json" ]]; then
        if [[ -f "$INSTALL_DIR/config/proxy_pool.template.json" ]]; then
            cp "$INSTALL_DIR/config/proxy_pool.template.json" "$CONFIG_DIR/proxy_pool.json"
            info "Created proxy_pool.json — edit with your proxy credentials"
        else
            warn "proxy_pool.template.json not found — skipping"
        fi
    else
        info "proxy_pool.json already exists — keeping"
    fi

    if [[ -f "$INSTALL_DIR/config/opencode.json" ]]; then
        mkdir -p "$HOME/.config/opencode"
        cp "$INSTALL_DIR/config/opencode.json" "$HOME/.config/opencode/opencode.json" 2>/dev/null || true
    fi
    pass "Configuration files ready"
}

setup_shell_integration() {
    header "Shell Integration"
    local bashrc="$HOME/.bashrc"
    local marker="# ─── 🦉 OWL-AGENT SHELL INTEGRATION"

    if grep -qF "$marker" "$bashrc" 2>/dev/null; then
        info "Shell integration already present — updating"
        sed -i "/$marker/,/# ─── END OWL-AGENT/d" "$bashrc"
    fi

    cat >> "$bashrc" << 'SHELL'

# ─── 🦉 OWL-AGENT SHELL INTEGRATION ───────────────────────────────────────
export OWL_AGENT_HOME="$HOME/.owl-agent"
export OWL_AGENT_SKILLS="$OWL_AGENT_HOME/skills"
export OWL_AGENT_WORKSPACE="$OWL_AGENT_HOME/workspace"
export OWL_AGENT_CONFIG="$OWL_AGENT_HOME/config"
export OWL_AGENT_LOGS="$OWL_AGENT_HOME/logs"
export OWL_AGENT_CACHE="$OWL_AGENT_HOME/cache"
export OWL_AGENT_VENV="$OWL_AGENT_HOME/venv"

if [ -f "$OWL_AGENT_VENV/bin/activate" ] && [ -z "${VIRTUAL_ENV:-}" ]; then
    source "$OWL_AGENT_VENV/bin/activate"
fi

alias owl-status='echo "🦉 Owl Agent Status" && echo "  Skills: $(find "$OWL_AGENT_SKILLS" -name "*.md" 2>/dev/null | wc -l)" && echo "  Cache: $(ls "$OWL_AGENT_CACHE/http" 2>/dev/null | wc -l) entries" && python3 --version && echo "  Venv: $OWL_AGENT_VENV"'
alias owl-proxy='python3 "$OWL_AGENT_WORKSPACE/projects/proxy_defense.py"'
alias owl-skills='ls -la "$OWL_AGENT_SKILLS"'
alias owl-logs='tail -f "$OWL_AGENT_LOGS/opencode.log" 2>/dev/null || echo "No logs yet"'
alias owl-cache='ls -la "$OWL_AGENT_CACHE/http"'
alias owl-venv='source "$OWL_AGENT_VENV/bin/activate"'

owl-skill() {
    local query="$1"
    if [ -z "$query" ]; then
        echo "Usage: owl-skill <search-term>"
        return 1
    fi
    find "$OWL_AGENT_SKILLS" -name "*.md" -exec grep -l "$query" {} + 2>/dev/null | head -5
}

owl-upgrade() {
    local dir="${1:-$OWL_AGENT_WORKSPACE}"
    if [ -d "$dir/.git" ]; then
        git -C "$dir" pull --ff-only
    fi
}
# ─── END OWL-AGENT ──────────────────────────────────────────────────────────
SHELL
    pass "Shell integration added to ~/.bashrc"
}

copy_source_files() {
    header "Copying Source Files"
    mkdir -p "$WORKSPACE_DIR/projects"
    cp "$INSTALL_DIR/proxy_defense.py" "$WORKSPACE_DIR/projects/proxy_defense.py"
    cp "$INSTALL_DIR/requirements.txt" "$WORKSPACE_DIR/projects/requirements.txt"
    cp -r "$INSTALL_DIR/skills/"* "$SKILLS_DIR/" 2>/dev/null || true
    cp -r "$INSTALL_DIR/docs/"* "$WORKSPACE_DIR/projects/" 2>/dev/null || true
    chmod +x "$WORKSPACE_DIR/projects/proxy_defense.py"
    pass "Source files deployed"
}

run_validation() {
    header "Validation"
    source "$VENV_DIR/bin/activate"

    info "Running unit tests..."
    if [[ -f "$INSTALL_DIR/tests/test_proxy_defense.py" ]]; then
        $PYTHON -m pytest "$INSTALL_DIR/tests/test_proxy_defense.py" -v 2>&1 | tail -5 || warn "Some tests failed"
        pass "Unit tests complete"
    else
        warn "Test file not found — skipping"
    fi

    info "Running CI/CD pre-merge check..."
    if [[ -f "$INSTALL_DIR/.github/scripts/ci-check.sh" ]]; then
        bash "$INSTALL_DIR/.github/scripts/ci-check.sh" 2>&1 || warn "CI/CD check flagged items (review above)"
    else
        warn "CI/CD script not found — skipping"
    fi

    info "Running integration test..."
    cd "$WORKSPACE_DIR/projects"
    $PYTHON proxy_defense.py 2>&1 || warn "Integration test failed"

    info "Protocol availability:"
    $PYTHON -c "
import sys
sys.path.insert(0, '.')
from proxy_defense import HTTP2_AVAILABLE, JA3_AVAILABLE, WS_AVAILABLE, PLAYWRIGHT_AVAILABLE
print(f'  http/1.1: ✅ always')
print(f'  http/2:   {\"✅\" if HTTP2_AVAILABLE else \"⬜\"} available')
print(f'  ja3:     {\"✅\" if JA3_AVAILABLE else \"⬜\"} available')
print(f'  ws:      {\"✅\" if WS_AVAILABLE else \"⬜\"} available')
print(f'  browser: {\"✅\" if PLAYWRIGHT_AVAILABLE else \"⬜\"} available')
" 2>&1 || true
}

print_summary() {
    header "Installation Complete"
    echo ""
    echo "  🦉 OWL-AGENT Proxy Defense Stack v3.0"
    echo ""
    echo "  Repository:     $INSTALL_DIR"
    echo "  Virtual Env:    $VENV_DIR"
    echo "  Config:         $CONFIG_DIR"
    echo "  Cache:          $CACHE_DIR"
    echo "  Source:         $WORKSPACE_DIR/projects/proxy_defense.py"
    echo ""
    echo "  Commands:"
    echo "    source ~/.bashrc          # reload shell integration"
    echo "    owl-status                # show agent status"
    echo "    owl-proxy                 # run proxy defense test"
    echo "    owl-venv                  # activate virtual env"
    echo "    owl-skills                # list installed skills"
    echo "    python proxy_defense.py   # run built-in test"
    echo ""
    echo "  Install protocols on demand:"
    echo "    pip install httpx[http2]     # HTTP/2"
    echo "    pip install curl-cffi        # JA3"
    echo "    pip install websockets       # WebSocket"
    echo "    pip install playwright       # Browser"
    echo ""
    echo "  Edit proxy pool:  $CONFIG_DIR/proxy_pool.json"
    echo "  CI/CD check:      bash $INSTALL_DIR/.github/scripts/ci-check.sh"
    echo "  Unit tests:       pytest $INSTALL_DIR/tests/ -v"
    echo ""
    if [ "$ERRORS" -gt 0 ]; then
        echo -e "  ${YELLOW}⚠ $ERRORS non-fatal warnings — review above${NC}"
    fi
    echo -e "  ${GREEN}✅ Installation complete${NC}"
    echo ""
}

main() {
    local mode="${1:-full}"

    echo ""
    echo "  ╔══════════════════════════════════════════════════════════════╗"
    echo "  ║   🦉 OWL-AGENT Proxy Defense Stack v3.0                    ║"
    echo "  ║   Ubuntu Installer                                         ║"
    echo "  ╚══════════════════════════════════════════════════════════════╝"
    echo ""

    check_ubuntu
    check_root "${@}"
    check_python || exit 1

    install_system_deps
    clone_repo
    setup_venv
    setup_directories

    install_phase1_core

    if [[ "$mode" == "full" ]] || [[ "$mode" == "--minimal" ]]; then
        if [[ "$mode" == "full" ]]; then
            install_phase2_http2 || true
            install_phase3_ja3 || true
            install_phase4_websocket || true
            install_phase5_browser || true
        fi
    fi

    setup_config
    setup_shell_integration
    copy_source_files
    run_validation
    print_summary
}

main "${@}"
