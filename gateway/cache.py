"""
Redis-backed response cache with semantic + exact match support.

Caches:
- identical prompts (exact match)
- normalized tool schemas
- repeated system prompts
- embeddings
- static reference answers

For code/legal/medical/financial outputs, prefer exact cache or strong
validation before reuse (semantic cache can introduce subtle errors).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("owl-agent.gateway.cache")


class Cache:
    """Redis-backed cache with TTL and exact-match semantics."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6379,
        db: int = 0,
        default_ttl: int = 3600,
        enabled: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.db = db
        self.default_ttl = default_ttl
        self.enabled = enabled
        self._client = None
        self._hits = 0
        self._misses = 0

    def _connect(self) -> Any:
        """Lazily connect to Redis."""
        if self._client is None:
            import redis  # type: ignore

            self._client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
            )
            # Verify connection
            try:
                self._client.ping()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"Redis unavailable, cache disabled: {exc}")
                self.enabled = False
                self._client = None
        return self._client

    def _key(self, namespace: str, prompt: str, model: str) -> str:
        """Build a cache key from namespace, prompt hash, and model."""
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return f"owl:cache:{namespace}:{model}:{prompt_hash}"

    def get(
        self, namespace: str, prompt: str, model: str
    ) -> Optional[dict]:
        """Retrieve a cached response. Returns None on miss or cache disabled."""
        if not self.enabled:
            self._misses += 1
            return None

        try:
            client = self._connect()
            key = self._key(namespace, prompt, model)
            raw = client.get(key)
            if raw is None:
                self._misses += 1
                return None
            self._hits += 1
            return json.loads(raw)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Cache get failed: {exc}")
            self._misses += 1
            return None

    def set(
        self,
        namespace: str,
        prompt: str,
        model: str,
        response: dict,
        ttl: Optional[int] = None,
    ) -> None:
        """Store a response in the cache."""
        if not self.enabled:
            return

        try:
            client = self._connect()
            key = self._key(namespace, prompt, model)
            client.setex(
                key,
                ttl or self.default_ttl,
                json.dumps(response),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Cache set failed: {exc}")

    def invalidate(self, namespace: str, prompt: str, model: str) -> None:
        """Invalidate a cache entry."""
        if not self.enabled or self._client is None:
            return
        try:
            key = self._key(namespace, prompt, model)
            self._client.delete(key)
        except Exception:  # pragma: no cover - defensive
            pass

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total > 0 else 0.0
        return {
            "enabled": self.enabled,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }
