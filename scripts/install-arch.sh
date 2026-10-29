#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# 🦉 OWL-AGENT PROXY DEFENSE STACK v7.1 — Arch Linux / omArchy system installer
# ═══════════════════════════════════════════════════════════════════════════════
# Usage:
#   chmod +x scripts/install-arch.sh
#   sudo ./scripts/install-arch.sh            # system packages + install + verify
#   ./scripts/install-arch.sh --user          # skip pacman, user-only
#   ./scripts/install-arch.sh --minimal       # core only (http/1.1)
#   ./scripts/install-arch.sh --full          # + h2 / curl_cffi / websockets / redis
#   ./scripts/install-arch.sh --no-live       # skip network verification
#   ./scripts/install-arch.sh --verify        # verify an existing install
#
# Arch and omArchy differences from the Debian path, all handled here:
#   * python ships venv and ensurepip — there is no python3-venv package
#   * there is no python3-dev; headers ship inside `python`
#   * system pip is EXTERNALLY-MANAGED (PEP 668) — the venv is mandatory
#   * pacman -S aborts on an unknown package name, so every name is verified
#     first and skipped-with-a-warning instead of killing the install
#
# Module install, config merge, backups and verification are delegated to
# install-owl.sh (repo root) so there is exactly one canonical layout:
# ~/.owl-agent.
# ═══════════════════════════════════════════════════════════════════════════════

REPO_URL="https://github.com/marktantongco/owl-agent-proxy.git"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON="${PYTHON:-python}"
MIN_PYTHON="3.10"

MODE="full"
ASSUME_YES=0
LIVE=1

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${BLUE}→${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
header() { echo -e "\n${BLUE}═ $1 ${NC}"; }

usage() { sed -n '9,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

ERRORS=0
SKIPPED_PKGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)   usage; exit 0 ;;
        --user)      MODE="user" ;;
        --minimal)   MODE="minimal" ;;
        --full)      MODE="full" ;;
        --verify)    MODE="verify" ;;
        --no-live)   LIVE=0 ;;
        --ci)        CI_MODE=1 ;;
        --yes|-y)    ASSUME_YES=1 ;;
        *)           fail "unknown option: $1 (see --help)"; exit 1 ;;
    esac
    shift
done

[ "${CI_MODE:-0}" = "1" ] && ASSUME_YES=1

# ── preflight ────────────────────────────────────────────────────────────────
check_arch() {
    local os_release="${OWL_OS_RELEASE:-/etc/os-release}"
    if [[ ! -r "$os_release" ]]; then
        fail "$os_release missing — cannot confirm this is Arch"
        return 1
    fi
    local id like pretty
    id="$(. "$os_release"; printf '%s' "${ID:-unknown}")"
    like="$(. "$os_release"; printf '%s' "${ID_LIKE:-}")"
    pretty="$(. "$os_release"; printf '%s' "${PRETTY_NAME:-$id}")"

    case "$id $like" in
        *arch*|*manjaro*|*endeavouros*|*cachyos*|*garuda*)
            pass "$pretty"
            ;;
        *)
            warn "This script targets Arch-based systems. Detected: $pretty"
            warn "Use scripts/install-ubuntu.sh on Debian/Ubuntu instead."
            if [[ "$ASSUME_YES" != "1" ]]; then
                read -rp "Continue anyway? [y/N] " choice
                [[ "${choice:-n}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
            fi
            return 0
            ;;
    esac

    if [[ -d /usr/share/omarchy || -d "$HOME/.local/share/omarchy" ]]; then
        pass "omArchy detected (Arch + Hyprland)"
        if compgen -G "$HOME/.local/bin/*" >/dev/null 2>&1; then
            info "agent launcher stubs present in ~/.local/bin — MCP wiring is host-side, see docs/MCP_INTEGRATION.md"
        fi
    fi
}

check_python() {
    if ! command -v "$PYTHON" &>/dev/null; then
        fail "Python not found. Install it: sudo pacman -S python"
        return 1
    fi
    local ver
    ver="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
    if [[ "$(printf '%s\n' "$MIN_PYTHON" "$ver" | sort -V | head -n1)" != "$MIN_PYTHON" ]]; then
        fail "Python $ver detected. Need >= $MIN_PYTHON"
        return 1
    fi
    pass "Python $ver ($(command -v "$PYTHON"))"

    # A mise/asdf/pyenv shim ties the venv to one interpreter version; switching
    # runtimes later leaves a broken venv behind. Arch itself has no python-venv
    # package because venv is bundled with `python`.
    case "$(command -v "$PYTHON")" in
        */mise/*|*/.asdf/*|*/.pyenv/*|*/.rtx/*)
            warn "Interpreter is managed by mise/asdf/pyenv."
            warn "The venv is pinned to this exact version. For a stable install use:"
            warn "  PYTHON=/usr/bin/python sudo ./scripts/install-arch.sh"
            ;;
    esac
}

# ── system packages ──────────────────────────────────────────────────────────
# Every name is checked against the sync database before use. A package that
# does not exist is skipped with a warning: pacman -S aborts the whole
# transaction otherwise, and names drift on a rolling release.
pkg_available() { pacman -Si "$1" &>/dev/null; }

install_pkgs() {
    local group="$1"; shift
    local wanted=() missing=()
    for pkg in "$@"; do
        if pkg_available "$pkg"; then
            wanted+=("$pkg")
        else
            warn "package '$pkg' not found in the repos — skipping"
            SKIPPED_PKGS+=("$pkg")
            ((ERRORS++)) || true
        fi
    done
    if [[ "$group" == "core" && ${#wanted[@]} -eq 0 ]]; then
        fail "no core packages available — is the pacman database synced? try: sudo pacman -Sy"
        return 1
    fi
    if [[ ${#wanted[@]} -eq 0 ]]; then
        return 0
    fi
    pacman -S --needed --noconfirm "${wanted[@]}" 2>&1 | tail -2
}

install_system_deps() {
    header "System Dependencies (pacman)"

    if [[ "$MODE" == "user" ]]; then
        warn "Skipping pacman (--user)"
        warn "If a build fails, install: sudo pacman -S base-devel python openssl libffi pkgconf"
        return 0
    fi
    if [[ $EUID -ne 0 ]]; then
        warn "Not root — skipping system packages"
        warn "Re-run with sudo for a complete install, or install manually:"
        warn "  sudo pacman -S base-devel python git curl openssl libffi pkgconf"
        ((ERRORS++)) || true
        return 0
    fi

    # A full upgrade is the supported Arch path (partial upgrades are not).
    # The CI container is ephemeral, so it only syncs to save a minute.
    if [[ "${CI_MODE:-0}" == "1" ]]; then
        info "Syncing package database..."
        pacman -Sy --noconfirm 2>&1 | tail -1
    else
        info "Upgrading the system (pacman -Syu — the supported path on Arch)..."
        pacman -Syu --noconfirm 2>&1 | tail -2
    fi

    # Headers/build tooling are only needed if a pinned wheel has no cp3xx
    # manylinux build for this interpreter (cryptography would then need Rust).
    info "Installing core build + runtime packages..."
    install_pkgs core base-devel python git curl ca-certificates openssl libffi pkgconf

    if [[ "$MODE" == "full" ]]; then
        info "Installing browser automation libraries (Playwright/Chromium)..."
        install_pkgs full nss at-spi2-core libcups libdrm libxkbcommon mesa \
            libxcomposite libxdamage libxfixes libxrandr pango cairo alsa-lib gtk3
    fi
    pass "System dependencies processed"
}

# ── source ───────────────────────────────────────────────────────────────────
locate_source() {
    header "Source"
    if [[ -f "$INSTALL_DIR/install-owl.sh" ]]; then
        pass "Using local checkout: $INSTALL_DIR"
        return 0
    fi
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Updating $INSTALL_DIR"
        git -C "$INSTALL_DIR" pull --ff-only 2>&1 | tail -1
    else
        INSTALL_DIR="${INSTALL_DIR:-$HOME/owl-agent-proxy}"
        info "Cloning into $INSTALL_DIR"
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone "$REPO_URL" "$INSTALL_DIR" 2>&1 | tail -1
    fi
    [[ -f "$INSTALL_DIR/install-owl.sh" ]] || { fail "install-owl.sh not found in $INSTALL_DIR"; exit 1; }
    pass "Repository at $INSTALL_DIR"
}

# ── install ──────────────────────────────────────────────────────────────────
run_installer() {
    header "Install (delegated to install-owl.sh)"
    local args=()
    [[ "$LIVE" == "1" ]] || args+=(--no-live)
    [[ "$MODE" == "full" ]] && args+=(--full)
    [[ "$ASSUME_YES" == "1" ]] && args+=(--yes)

    cd "$INSTALL_DIR"
    PYTHON="$PYTHON" bash ./install-owl.sh "${args[@]}" || {
        fail "install-owl.sh failed"
        exit 1
    }
}

run_verify() {
    header "Verify existing install"
    cd "$INSTALL_DIR"
    local args=(--verify-only)
    [[ "$LIVE" == "1" ]] || args+=(--no-live)
    PYTHON="$PYTHON" bash ./install-owl.sh "${args[@]}" || exit 1
}

print_summary() {
    header "Done"
    echo ""
    echo "  🦉 OWL-AGENT Proxy Defense Stack v7.1 — Arch/omArchy"
    echo ""
    echo "  Repository:   $INSTALL_DIR"
    echo "  Install root: ${OWL_HOME:-$HOME/.owl-agent}"
    echo "  Python:       $PYTHON ($("$PYTHON" -V 2>&1))"
    echo ""
    echo "  Commands:"
    echo "    ~/.owl-agent/run.sh stats          # pool + source telemetry"
    echo "    ~/.owl-agent/run.sh fetch URL      # fetch through the stack"
    echo "    ~/.owl-agent/run.sh mcp-selftest   # MCP protocol check"
    echo "    ~/.owl-agent/run.sh verify --no-live"
    echo ""
    if [[ ${#SKIPPED_PKGS[@]} -gt 0 ]]; then
        echo -e "  ${YELLOW}⚠ skipped packages: ${SKIPPED_PKGS[*]}${NC}"
        echo "    Not fatal: the stack runs on http/1.1 without them."
        echo ""
    fi
    if [ "$ERRORS" -gt 0 ]; then
        echo -e "  ${YELLOW}⚠ $ERRORS non-fatal warning(s) — review above${NC}"
        echo ""
    fi
    echo -e "  ${GREEN}✅ Arch/omArchy install complete${NC}"
    echo ""
}

main() {
    echo ""
    echo "  ╔══════════════════════════════════════════════════════════════╗"
    echo "  ║   🦉 OWL-AGENT Proxy Defense Stack v7.1                    ║"
    echo "  ║   Arch Linux / omArchy Installer                           ║"
    echo "  ╚══════════════════════════════════════════════════════════════╝"
    echo ""

    check_arch
    check_python || exit 1
    locate_source

    if [[ "$MODE" == "verify" ]]; then
        run_verify
        print_summary
        return 0
    fi

    install_system_deps
    run_installer
    print_summary
}

main "$@"
