#!/usr/bin/env bash
# 🦉 OWL-AGENT CI/CD PRE-MERGE CHECK
# Enforces: "Why not http/1.1?" must be answered before protocol escalation

set -euo pipefail
ERRORS=0
WARNINGS=0

log_err()  { echo "[FAIL] $1"; ERRORS=$((ERRORS + 1)); }
log_ok()   { echo "[PASS] $1"; }
log_warn() { echo "[WARN] $1"; WARNINGS=$((WARNINGS + 1)); }

# Local installs and build output are not part of the change under review.
GREP_EXCLUDES=(--exclude-dir=.git --exclude-dir=venv --exclude-dir=.venv
               --exclude-dir=node_modules --exclude-dir=__pycache__
               --exclude-dir=dist --exclude-dir=build)

check_protocol_escalation() {
    echo "CHECK 1: Protocol Escalation Justification"
    local files
    # Tests reference protocol names to assert behaviour; they do not decide to
    # escalate. CHECK 2 below already ignores them for the same reason.
    files=$(grep -rn "${GREP_EXCLUDES[@]}" 'protocol\s*=\s*["'"'"']\(ja3\|browser\|stealth\|http/2\|websocket\)["'"'"']' --include="*.py" --include="*.js" --include="*.ts" --exclude="test_*.py" . 2>/dev/null || true)

    if [ -z "$files" ]; then
        log_ok "No protocol escalation found"
        return 0
    fi

    while IFS= read -r line; do
        local file
        file=$(echo "$line" | cut -d: -f1)
        local lineno
        lineno=$(echo "$line" | cut -d: -f2)
        local context
        context=$(sed -n "$((lineno-5)),$((lineno-1))p" "$file" 2>/dev/null || true)

        local score=0
        echo "$context" | grep -qiE 'http/1\.1|http1|baseline' && score=$((score + 1))
        echo "$context" | grep -qiE 'cloudflare|datadome|akamai|anti.bot' && score=$((score + 1))
        echo "$context" | grep -qiE 'latency|ms|benchmark|tested' && score=$((score + 1))
        echo "$context" | grep -qiE 'approved|APPROVED' && score=$((score + 1))

        if [ "$score" -ge 3 ]; then
            log_ok "$file:$lineno — Justified (score: $score/4)"
        elif [ "$score" -ge 2 ]; then
            log_warn "$file:$lineno — Weak justification (score: $score/4)"
        else
            log_err "$file:$lineno — Missing justification (score: $score/4)"
        fi
    done <<< "$files"
}

check_proxy_credentials() {
    echo "CHECK 2: Proxy Credential Security"
    local hardcoded
    hardcoded=$(grep -rnE "${GREP_EXCLUDES[@]}" '://[^:]+:[^@]+@' --include="*.py" --include="*.js" --include="*.ts" --include="*.json" . 2>/dev/null | grep -v "proxy_pool.json" | grep -v "test_" || true)

    if [ -z "$hardcoded" ]; then
        log_ok "No hardcoded proxy credentials"
        return 0
    fi

    while IFS= read -r line; do
        log_err "Hardcoded credentials: $line"
    done <<< "$hardcoded"
}

main() {
    echo "🦉 OWL-AGENT CI/CD PRE-MERGE CHECK"
    check_protocol_escalation
    check_proxy_credentials

    echo "RESULTS: Errors: $ERRORS, Warnings: $WARNINGS"
    if [ "$ERRORS" -gt 0 ]; then
        echo "MERGE BLOCKED: Fix errors above"
        exit 1
    fi
    echo "ALL CHECKS PASSED"
}

main "$@"
