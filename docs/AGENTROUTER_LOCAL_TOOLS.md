# Local AgentRouter diagnostics

These optional tools complement, but do not modify, OWL or either upstream sidecar. They provide **recommendations, not automatic endpoint switching**: they never replay inference requests, persist state, edit client configs or share keys between proxies. Install the project with `pip install -e .` to use `owl-agentrouter-tools`, or use `python3 agentrouter_tools.py` from the checkout. Only Python's standard library is required except for the optional OpenCode lab launcher, which uses the installed upstream proxy's dependencies.

## 1. Proxy referee

```bash
owl-agentrouter-tools referee --protocol anthropic
owl-agentrouter-tools referee --protocol openai --go-port 8318 --opencode-port 7187 --timeout 1
```

The command makes **GET requests only** to `127.0.0.1`: Go `/health` and OpenCode `/v1/models`. It prefers Go when its health endpoint reports `ok` without an open circuit; it recommends OpenCode only for Anthropic and only if Go is unavailable. An OpenAI client is never pointed at the Anthropic-only OpenCode sidecar. Equal ports are rejected. A null recommendation means neither eligible endpoint passed its local probe. Timeout is per socket operation, not a whole-command service-level guarantee.

**Important:** the Go health endpoint and the OpenCode static model list show local responsiveness, **not** successful authentication, model capacity or upstream availability. An unrelated local service on a probed port might mimic the expected shape. The command neither changes the active client's endpoint nor retries requests; changing endpoints manually can still produce new billable requests. Upstream proxies and SDKs may themselves retry; configure them separately.

## 2. Compatibility lab

The lab is synthetic and binds only `127.0.0.1`. It has no external upstream, logs no request content, and rejects model names outside the `lab-*` list. It is for a trusted local test environment, not a public service or security boundary.

```bash
# Terminal 1: fake upstream on 127.0.0.1:8199
owl-agentrouter-tools lab --port 8199

# Terminal 2: original Go proxy connected to the fake upstream.
# This overrides the target, disables upstream discovery and retries, and uses a test-only model list.
env TARGET_PROTOCOL=http TARGET_HOST=127.0.0.1 TARGET_PORT=8199 \
  LISTEN_PORT=8320 AR_API_KEY= PROXY_AUTH_TOKEN= MAX_RETRIES=0 \
  MODELS_CSV=lab-normal,lab-split,lab-billing,lab-503,lab-malformed,lab-delay,lab-disconnect \
  ./scripts/run-agentrouter-proxy.sh go

# Terminal 3: original OpenCode code connected to the lab, not AgentRouter.
# Replace the venv path if OWL_AGENTROUTER_HOME was set during installation.
~/.owl-agent/agentrouter/opencode-venv/bin/python agentrouter_tools.py opencode-lab \
  --lab-port 8199 --port 7188
```

The OpenCode lab command loads the installed upstream `proxy.py` without editing it, replaces its upstream target with `http://127.0.0.1:<lab-port>`, clears API-key/auth-token environment variables, supplies a synthetic key, and disables environment-based HTTP proxies for its upstream client. It runs on a **different port** from the production OpenCode proxy. It requires the original project and dependencies installed using [the sidecar installer](AGENTROUTER_UPSTREAM_SERVICES.md). It runs local upstream code, so review that code before use. SDK-level retries are still possible; never confuse this lab-only launcher with the real proxy.

Use synthetic payloads and credentials only. For example, with both lab and Go sidecar running:

```bash
curl -s http://127.0.0.1:8320/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"lab-normal","messages":[{"role":"user","content":"test"}]}'
```

For either sidecar's Anthropic endpoint use `/v1/messages` and include `max_tokens`. Supported scenarios are selected with the model field:

| Model | Simulated behavior |
|---|---|
| `lab-normal` | Valid non-streaming JSON or SSE response |
| `lab-split` | SSE emitted in small writes; TCP may coalesce them |
| `lab-billing` | Anthropic SSE includes a synthetic `billing_summary` event |
| `lab-503` | Model failure: HTTP 503 |
| `lab-malformed` | HTTP 200 with malformed JSON |
| `lab-delay` | Brief delayed response |
| `lab-disconnect` | Stream closes before its terminal event |

The separate **slow-upload client probe** sends a synthetic partial request to a local port, waits, then reads at most a status line with a socket timeout:

```bash
owl-agentrouter-tools slow-upload --port 8320 --delay 0.2 --timeout 2
```

Use it only against a lab-configured proxy with local auth disabled; it intentionally sends an incomplete request. A null status means no status was observed, not that a specific server behavior was proved. It can occupy one server connection until the receiver's own deadline expires. The lab does not implement arbitrary AgentRouter APIs, TLS, HTTP/2, chunked uploads, rate limits or production timing. Model failure and disconnected streams are simulations; a proxy can transform, retry, or filter them.

## 3. Redacted request preview

Supply a JSON object with `headers` and `body` on stdin. The tool makes **no network calls** and does not print any input values or unknown field/header names, even nested values. It is a static description based on the pinned upstream versions, not a wire capture or proof of current behavior.

```bash
printf '%s' '{"headers":{"x-api-key":"example"},"body":{"model":"lab-normal","messages":[],"thinking":{"type":"adaptive"}}}' |
  owl-agentrouter-tools explain --proxy opencode --path /v1/messages

printf '%s' '{"headers":{},"body":{"messages":[]}}' |
  owl-agentrouter-tools explain --proxy go --path /v1/chat/completions --go-prompt disabled
```

`--go-prompt` declares what configuration to describe; the preview does not inspect the running service. The OWL Go launcher defaults to disabled prompt injection, while the upstream direct default is enabled. The Go proxy may forward incoming `Authorization` and `x-api-key`; `X-Proxy-Token` is a local gate and is not forwarded. The OpenCode proxy ignores inbound credentials and strips `thinking` and `output_config`; its Anthropic SDK constructs headers and handles `stream` separately. The preview does not predict SDK validation, every endpoint, middleware, model capabilities, network cookies or current changes in upstream code. Never rely on it as a security audit.

## Tests

```bash
pytest -q -o addopts='' tests/test_agentrouter_tools.py
# Optional: include real, separately installed sidecars against the local lab only:
OWL_TEST_UPSTREAM_INSTALL="$HOME/.owl-agent/agentrouter" pytest -q -o addopts='' tests/test_agentrouter_tools.py
```

The optional test launches the pinned sidecars on temporary loopback ports with synthetic keys, sends non-streaming and streaming requests, checks split-SSE and billing-event behavior, and stops both processes. It needs the separate sidecar installation and Go binary. No live AgentRouter tests or paid requests are made. The original Go proxy still has the unresolved upstream rejection issues documented in [the 413 research](AGENTROUTER_413_RESEARCH.md).
