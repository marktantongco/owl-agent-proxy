"""Local Anthropic Messages bridge inspired by agentrouter-opencode-proxy.

This is independent of OWL's web-fetch cache and untrusted proxy pool.
"""
import asyncio
import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import anthropic
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

KEY_FILE = Path.home() / ".config/opencode/api_keys/AGENT_ROUTER_API_KEY"
CHUNK_TIMEOUT = 120
_END = object()


def target_url():
    target = os.environ.get("AGENTROUTER_BASE_URL", "https://agentrouter.org").rstrip("/")
    u = urlsplit(target)
    # SDK adds /v1/messages; reject paths rather than silently changing them.
    if u.scheme != "https" or not u.hostname or u.path or u.query or u.fragment or u.username or u.password:
        raise ValueError("AGENTROUTER_BASE_URL must be an HTTPS origin without a path (no /v1)")
    return target


def api_key():
    key = os.environ.get("AGENTROUTER_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
    if not key:
        raise RuntimeError("Set AGENTROUTER_API_KEY or create the documented key file")
    return key


_client_instance = None
_client_lock = threading.Lock()


def client():
    global _client_instance
    with _client_lock:
        if _client_instance is None:
            _client_instance = anthropic.Anthropic(
                api_key=api_key(), base_url=target_url(), max_retries=0,
                http_client=httpx.Client(
                    limits=httpx.Limits(max_connections=50, max_keepalive_connections=5, keepalive_expiry=20),
                    timeout=httpx.Timeout(connect=10, read=CHUNK_TIMEOUT, write=10, pool=5),
                ),
            )
        return _client_instance


@asynccontextmanager
async def lifespan(_app):
    global _client_instance
    yield
    with _client_lock:
        if _client_instance is not None:
            _client_instance.close()
            _client_instance = None


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def filtered_events(chunks):
    """Emit complete SSE records, dropping billing_summary regardless of chunk boundaries."""
    buffer = b""
    record = []
    size = 0
    for chunk in chunks:
        buffer += chunk
        if len(buffer) + size > 4 * 1024 * 1024:
            raise ValueError("SSE record exceeds 4 MiB")
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            record.append(line + b"\n")
            size += len(line) + 1
            if not line.rstrip(b"\r"):
                if not any(x.rstrip(b"\r\n").startswith(b"event:") and
                           x.rstrip(b"\r\n")[6:].strip() == b"billing_summary" for x in record):
                    yield b"".join(record)
                record = []
                size = 0
    if buffer:
        record.append(buffer)
    if record and not any(x.rstrip(b"\r\n").startswith(b"event:") and
                          x.rstrip(b"\r\n")[6:].strip() == b"billing_summary" for x in record):
        yield b"".join(record)


def error_response(exc):
    if isinstance(exc, anthropic.APIStatusError):
        return JSONResponse(status_code=exc.status_code, content=exc.body or {"error": {"type": "api_error", "message": "Upstream request failed"}})
    # Do not leak credentials, URLs, or raw exceptions to clients.
    return JSONResponse(status_code=502, content={"error": {"type": "proxy_error", "message": "Upstream request failed; check proxy configuration"}})


def stream_worker(kwargs, out, stop):
    def put(item):
        while not stop.is_set():
            try:
                out.put(item, timeout=0.2)
                return
            except queue.Full:
                pass
    try:
        with client().messages.with_streaming_response.create(**kwargs, stream=True) as response:
            for event in filtered_events(response.iter_bytes()):
                if stop.is_set():
                    break
                put(event)
    except Exception as exc:
        put(exc)
    finally:
        put(_END)


async def next_item(out):
    # queue.get has its own timeout, so cancellation does not leave a permanent
    # executor thread blocked on an empty queue.
    try:
        return await asyncio.to_thread(out.get, True, CHUNK_TIMEOUT)
    except queue.Empty:
        return TimeoutError("Upstream stream stalled")


@app.post("/messages")
@app.post("/v1/messages")
async def messages(request: Request):
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"error": {"message": "Invalid JSON"}})
    if not isinstance(body, dict) or not isinstance(body.get("stream", False), bool):
        return JSONResponse(status_code=400, content={"error": {"message": "Expected a JSON object with boolean stream"}})
    kwargs = {k: v for k, v in body.items() if k not in {"stream", "thinking", "output_config"}}
    if not body.get("stream", False):
        try:
            result = await asyncio.to_thread(lambda: client().messages.create(**kwargs))
            return Response(result.model_dump_json(), media_type="application/json")
        except Exception as exc:
            return error_response(exc)

    out = queue.Queue(maxsize=16)
    stop = threading.Event()
    threading.Thread(target=stream_worker, args=(kwargs, out, stop), daemon=True).start()
    try:
        first = await next_item(out)
    except BaseException:
        stop.set()
        raise
    if isinstance(first, Exception):
        stop.set()
        return error_response(first)

    async def generate():
        item = first
        try:
            while item is not _END:
                if isinstance(item, Exception):
                    error = json.dumps({"type": "error", "error": {"type": "api_error", "message": "Upstream stream failed"}})
                    yield f"event: error\ndata: {error}\n\n".encode()
                    break
                yield item
                item = await next_item(out)
        finally:
            stop.set()
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


@app.get("/v1/models")
@app.get("/models")
async def models():
    # This is a local static list, not proof of upstream availability.
    ids = [x.strip() for x in os.environ.get("AGENTROUTER_MODELS", "claude-opus-4-6").split(",") if x.strip()]
    return {"object": "list", "data": [{"id": x, "object": "model"} for x in ids]}


def main():
    # Validate before starting, without printing the key.
    try:
        target_url()
        api_key()
    except (ValueError, RuntimeError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("AGENTROUTER_PORT", "7187")), log_level="warning")


if __name__ == "__main__":
    main()
