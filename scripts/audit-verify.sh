#!/usr/bin/env bash
# =============================================================================
# audit-verify.sh — OWL Agent Proxy Governed Token Plane Audit Verification
#
# Runs the full audit verification suite:
#   1. Installs/verifies dependencies
#   2. Runs all test suites
#   3. Verifies config.json structure
#   4. Verifies gateway imports
#   5. Verifies free catalog offline availability
#   6. Reports pass/fail
#
# Usage: ./scripts/audit-verify.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "============================================================"
echo " OWL Agent Proxy — Audit Verification"
echo " Repo: $REPO_ROOT"
echo "============================================================"
echo ""

FAILURES=0

# ---------------------------------------------------------------------------
# Step 1: Verify Python dependencies
# ---------------------------------------------------------------------------
echo "[1/6] Verifying Python dependencies..."
for mod in pytest pytest_asyncio httpx curl_cffi fastapi uvicorn redis aiohttp aiofiles; do
  if python3 -c "import $mod" 2>/dev/null; then
    echo "   OK: $mod installed"
  else
    echo "   FAIL: $mod NOT installed"
    FAILURES=$((FAILURES + 1))
  fi
done
echo ""

# ---------------------------------------------------------------------------
# Step 2: Verify config.json structure
# ---------------------------------------------------------------------------
echo "[2/6] Verifying config.json..."
if python3 -c "
import json
with open('config.json') as f:
    cfg = json.load(f)
# Check governed_token_plane section
gtp = cfg.get('governed_token_plane', {})
assert gtp.get('enabled') == True, 'governed_token_plane.enabled must be true'
assert gtp.get('key_isolation', {}).get('provider_keys_in_gateway_env_only') == True
assert gtp.get('routing', {}).get('strategy') == 'free_catalog_first'
tiers = gtp.get('routing', {}).get('tiers', [])
tier_names = [t.get('tier') for t in tiers]
assert 1 in tier_names, 'Tier 1 (free catalog) must exist'
assert 2 in tier_names, 'Tier 2 (paid fallback) must exist'
assert 3 in tier_names, 'Tier 3 (local) must exist'
fc = gtp.get('free_catalog', {})
assert fc.get('enabled') == True, 'free_catalog.enabled must be true'
assert fc.get('vendored_file') == 'gateway/free_catalog/providers.json'
print('config.json: OK')
" 2>&1; then
  echo "   OK: config.json structure valid"
else
  echo "   FAIL: config.json structure invalid"
  FAILURES=$((FAILURES + 1))
fi
echo ""

# ---------------------------------------------------------------------------
# Step 3: Verify gateway imports
# ---------------------------------------------------------------------------
echo "[3/6] Verifying gateway imports..."
if PYTHONPATH=gateway python3 -c "
from auth import validate_gateway_token, GATEWAY_TOKEN
from circuit_breaker import CircuitBreaker
from cache import Cache
from billing import Billing
from router import Router, ModelRoute, RouteDecision
print('gateway imports: OK')
" 2>&1; then
  echo "   OK: gateway modules import correctly"
else
  echo "   FAIL: gateway module import error"
  FAILURES=$((FAILURES + 1))
fi
echo ""

# ---------------------------------------------------------------------------
# Step 4: Verify free catalog offline availability
# ---------------------------------------------------------------------------
echo "[4/6] Verifying free catalog (offline)..."
if PYTHONPATH=gateway python3 -c "
from free_catalog.loader import load_catalog, load_routes
providers = load_catalog()
routes = load_routes()
assert len(providers) == 15, f'Expected 15 providers, got {len(providers)}'
assert len(routes) > 0, 'Expected at least 1 route'
enabled = [p for p in providers if p.enabled]
assert len(enabled) == 11, f'Expected 11 enabled providers, got {len(enabled)}'
disabled = [p for p in providers if not p.enabled]
assert len(disabled) == 4, f'Expected 4 disabled providers, got {len(disabled)}'
print(f'free catalog: OK ({len(providers)} providers, {len(routes)} routes, 11 enabled, 4 disabled)')
" 2>&1; then
  echo "   OK: free catalog loads offline with 15 providers"
else
  echo "   FAIL: free catalog load error"
  FAILURES=$((FAILURES + 1))
fi
echo ""

# ---------------------------------------------------------------------------
# Step 5: Run full test suite
# ---------------------------------------------------------------------------
echo "[5/6] Running full test suite..."
if python3 -m pytest tests/ -q 2>&1 | tail -1 | grep -q "passed"; then
  RESULT=$(python3 -m pytest tests/ -q 2>&1 | tail -1)
  echo "   $RESULT"
  # Check for any failures
  if echo "$RESULT" | grep -qE "failed"; then
    echo "   FAIL: test suite has failures"
    FAILURES=$((FAILURES + 1))
  fi
else
  echo "   FAIL: test suite did not complete successfully"
  FAILURES=$((FAILURES + 1))
fi
echo ""

# ---------------------------------------------------------------------------
# Step 6: Run gateway + catalog + reverse proxy tests specifically
# ---------------------------------------------------------------------------
echo "[6/6] Running gateway + catalog + reverse proxy tests..."
if python3 -m pytest tests/test_gateway.py tests/test_free_catalog.py tests/test_reverse_proxy.py -q 2>&1 | tail -1 | grep -q "passed"; then
  RESULT=$(python3 -m pytest tests/test_gateway.py tests/test_free_catalog.py tests/test_reverse_proxy.py -q 2>&1 | tail -1)
  echo "   $RESULT"
else
  echo "   FAIL: gateway/catalog/reverse-proxy tests failed"
  FAILURES=$((FAILURES + 1))
fi
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "============================================================"
if [ "$FAILURES" -eq 0 ]; then
  echo " AUDIT VERIFICATION: ALL CHECKS PASSED (0 failures)"
  echo "============================================================"
  exit 0
else
  echo " AUDIT VERIFICATION: $FAILURES CHECK(S) FAILED"
  echo "============================================================"
  exit 1
fi
