# AgentRouter Integration Assessment and Implementation Plan

> **For agentic workers:** Use a test-driven execution workflow and verify each task before proceeding. Steps use checkboxes. This is a proposal, not a claim that these changes have been implemented.

**Goal:** Make an informed, safe decision about the optional OWL AgentRouter bridge, and prepare it for a limited Linux/OpenCode trial without weakening OWL's existing web-fetch stack.

**Architecture:** Keep OWL's existing HTTP/MCP stack independent. If retained, run the bridge as a loopback-only Anthropic Messages sidecar using the synchronous SDK; do not use the untrusted harvested proxy pool for credentials or prompts. For broad OpenAI API coverage and model-health routing, evaluate the original Go proxy separately rather than claiming parity.

**Tech stack:** Python, FastAPI, httpx, Anthropic SDK, pytest; OpenCode; optional Go proxy for comparison.

**Inputs:** Existing `docs/AGENTROUTER_OPENCODE.md`, `config/opencode.agentrouter.example.json`, user request and the upstream READMEs linked below. No separate approved specification exists yet.

## Skills to use

Research used [`find-skills`](https://github.com/vercel-labs/skills/tree/main/skills/find-skills) and the [skills.sh trending page](https://skills.sh/trending). Relevant workflow skills to review before implementation: [`writing-plans`](https://skills.sh/obra/superpowers/writing-plans), [`test-driven-development`](https://skills.sh/obra/superpowers/test-driven-development), [`systematic-debugging`](https://skills.sh/obra/superpowers/systematic-debugging), and [`verification-before-completion`](https://skills.sh/obra/superpowers/verification-before-completion). [`code-review`](https://skills.sh/mattpocock/skills/code-review) is useful for a separate review, but its prescribed fixed-ref/parallel-agent workflow needs adaptation for uncommitted files and the tools actually available. Skills are external instructions, not trusted authority: inspect their source, dependencies and licenses; don't execute installation scripts or request credentials blindly. Popularity is not a security audit. No skills were installed as part of this assessment.

## Scope and comparison

The base OWL project provides an HTTP defense/proxy pool and MCP tools; it is not an Anthropic/OpenAI server. The uncommitted changes add `agentrouter_bridge.py`, an optional `agentrouter` extra and CLI entry point, a sample OpenCode provider configuration, docs and mock tests. They do **not** install the named upstream OpenCode proxy, connect the bridge to OWL's pool, automatically configure OpenCode, or establish live AgentRouter functionality.

| Candidate | Strengths | Costs / gaps | Assessment for Linux OpenCode |
|---|---|---|---|
| Base OWL | Existing pool, HTTP protections and MCP workflow remain unchanged | No AgentRouter Messages endpoint | 3/10 as a standalone AgentRouter solution; higher for its intended web-fetch use |
| [Original Go spoof proxy](https://github.com/trefeon/agentrouter-spoof-proxy) | Documented OpenAI and Anthropic routes, health routing, WAF cookie handling, retries, optional auth, static binary | Separate service; adds spoofing and by default a system prompt; compatibility and defaults must be independently tested | 7/10 for broader API needs |
| [Upstream OpenCode proxy](https://github.com/Goodnessmbakara/agentrouter-opencode-proxy) | Sync SDK, Messages routes and OpenCode-oriented filtering; direct implementation requested previously | Separate Python service, limited API surface; stream error handling commits HTTP 200 before generator runs; inspect license and maintenance before adoption | 6/10 for a narrow Messages trial |
| Current OWL bridge | Optional package extra and CLI; loopback binding, bounded stream queue, configurable models, early stream-error propagation and mock tests | Independent reimplementation rather than installed upstream; no model health/failover, OpenAI API or local authentication; strips request fields and has untested production failure modes | 5/10 for trial readiness; not production-ready |

Scores are subjective fit/readiness judgments, not measurements. Confidence in the recommendation: **65/100** (moderate-low), because neither service was tested against a real AgentRouter account or compared under load. The current branch tests passed in this environment: 183 passed, one dependency warning; the bridge tests use mock HTTP transport. The original Go proxy's features are based on its documentation, not a local audit or live benchmark.

**Recommendation:** Preserve original OWL and keep the bridge optional and experimental. For a broad, feature-complete proxy evaluate the original Go project first; for an OWL-native Anthropic-only OpenCode integration, harden and validate the bridge before deployment. Neither can be declared better for real AgentRouter connectivity without authorized live tests. Account usage, client impersonation and WAF workarounds must comply with provider terms.

## Global constraints

- No secrets in the repo, command arguments, logs, test snapshots or chat.
- Do not bind the bridge publicly. Incoming credentials are currently ignored; local users can spend the configured upstream key.
- No silent transformations beyond explicitly documented, configurable compatibility rules.
- Preserve existing OWL and MCP behavior. Use mock transport by default; live tests are opt-in and authorized.
- Maintain existing Python >=3.10 core support; validate the optional bridge's supported Python and dependency versions independently.

## Review focus

1. Local unauthorized clients accessing a paid upstream key.
2. Large or stalled uploads and unbounded concurrent streaming threads.
3. SSE split boundaries, stalled streams, disconnects and errors before/after headers.
4. Silently dropped `thinking` / `output_config` and changing Anthropic SDK interfaces.
5. Package, installer and OpenCode configuration mismatch; mock tests are not live acceptance tests.

## Task 1: Establish contract and security boundaries

**Files:** `docs/AGENTROUTER_OPENCODE.md`, `config/opencode.agentrouter.example.json`, `tests/test_agentrouter_bridge.py`, `agentrouter_bridge.py`.

- [ ] Specify and test loopback-only default and credential semantics: incoming bearer and x-api-key values must not replace the configured upstream key.
- [ ] Design an opt-in local authentication mechanism with constant-time token verification, secret storage instructions, and tests for missing/wrong tokens; decide whether auth should become the default before any shared-machine deployment.
- [ ] Add request body size, concurrency and timeout limits with negative tests. Ensure rejected requests never reach upstream and errors never expose credentials.
- [ ] Review whether stripping `thinking` and `output_config` should be opt-in; add tests for both enabled and disabled modes and document semantic changes.

**Acceptance:** security and translation tests pass; docs accurately state threat model and limitations. No claim that localhost isolates mutually untrusted local users.

## Task 2: Streaming and API correctness

**Files:** `agentrouter_bridge.py`, `tests/test_agentrouter_bridge.py`.

- [ ] Write tests for split SSE records, CRLF, comments, malformed and oversized records, multiple events in one chunk, and billing events at EOF. Confirm the limit applies per record, not to an aggregate chunk of multiple small events.
- [ ] Add tests for status errors before first event and SSE errors after first event, initial timeout, disconnect/cancellation, bounded queue backpressure and worker cleanup. Use controlled fake streams, not only buffered TestClient responses.
- [ ] Fix failures with bounded resource usage and preserve valid event ordering. Establish explicit maximum concurrent workers and deterministic shutdown expectations; avoid logging or returning upstream secrets.
- [ ] Test request validation, model lists and unsupported fields. Document that `/v1/models` is static and Anthropic Messages is not OpenAI Chat Completions.

**Acceptance:** focused tests pass offline, with no lingering workers after controlled disconnect tests. Define acceptable shutdown timing for a blocked upstream read.

## Task 3: Packaging, reproducibility and integration

**Files:** `pyproject.toml`, `install-owl.sh`, `docs/AGENTROUTER_OPENCODE.md`, `config/opencode.agentrouter.example.json`, CI workflow and tests as appropriate.

- [ ] Test a fresh `pip install -e '.[agentrouter]'` and built wheel; test base installation without the optional extra. Resolve the console script's behavior when its optional dependencies are missing.
- [ ] Decide whether the existing shell installer should offer an explicit opt-in for the bridge; currently it copies only the original modules. If supported, test its installation and entry point without altering the default install.
- [ ] Check Python 3.10/3.11 and compatible SDK/httpx versions in CI; avoid relying indefinitely on an old SDK pin without a security/update policy.
- [ ] Validate OpenCode's actual provider schema and key-file substitution against an installed version in a disposable config; preserve the user's existing config. Test one model ID the account actually supports rather than assuming the static default.

**Acceptance:** reproducible clean installs, documented optional-dependency behavior and a tested OpenCode config, with no regression in core installation.

## Task 4: Authorized live comparison and decision

**Files:** `docs/AGENTROUTER_OPENCODE.md`, an optional sanitized test report, and tests if opt-in harness is approved.

- [ ] With provider permission and a user-managed key, test both implementations on the same Linux host and account using minimal requests. Never print or persist keys or prompts.
- [ ] Record versions, date, endpoints, model IDs, HTTP status, streaming/non-streaming results, disconnect behavior and limitations. Do not infer a WAF cause from a status alone; distinguish timeout, auth and provider capacity failures.
- [ ] Compare documented required routes, default prompt modifications, local auth and resource usage under an agreed workload. If live access is unavailable, record the blocker and keep the bridge experimental.
- [ ] Re-rate the alternatives only after evidence is available and obtain approval before replacing or removing either design.

**Acceptance:** sanitized evidence supports the recommendation; no unsupported claim of guaranteed access or production readiness.

## Verification gate

Run `.venv/bin/pytest -q -o addopts=''`, focused bridge tests with coverage, a clean package build/install test and the relevant installer/CI checks. A live acceptance test is separate and must not be represented as passed unless it was actually performed.
