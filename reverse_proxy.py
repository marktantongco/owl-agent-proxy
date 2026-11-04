#!/usr/bin/env python3
"""
🦉 OWL-AGENT Reverse Proxy — HTTP ingress for the ResilientClient egress layer.

OWL Agent Proxy is a client-side library + stdio MCP server + CLI.
This module adds an optional HTTP ingress listener so the existing
ResilientClient (proxy rotation, caching, deduplication, domain rate
limiting, honeypot detection, sticky sessions) can sit in front of a
configurable upstream target and act as a reverse proxy.

Run:
    python reverse_proxy.py               # serve on :8080, forward to localhost:3000
    python reverse_proxy.py --port 9090   # custom listen port
    python reverse_proxy.py --target https://api.example.com  # custom upstream target

Config (config.json):
    {
        "reverse_proxy": {
            "port": 8080,
            "target_host": "http://localhost:3000"
        }
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

# Ensure the package directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

logger = logging.getLogger("owl-agent.reverse-proxy")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"
DEFAULT_PORT = 8080
DEFAULT_TARGET_HOST = "http://localhost:3000"


class ReverseProxy:
    """HTTP ingress that forwards requests through ResilientClient egress.

    Wraps ResilientClient so every proxied request benefits from the existing
    egress defenses: proxy rotation, caching, deduplication, domain rate
    limiting, honeypot detection, sticky sessions, and protocol routing.
    """

    def __init__(
        self,
        target_host: str,
        listen_port: int = DEFAULT_PORT,
        cache_ttl: int = 60,
        cache_max_entries: int = 10_000,
        rate_limit: float = 10.0,
        max_retries: int = 3,
        auto_load_proxies: bool = True,
        agent_id: str = "reverse-proxy",
    ):
        import proxy_defense as pd

        self.target_host = target_host.rstrip("/")
        self.listen_port = listen_port
        self.agent_id = agent_id

        self.client = pd.ResilientClient(
            cache_ttl=cache_ttl,
            cache_max_entries=cache_max_entries,
            rate_limit=rate_limit,
            max_retries=max_retries,
            auto_load_proxies=auto_load_proxies,
        )
        self._session: Optional[aiohttp.ClientSession] = None
        self._server: Optional[web.Server] = None
        self._runner: Optional[web.AppRunner] = None

        # Request stats
        self._requests_total = 0
        self._requests_ok = 0
        self._requests_error = 0

    async def start(self) -> None:
        """Initialize the client session and start the aiohttp server."""
        self._session = aiohttp.ClientSession()
        await self.client.__aenter__()

        app = web.Application(middlewares=[self._logging_middleware])
        app.router.add_route("*", "/{path:.*}", self._handle_request)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.listen_port)
        await site.start()

        logger.info(
            f"Reverse proxy listening on :{self.listen_port} -> {self.target_host}"
        )

    async def stop(self) -> None:
        """Shutdown the server and client session."""
        if self._runner:
            await self._runner.cleanup()
        if self._session:
            await self._session.close()
        await self.client.__aexit__(None, None, None)
        logger.info("Reverse proxy stopped")

    @staticmethod
    async def _logging_middleware(request: web.Request, handler) -> web.StreamResponse:
        start = time.time()
        try:
            resp = await handler(request)
            return resp
        finally:
            duration = (time.time() - start) * 1000
            logger.info(
                f"{request.method} {request.path_qs} -> {resp.status} ({duration:.0f}ms)"
            )

    async def _handle_request(self, request: web.Request) -> web.StreamResponse:
        """Proxy an incoming HTTP request through ResilientClient to the target."""
        self._requests_total += 1

        # Build the target URL
        path = request.match_info.get("path", "")
        query = request.query_string
        target_url = f"{self.target_host}/{path}"
        if query:
            target_url += f"?{query}"

        # Forward headers (skip hop-by-hop headers)
        forward_headers = {}
        hop_by_hop = {
            "connection", "keep-alive", "proxy-authenticate",
            "proxy-authorization", "te", "trailers", "transfer-encoding",
            "upgrade",
        }
        for key, value in request.headers.items():
            if key.lower() not in hop_by_hop:
                forward_headers[key] = value

        # Read body
        body = await request.read()

        try:
            resp = await self.client.request(
                method=request.method,
                url=target_url,
                params=request.query,
                headers=forward_headers,
                agent_id=self.agent_id,
                rotation_mode="sticky",
            )

            self._requests_ok += 1

            # Build aiohttp response
            response = web.Response(
                status=resp.status,
                body=resp.content,
                content_type=resp.headers.get("content-type"),
            )
            # Forward response headers (skip hop-by-hop)
            hop_by_hop = {
                "connection", "keep-alive", "proxy-authenticate",
                "proxy-authorization", "te", "trailers",
                "transfer-encoding", "upgrade",
            }
            for key, value in resp.headers.items():
                if key.lower() not in hop_by_hop:
                    response.headers[key] = value
            return response

        except Exception as exc:  # noqa: BLE001
            self._requests_error += 1
            logger.error(f"Proxy error for {request.method} {target_url}: {exc}")
            return web.Response(
                status=502,
                body=b"Bad Gateway",
                content_type="text/plain",
            )

    def stats(self) -> Dict[str, Any]:
        """Return reverse proxy statistics."""
        return {
            "listen_port": self.listen_port,
            "target_host": self.target_host,
            "requests_total": self._requests_total,
            "requests_ok": self._requests_ok,
            "requests_error": self._requests_error,
        }


def load_config() -> dict:
    """Load configuration from config.json."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"config load failed ({CONFIG_FILE}): {exc}")
    return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OWL Agent Reverse Proxy — HTTP ingress for ResilientClient egress"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Listen port (default: {DEFAULT_PORT}, or config.json reverse_proxy.port)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help=f"Upstream target host (default: {DEFAULT_TARGET_HOST}, or config.json reverse_proxy.target_host)",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    config = load_config()

    rp_config = config.get("reverse_proxy", {})

    port = args.port if args.port is not None else rp_config.get("port", DEFAULT_PORT)
    target = (
        args.target
        if args.target is not None
        else rp_config.get("target_host", DEFAULT_TARGET_HOST)
    )

    proxy = ReverseProxy(
        target_host=target,
        listen_port=port,
    )

    try:
        await proxy.start()
        print(f"Reverse proxy running on http://0.0.0.0:{port} -> {target}", file=sys.stderr)
        print("Press Ctrl+C to stop", file=sys.stderr)
        # Run forever until interrupted
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await proxy.stop()


def main() -> int:
    asyncio.run(main_async())
    return 0


if __name__ == "__main__":
    sys.exit(main())
