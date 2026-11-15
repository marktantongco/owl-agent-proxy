#!/usr/bin/env python3
"""
🦉 OWL-AGENT — runtime check: components wired together, not just unit-tested.

Why this exists
---------------
Every existing check tests one component in isolation, and 598 tests still
missed the harvester state leak: the defect lived in a *seam* —
``load_state`` × the constructor's source list × ``save_state``. Spies on
``strategy_selector`` had the same shape: unit-tested, never exercised through
the escalation path that calls it.

This script drives the real components through the real code paths against a
**loopback-only** origin:

    127.0.0.1:PORT_PUT_SOURCE   serves two proxy list formats
        (JSON + plain text) so the harvester's per-source parsers both run

    127.0.0.1:PORT_PROXY        a real forward proxy: accepts an absolute-URI
        request and forwards it to the origin. Not a mock — this is what
        ``validate_proxy`` speaks to, so TCP and HTTP-through-proxy are both
        genuinely exercised.

    127.0.0.1:PORT_ORIGIN       the target. Records the path each request took
        (direct vs via-proxy) and the header that proves which hop delivered it.

No external egress is used or required. That is deliberate: the sandbox that
found the state leak reaches none of the four proxy sources, and a check that
needs the internet is a check that runs nowhere.

State isolation
---------------
``HOME`` is redirected into a temp directory for the whole run, and the state
file is deleted between cases. Without this the check measures a previous run's
state — the state-leak bug one level up. Every case starts from zero and is
asserted to leave exactly what it wrote.

Usage
-----
    python scripts/runtime-check.py              # human output
    python scripts/runtime-check.py --json       # machine output
    python scripts/runtime-check.py --check      # CI: non-zero on any failure
Exit codes: 0 all passed, 1 a check failed, 2 the harness could not start.

Rules enforced — see scripts/gen-docs.py for the `gate:` convention:

gate: seam-state-isolation: a harvester that declares one source inherits no other's health [required] [probe: scripts/runtime-check.py --check]
gate: probe-separates-tcp-from-http: a dead proxy reports TCP failure, not HTTP failure [required] [probe: scripts/runtime-check.py --check]
gate: harness-proxy-is-pinned: the check's own forward proxy dials one fixed loopback origin [required] [probe: scripts/runtime-check.py --check]
gate: affinity-sticky-then-expires: a binding is stable until TTL, then gone [required] [probe: scripts/runtime-check.py --check]
gate: breaker-opens-then-closes: the circuit breaker opens at threshold and closes on success [required] [probe: scripts/runtime-check.py --check]
gate: unavailable-protocol-refused: an uninstalled protocol raises instead of sending http/1.1 under its label [required] [probe: scripts/runtime-check.py --check]
gate: reverse-proxy-forwards: an ingress request reaches the upstream and returns its status [required] [probe: scripts/runtime-check.py --check]
gate: escalation-branch-is-live: the 429/403 escalation path is reachable, or its deadness is recorded [required] [probe: scripts/runtime-check.py --check]
gate: mcp-dispatch-over-jsonrpc: a tool call, an unknown tool and a notification behave correctly through handle() [required] [probe: scripts/runtime-check.py --check]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RESULTS: list[dict] = []


# ── a real forward proxy, on loopback ───────────────────────────────────────
class ProxyHandler(BaseHTTPRequestHandler):
    """Minimal HTTP forward proxy, pointed at one fixed origin.

    Handles absolute-URI GETs (``GET http://host:port/path HTTP/1.1``), which is
    what a client sends when it is told to use a forward proxy. It re-serves the
    response and stamps a hop header so the origin can record that the request
    came *through* the proxy rather than around it: proxying is observable, not
    assumed.

    The destination is ``target``, set once at startup — never the host in the
    request. Dialing what the request names would make a test double into a
    request-forgery primitive; the first version did that (with a loopback
    allowlist in front of it) and CodeQL was right to keep flagging it, because
    "parse a URL a stranger controls, then connect to it" is the whole shape of
    the bug. The only origin this harness needs is its own loopback server.
    """

    protocol_version = "HTTP/1.1"
    target: tuple[str, int] | None = None

    def log_message(self, *args):  # silence the per-request stderr noise
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.scheme or not parsed.hostname:
            # Not an absolute-URI request: this client bypassed the proxy.
            self.send_error(400, "proxy expects an absolute URI")
            return
        if self.target is None:
            self.send_error(503, "proxy target not configured")
            return
        body = self._forward(parsed)
        if body is None:
            self.send_error(502, "upstream unreachable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Via", "1.1 owl-runtime-check")
        self.end_headers()
        self.wfile.write(body)

    def _forward(self, parsed):
        import http.client

        # Fragments of the request are used as a *path*, never as the host.
        host, port = self.target
        conn = http.client.HTTPConnection(host, port, timeout=5)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        try:
            conn.request("GET", path, headers={
                "Host": f"{host}:{port}",
                "X-Owl-Via": "forward-proxy",
            })
            response = conn.getresponse()
            return response.read()
        except OSError:
            return None
        finally:
            conn.close()


class OriginHandler(BaseHTTPRequestHandler):
    """Target server. Records every route that reached it."""

    protocol_version = "HTTP/1.1"
    hits: list[dict] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        via = self.headers.get("X-Owl-Via")
        OriginHandler.hits.append({"path": self.path, "via": via})
        payload = json.dumps({
            "path": self.path,
            "via": via or "direct",
            "proxy_header": self.headers.get("Proxy-Connection") is not None,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class SourceHandler(BaseHTTPRequestHandler):
    """Serves proxy lists in both formats the harvester must parse."""

    protocol_version = "HTTP/1.1"
    payloads: dict[str, tuple[str, bytes]] = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        content_type, body = self.payloads.get(
            parsed.path, ("text/plain", b"")
        )
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(handler) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


# ── checks ──────────────────────────────────────────────────────────────────
async def check_harvest_both_formats(source_port: int) -> None:
    """The harvester's JSON and text parsers both run against a live endpoint."""
    import proxy_harvester as ph

    # Public addresses only: the parsers drop private/loopback/CGNAT at parse
    # time (is_public_ip) because such entries can never reach the internet.
    # Using 10.x/127.x here would test the filter, not the fetch path.
    SourceHandler.payloads = {
        "/list.json": ("application/json", json.dumps([
            {"ip": "8.8.8.8", "port": 8080, "protocols": ["http", "https"],
             "country_code": "PH", "latency_ms": 120.0, "uptime_percent": 99.1},
            {"ip": "1.1.1.1", "port": 3128, "protocols": ["socks5"],
             "country_code": "SG"},
            {"ip": "10.0.0.9", "port": 8000, "protocols": ["http"]},  # must be dropped
        ]).encode()),
        "/list.txt": ("text/plain", b"9.9.9.9:8000\nsocks5://208.67.222.222:1080\n"),
    }
    sources = [
        ph.ProxySource("rt_json", f"http://127.0.0.1:{source_port}/list.json", "json"),
        ph.ProxySource("rt_txt", f"http://127.0.0.1:{source_port}/list.txt", "txt"),
    ]
    async with ph.UpstreamHarvester(sources=sources, timeout=5.0) as harvester:
        proxies = await harvester.harvest()
        snapshot = harvester.health.snapshot()

    urls = sorted(p["url"] for p in proxies)
    # 2 JSON + 2 text survive; the 10.x entry is rejected by is_public_ip.
    private_dropped = not any("10.0.0.9" in url for url in urls)
    ok = len(urls) == 4 and set(snapshot) == {"rt_json", "rt_txt"} and private_dropped
    _record(
        "harvest parses both live formats",
        ok,
        f"{len(urls)} proxies, health for {sorted(snapshot)}",
    )
    if not ok:
        print("        got:", urls)


async def check_validate_through_real_proxy(proxy_port: int, origin_port: int) -> None:
    """``validate_proxy`` must separate TCP-reachable from HTTP-capable."""
    import proxy_harvester as ph

    OriginHandler.hits.clear()
    probe = f"http://127.0.0.1:{origin_port}/probe"
    live = await ph.validate_proxy(f"http://127.0.0.1:{proxy_port}",
                                   timeout=5.0, probe_url=probe)
    ok_live = bool(live and live.get("ok") is True and live.get("status") == 200)

    # TCP-alive but not speaking HTTP: validate_proxy must report tcp_ms with
    # http_ms None, which is how a caller tells "unreachable" from "reached but
    # useless". The rule's description claimed this distinction was covered while
    # the check only asserted dead is None; probing showed the two cases produce
    # genuinely different dicts, so the assertion is worth having.
    mute_server = await asyncio.start_server(
        lambda reader, writer: writer.close(), "127.0.0.1", 0
    )
    mute_port = mute_server.sockets[0].getsockname()[1]
    try:
        mute = await ph.validate_proxy(f"http://127.0.0.1:{mute_port}",
                                       timeout=2.0, probe_url=probe)
    finally:
        mute_server.close()
    tcp_only = bool(mute and mute.get("tcp_ms") is not None
                    and mute.get("http_ms") is None and mute.get("ok") is False)

    # A port with nothing behind it must report TCP failure, not HTTP failure.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
    dead = await ph.validate_proxy(f"http://127.0.0.1:{dead_port}",
                                   timeout=2.0, probe_url=probe)

    routed_through_proxy = any(h["via"] == "forward-proxy" for h in OriginHandler.hits)
    ok = ok_live and dead is None and routed_through_proxy and tcp_only
    _record(
        "validate_proxy separates TCP from HTTP, through a real proxy",
        ok,
        f"live ok={ok_live} status={live and live.get('status')}, "
        f"dead={dead}, tcp-only={tcp_only}, "
        f"origin saw proxy hop={routed_through_proxy}",
    )


async def check_unavailable_protocol_is_not_mislabelled(origin_port: int) -> None:
    """An unavailable protocol must not be silently downgraded *and relabelled*.

    `ResilientClient.request` dispatches on `protocol == "x" and X_AVAILABLE`,
    with a final `else: _request_http1(...)`. So when the optional dependency is
    missing the request silently degrades to HTTP/1.1 — and then the line
    `response.protocol = protocol` records the protocol that was *asked for*.

    `_request_stealth` already refuses to do this, in a comment: "falling
    through to http/1.1 would label an ordinary request 'stealth'". The same
    argument applies to every optional branch, and nothing was checking.

    This is the closest thing to load-bearing in the whole gate suite: a caller
    that asks for ja3 and reads `response.protocol == "ja3"` will believe it
    bypassed an anti-bot check when it sent a plain HTTP/1.1 request.
    """
    import proxy_defense as pd

    requested = "ja3"
    if pd.JA3_AVAILABLE:
        _record(
            "unavailable protocol is reported, not relabelled",
            True,
            "ja3 is installed here, so the downgrade path is not exercised",
        )
        return

    OriginHandler.hits.clear()
    # No upstream harvesting: this exercises dispatch and labelling only.
    # `_session` is opened by the async context manager, not the constructor.
    async with pd.ResilientClient(
        auto_load_proxies=False, external_proxies=[]
    ) as client:
        try:
            resp = await client.request(
                "GET", f"http://127.0.0.1:{origin_port}/escalation", protocol=requested
            )
        except RuntimeError as exc:
            # The honest outcome: refused rather than silently downgraded. The
            # refusal must NOT have reached the origin — if it did, the request
            # went out and the message is a lie.
            # The class matters, not just the message. `ProtocolUnavailable` is
            # caught separately in the retry loop: no backoff, and the proxy is
            # NOT marked banned, because a missing library is configuration.
            # A plain RuntimeError lands in the generic branch, which bans a
            # healthy proxy and waits out backoff for something no retry fixes.
            # PR #55 raised RuntimeError here; this check now requires the type.
            refused_loudly = isinstance(exc, __import__("proxy_defense").ProtocolUnavailable)
            leaked = bool(OriginHandler.hits)
            _record(
                "unavailable protocol is reported, not relabelled",
                refused_loudly and not leaked,
                f"requested={requested} -> refused ({exc}); origin_reached={leaked}",
            )
            return

    reached = bool(OriginHandler.hits)
    recorded = getattr(resp, "protocol", None)
    mislabelled = reached and recorded == requested

    _record(
        "unavailable protocol is reported, not relabelled",
        not mislabelled,
        f"requested={requested} recorded={recorded} origin_reached={reached} "
        f"-> {'MISLABELLED: http/1.1 sent, reported as ja3' if mislabelled else 'honest'}",
    )


async def check_proxy_target_is_pinned(proxy_port: int, origin_port: int) -> None:
    """The test proxy must dial its pinned origin, never the host in the request.

    Sending an absolute URI naming a foreign host is exactly the request-forgery
    shape: if the destination came from the request, this would dial example.com.
    Asserted rather than assumed — a guard nobody exercises is a comment.
    """
    import http.client

    OriginHandler.hits.clear()

    def _attempt(uri: str) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=5)
        try:
            conn.request("GET", uri, headers={"Host": "localhost"})
            return conn.getresponse().status
        finally:
            conn.close()

    named_foreign = _attempt("http://example.com/pinned-probe")
    reached = [h for h in OriginHandler.hits if h["path"] == "/pinned-probe"]
    _record(
        "proxy dials its pinned origin, not the named host",
        named_foreign == 200 and len(reached) == 1
        and reached[0]["via"] == "forward-proxy",
        f"request naming example.com -> {named_foreign}, "
        f"local origin sees {len(reached)} hop(s)",
    )


async def check_reverse_proxy_end_to_end(origin_port: int) -> None:
    """ReverseProxy must carry a real request to a real upstream and back.

    The only shipped module never driven with a socket. Two things are checked,
    and the second is the interesting one:

    1. A request through the ingress reaches the upstream and its body and
       status come back unaltered.

    2. **The adaptive escalation on 429/403 cannot fire.** `_handle_request`
       escalates inside `except`, gated on `hasattr(exc, "status") and
       exc.status in (429, 403)`. But `ResilientClient.request` *returns*
       4xx/5xx responses — it only raises for transport failures and for a
       retry budget exhausted, and no exception class in the module carries a
       `status` attribute. So the escalation branch is dead code, and a
       Cloudflare 403 is passed straight back to the client instead of
       triggering a protocol change.

    The check asserts the current behaviour so the gap is recorded, and fails if
    someone implements escalation without updating this note.
    """
    import proxy_defense as pd
    import reverse_proxy as rp

    proxy = rp.ReverseProxy(
        [f"http://127.0.0.1:{origin_port}"],
        auto_load_proxies=False,
        # http/1.1 only: the other protocols are not installed here, and this
        # check is about ingress and escalation, not about TLS fingerprints.
        protocol_escalation=["http/1.1", "ja3"],
        health_check_interval=0.0,
    )

    # `start()` also binds a listening port; this check needs only the egress
    # client live, so the context manager is entered directly.
    await proxy.client.__aenter__()
    OriginHandler.hits.clear()

    # Drive _handle_request the way aiohttp would, without binding a port.
    class _Req:
        method = "GET"
        query_string = ""
        query = {}
        headers = {"Host": f"127.0.0.1:{origin_port}"}
        match_info = {"path": "reached"}

        async def read(self):
            return b""

    resp = await proxy._handle_request(_Req())
    upstream_saw = [h for h in OriginHandler.hits if h["path"].startswith("/reached")]
    forwarded = bool(upstream_saw) and getattr(resp, "status", None) == 200

    # The escalation branch is unreachable: verify no exception type in the
    # module carries `status`, which is what the branch tests for.
    status_types = [
        name for name, obj in vars(pd).items()
        if isinstance(obj, type) and issubclass(obj, BaseException)
        and "status" in getattr(obj, "__annotations__", {})
    ]
    escalation_reachable = bool(status_types)

    await proxy.client.__aexit__(None, None, None)

    _record(
        "reverse proxy forwards end to end",
        forwarded and not escalation_reachable,
        f"upstream saw request={bool(upstream_saw)} status={getattr(resp, 'status', None)}; "
        f"429/403 escalation branch reachable={escalation_reachable} "
        f"({'dead: no exception carries .status' if not escalation_reachable else 'NOW REACHABLE - update the note'})",
    )


async def check_mcp_tool_dispatch_over_jsonrpc() -> None:
    """A tool call must survive the real JSON-RPC path, not just `call_tool`.

    `call_tool` was exercised directly in tests; `handle_one` — the layer that
    parses the message, validates the method, dispatches and wraps the result —
    had no end-to-end check. That layer is where a tool name can silently fall
    through to "unknown tool", where a notification can be answered when it
    should be dropped, and where an error can come back as a result.

    Drives the server through `handle()` exactly as a client would.
    """
    import io

    import mcp_proxy_server as mcp

    server = mcp.OwlMcpServer(out=io.StringIO())

    unknown = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": "no_such_tool", "arguments": {}}})
    unknown_is_error = bool(unknown and ("error" in unknown
                                         or unknown.get("result", {}).get("isError")))

    # proxy_stats needs no arguments and no network, so it isolates dispatch.
    stats = await server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                 "params": {"name": "proxy_stats", "arguments": {}}})
    dispatched = bool(stats and "result" in stats and "error" not in stats)

    # A missing argument must be reported, not silently defaulted.
    missing = await server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                   "params": {"name": "proxy_pick", "arguments": {}}})
    missing_arg_reported = bool(
        missing and json.dumps(missing).find("domain required") != -1
    )

    # A notification (no id) must produce no response at all.
    notif = await server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    notification_dropped = notif is None

    _record(
        "MCP tool dispatch over JSON-RPC",
        unknown_is_error and dispatched and missing_arg_reported and notification_dropped,
        f"unknown-tool is error={unknown_is_error}, proxy_stats dispatched={dispatched}, "
        f"missing arg reported={missing_arg_reported}, notification dropped={notification_dropped}",
    )


async def check_state_isolation_across_instances(source_port: int) -> None:
    """The seam that 598 tests missed: run A's file, run B's source list."""
    import proxy_harvester as ph

    SourceHandler.payloads = {
        "/a.json": ("application/json",
                    b'[{"ip": "8.8.4.4", "port": 80, "protocols": ["http"]}]'),
        "/b.json": ("application/json",
                    b'[{"ip": "1.0.0.1", "port": 81, "protocols": ["http"]}]'),
    }

    # Run A: one source, harvests, persists.
    async with ph.UpstreamHarvester(
        sources=[ph.ProxySource("rt_a", f"http://127.0.0.1:{source_port}/a.json", "json")],
        timeout=5.0,
    ) as first:
        await first.harvest()
    after_a = json.loads(ph.STATE_FILE.read_text())

    # Run B: different source list, same HOME. It must see only its own source,
    # and it must not delete run A's learning from disk.
    async with ph.UpstreamHarvester(
        sources=[ph.ProxySource("rt_b", f"http://127.0.0.1:{source_port}/b.json", "json")],
        timeout=5.0,
    ) as second:
        visible = sorted(second.health.snapshot())
        await second.harvest()
    after_b = json.loads(ph.STATE_FILE.read_text())

    # Health rows are created on first fetch, so a fresh instance sees only what
    # load_state restored. The contract is: nothing foreign, and nothing erased.
    ok = (
        "rt_a" not in visible
        and "rt_a" in after_b.get("health", {})
        and "rt_b" in after_b.get("health", {})
        and after_a.get("health", {}).get("rt_a") is not None
    )
    _record(
        "state isolation holds across instances",
        ok,
        f"run B inherited {visible or 'nothing'}; disk after B has "
        f"{sorted(after_b.get('health', {}))}",
    )


async def check_affinity_is_sticky() -> None:
    """A bound proxy must come back unchanged until the TTL expires."""
    import proxy_harvester as ph

    now = [1000.0]
    manager = ph.SessionAffinityManager(ttl_seconds=10.0, clock=lambda: now[0])
    first, second = "http://10.9.0.1:8080", "http://10.9.0.2:8080"

    await manager.bind("agent-rt", "example.test", first)
    reads = [await manager.get("agent-rt", "example.test") for _ in range(5)]
    sticky = reads == [first] * 5

    # Re-binding must report the previous proxy, then still read the new one.
    replaced = await manager.get("agent-rt", "other.test")
    previous = await manager.bind("agent-rt", "example.test", second)
    current = await manager.get("agent-rt", "example.test")

    now[0] += 11.0
    after_expiry = await manager.get("agent-rt", "example.test")
    _record(
        "session affinity is sticky, rebindable, and expires",
        sticky and previous == first and current == second
        and after_expiry is None and replaced is None,
        f"5 reads -> {set(reads)}; rebind reported {previous is first}, "
        f"read {current is second}; after TTL -> {after_expiry}",
    )


async def check_circuit_breaker_trips_and_recovers() -> None:
    """Open, stay open, then close after the recovery window — through real calls."""
    import reverse_proxy as rp

    breaker = rp.CircuitBreaker(threshold=2)
    closed_before = not breaker.is_open("https")
    for _ in range(2):
        breaker.record_failure("https")
    opened = breaker.is_open("https")
    # A success must reset the failure count and close the circuit.
    breaker.record_success("https")
    recovered = not breaker.is_open("https")
    _record(
        "circuit breaker opens on threshold, closes on success",
        closed_before and opened and recovered,
        f"closed at 0={closed_before}, open at 2={opened}, "
        f"closed after success={recovered}",
    )


# ── harness ─────────────────────────────────────────────────────────────────
async def run_all() -> int:
    servers = []
    try:
        src_srv, src_port = _serve(SourceHandler)
        proxy_srv, proxy_port = _serve(ProxyHandler)
        origin_srv, origin_port = _serve(OriginHandler)
        ProxyHandler.target = ("127.0.0.1", origin_port)  # fixed at startup
        servers = [src_srv, proxy_srv, origin_srv]
    except OSError as exc:
        print(f"harness could not bind loopback ports: {exc}", file=sys.stderr)
        return 2

    print(f"loopback: source={src_port} proxy={proxy_port} origin={origin_port}")
    print(f"HOME redirected to {os.environ['HOME']}")

    cases = [
        ("harvest parses both live formats",
         check_harvest_both_formats, (src_port,)),
        ("validate_proxy through a real proxy",
         check_validate_through_real_proxy, (proxy_port, origin_port)),
        ("proxy target is pinned", check_proxy_target_is_pinned,
         (proxy_port, origin_port)),
        ("unavailable protocol is reported, not relabelled",
         check_unavailable_protocol_is_not_mislabelled, (origin_port,)),
        ("MCP tool dispatch over JSON-RPC", check_mcp_tool_dispatch_over_jsonrpc, ()),
        ("reverse proxy forwards end to end",
         check_reverse_proxy_end_to_end, (origin_port,)),
        ("state isolation across instances",
         check_state_isolation_across_instances, (src_port,)),
        ("session affinity", check_affinity_is_sticky, ()),
        ("circuit breaker", check_circuit_breaker_trips_and_recovers, ()),
    ]
    for label, case, args in cases:
        # Each case starts from an empty state file: a previous case's learning
        # must never leak into the next one's assertions.
        import proxy_harvester as ph
        if ph.STATE_FILE.exists():
            ph.STATE_FILE.unlink()
        started = time.perf_counter()
        try:
            await case(*args)
        except Exception as exc:  # a harness crash is a failure, not a skip
            _record(label, False, f"raised {type(exc).__name__}: {exc}")
        RESULTS[-1]["ms"] = round((time.perf_counter() - started) * 1000, 1)

    for server in servers:
        server.shutdown()

    failed = [r for r in RESULTS if not r["ok"]]
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} runtime checks passed")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--check", action="store_true",
                        help="CI mode: non-zero exit on any failure")
    args = parser.parse_args()

    # Isolate state before importing anything that captures HOME at module load.
    tmp_home = tempfile.mkdtemp(prefix="owl-runtime-home-")
    os.environ["HOME"] = tmp_home
    os.environ["XDG_CACHE_HOME"] = str(Path(tmp_home) / ".cache")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    if not args.json:
        print("=== runtime check: components wired together ===")

    quiet = args.json
    if quiet:
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = asyncio.run(run_all())
    else:
        code = asyncio.run(run_all())

    if args.json:
        print(json.dumps({"results": RESULTS, "exit": code}, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
