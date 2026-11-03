# Upstream contribution draft: bounded local request rejection

**Status:** Prepared for review; not submitted. Target: `trefeon/agentrouter-spoof-proxy`, base commit `afa0be17622f95c276d447ab45decb6a049095a7` (verify it is still relevant before submitting). The proposed patches are experimental and intentionally not applied to the managed installation. See [detailed investigation](AGENTROUTER_413_RESEARCH.md).

## Suggested pull request title

`fix: respond promptly and bound drains on rejected uploads`

## Suggested pull request description

### Problem

When a request declares a `Content-Length` above the 20 MiB limit, the proxy rejects it before `readBody` installs the upload deadline. The rejection path then attempts to drain request data before the buffered response is flushed. A client that sends only the headers can wait indefinitely for the 413 while the server waits for the request body; this was reproduced both with and without `Expect: 100-continue`.

Separately, local errors such as unknown routes and unauthorized requests drain the request body without a limit or read deadline. The local token-count route also reads a request body without an upload deadline. In a Linux loopback test, these paths did not respond within two seconds when a client sent headers but stalled before sending the body.

The existing `TestOversizedContentLength413` writes a full 21 MiB request before reading the response. It failed 10/10 runs in our environment with `broken pipe` after the server logged a 413. That failure alone does not prove whether a client received the response; it is separate from the reproduced stalled-header behavior.

### Proposed changes

- For early oversized-length rejection, set a short, bounded read deadline and flush the 413 before bounded draining.
- For local rejection with an unread body, flush the error, mark HTTP/1 connections for close, and bound the explicit drain and its duration.
- Apply the configured upload deadline to local token counting, return 413 for an oversized declared length and 408 for a read timeout.
- Replace the existing write-first oversized-length test with a deterministic `Expect: 100-continue` check, and add loopback socket tests for stalled headers, error codes, successful local token counting and absence of upstream POSTs.

### Verification

Using Go 1.26.5 on Linux against mock upstreams, on the stated base commit with both proposed patches applied:

- `go test ./...` passed on the **modified** test suite. The first patch replaces the write-first oversized test; this is not evidence that write-first clients always receive 413.
- `go vet ./...` passed.
- Focused local-rejection tests passed with `go test -race` (previous verification); focused oversized and stalled-upload tests also passed with `-race` and repeated runs.
- Tests did not contact AgentRouter or use credentials. No production, reverse-proxy, HTTP/2 or TLS validation was performed.

### Review questions and limitations

- The patches intentionally close HTTP/1 connections for rejected requests with bodies; is this behavior and the chosen two-second / 1 MiB drain policy appropriate for this project?
- `http.ResponseController` errors are currently ignored; middleware or writers without deadline/flush support require further design.
- An early response cannot guarantee that every client which is already uploading receives the 413 instead of a transport reset. An additional concurrent-read/upload client test is desirable.
- Dashboard mode handling and other independent body-read paths need a separate audit; these patches are not a general DoS fix.
- The one-second timing assertion and fixed deadlines may be flaky on slow CI. Consider synchronization and suitable timing margins.

## Patch application and checks

Apply the patches in this order to a **disposable** checkout at the base commit; paths below are placeholders for the local OWL checkout, not commands to run against a production installation:

```bash
git apply --check /path/to/owl-agent-proxy/patches/agentrouter-go-oversize-413.patch
git apply /path/to/owl-agent-proxy/patches/agentrouter-go-oversize-413.patch
git apply --check /path/to/owl-agent-proxy/patches/agentrouter-go-local-rejections.patch
git apply /path/to/owl-agent-proxy/patches/agentrouter-go-local-rejections.patch
git diff --check
go test ./...
go vet ./...
go test -race ./e2e -run '^(TestOWLHeaderOnlyOversize|TestOversizedContentLength413|TestOversizedChunked413|TestStalledUpload408|TestOWLLocalRejectStalledBodies|TestOWLCountTokensNormal)$'
```

Patch SHA-256 checksums:

- `agentrouter-go-oversize-413.patch`: `4820a761645b6bfff6a725ddade296b34211ebb3e6b00da9e1910545d2b8b5cf`
- `agentrouter-go-local-rejections.patch`: `c4dcf75954aae34fcd1a7af8bf9cdef610b6480dc4cdddb1ca694b2c5331ef49`

In this sandbox, Go modules were fetched directly from GitHub with `GOPROXY=direct GOSUMDB=off`, and verified against the pinned `go.sum`; the external Go checksum database was not consulted. Prefer normal Go checksum verification when available.
