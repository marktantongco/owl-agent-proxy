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
    # No file is exempt: an escalation hidden in a test is still an escalation.
    # A test that must name a protocol carries the same justification a
    # production call site would.
    files=$(grep -rn "${GREP_EXCLUDES[@]}" 'protocol\s*=\s*["'"'"']\(ja3\|browser\|stealth\|http/2\|websocket\)["'"'"']' --include="*.py" --include="*.js" --include="*.ts" . 2>/dev/null || true)

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

        # Bookkeeping exemption. A protocol name may legitimately appear without
        # escalating anything: as a cache key, a dataclass field, or inside a
        # handler that already carries its own justification comment. What must
        # justify itself is a *call site* that selects a protocol without a
        # preceding rationale.
        #
        # 1. Cache keys / cache lookups: the string never reaches the network.
        # 2. Data construction (CachedResponse(..., protocol=...)) where the
        #    enclosing handler is already justified within the same context.
        if echo "$line" | grep -qE 'cache\.(get|set)\(|CacheKey'; then
            log_ok "$file:$lineno — bookkeeping (cache key), not an escalation"
            continue
        fi
        if echo "$line" | grep -q 'CachedResponse' \
           && echo "$context" | grep -qiE 'APPROVED|baseline'; then
            log_ok "$file:$lineno — data literal inside an already-justified handler"
            continue
        fi
        # 3. Explicit opt-out, same idiom as check-swallows.py's `# swallow:`.
        #    For a call site where naming a protocol escalates nothing, say why
        #    on the line: `# no-escalation: <reason>`.
        if echo "$line" | grep -q '# no-escalation:' \
           || echo "$context" | grep -q '# no-escalation:'; then
            log_ok "$file:$lineno — opted out inline"
            continue
        fi

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
