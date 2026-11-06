# Security Checklist — owl-agent-proxy Governed Token Plane

**Project:** marktantongco/owl-agent-proxy  
**Branch:** `arena/84a46d1e-owl-agent-proxy`  
**Version:** Gateway v1.0.0 / Reverse Proxy v2.1 / Core v7.1

---

## 1. Provider Key Isolation

| Check | Status | Evidence |
|-------|--------|----------|
| Provider keys live only in gateway environment | PASS | `gateway/auth.py` — `GATEWAY_TOKEN = os.environ.get("OWL_GATEWAY_TOKEN")`; `gateway/router.py` `resolve_api_key()` reads `os.environ.get(route.api_key_env)` |
| Clients receive gateway token only, never provider keys | PASS | `gateway/auth.py` — `validate_gateway_token()` validates bearer token; `gateway/app.py` — `require_auth` dependency on all routes |
| No provider keys in client-facing responses | PASS | `gateway/app.py` — responses include `provider`, `tier`, `content`, `usage` but never `api_key` |
| No provider keys in audit logs | PASS | `gateway/audit.py` — `REDACTED_FIELDS` includes `api_key`, `authorization`, `x-api-key`, `token`, `secret`, `password`, `credential`; `sanitize_headers()` and `redact()` applied |
| Provider keys not logged in errors | PASS | `gateway/app.py` — `audit.log_error()` receives error strings and provider name only, never keys |
| `config.json` key_isolation confirms gateway-only keys | PASS | `config.json` — `governed_token_plane.key_isolation.provider_keys_in_gateway_env_only: true` |

---

## 2. Authentication & Authorization

| Check | Status | Evidence |
|-------|--------|----------|
| Bearer token validation on all protected routes | PASS | `gateway/app.py` — `require_auth` dependency on `/v1/models`, `/v1/chat/completions`, `/v1/stats`, `/v1/admin/*` |
| Constant-time token comparison | PASS | `gateway/auth.py` — `secrets.compare_digest(token, GATEWAY_TOKEN)` |
| Missing token returns 401 | PASS | `gateway/auth.py` — `validate_gateway_token(None)` raises `HTTPException(401)` |
| Invalid token returns 401 | PASS | `gateway/auth.py` — `secrets.compare_digest` mismatch raises `HTTPException(401)` |
| One-time token generated for local dev if env not set | PASS | `gateway/auth.py` — generates `base64.urlsafe_b64encode(secrets.token_bytes(32))` if `OWL_GATEWAY_TOKEN` not set |

---

## 3. Edge Layer Security (Nginx / Caddy)

| Check | Status | Evidence |
|-------|--------|----------|
| TLS termination on port 443 | PASS | `nginx.conf` — `listen 443 ssl http2;` with `ssl_certificate` and `ssl_certificate_key` |
| HTTP → HTTPS redirect | PASS | `nginx.conf` — `listen 80;` → `return 301 https://$host$request_uri;` |
| Rate limiting at edge | PASS | `nginx.conf` — `limit_req_zone $binary_remote_addr zone=gateway:10m rate=10r/s;` with `burst=20 nodelay` |
| Security headers set | PASS | `nginx.conf` — `X-Frame-Options DENY`, `X-Content-Type-Options nosniff`, `Referrer-Policy no-referrer` |
| Authorization header forwarded to gateway | PASS | `nginx.conf` — `proxy_set_header Authorization $http_authorization;` |
| Upstream provider headers hidden | PASS | `nginx.conf` — `proxy_hide_header X-Upstream-Provider`, `proxy_hide_header X-Provider-Key` |
| Gateway bound to 127.0.0.1 only | PASS | `docker-compose.yml` — `ports: "127.0.0.1:20128:20128"`; `gateway/app.py` — `host="127.0.0.1"` |
| Caddy alternative config available | PASS | `Caddyfile` — reverse proxy to `127.0.0.1:20128`, security headers, upstream header hiding |
| Caddy rate limiting noted as module-dependent | INFO | `Caddyfile` — rate limit commented out with note that Caddy rate_limit module may need to be built in |

---

## 4. Budget Enforcement

| Check | Status | Evidence |
|-------|--------|----------|
| Per-client token budget | PASS | `gateway/billing.py` — `Budget.token_limit`, `check_budget()` rejects when `tokens_used + estimated_tokens > token_limit` |
| Per-client cost budget | PASS | `gateway/billing.py` — `Budget.cost_limit_usd`, `check_budget()` rejects when estimated cost exceeds limit |
| 24-hour budget window with auto-reset | PASS | `gateway/billing.py` — `window_seconds=86400`, `reset_if_expired()` |
| Global kill switch | PASS | `gateway/billing.py` — `kill_switch` flag blocks all requests when `true`; `/v1/admin/kill-switch` endpoint |
| Per-client manual block/unblock | PASS | `gateway/billing.py` — `block_client()`, `unblock_client()` |
| Budget exceeded blocks paid routes only | PASS | `gateway/router.py` — `route()` skips non-local routes when `client_cost_remaining_usd <= 0`; local routes (tier 3) bypass cost budget |
| Local routes cost $0 (free hardware cost) | PASS | `gateway/router.py` — `ModelRoute.cost_per_1k_tokens=0.0` for ollama/vllm |

---

## 5. Circuit Breaker

| Check | Status | Evidence |
|-------|--------|----------|
| Per-provider failure tracking | PASS | `gateway/circuit_breaker.py` — `CircuitState.failures`, `record_failure()` |
| Configurable threshold (default 5) | PASS | `gateway/circuit_breaker.py` — `threshold=5` default |
| Configurable cooldown (default 60s) | PASS | `gateway/circuit_breaker.py` — `cooldown_seconds=60.0` default |
| Circuit opens after threshold | PASS | `gateway/circuit_breaker.py` — `record_failure()` sets `open_until` when `failures >= threshold` |
| Half-open trial after cooldown | PASS | `gateway/circuit_breaker.py` — `is_open()` resets `open_until` after cooldown expires |
| Fallback chain selection | PASS | `gateway/circuit_breaker.py` — `select_provider()` iterates fallback chain, returns first available |
| Circuit breaker integrated into gateway | PASS | `gateway/app.py` — `cb_availability` built from all routes, passed to `router.route()` |

---

## 6. Cache Security

| Check | Status | Evidence |
|-------|--------|----------|
| Redis-backed cache | PASS | `gateway/cache.py` — `redis.Redis` with `decode_responses=True` |
| Cache disabled gracefully when Redis unavailable | PASS | `gateway/cache.py` — `_connect()` catches exceptions, sets `self.enabled = False` |
| Cache key includes model + prompt hash | PASS | `gateway/cache.py` — `_key()` uses SHA-256 of prompt + model |
| No sensitive data in cache keys | PASS | `gateway/cache.py` — keys use hash, not raw prompt content |

---

## 7. Code-Level Security Scan

| Check | Status | Evidence |
|-------|--------|----------|
| No hardcoded API keys in gateway code | PASS | Grep for `sk-`, `AKIA`, `ghp_`, `glpat`, `xoxb` in `gateway/`, `reverse_proxy.py`, `proxy_defense.py` — no matches |
| No hardcoded provider keys in `config.json` | PASS | `config.json` — `api_key_env` values are env var names, not actual keys |
| `eval()` / `exec()` not used | PASS | Grep found no `eval(` or `exec(` in gateway code |
| `shell=True` not used in subprocess calls | PASS | No subprocess calls with `shell=True` in gateway code |
| Path traversal protection | INFO | Cache key uses SHA-256 hash, not raw user input as filesystem path |
| SQL injection not applicable | INFO | No SQL database used (Redis only, key-value) |

---

## 8. Dependencies

| Package | Purpose | Security Note |
|---------|---------|---------------|
| `fastapi` | Gateway web framework | Actively maintained |
| `uvicorn` | ASGI server | Actively maintained |
| `httpx` | HTTP client for provider calls | Actively maintained |
| `redis` | Redis client | Actively maintained |
| `curl_cffi` | Stealth mode TLS impersonation | Used only in reverse proxy stealth mode |
| `pydantic` | Data validation (FastAPI dependency) | Actively maintained |

---

## 9. Residual Risks & Recommendations

| Risk | Severity | Recommendation |
|------|----------|----------------|
| Caddy rate limiting module may not be available | Low | Uncomment rate_limit in Caddyfile only if `caddy` is built with rate limit module; otherwise rely on Nginx |
| Gateway token generated at startup if env not set | Medium | For production, always set `OWL_GATEWAY_TOKEN` explicitly; do not rely on one-time generated token |
| Estimated cost pricing is approximate | Low | Replace `Billing.ESTIMATED_COST_PER_1K_TOKENS` with actual provider pricing when available |
| Redis without authentication/password | Medium | For production, configure Redis with `requirepass` and TLS |
| `proxy_harvester.py` harvests from public proxy lists | Low | This is the client-side defense library, not the gateway; ensure harvested proxies are validated before use |
| Stealth mode uses curl_cffi which requires outbound network | Low | Stealth mode is optional; disable if outbound network is restricted |

---

## 10. Sign-off

| Area | Reviewer | Status | Date |
|------|----------|--------|------|
| Provider key isolation | Audit | PASS | 2026-11-06 |
| Authentication & authorization | Audit | PASS | 2026-11-06 |
| Edge layer security (Nginx/Caddy) | Audit | PASS | 2026-11-06 |
| Budget enforcement | Audit | PASS | 2026-11-06 |
| Circuit breaker | Audit | PASS | 2026-11-06 |
| Cache security | Audit | PASS | 2026-11-06 |
| Code-level security scan | Audit | PASS | 2026-11-06 |
| **Overall** | **Audit** | **PASS** | **2026-11-06** |
