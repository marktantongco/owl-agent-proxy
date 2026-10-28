# 🦉 OWL-AGENT WORKLOG

## Session: 2026-10-28 — v7.1 integration

### Tasks Completed
- [x] Integrated the v7.1 research-grounded stack into the repo (additive, no breaking changes)
- [x] `proxy_harvester.py`: 4-source harvest, tolerant schema parsing, source-health learning, honeypot detector, session affinity, proxy probe
- [x] `mcp_proxy_server.py`: stdlib-only stdio JSON-RPC server with 4 tools + stdout purity guard
- [x] `proxy_defense.py`: sticky selection, quarantine/validation, honeypot screening, pool persistence, config merge, CLI (`stats`/`fetch`/`harvest`/`validate`), v7.1 telemetry
- [x] `install-owl.sh`: idempotent installer with backup/rollback/purge, core + optional deps, verification, no heredoc-duplicated code
- [x] `scripts/verify-install.py`: 18 offline + 2 live checks (SKIP, never false-FAIL, without egress)
- [x] Tests: 9 → 136, all offline (harvester schemas, affinity, honeypot, MCP framing/stdio, sticky pool)
- [x] CI: pytest matrix (3.10/3.11/3.12) + installer smoke test; local venv exclusion in guard script
- [x] Docs: README v7.1, `docs/MCP_INTEGRATION.md`, `docs/V7_UPSTREAM.md`, INSTALL_UBUNTU

### Pre-existing bugs found and fixed
| Bug | Impact | Fix |
|-----|--------|-----|
| `HTTP2_AVAILABLE` true whenever `httpx` imports | `ResilientClient()` crashed with `ImportError: h2 not installed` on a stock `pip install httpx` | detect `h2`, degrade gracefully, close sessions on failure |
| `_request_http2` used removed `proxies=` mapping | `TypeError` on httpx ≥ 0.28 | use `proxy=`, fall back to `proxies=` |
| `RequestDeduplicator` leaked failed futures | "Future exception was never retrieved" tracebacks | mark exception retrieved, cover with tests |
| `scripts/install-ubuntu.sh` unquoted `pkg>=ver` args | created a file named `=0.10.0`, installed nothing | quote constraints |
| Legacy tests used `asyncio.get_event_loop()` | broke when pytest-asyncio closed the loop first | `asyncio.run()` |
| v7.1 draft called `SessionAffinityManager` without importing it | `NameError` on client construction | ported components into the repo module instead of replacing it |

### Skills Used
- `research` (source schemas, sticky-session consensus)
- `simulator` (request → pool → protocol trace)
- `code-generation` (module + test scaffolding)
- `audit-optimizer` (installer/verification loops)

### Decisions Made

| Decision | Rationale | Risk |
|----------|-----------|------|
| Extend `proxy_defense.py` rather than replace it with the v7.1 draft | Draft raises `NameError` on construction and would break 9 tests, examples, CI and docs; repo module is the working baseline | Two "versions" conceptually — mitigated by README/version strings |
| Installer copies repo modules instead of embedding heredocs | Single source of truth; ~2,000 duplicated lines would drift | Installer requires a checkout (documented) |
| Verification lives in `scripts/verify-install.py` | Testable, reusable in CI, no shell-quoting hazards | One more file to keep in sync |
| Harvested proxies quarantined at tier 4, `healthy=False` | A stale free list must never reach the request path | Slower first useful proxy (~1–3 min) |
| Honeypot detector fails open | A missing baseline must not empty the pool on a plane/captive portal | Tampering undetected when offline |
| Session affinity is in-memory per process | Simple, no shared store needed; TTL-bounded | Bindings lost on restart (acceptable for tasks) |
| `use_upstream_harvester` defaults off in the library, on in the installer | Library users shouldn't get surprise network traffic; installed CLI should work out of the box | Different defaults — documented in both places |

### Bottlenecks Found

| Location | Symptom | Root Cause | Fix |
|----------|---------|------------|-----|
| Validation | Harvested pool stays at 0 for minutes | every candidate needs a real TCP+HTTP probe | bounded concurrency (10), quarantine means requests never block on it |
| `ProxyRotator._trim` | managed proxies evicted first | sort key inverted the tier preference | key on `tier == 1`, prefer managed |
| `harvest(include_seen=True)` | yield signal inflated by snapshots | snapshots counted as "new" | record `valid=0` for snapshots; dedupe across sources |

### Next Steps
⚡⚡ v7.2 candidates: per-session fingerprint pool `(proxy, impersonate)`, socks validation via `python-socks`, metrics endpoint (Prometheus), source plugins for paid providers.

### 3 Insights
- **Tactical:** the highest-leverage safety property was *quarantine* — never letting a harvested URL into the selection path before a probe succeeds.
- **Strategic:** MCP is the integration seam that matters; a proxy pool an agent cannot call is shelfware.
- **Reframe:** verification that can FAIL offline is worse than no verification — SKIP-with-reason keeps installers trustworthy on locked-down machines.

---

*Build it once → it runs forever.*
