# AgentRouter Local Tools Implementation Plan

**Goal:** Add opt-in, loopback-only diagnostics around the two existing upstream sidecars without modifying OWL's core or replaying user requests.

**Architecture:** A standalone stdlib CLI supplies a one-shot, read-only referee, an artificial AgentRouter-compatible lab, a bounded slow-upload probe, and a static redacted request preview. A separate lab-only launcher loads the actual OpenCode proxy with its upstream redirected to the local lab and a fake key. Neither tool changes client configuration, contacts AgentRouter or persists credentials.

**Test-first tasks:**
- [ ] Write tests for protocol-aware recommendations, healthy/unhealthy/malformed probe responses and loopback validation; implement bounded probes with no request replay or auto-switching.
- [ ] Write tests for lab normal/model failure/malformed/split SSE, billing event, delay and socket disconnect scenarios; implement a local-only mock and a bounded slow-upload client probe.
- [ ] Write tests for request-preview handling, differences between Go and OpenCode behavior, and redaction of secrets in values and unknown keys; implement a no-network, value-free static preview with explicit uncertainty and SDK-version limitations.
- [ ] Validate a lab-only OpenCode launcher uses fake credentials and fixed localhost target; never alter installed upstream code.
- [ ] Test the CLI, cleanup and package installation; document safety, scope, and real-sidecar tests versus mocks.
