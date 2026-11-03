# Original AgentRouter proxies alongside OWL (Linux)

This integration installs the **actual upstream projects**, unchanged, as independent optional sidecars. OWL's web-fetch cache, MCP server, pool, original installer and optional `owl-agentrouter` bridge are not replaced. The sidecars do not chain through each other or through OWL's proxy pool. Choose one as a client endpoint; they can run simultaneously on distinct ports.

| Sidecar | Client endpoint | API scope | Upstream credential |
|---|---|---|---|
| [Go spoof proxy](https://github.com/trefeon/agentrouter-spoof-proxy) | `http://127.0.0.1:8318` | OpenAI- and Anthropic-style routes | Supplied by each client; optional `AR_API_KEY` is for model discovery |
| [OpenCode proxy](https://github.com/Goodnessmbakara/agentrouter-opencode-proxy) | `http://127.0.0.1:7187` | Anthropic Messages; static model list | One server-side `AGENTROUTER_API_KEY` or key file; incoming client key is ignored |

## Installation

Requires Git, Python 3.11+, `venv` and Go 1.26.5+ for the pinned Go source, plus network access to GitHub, the Go module proxy and Python package index. Review each upstream project and its license/terms before deploying: the Go repo has an MIT license, while the pinned OpenCode repo contains no LICENSE file. This installer clones the originals at fixed commits; it does not vendor their source into OWL.

```bash
./scripts/install-agentrouter-proxies.sh all
# Or install independently: ./scripts/install-agentrouter-proxies.sh go
#                           ./scripts/install-agentrouter-proxies.sh opencode
```

Default installation directory is `~/.owl-agent/agentrouter`, configurable with `OWL_AGENTROUTER_HOME`. Set `GO` or `PYTHON` to an interpreter/compiler executable when needed. Go and OpenCode sources are pinned respectively to `afa0be17622f95c276d447ab45decb6a049095a7` and `cbc6e540a85900e1f50398a8b72885237970702b`. Go's `go.sum` verifies its pinned module; Python pins the Anthropic SDK to 0.49.0, while other dependencies use ranges and thus are not a fully locked build. The OpenCode project uses its own Python venv; it does not mutate OWL's venv. Existing checkout revisions and tracked modifications are checked and never silently overwritten. Re-running rebuilds Go and refreshes the separate Python dependencies.

In this restricted sandbox, installation was performed with a separately installed Go 1.26.5 compiler and `GOPROXY=direct GOSUMDB=off`, using GitHub to fetch the Go dependency and the checked-in `go.sum` to verify it. That workaround disables Go's external checksum database and is not the recommended default outside this restricted environment.

## Credentials and startup

Do not paste keys into chat or commit them. For the OpenCode proxy, put the AgentRouter key in `~/.config/opencode/api_keys/AGENT_ROUTER_API_KEY` (directory private, file mode `600`), or supply `AGENTROUTER_API_KEY` in the process environment. The proxy reads one shared key; its local HTTP endpoint has **no authentication**, so any local process that connects can use that key. The upstream binds to `127.0.0.1:7187` and has a hardcoded target and port.

Start each in its own terminal from the OWL checkout:

```bash
./scripts/run-agentrouter-proxy.sh go
./scripts/run-agentrouter-proxy.sh opencode
```

The launcher forces the Go proxy to bind `127.0.0.1` and sets `INJECT_SYSTEM_PROMPT` to empty unless explicitly supplied; otherwise upstream injects a default prompt. Go's `LISTEN_PORT` can be set if needed. The OpenCode proxy has a fixed port, so it conflicts with OWL's independent experimental bridge if both are started. Neither sidecar is auto-started or installed as a system service.

For Go, set `PROXY_AUTH_TOKEN` in its environment for local access control. If using a distinct AgentRouter bearer key, the client must send `X-Proxy-Token` for the proxy token **and** `Authorization: Bearer <upstream key>` for the upstream: the original Go proxy forwards Authorization upstream, including a local token placed there. For Anthropic clients, an upstream `x-api-key` can be sent independently, but verify the exact client's header behavior. Health and model-list endpoints remain public locally. The example client configuration below omits proxy auth; use it only on a trusted single-user host, or add the separate local token through your client's supported custom-header configuration. Do not expose the proxy publicly without a properly reviewed TLS/auth design.

## Connect OpenCode

Merge, do not replace, the provider section from either:

- `config/opencode.agentrouter-go.example.json` for the Go sidecar; or
- `config/opencode.agentrouter.example.json` for the original OpenCode sidecar.

Both examples use the same key-file reference for OpenCode's client credential; the OpenCode sidecar authenticates upstream with its own environment/file key, not the incoming header. Change the model whitelist to an ID your account can actually use and verify it against your OpenCode version. Both URLs omit `/v1` for an Anthropic client. An OpenAI-compatible client should use the Go proxy's `http://127.0.0.1:8318/v1` base instead, with its own upstream key and, if enabled, separate proxy token.

The upstream OpenCode proxy strips `thinking` and `output_config` from requests and filters `billing_summary` SSE events. Its streaming errors can be sent as SSE inside HTTP 200 after headers are committed. The Go proxy normally strips OpenAI thinking tags (`STRIP_THINKING_TAGS=true`) and can retry requests; retries may duplicate billable work. The Go model list can be health-filtered, whereas the OpenCode model list is a static stub; neither guarantees actual model availability.

## Verification

```bash
curl http://127.0.0.1:8318/health
curl http://127.0.0.1:7187/v1/models
OWL_TEST_UPSTREAM_INSTALL="$HOME/.owl-agent/agentrouter" \
  .venv/bin/pytest -q -o addopts='' tests/test_agentrouter_upstream_services.py
```

Set `OWL_TEST_UPSTREAM_INSTALL` to your custom install directory if applicable. These smoke tests use loopback mock upstreams and test Go bearer/token separation, OpenAI chat routing and upstream OpenCode Messages plus SSE filtering. The OpenCode launcher test uses a pre-bound ephemeral loopback socket: a subprocess-only shim verifies the upstream requested `127.0.0.1:7187` but serves on the owned test socket, avoiding collisions and TIME_WAIT skips without changing upstream source. This does not test whether port 7187 itself is available for a real installation. They do not test a live AgentRouter account. In the current environment Go's internal package tests passed; its full upstream suite had `TestOversizedContentLength413` fail on a broken pipe when writing the oversized body even though the server logged a 413. Investigate that before production use.

To test actual service connectivity, use your own authorized account and a minimal streamed and non-streamed request via the chosen client. This requires network access to AgentRouter, which is unavailable in this sandbox. Availability, upstream policies and model names may change. Comply with provider terms. Review logs before retaining or sharing them; upstream may log response/error content.

For investigation and an **unapplied experimental patch** for the upstream 413 failure, see [oversized-upload research](AGENTROUTER_413_RESEARCH.md).
