# Go proxy: oversized-upload failure investigation

**Date:** 2026-11-03. **Scope:** [trefeon/agentrouter-spoof-proxy](https://github.com/trefeon/agentrouter-spoof-proxy) at commit [`afa0be17622f95c276d447ab45decb6a049095a7`](https://github.com/trefeon/agentrouter-spoof-proxy/tree/afa0be17622f95c276d447ab45decb6a049095a7), Go 1.26.5, Linux, loopback mock upstream. This is a focused investigation, not a complete security or HTTP conformance audit. The [experimental patch](../patches/agentrouter-go-oversize-413.patch) is supplied for review, **not automatically applied or deployed**.

## Summary

There are two related but distinct problems:

1. **Test/client assumption:** [`rawConn`](https://github.com/trefeon/agentrouter-spoof-proxy/blob/afa0be17622f95c276d447ab45decb6a049095a7/e2e/proxy_e2e_test.go#L215) writes the entire request before reading a response. The test sends 21 MiB while the proxy rejects the declared length at 20 MiB and drains at most 1 MiB before closing. A write can therefore fail with `broken pipe` before the helper reads the response. In this environment the original test failed **10/10 runs**, each with `raw write: ... broken pipe`; the server logged `REJECTED 413`. The log alone does **not** prove the client received a complete 413.
2. **Production-path stall:** [`ServeProxy`](https://github.com/trefeon/agentrouter-spoof-proxy/blob/afa0be17622f95c276d447ab45decb6a049095a7/internal/proxy/handler.go#L97) rejects a known oversized `Content-Length` before `readBody` establishes its upload deadline. [`rejectBody`](https://github.com/trefeon/agentrouter-spoof-proxy/blob/afa0be17622f95c276d447ab45decb6a049095a7/internal/proxy/handler.go#L245) writes a buffered response then tries to drain the body. With a client that sends only oversized headers, both with and without `Expect: 100-continue`, a four-second response read timed out in our reproduction. The handler can wait on that drain until the client disconnects or the connection otherwise fails; the configured body upload timeout was not installed on this path.

RFC 9110 [§10.1.1 and §15.5.14](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.1.1) supports an immediate final response when headers alone permit it, and permits closing on a 413. Separate projects have documented early-response/write-error races, e.g. [Go issue #82143](https://github.com/golang/go/issues/82143) and [a bounded-drain gateway fix](https://github.com/Augustas11/macprovider/pull/2122). These are analogous reports, not proof of the exact failure mode of this test or evidence that any particular Go client is fixed.

## Brainstormed options

| Option | Benefit | Drawback / limitation |
|---|---|---|
| **A. Flush rejection and bound early drain; test `Expect`** | Addresses the stalled-header path and tests deterministic header-only 413 without buffering oversized data | Early send/close can still race a client already streaming; two-second drain cap is a policy choice. Proposed patch below. |
| B. Change only the test to use `Expect` | Removes the write-before-read assumption | Alone leaves the actual stalled-header path; reproduced as failing before the server change. |
| C. Drain the entire body before replying | May let write-first clients finish | Unbounded attacker-controlled work and stalled clients; not recommended. |
| D. Larger bounded drain and deadline | May help write-first clients see 413 | Cannot guarantee delivery for arbitrary sizes and increases resource exposure. |
| E. Concurrently read response while uploading | Better client behavior and realistic transport test | Still subject to TCP resets; cannot guarantee 413 for every client/network. Useful as additional tests, not a substitute for a server deadline. |
| F. Client preflights body size / `Expect: 100-continue` | Avoids sending an already-rejected large body | Depends on client and intermediaries; cannot protect the server from arbitrary clients. |

**Recommendation:** A for a reviewable experimental fix, plus E and F for compatibility. Never claim every client is guaranteed to receive 413 after already sending an oversized body.

## Patch behavior

The patch changes only the upstream Go checkout when explicitly applied:

- Installs a read deadline of the lesser of the configured upload timeout and two seconds **before** the known-length early rejection. The existing maximum drain of 1 MiB stays unchanged.
- Flushes the rejection response before draining; this affects other `rejectBody` calls too, including 408 and chunked rejection, so regression testing matters.
- Converts the write-first 21 MiB test into an `Expect: 100-continue` header-only request and keeps the 413 JSON / no-upstream assertions. This removes coverage of a write-first client; it does not prove that such clients receive a response.
- Adds a new real-socket regression test for stalled oversized headers, with and without `Expect`, checking prompt 413, error code and zero upstream POSTs.

**Limits:** deadlines and flushing use `http.ResponseController`; the patch ignores unsupported-controller errors just as the upstream code already does, so behavior with middleware/writers that do not support those operations is not established. The 1 MiB drain, a two-second per-connection wait and connection close are not a global concurrency limit. Header-only tests do not replace slow-upload, concurrent-streaming, TLS, reverse-proxy or HTTP/2 tests. The test's one-second response threshold is environment-sensitive. The patch is a prototype, not an upstream-reviewed fix.

## Verification performed

- Unmodified upstream: targeted oversized content-length test failed 10/10 on broken pipe; a separate header-only stalled test failed for both expectation modes on a four-second read timeout.
- Patched temporary clone: `go test ./...` passed. A separate fresh clone accepted the patch via `git apply --check`, applied it, and also passed `go test ./...`.
- Patched upstream: targeted known-length, chunked and stalled-upload cases plus the new header-only tests passed with `-count=5`; the same focused tests passed once under `go test -race`.
- These were loopback mock tests. No live AgentRouter, TLS, production load or intermediary was tested. The full unmodified upstream suite is not claimed to pass.

## Separate follow-up: local rejection paths

[`rejectLocally`](https://github.com/trefeon/agentrouter-spoof-proxy/blob/afa0be17622f95c276d447ab45decb6a049095a7/internal/server/server.go#L344) uses an unbounded `io.Copy` for local rejections. On the first-patch-only clone, real-socket tests with a declared body and no body bytes timed out after two seconds for **six cases**: unknown route, rejected auth, wrong method, count-token rejected auth, count-token oversized length, and count-token stalled upload. The first patch alone does not fix these.

A [second experimental patch](../patches/agentrouter-go-local-rejections.patch) addresses these paths separately. Local rejections with bodies send and flush the response, mark HTTP/1 connections for close and drain at most 1 MiB explicitly with a two-second read deadline. The HTTP server's own body-close handling may read additional bounded data; the deadline limits time, not total network traffic or concurrent connections. Bodyless local errors keep the existing connection behavior. The token-counting route rejects known oversized lengths before reading, applies the configured upload timeout to reads, and returns 408 on a read timeout; its successful response shape is unchanged.

On an isolated clone with both patches, all seven new local-rejection cases (including an `Expect` variant), a successful token-count request, and the full **modified** upstream test suite passed (the first patch replaces the original write-first oversized-body test). The local test subset also passed with `-race`. Tests use HTTP/1 loopback sockets and mock upstreams. They do **not** establish HTTP/2, TLS, slow streaming, proxy-intermediary or high-concurrency behavior. Both patches ignore unsupported `ResponseController` operations, and the second patch uses a two-second drain window regardless of `BODY_UPLOAD_TIMEOUT_MS`; these choices require upstream review. In particular, other routes may have independent request-body reads: for example, the dashboard mode endpoint reads up to 1 MiB without this token-counting deadline. Do not treat the service as fully hardened.

## Review / try the patch

Use a disposable checkout of the exact commit; do not apply blindly to your deployed service. This patch changes tracked upstream files, so OWL's installer intentionally refuses to overwrite/rebuild that modified checkout on later runs. Avoid modifying the managed installation; build and test a separate checkout.

```bash
git clone https://github.com/trefeon/agentrouter-spoof-proxy.git agentrouter-413-review
cd agentrouter-413-review
git checkout --detach afa0be17622f95c276d447ab45decb6a049095a7
git apply --check /path/to/owl-agent-proxy/patches/agentrouter-go-oversize-413.patch
git apply /path/to/owl-agent-proxy/patches/agentrouter-go-oversize-413.patch
git apply --check /path/to/owl-agent-proxy/patches/agentrouter-go-local-rejections.patch
git apply /path/to/owl-agent-proxy/patches/agentrouter-go-local-rejections.patch
go test ./...
```

Go 1.26.5 or compatible is required. Obtain dependencies through the normal Go module and checksum services when available. In this restricted sandbox, `GOPROXY=direct GOSUMDB=off` was used because only GitHub and package registries are reachable; the checked-in `go.sum` still verifies the recorded module hash, but the checksum database was not consulted.

**Confidence:** 90/100 for the reproduced local stall and the test's write-before-read assumption; 70/100 for the proposed patch as an experimental mitigation. Confidence is lower for production and arbitrary clients because the above protocol, load and intermediary tests remain open.
