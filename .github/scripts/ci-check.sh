#!/usr/bin/env bash
# 🦉 OWL-AGENT CI/CD PRE-MERGE CHECK
# Enforces: "Why not http/1.1?" must be answered before protocol escalation

set -euo pipefail

# Rules enforced (generated into AGENTS.md by scripts/gen-docs.py; see the
# "gate:" convention at the top of gen-docs.py):
#
# gate: protocol-escalation-justified: an escalated protocol at a call site carries a stated reason, and its opt-out names one [required] [probe: tests/test_gate_rules_fire.py] [probe: tests/test_ci_check_scoring.py] [probe: tests/test_opt_out_markers.py]
# gate: proxy-credentials-not-committed: no hardcoded user:password@ proxy URL anywhere in the tree [required] [probe: tests/test_ci_check_credentials.py] [probe: tests/test_opt_out_markers.py]

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
        local context start
        # Clamp the window. Without this, an escalation on line <= 5 computes a
        # negative start and `sed -n "-2,2p"` is parsed as an *option*, so sed
        # errors and context comes back empty — a fully justified escalation near
        # the top of a file scored 0/4 and blocked the merge. This is the real
        # source of the "false positives that blocked merges for three days";
        # it was arithmetic, not the scoring heuristic.
        start=$(( lineno - 5 ))
        [ "$start" -lt 1 ] && start=1
        context=$(sed -n "${start},$((lineno-1))p" "$file" 2>/dev/null || true)

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
        # The reason is required, not decorative: `# no-escalation:` alone used
        # to exempt a line, which made the marker a switch rather than a
        # justification. `[^ ]` requires at least one non-space character after
        # the colon. Every existing marker in the tree already carries a reason.
        if echo "$line" | grep -qE '# no-escalation:[[:space:]]*[^[:space:]]' \
           || echo "$context" | grep -qE '# no-escalation:[[:space:]]*[^[:space:]]'; then
            log_ok "$file:$lineno — opted out inline"
            continue
        fi

        # Each signal is word-bounded. Unbounded `ms` matched systems, problems,
        # items, params, terms, forms, claims and algorithms, so ordinary prose
        # scored a point -- enough to turn a blocking 1/4 into a passing 2/4.
        # `approved` and `tested` were worse: unapproved, untested and "not yet
        # approved" all scored, so a comment saying the change was NOT approved
        # justified itself. The prose cannot be allowed to invent the evidence.
        local score=0
        echo "$context" | grep -qiE '\b(http/1\.1|http1|baseline)\b' && score=$((score + 1))
        echo "$context" | grep -qiE '\b(cloudflare|datadome|akamai|anti-?bot)\b' && score=$((score + 1))
        if echo "$context" | grep -qiE '\b([0-9]+(\.[0-9]+)?|one|two|three|five|ten|twenty|fifty|hundred)[[:space:]]*ms\b' \
           || echo "$context" | grep -qiE '\b(latency|benchmark|measured)\b' \
           || { echo "$context" | grep -qiE '\btested\b' \
                && ! echo "$context" | grep -qiE '\buntested\b|\bnot[[:space:]]+tested\b'; }; then
            score=$((score + 1))
        fi
        if echo "$context" | grep -qiE '\bapproved\b' \
           && ! echo "$context" | grep -qiE '\bunapproved\b|\bnot[[:space:]]+(yet[[:space:]]+)?approved\b'; then
            score=$((score + 1))
        fi

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
    # Scans every text format a credential can hide in, not just source files:
    # a secret pasted into a shell script or a workflow is the same leak. The old
    # version matched only *.py/*.js/*.ts/*.json and skipped any path containing
    # "test_" — while the rule claimed "anywhere in the tree". Probed: a
    # `https://user:pass@host` in a .sh or .yml file passed clean.
    #
    # No path is excluded for being a test or a doc. Those files legitimately
    # contain fake creds, so they opt out the same way everything else does:
    #   - obvious placeholders (YOUR_USERNAME, example.com, pass1, ...) are ignored
    #   - otherwise the line carries `# cred-ok: <reason>`
    # A blanket `grep -v test_` is what let the original gap stay invisible.
    # cred-ok: this is the detection pattern, not a credential
    hardcoded=$(grep -rnE "${GREP_EXCLUDES[@]}" '://[^:/@[:space:]]+:[^@[:space:]]+@' \
        --include="*.py" --include="*.js" --include="*.ts" --include="*.json" \
        --include="*.sh" --include="*.yml" --include="*.yaml" --include="*.toml" \
        --include="*.cfg" --include="*.ini" \
        . 2>/dev/null \
        | grep -v 'config/proxy_pool.template.json' \
        | grep -v 'proxy_pool.json' \
        | grep -vE '://(YOUR|your|USER|user|USERNAME|user1|user2|embedded|FAKE|fake|test)[^@]*@' \
        | grep -viE '@(proxy\.)?example\.(com|org|test)|@(host|proxy|localhost)(:[0-9]+)?([/"'"'"'[:space:]]|$)' || true)

    if [ -z "$hardcoded" ]; then
        log_ok "No hardcoded proxy credentials"
        return 0
    fi

    while IFS= read -r line; do
        # Opt-out check looks at the line and the one above it, because the
        # pattern in this script has to be able to match itself.
        local file lineno
        file=$(echo "$line" | cut -d: -f1)
        lineno=$(echo "$line" | cut -d: -f2)
        # Reason required here too; see the note on `# no-escalation:` above.
        if echo "$line" | grep -qE 'cred-ok:[[:space:]]*[^[:space:]]' \
           || sed -n "$((lineno-1))p" "$file" 2>/dev/null \
              | grep -qE 'cred-ok:[[:space:]]*[^[:space:]]'; then
            log_ok "$file:$lineno — opted out (cred-ok)"
            continue
        fi
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
