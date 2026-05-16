#!/usr/bin/env python3
"""
🦉 OWL-AGENT Proxy Defense Stack — Usage Examples
"""

import asyncio
from proxy_defense import ResilientClient


async def example_basic():
    """Basic GET request using http/1.1 (default)"""
    async with ResilientClient() as client:
        resp = await client.request("GET", "https://httpbin.org/get")
        print(f"Status: {resp.status}, Protocol: {resp.protocol}")


async def example_with_protocol():
    """Escalate to JA3 for anti-bot protection"""
    async with ResilientClient() as client:
        resp = await client.request("GET", "https://example.com", protocol="ja3")
        print(f"Status: {resp.status}, Protocol: {resp.protocol}")


async def example_with_headers():
    """Custom headers with rate limiting"""
    async with ResilientClient(rate_limit=2.0) as client:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = await client.request("GET", "https://httpbin.org/headers", headers=headers)
        print(f"Status: {resp.status}")


async def example_stats():
    """Get defense stack statistics"""
    async with ResilientClient() as client:
        stats = await client.get_stats()
        print(f"Proxies: {stats['proxies_healthy']}/{stats['proxies_total']} healthy")
        print(f"Protocols: {stats['protocols_available']}")
        print(f"Cache entries: {stats['cache_memory_size']}")


async def main():
    print("=== Example 1: Basic Request ===")
    await example_basic()

    print("\n=== Example 2: Protocol Escalation ===")
    await example_with_protocol()

    print("\n=== Example 3: Custom Headers ===")
    await example_with_headers()

    print("\n=== Example 4: Stats ===")
    await example_stats()


if __name__ == "__main__":
    asyncio.run(main())
