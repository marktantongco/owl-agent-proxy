#!/usr/bin/env python3
"""OWL Agent Proxy CLI wrapper.

Subcommands:
    stats [--json]       Print pool/session/source health as JSON or text
    fetch <url> [--json] Fetch a URL through the proxy pool and print result
    harvest [--seconds N] Force one upstream harvest sweep
    mcp-selftest         Run MCP server initialize/tools/resources/ping selftest
    verify [--no-live]   Run the installation verification suite
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure the package directory (this file's parent) is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _build_stats() -> dict:
    import proxy_defense as pd

    client = pd.ResilientClient(auto_load_proxies=False, cache_file=None)
    rotator = client.rotator
    total = len(rotator.proxies)
    healthy = sum(1 for p in rotator.proxies if p.healthy)
    return {
        "version": "7.1",
        "proxies_total": total,
        "proxies_healthy": healthy,
        "session_affinity": len(getattr(rotator, "_sessions", {})),
        "source_health": getattr(rotator, "source_health", lambda: {})(),
        "upstream_harvester": bool(getattr(client, "use_upstream_harvester", False)),
        "protocols_available": ["http", "https"],
    }


def cmd_stats(args: argparse.Namespace) -> int:
    stats = _build_stats()
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(f"proxies: {stats['proxies_healthy']}/{stats['proxies_total']} healthy")
        print(f"session_affinity: {stats['session_affinity']}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    import proxy_defense as pd

    async def run() -> None:
        client = pd.ResilientClient(auto_load_proxies=False, cache_file=None)
        async with client:
            try:
                text = await client.get(args.url)
                if args.json:
                    print(json.dumps({"status": 200, "body": text[:500], "protocol": "http"}, indent=2))
                else:
                    print(text[:500])
            except Exception as exc:  # noqa: BLE001
                if args.json:
                    print(json.dumps({"status": 0, "error": str(exc)}, indent=2))
                else:
                    print(f"error: {exc}", file=sys.stderr)
                sys.exit(1)

    asyncio.run(run())
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    import proxy_defense as pd

    async def run() -> None:
        client = pd.ResilientClient(auto_load_proxies=False, cache_file=None)
        count = await client.harvest(max_per_source=50)
        print(f"harvested {count} proxies")

    asyncio.run(run())
    return 0


def cmd_mcp_selftest(args: argparse.Namespace) -> int:
    import subprocess

    env = dict(os.environ)
    env["OWL_MCP_HARVEST"] = "0"
    env["OWL_MCP_WARMUP_SEC"] = "0"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "mcp_proxy_server.py"), "--selftest"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def cmd_verify(args: argparse.Namespace) -> int:
    import subprocess

    env = dict(os.environ)
    cmd = [sys.executable, str(Path(__file__).parent / "scripts" / "verify-install.py")]
    if args.no_live:
        cmd.append("--no-live")
    result = subprocess.run(cmd, env=env)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="OWL Agent Proxy CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stats = sub.add_parser("stats", help="Print pool/session health")
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=cmd_stats)

    p_fetch = sub.add_parser("fetch", help="Fetch a URL through the proxy")
    p_fetch.add_argument("url")
    p_fetch.add_argument("--json", action="store_true")
    p_fetch.set_defaults(func=cmd_fetch)

    p_harvest = sub.add_parser("harvest", help="Force an upstream harvest sweep")
    p_harvest.add_argument("--seconds", type=int, default=20)
    p_harvest.set_defaults(func=cmd_harvest)

    p_mcp = sub.add_parser("mcp-selftest", help="Run MCP selftest")
    p_mcp.set_defaults(func=cmd_mcp_selftest)

    p_verify = sub.add_parser("verify", help="Run installation verification")
    p_verify.add_argument("--no-live", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
