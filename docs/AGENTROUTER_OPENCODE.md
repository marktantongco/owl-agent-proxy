# AgentRouter / OpenCode bridge on Linux

This optional bridge is an independent implementation inspired by [agentrouter-opencode-proxy](https://github.com/Goodnessmbakara/agentrouter-opencode-proxy), not a vendored installation of that repository. It integrates the upstream project's documented compatibility ideas into OWL; it does not install or run that project's source. It serves **Anthropic Messages**, not OpenAI Chat Completions. It is separate from OWL's cache, deduplication, proxy rotation, browser and MCP layers: LLM prompts and keys do not go through the harvested proxy pool.

## Install and configure

1. Use Python 3.11+ (the upstream project's requirement) and create a virtual environment from the OWL checkout:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e '.[agentrouter]'
   ```

   The optional extra pins `anthropic==0.49.0`, the SDK version used by the upstream repository's test harness. Its HTTP client uses OWL's supported httpx range. Changes in the SDK or AgentRouter's network policy can change behavior.
2. Obtain your own authorized AgentRouter key. Either export `AGENTROUTER_API_KEY` in the proxy's environment, or create `~/.config/opencode/api_keys/AGENT_ROUTER_API_KEY` with permissions `600`. Avoid putting the key in source control, process arguments, or chat. The proxy uses the environment variable first and the file second. The key sent by a client to the local bridge is **not** used for upstream authentication.
3. Merge the `provider` section of `config/opencode.agentrouter.example.json` into your existing OpenCode configuration at `~/.config/opencode/opencode.json`. Preserve your existing settings. The example uses the key file so OpenCode can satisfy its own credential configuration; if you choose env-only credentials, configure OpenCode's API key separately. Select a model available to your account. Do not blindly replace your full existing config.
4. Start `.venv/bin/owl-agentrouter` in a terminal. It listens only on `127.0.0.1:7187`; `AGENTROUTER_PORT` changes the port. The OpenCode `baseURL` is the local origin **without** `/v1`.
5. Check `curl http://127.0.0.1:7187/v1/models` and make a small request through OpenCode. Check both streamed and non-streamed Messages requests against your own account. The models response is static, not a live availability check; override it with `AGENTROUTER_MODELS` as comma-separated IDs and match your OpenCode model configuration.

Optional `AGENTROUTER_BASE_URL` overrides the upstream HTTPS **origin**, without a path, query, or `/v1`; the SDK adds `/v1/messages`. Default: `https://agentrouter.org`. An override sends your credential to that host, so use only a trusted service. Restart the bridge after changing configuration or credentials.

## Research trail, in order

1. The upstream project reports AgentRouter can reject clients by network fingerprint, not only API key ([issue](https://github.com/agentrouter-org/docs/issues/21)). Neither a valid key nor this bridge guarantees access.
2. OpenCode users reported a similar client rejection ([issue](https://github.com/anomalyco/opencode/issues/5060)).
3. The bridge sends Anthropic Messages using the synchronous Anthropic SDK, not raw httpx or OpenAI Chat Completions ([research](https://github.com/yowanda/Reckora/pull/67)).
4. Both upstream and local configured base URLs must be origins without `/v1`; the bridge rejects upstream paths ([research](https://github.com/yowanda/Reckora/pull/68)).
5. The SDK is synchronous; non-streaming calls run in a worker thread and streams in a dedicated worker thread, leaving the event loop free ([research](https://github.com/yowanda/Reckora/pull/69)). A pooled sync httpx client uses 20-second keepalive expiry and 120-second read timeout, following the upstream implementation.
6. Streaming filters complete `billing_summary` SSE records even when split across network chunks.
7. `thinking` and `output_config` are removed from requests for compatibility. **This changes request semantics**; adaptive thinking and output configuration will not be honored.
8. Both `/messages` and `/v1/messages` are accepted.

The five additional quirks in the upstream README overlap these steps: sync SDK rather than async/raw HTTP (3, 5); billing event filtering (6); stripping two fields (7); both message routes (8); and local `/v1/models` (also `/models`) instead of upstream discovery. The local list does not claim that any model is currently available.

## Limitations and security

- Only Anthropic Messages and the local models list are implemented; this is not an OpenAI API adapter or a full Anthropic API. Unsupported SDK parameters may be rejected. No OWL model-health routing or automatic model failover is provided.
- The bridge authenticates upstream with **one configured key**, ignores incoming client credentials, and has no local access control. Any local user/process that can connect can spend that key and read requests it sends itself. Do not expose the port to a network; use OS isolation or an authenticated front end if stronger isolation is needed.
- Stream errors before the first event return an HTTP error where possible. After streaming begins the status is already committed; errors arrive as an SSE error event. Upstream network timeouts and client disconnects can leave a worker alive until its current read times out.
- Test results are mocked, not a live AgentRouter verification. Upstream filtering, TLS behavior, service policy, model names and availability may change. Respect provider terms; a 401, 403 or 503 is not proof of a specific cause.
