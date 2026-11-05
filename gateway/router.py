"""
Model routing logic: local → free-tier cloud → paid fallback.

Routes requests based on:
1. Task type (cheap/local for summarization, classification, extraction;
   cloud for difficult reasoning, code generation)
2. Client budget (local first if budget is tight)
3. Provider health (circuit breaker state)
4. Fallback chain when primary provider fails
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("owl-agent.gateway.router")


@dataclass
class ModelRoute:
    """A single model route definition."""

    name: str
    provider: str  # "ollama", "vllm", "openai", "anthropic", etc.
    model_id: str
    tier: int  # 1 = local (cheapest), 2 = free cloud, 3 = paid fallback
    api_base: Optional[str] = None
    api_key_env: Optional[str] = None  # Env var name — key lives in gateway env
    cost_per_1k_tokens: float = 0.0
    enabled: bool = True
    context_window: int = 4096

    @property
    def is_local(self) -> bool:
        return self.provider in ("ollama", "vllm")


@dataclass
class RouteDecision:
    """Result of routing a request."""

    provider: str
    model_id: str
    api_base: Optional[str]
    api_key: Optional[str]  # Resolved from gateway env — never sent to client
    tier: int
    reason: str

    @property
    def is_local(self) -> bool:
        return self.provider in ("ollama", "vllm")


class Router:
    """Routes model requests through a tiered fallback chain."""

    def __init__(self) -> None:
        # Default route table: local bulk engine first, then cloud burst, then paid
        self.routes: Dict[str, List[ModelRoute]] = {}
        self._build_default_routes()

    def _build_default_routes(self) -> None:
        """Build the default route table."""
        self.routes["default"] = [
            # Tier 1 — Local bulk engine (free, hardware cost only)
            ModelRoute(
                name="ollama-qwen2.5-14b",
                provider="ollama",
                model_id="qwen2.5:14b",
                tier=1,
                api_base="http://127.0.0.1:11434",
                cost_per_1k_tokens=0.0,
                context_window=32768,
            ),
            # Tier 2 — Free-tier cloud burst
            ModelRoute(
                name="gpt-4o-mini-free",
                provider="openai",
                model_id="gpt-4o-mini",
                tier=2,
                api_base="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                cost_per_1k_tokens=0.15,
                context_window=128000,
            ),
            # Tier 3 — Paid fallback
            ModelRoute(
                name="claude-3-5-haiku-paid",
                provider="anthropic",
                model_id="claude-3-5-haiku-20241022",
                tier=3,
                api_base="https://api.anthropic.com",
                api_key_env="ANTHROPIC_API_KEY",
                cost_per_1k_tokens=0.80,
                context_window=200000,
            ),
        ]

        self.routes["reasoning"] = [
            ModelRoute(
                name="ollama-qwen2.5-14b",
                provider="ollama",
                model_id="qwen2.5:14b",
                tier=1,
                api_base="http://127.0.0.1:11434",
                cost_per_1k_tokens=0.0,
                context_window=32768,
            ),
            ModelRoute(
                name="gpt-4o-mini-free",
                provider="openai",
                model_id="gpt-4o-mini",
                tier=2,
                api_base="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                cost_per_1k_tokens=0.15,
                context_window=128000,
            ),
            ModelRoute(
                name="claude-3-5-sonnet-paid",
                provider="anthropic",
                model_id="claude-3-5-sonnet-20241022",
                tier=3,
                api_base="https://api.anthropic.com",
                api_key_env="ANTHROPIC_API_KEY",
                cost_per_1k_tokens=3.00,
                context_window=200000,
            ),
        ]

    def add_route(self, task_type: str, route: ModelRoute) -> None:
        """Add a route for a task type."""
        if task_type not in self.routes:
            self.routes[task_type] = []
        self.routes[task_type].append(route)
        # Sort by tier (cheapest first)
        self.routes[task_type].sort(key=lambda r: r.tier)

    def resolve_api_key(self, route: ModelRoute) -> Optional[str]:
        """Resolve the API key from the gateway environment.

        The key is read from the gateway's env/secrets manager and is
        NEVER exposed to the client.
        """
        if not route.api_key_env:
            return None
        return os.environ.get(route.api_key_env)

    def route(
        self,
        task_type: str = "default",
        client_budget_tokens_remaining: int = 0,
        client_cost_remaining_usd: float = 0.0,
        circuit_breaker_available: Optional[Dict[str, bool]] = None,
    ) -> Optional[RouteDecision]:
        """
        Select the best provider/model for a request.

        Priority:
        1. Local models (tier 1) — always preferred if available
        2. Free cloud (tier 2) — if local unavailable or budget constrained
        3. Paid fallback (tier 3) — only when necessary and budget allows

        Args:
            task_type: Type of task (affects route table selection)
            client_budget_tokens_remaining: Client's remaining token budget
            client_cost_remaining_usd: Client's remaining cost budget
            circuit_breaker_available: Dict of provider -> is_available

        Returns:
            RouteDecision or None if no route is available.
        """
        circuit_breaker_available = circuit_breaker_available or {}
        routes = self.routes.get(task_type, self.routes["default"])

        for route in routes:
            if not route.enabled:
                continue

            # Check circuit breaker
            if not circuit_breaker_available.get(route.provider, True):
                logger.info(
                    f"Skipping {route.provider}/{route.model_id}: circuit open"
                )
                continue

            # Check budget constraints for non-local routes
            if not route.is_local:
                if client_cost_remaining_usd <= 0:
                    logger.info(
                        f"Skipping {route.provider}/{route.model_id}: "
                        f"client cost budget exhausted"
                    )
                    continue

            # Select this route
            api_key = self.resolve_api_key(route)
            reason = self._selection_reason(route, client_budget_tokens_remaining)

            return RouteDecision(
                provider=route.provider,
                model_id=route.model_id,
                api_base=route.api_base,
                api_key=api_key,  # Gateway-internal only
                tier=route.tier,
                reason=reason,
            )

        # No route available
        logger.error(f"No available route for task_type={task_type}")
        return None

    def _selection_reason(
        self,
        route: ModelRoute,
        client_budget_tokens_remaining: int,
    ) -> str:
        """Human-readable reason for route selection."""
        if route.is_local:
            return f"Local model {route.model_id} — free (hardware cost only)"
        if route.tier == 2:
            return (
                f"Free-tier cloud {route.model_id} — "
                f"~${route.cost_per_1k_tokens}/1K tokens"
            )
        return (
            f"Paid fallback {route.model_id} — "
            f"~${route.cost_per_1k_tokens}/1K tokens"
        )

    def stats(self) -> dict:
        """Return router statistics."""
        return {
            "task_types": list(self.routes.keys()),
            "total_routes": sum(len(r) for r in self.routes.values()),
            "local_routes": sum(
                1 for r in self.routes.get("default", []) if r.is_local
            ),
        }



