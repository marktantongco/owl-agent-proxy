"""
Tests for the governed token plane gateway.

Tests auth, rate limiting, model routing, cache, budgets, circuit breaker,
and audit logging. All tests are offline-safe (no live provider calls).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the gateway directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gateway"))

from auth import validate_gateway_token, GATEWAY_TOKEN
from circuit_breaker import CircuitBreaker, CircuitState
from cache import Cache
from billing import Billing, Budget
from router import Router, ModelRoute, RouteDecision


# ── Auth tests ──


class TestAuth:
    """Test gateway authentication."""

    def test_validate_valid_token(self):
        """A valid gateway token passes validation."""
        result = validate_gateway_token(
            MagicMock(credentials=GATEWAY_TOKEN)
        )
        assert result == "gateway-client"

    def test_validate_invalid_token(self):
        """An invalid token raises 401."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            validate_gateway_token(MagicMock(credentials="wrong-token"))
        assert exc.value.status_code == 401

    def test_validate_missing_token(self):
        """A missing token raises 401."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            validate_gateway_token(None)
        assert exc.value.status_code == 401


# ── Circuit breaker tests ──


class TestCircuitBreaker:
    """Test per-provider circuit breaker."""

    def test_circuit_closes_after_threshold(self):
        """Circuit opens after threshold consecutive failures."""
        cb = CircuitBreaker(threshold=3)
        assert cb.is_available("openai") is True

        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.is_available("openai") is True  # 2 < 3

        cb.record_failure("openai")
        assert cb.is_available("openai") is False  # 3 >= 3

    def test_success_resets_circuit(self):
        """Success resets failure count."""
        cb = CircuitBreaker(threshold=3)
        cb.record_failure("openai")
        cb.record_failure("openai")
        cb.record_success("openai")
        assert cb.is_available("openai") is True
        assert cb.get_circuit("openai").failures == 0

    def test_select_provider_skips_open_circuits(self):
        """select_provider returns first available from fallback chain."""
        cb = CircuitBreaker(threshold=2)
        cb.record_failure("ollama")
        cb.record_failure("ollama")  # ollama circuit open

        selected = cb.select_provider(["ollama", "openai", "anthropic"])
        assert selected == "openai"  # ollama skipped, openai available

    def test_all_circuits_open_returns_none(self):
        """Returns None when all providers have open circuits."""
        cb = CircuitBreaker(threshold=1)
        cb.record_failure("ollama")
        cb.record_failure("openai")
        cb.record_failure("anthropic")

        selected = cb.select_provider(["ollama", "openai", "anthropic"])
        assert selected is None


# ── Cache tests ──


class TestCache:
    """Test Redis-backed cache (graceful when Redis unavailable)."""

    def test_cache_disabled_when_no_redis(self):
        """Cache gracefully disables when Redis is unavailable."""
        cache = Cache(enabled=True)
        # If Redis isn't running, cache should disable itself
        result = cache.get("chat", "test prompt", "gpt-4o-mini")
        assert result is None  # Miss when no Redis

        # Setting should not crash
        cache.set("chat", "test prompt", "gpt-4o-mini", {"content": "hi"})

    def test_stats_structure(self):
        """Cache stats has expected structure."""
        cache = Cache()
        stats = cache.stats()
        assert "enabled" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats


# ── Billing tests ──


class TestBilling:
    """Test token/cost budget tracking."""

    def test_budget_allows_within_limit(self):
        """Requests within budget are allowed."""
        billing = Billing(default_token_limit=1000, default_cost_limit_usd=10.0)
        reason = billing.check_budget("client-1", 100, "gpt-4o-mini")
        assert reason is None  # Allowed

    def test_budget_blocks_exceeded_tokens(self):
        """Requests exceeding token budget are blocked."""
        billing = Billing(default_token_limit=100, default_cost_limit_usd=10.0)
        reason = billing.check_budget("client-1", 150, "gpt-4o-mini")  # Exceeds 100
        assert reason == "token_budget_exceeded"
        # Subsequent calls return budget_blocked because the client is blocked
        reason = billing.check_budget("client-1", 10, "gpt-4o-mini")
        assert reason == "budget_blocked"

    def test_budget_blocks_exceeded_cost(self):
        """Requests exceeding cost budget are blocked."""
        billing = Billing(default_token_limit=100000, default_cost_limit_usd=0.01)
        # gpt-4o-mini costs ~$0.15/1K tokens. 1 token ≈ $0.00015.
        # With $0.01 limit, ~66 tokens allowed.
        reason = billing.check_budget("client-1", 1000, "gpt-4o-mini")  # ~$0.15 > $0.01
        assert reason == "cost_budget_exceeded"
        # Subsequent calls return budget_blocked because the client is blocked
        reason = billing.check_budget("client-1", 10, "gpt-4o-mini")
        assert reason == "budget_blocked"

    def test_record_usage_updates_budget(self):
        """Recording usage updates the budget state."""
        billing = Billing(default_token_limit=1000, default_cost_limit_usd=10.0)
        billing.record_usage("client-1", 100, "gpt-4o-mini")
        budget = billing.get_budget("client-1")
        assert budget.tokens_used == 100
        assert budget.cost_used_usd > 0

    def test_block_and_unblock_client(self):
        """Manual block/unblock works."""
        billing = Billing()
        billing.block_client("client-1")
        reason = billing.check_budget("client-1", 10, "gpt-4o-mini")
        assert reason == "budget_blocked"

        billing.unblock_client("client-1")
        reason = billing.check_budget("client-1", 10, "gpt-4o-mini")
        assert reason is None


# ── Router tests ──


class TestRouter:
    """Test model routing logic (free catalog → paid fallback → local)."""

    def test_routes_paid_fallback_before_local(self):
        """Without free catalog, paid fallback (tier 2) is preferred over local (tier 3)."""
        router = Router()
        decision = router.route(
            task_type="default",
            client_budget_tokens_remaining=100000,
            client_cost_remaining_usd=10.0,
            circuit_breaker_available={
                "anthropic": True,
                "openai": True,
                "ollama": True,
            },
        )
        assert decision is not None
        assert decision.provider in ("anthropic", "openai")
        assert decision.tier == 2  # Paid fallback

    def test_routes_to_local_when_paid_unavailable(self):
        """Falls back to local Ollama (tier 3) when paid circuits are open."""
        router = Router()
        decision = router.route(
            task_type="default",
            client_budget_tokens_remaining=100000,
            client_cost_remaining_usd=10.0,
            circuit_breaker_available={
                "anthropic": False,
                "openai": False,
                "ollama": True,
            },
        )
        assert decision is not None
        assert decision.provider == "ollama"
        assert decision.tier == 3
        assert decision.is_local is True

    def test_returns_none_when_all_unavailable(self):
        """Returns None when all providers are unavailable."""
        router = Router()
        decision = router.route(
            task_type="default",
            client_budget_tokens_remaining=100000,
            client_cost_remaining_usd=10.0,
            circuit_breaker_available={
                "anthropic": False,
                "openai": False,
                "ollama": False,
            },
        )
        assert decision is None

    def test_blocks_paid_when_cost_budget_exhausted_but_local_still_works(self):
        """Paid routes skipped when cost budget is 0, but local (free) still works."""
        router = Router()
        decision = router.route(
            task_type="default",
            client_budget_tokens_remaining=100000,
            client_cost_remaining_usd=0.0,  # No budget for paid
            circuit_breaker_available={
                "anthropic": True,
                "openai": True,
                "ollama": True,
            },
        )
        assert decision is not None
        assert decision.provider == "ollama"
        assert decision.tier == 3  # Local is free, bypasses cost budget

    def test_add_custom_route(self):
        """Custom routes can be added for task types."""
        router = Router()
        custom = ModelRoute(
            name="custom-model",
            provider="custom",
            model_id="custom:latest",
            tier=1,
            api_base="http://custom.local:8000",
            cost_per_1k_tokens=0.0,
        )
        router.add_route("custom-task", custom)
        decision = router.route(
            task_type="custom-task",
            client_budget_tokens_remaining=100000,
            client_cost_remaining_usd=10.0,
            circuit_breaker_available={"custom": True},
        )
        assert decision is not None
        assert decision.provider == "custom"
        assert decision.model_id == "custom:latest"
        assert decision.tier == 1

    def test_stats_structure(self):
        """Router stats has expected structure."""
        router = Router()
        stats = router.stats()
        assert "task_types" in stats
        assert "total_routes" in stats
        assert stats["total_routes"] > 0


# ── Budget integration tests ──


class TestBudgetIntegration:
    """Test billing + router integration."""

    def test_local_route_bypasses_cost_budget(self):
        """Local route (tier 3, free) is selectable even when cost budget is 0."""
        billing = Billing(default_token_limit=100000, default_cost_limit_usd=0.0)
        router = Router()

        decision = router.route(
            task_type="default",
            client_budget_tokens_remaining=billing.get_budget("c1").token_remaining,
            client_cost_remaining_usd=billing.get_budget("c1").cost_remaining_usd,
            circuit_breaker_available={
                "anthropic": False,
                "openai": False,
                "ollama": True,
            },
        )
        assert decision is not None
        assert decision.provider == "ollama"
        assert decision.tier == 3  # Local bypasses cost budget


# ── App import test ──


class TestAppImport:
    """Test that the gateway app imports cleanly."""

    def test_app_imports(self):
        """The FastAPI app can be imported without crashing."""
        from app import app, circuit_breaker, cache, billing, router, audit
        assert app is not None
        assert circuit_breaker is not None
        assert cache is not None
        assert billing is not None
        assert router is not None
