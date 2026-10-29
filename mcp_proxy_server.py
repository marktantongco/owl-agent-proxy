#!/usr/bin/env python3
"""
🦉 OWL-AGENT v7.1 — MCP server for AI agents.

Transport: newline-delimited JSON-RPC 2.0 over stdio (also tolerates
``Content-Length`` framed clients, which some older hosts still send).
Protocol layer is **stdlib-only**. The proxy backend (``proxy_defense``) is
imported lazily on the first tool call, so ``initialize`` and ``tools/list``
answer in milliseconds even on a cold machine.

Three stdio rules are enforced:

1. stdout carries JSON-RPC frames only — the backend's stray ``print`` calls are
   redirected to stderr while a tool runs.
2. diagnostics go to stderr.
3. exactly one JSON object per line.

Tools: proxy_pick, proxy_stats, proxy_rotate, proxy_validate.

Run:
    python mcp_proxy_server.py            # serve on stdio
    python mcp_proxy_server.py --selftest # in-process smoke test, exits 0/1
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

SERVER_NAME = "owl-proxy"
SERVER_VERSION = "7.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

# NOTE: stdout is captured before anything else can touch it.
_STDOUT = sys.stdout

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,  # never stdout
)
logger = logging.getLogger("owl-agent.mcp")

# ── tool registry ──────────────────────────────────────────────────────────
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "proxy_pick",
        "description": (
            "Return a healthy proxy URL for a task. Honours sticky sessions per "
            "(agent_id, domain) when rotation_mode='sticky'. Returns proxy=null "
            "when the pool is still warming up — callers should fall back to a "
            "direct fetch in that case."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "target domain, e.g. example.com"},
                "agent_id": {"type": "string", "default": "default"},
                "rotation_mode": {
                    "type": "string",
                    "enum": ["sticky", "random", "round_robin"],
                    "default": "sticky",
                },
            },
            "required": ["domain"],
        },
    },
    {
        "name": "proxy_stats",
        "description": "Pool health: totals, per-source yield, session bindings, protocol availability.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "proxy_rotate",
        "description": "Invalidate the sticky proxy binding for (agent_id, domain).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "agent_id": {"type": "string", "default": "default"},
            },
            "required": ["domain"],
        },
    },
    {
        "name": "proxy_validate",
        "description": "Probe one proxy URL: TCP/HTTP timings plus honeypot/injection verdict.",
        "inputSchema": {
            "type": "object",
            "properties": {"proxy_url": {"type": "string"}},
            "required": ["proxy_url"],
        },
    },
]

_TOOL_NAMES = {tool["name"] for tool in TOOLS}


# ── framing ────────────────────────────────────────────────────────────────
class ProtocolError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def encode_message(message: Dict[str, Any]) -> str:
    """Serialize one JSON-RPC message as a single line."""
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"


def read_message(stream, max_bytes: int = 8 * 1024 * 1024) -> Optional[Dict[str, Any]]:
    """Read one message from a text stream.

    Supports newline-delimited JSON (the documented transport) *and*
    ``Content-Length`` framing, because a few hosts still emit LSP-style frames.
    Returns ``None`` at EOF. Raises ``ProtocolError`` on malformed input.
    """
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("content-length:"):
            length = 0
            try:
                length = int(line.split(":", 1)[1].strip())
            except ValueError as exc:
                raise ProtocolError(-32700, f"bad Content-Length: {line}") from exc
            while True:
                header = stream.readline()
                if not header or not header.strip():
                    break
            if length <= 0 or length > max_bytes:
                raise ProtocolError(-32700, f"unreasonable Content-Length: {length}")
            payload = stream.read(length)
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ProtocolError(-32700, f"parse error: {exc}") from exc
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProtocolError(-32700, f"parse error: {exc}") from exc


@contextlib.contextmanager
def stdout_guard() -> Iterator[None]:
    """Send any stray ``print()`` from the backend to stderr, not the wire."""
    original = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = original


# ── backend adapter ────────────────────────────────────────────────────────
class ProxyBackend:
    """Thin adapter over ``proxy_defense.ResilientClient``.

    Started lazily. Every method is failure-tolerant: a warm-up or import error
    must degrade the tool result, never kill the server.
    """

    def __init__(self, harvest: Optional[bool] = None, warmup_seconds: float = 3.0,
                 session_ttl: float = 900.0):
        # None → defer to config.json (so `use_upstream_harvester: false` really
        # is a kill switch); explicit env/argument wins.
        env = os.environ.get("OWL_MCP_HARVEST")
        if harvest is None and env is not None:
            harvest = env.strip() not in ("0", "false", "False", "no")
        self.harvest = harvest
        self.warmup_seconds = max(0.0, float(warmup_seconds))
        self.session_ttl = session_ttl
        self._client: Any = None
        self._start_lock = asyncio.Lock()
        self._started_at = 0.0
        self._start_error: Optional[str] = None

    @property
    def started(self) -> bool:
        return self._client is not None

    async def start(self) -> None:
        if self._client is not None:
            return
        async with self._start_lock:
            if self._client is not None:
                return
            try:
                if _OWL_HOME not in sys.path:
                    sys.path.insert(0, _OWL_HOME)
                from proxy_defense import ResilientClient  # lazy: heavy deps live here
                client = ResilientClient(
                    use_upstream_harvester=self.harvest,
                    session_ttl=self.session_ttl,
                )
                await client.__aenter__()
                self._client = client
                self._started_at = time.time()
                logger.info("backend started (harvest=%s)", self.harvest)
            except Exception as exc:
                self._start_error = f"{type(exc).__name__}: {exc}"
                logger.error("backend start failed: %s", self._start_error)
                raise

    async def stop(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.__aexit__(None, None, None)
            self._client = None

    async def _wait_for_pool(self) -> None:
        """Give the harvester a bounded head start on the first pick."""
        harvesting = bool(self._client and getattr(self._client, "use_upstream_harvester", False))
        if not harvesting or not self.warmup_seconds:
            return
        deadline = self._started_at + self.warmup_seconds
        while time.time() < deadline:
            if await self.healthy_count() > 0:
                return
            await asyncio.sleep(0.2)

    async def healthy_count(self) -> int:
        if self._client is None:
            return 0
        try:
            stats = await self._client.get_stats()
            return int(stats.get("proxies_healthy", 0))
        except Exception:  # warmup probe: a failing pool is not a protocol error
            logger.debug("get_stats failed during warmup; treating pool as empty", exc_info=True)
            return 0

    # ── tools ──
    async def pick(self, domain: str, agent_id: str, rotation_mode: str) -> Dict[str, Any]:
        await self.start()
        await self._wait_for_pool()
        entry = await self._client.rotator.get_proxy(
            domain=domain, agent_id=agent_id, rotation_mode=rotation_mode
        )
        if entry is None:
            return {
                "proxy": None,
                "domain": domain,
                "agent_id": agent_id,
                "rotation_mode": rotation_mode,
                "reason": "pool empty or still validating — fall back to a direct fetch",
            }
        return {
            "proxy": entry.url,
            "domain": domain,
            "agent_id": agent_id,
            "rotation_mode": rotation_mode,
            "protocol": entry.protocol,
            "tier": entry.tier,
            "source": entry.source,
            "latency_ms": round(entry.latency_ms, 1) if entry.latency_ms else None,
        }

    async def stats(self) -> Dict[str, Any]:
        await self.start()
        stats = await self._client.get_stats()
        stats["server"] = {"name": SERVER_NAME, "version": SERVER_VERSION}
        stats["backend_started_at"] = self._started_at or None
        return stats

    async def rotate(self, domain: str, agent_id: str) -> Dict[str, Any]:
        await self.start()
        rotated = await self._client.rotator.rotate(agent_id=agent_id, domain=domain)
        return {"rotated": rotated, "domain": domain, "agent_id": agent_id}

    async def validate(self, proxy_url: str) -> Dict[str, Any]:
        from proxy_harvester import HoneypotDetector, validate_proxy

        metrics = await validate_proxy(proxy_url)
        if not metrics:
            return {"valid": False, "url": proxy_url, "trusted": False,
                    "reason": "tcp-or-http-probe-failed"}
        if not metrics.get("ok"):
            # reachable socket but no usable HTTP response: never "trusted"
            return {"valid": False, "url": proxy_url, "trusted": False,
                    "reason": f"http-probe-failed-status-{metrics.get('status')}", **metrics}
        detector = HoneypotDetector()
        if await detector.establish_baseline():
            trusted, reason = await detector.check(proxy_url)
        else:
            trusted, reason = True, "no-baseline"
        return {"valid": bool(metrics.get("ok")), "trusted": trusted, "reason": reason, **metrics}


_OWL_HOME = str(Path(os.environ.get("OWL_AGENT_HOME", Path.home() / ".owl-agent")))
if Path(__file__).resolve().parent.as_posix() != _OWL_HOME:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


# ── JSON-RPC dispatch ──────────────────────────────────────────────────────
def _ok(id_: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": error}


class OwlMcpServer:
    def __init__(self, backend: Optional[ProxyBackend] = None,
                 out=None) -> None:
        self.backend = backend or ProxyBackend(
            warmup_seconds=float(os.environ.get("OWL_MCP_WARMUP_SEC", "3")),
        )
        self._out = out or _STDOUT
        self.initialized = False
        self.should_exit = False

    # ── output ──
    def write(self, message: Dict[str, Any]) -> None:
        self._out.write(encode_message(message))
        self._out.flush()

    # ── request handling ──
    async def handle(self, message: Any) -> Optional[Dict[str, Any]]:
        if isinstance(message, list):
            # JSON-RPC batch: answer each, drop notifications
            responses = [await self.handle_one(item) for item in message]
            responses = [r for r in responses if r is not None]
            return responses or None
        return await self.handle_one(message)

    async def handle_one(self, message: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(message, dict):
            return _err(None, -32600, "invalid request: not an object")
        method = message.get("method")
        id_ = message.get("id")
        is_notification = "id" not in message
        params = message.get("params") or {}

        if not isinstance(method, str):
            if "result" in message or "error" in message:
                return None  # a client response to a server request; ignore
            return None if is_notification else _err(id_, -32600, "invalid request: missing method")

        try:
            if method == "initialize":
                return self._initialize(id_, params)
            if method in ("notifications/initialized", "notifications/cancelled",
                          "notifications/roots/list_changed"):
                return None
            if method == "ping":
                return _ok(id_, {})
            if method == "tools/list":
                return _ok(id_, {"tools": TOOLS})
            if method == "tools/call":
                return await self._tools_call(id_, params)
            if method == "resources/list":
                return _ok(id_, {"resources": []})
            if method == "resources/templates/list":
                return _ok(id_, {"resourceTemplates": []})
            if method == "prompts/list":
                return _ok(id_, {"prompts": []})
            if method == "logging/setLevel":
                return _ok(id_, {})
            if method == "shutdown":
                # MCP/LSP semantics: acknowledge, then stop reading stdin
                self.should_exit = True
                return _ok(id_, {})
            if method == "exit":
                self.should_exit = True
                return None
            if is_notification:
                return None
            return _err(id_, -32601, f"method not found: {method}")
        except ProtocolError as exc:
            return None if is_notification else _err(id_, exc.code, exc.message)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("handler crashed for %s", method)
            return None if is_notification else _err(id_, -32603, f"internal error: {exc}")

    def _initialize(self, id_: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        self.initialized = True
        return _ok(id_, {
            "protocolVersion": version,
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "OWL-AGENT proxy pool. Call proxy_pick before fetching a domain; "
                "if proxy is null, fetch directly. Use proxy_rotate when a target "
                "starts rejecting the current exit IP."
            ),
        })

    async def _tools_call(self, id_: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(params, dict):
            return _err(id_, -32602, "invalid params")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in _TOOL_NAMES:
            return _err(id_, -32602, f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            return _err(id_, -32602, "arguments must be an object")

        try:
            with stdout_guard():
                result = await self.call_tool(name, arguments)
            is_error = isinstance(result, dict) and "error" in result
            return _ok(id_, {
                "content": [{"type": "text",
                             "text": json.dumps(result, indent=2, default=str)}],
                "structuredContent": result,
                "isError": is_error,
            })
        except Exception as exc:
            logger.warning("tool %s failed: %s", name, exc)
            return _ok(id_, {
                "content": [{"type": "text", "text": f"error: {type(exc).__name__}: {exc}"}],
                "isError": True,
            })

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "proxy_pick":
            domain = str(args.get("domain") or "").strip()
            if not domain:
                return {"error": "domain required"}
            mode = str(args.get("rotation_mode") or "sticky")
            if mode not in ("sticky", "random", "round_robin"):
                return {"error": f"unsupported rotation_mode: {mode}"}
            return await self.backend.pick(domain, str(args.get("agent_id") or "default"), mode)
        if name == "proxy_stats":
            return await self.backend.stats()
        if name == "proxy_rotate":
            domain = str(args.get("domain") or "").strip()
            if not domain:
                return {"error": "domain required"}
            return await self.backend.rotate(domain, str(args.get("agent_id") or "default"))
        if name == "proxy_validate":
            proxy_url = str(args.get("proxy_url") or "").strip()
            if not proxy_url:
                return {"error": "proxy_url required"}
            return await self.backend.validate(proxy_url)
        raise ValueError(f"unknown tool: {name}")

    # ── main loop ──
    async def serve(self, stream=None) -> int:
        stream = stream or sys.stdin
        try:
            while not self.should_exit:
                try:
                    # Reading stdin is blocking; run it in a worker thread so
                    # the pool's harvest/validation tasks keep progressing
                    # while the host is idle. Exit happens after a message is
                    # processed, so no read is left pending.
                    message = await asyncio.to_thread(read_message, stream)
                except ProtocolError as exc:
                    self.write(_err(None, exc.code, exc.message))
                    continue
                if message is None:
                    break
                response = await self.handle(message)
                if response is not None:
                    self.write(response)
        finally:
            await self.backend.stop()
        return 0


async def _selftest() -> int:
    """In-process protocol smoke test; no network required."""
    import io

    out = io.StringIO()
    server = OwlMcpServer(out=out)
    stream = io.StringIO("\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "selftest", "version": "0"}}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "resources/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 4, "method": "nope/method"}),
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"}),
    ]) + "\n")
    await server.serve(stream)

    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    by_id = {frame.get("id"): frame for frame in frames}
    problems = []
    if len(frames) != 5:
        problems.append(f"expected 5 frames, got {len(frames)}")
    info = by_id.get(1, {}).get("result", {}).get("serverInfo", {})
    if info.get("name") != SERVER_NAME or info.get("version") != SERVER_VERSION:
        problems.append(f"bad serverInfo: {info}")
    tools = {tool["name"] for tool in by_id.get(2, {}).get("result", {}).get("tools", [])}
    if tools != _TOOL_NAMES:
        problems.append(f"bad tool list: {tools}")
    if by_id.get(3, {}).get("result", {}).get("resources") != []:
        problems.append("resources/list did not return []")
    if by_id.get(4, {}).get("error", {}).get("code") != -32601:
        problems.append("unknown method did not return -32601")
    if by_id.get(5, {}).get("result") != {}:
        problems.append("ping did not return {}")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print("selftest OK: initialize, tools/list, resources/list, -32601, ping")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return asyncio.run(_selftest())
    if "--version" in argv:
        print(f"{SERVER_NAME} {SERVER_VERSION}")
        return 0
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    try:
        return asyncio.run(OwlMcpServer().serve())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
