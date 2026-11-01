#!/usr/bin/env python3
"""Smoke-test the stealth rung end to end, on a machine with normal networking.

This exists because the CI environment cannot verify a real browser launch: the
sealed Firefox is downloaded from a host that sandboxed networks block. Everything
up to the launch is covered by tests/test_stealth.py; this script closes the last
gap by actually starting the engine.

    python scripts/smoke-stealth.py                 # example.com, no proxy
    python scripts/smoke-stealth.py --url https://… # a target you may access
    python scripts/smoke-stealth.py --timezone Asia/Manila --no-proxy-check

It downloads ~260 MB on first run (~550 MB unpacked) and starts a real browser.
Exit codes: 0 verified, 1 failed, 2 not installed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fail(message: str, code: int = 1) -> int:
    print(f"  FAIL  {message}")
    return code


async def run(url: str, timezone: str, use_pool: bool) -> int:
    import proxy_defense as pd

    # 1. library present?
    print(f"  ..    invisible-playwright installed: {pd.STEALTH_INSTALLED}")
    if not pd.STEALTH_INSTALLED:
        return _fail(
            "not installed — pip install invisible-playwright (Python >= 3.11)",
            code=2,
        )

    # 2. binary present? Fetch is a separate step and is the usual thing missed.
    try:
        from invisible_playwright import ensure_binary
    except ImportError as exc:  # pragma: no cover - only on a broken install
        return _fail(f"cannot import invisible_playwright: {exc}", code=2)

    print("  ..    resolving the sealed Firefox (downloads ~260 MB on first run)")
    try:
        binary = ensure_binary(status=lambda phase: print(f"          {phase}"))
    except Exception as exc:
        return _fail(f"browser fetch failed: {type(exc).__name__}: {exc}")
    print(f"  ok    engine: {binary}")

    # 3. drive it through the stack's own rung, not the library directly.
    client = pd.ResilientClient(auto_load_proxies=not use_pool)
    async with client:
        if use_pool:
            started = await client.rotator.start_upstream()
            print(f"  ..    pool harvesting started: {started}")
        try:
            response = await client._request_stealth(
                url, None, timezone=timezone, timeout=60)
        except Exception as exc:
            return _fail(f"launch/navigation failed: {type(exc).__name__}: {exc}")

    body = response.content.decode("utf-8", "replace")
    print(f"  ok    protocol={response.protocol} bytes={len(body)}")

    # 4. prove a real engine produced it, not an empty shell.
    if len(body) < 200:
        return _fail(f"page body suspiciously small ({len(body)} bytes)")
    if "<html" not in body.lower():
        return _fail("response does not look like a rendered document")

    print("\n  PASS  stealth rung verified end to end on this machine\n")
    print("  Note: this proves the engine launches and returns a document.")
    print("  It says nothing about any particular target's detection behaviour,")
    print("  and nothing about whether accessing that target is permitted.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://example.com",
                        help="target (default: example.com — a page that permits automated access)")
    parser.add_argument("--timezone", default="",
                        help="pin the timezone to skip egress-IP discovery (recommended)")
    parser.add_argument("--no-proxy-check", action="store_true",
                        help="skip starting the upstream pool")
    args = parser.parse_args()

    print("\n🦉 stealth rung smoke test\n")
    return asyncio.run(run(args.url, args.timezone, not args.no_proxy_check))


if __name__ == "__main__":
    sys.exit(main())
