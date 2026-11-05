"""
Tests for the free catalog integration.

Tests catalog loading, route conversion, rate limit parsing, paid vendor
filtering, and router integration. All tests are offline-safe — no live
provider calls.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure the gateway directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gateway"))

from free_catalog.loader import (
    FreeCatalogError,
    _is_paid_vendor_model,
    _parse_context_window,
    _parse_rate_limit,
    _parse_rpd,
    load_catalog,
    load_routes,
)
from free_catalog.router_integration import get_catalog_stats, wire_catalog_routes
from router import Router


# ── Catalog loading tests ──


class TestCatalogLoading:
    """Test loading the vendored free catalog."""

    def test_catalog_loads_without_error(self):
        """The vendored catalog JSON loads and validates correctly."""
        providers = load_catalog()
        assert len(providers) > 0
        assert len(providers) == 15  # All 15 providers from awesome-free-llm-apis

    def test_catalog_has_provider_structure(self):
        """Each provider has required fields."""
        providers = load_catalog()
        for p in providers:
            assert p.id
            assert p.name
            assert p.base_url
            assert p.category in ("provider_api", "inference_provider")
            assert isinstance(p.enabled, bool)
            assert isinstance(p.models, list)

    def test_catalog_file_missing_raises_error(self):
        """Missing catalog file raises FreeCatalogError."""
        from pathlib import Path
        try:
            load_catalog(Path("/nonexistent/providers.json"))
            assert False, "Should have raised FreeCatalogError"
        except FreeCatalogError:
            pass

    def test_enabled_providers_count(self):
        """Default enabled providers exclude verification-requiring ones."""
        providers = load_catalog()
        enabled = [p for p in providers if p.enabled]
        disabled = [p for p in providers if not p.enabled]

        # 11 enabled by default, 4 disabled (z-ai, gonka-broker, modelscope, siliconflow)
        assert len(enabled) == 11
        assert len(disabled) == 4

        disabled_ids = {p.id for p in disabled}
        assert disabled_ids == {"z-ai", "gonka-broker", "modelscope", "siliconflow"}

    def test_provider_api_key_env_mapping(self):
        """Each provider maps to the correct API key env var (or None for anonymous)."""
        providers = load_catalog()
        env_map = {p.id: p.api_key_env for p in providers}

        assert env_map["groq"] == "GROQ_API_KEY"
        assert env_map["openrouter"] == "OPENROUTER_API_KEY"
        assert env_map["mistral"] == "MISTRAL_API_KEY"
        assert env_map["gemini"] == "GEMINI_API_KEY"
        assert env_map["ovhcloud"] is None  # Anonymous tier
        assert env_map["kilo-code"] is None  # No key required

    def test_base_urls_are_valid(self):
        """All providers have valid base URLs."""
        providers = load_catalog()
        for p in providers:
            assert p.base_url.startswith("http://") or p.base_url.startswith("https://")


# ── Route conversion tests ──


class TestRouteConversion:
    """Test converting catalog entries to ModelRoute objects."""

    def test_routes_have_tier_2(self):
        """All catalog routes are tier 2 (free cloud)."""
        routes = load_routes()
        for r in routes:
            assert r.tier == 2

    def test_routes_have_provider_and_model(self):
        """Each route has provider and model_id set."""
        routes = load_routes()
        assert len(routes) > 0
        for r in routes:
            assert r.provider
            assert r.model_id
            assert r.api_base
            assert r.enabled

    def test_routes_sorted_by_provider_then_model(self):
        """Routes are sorted deterministically by provider then model ID."""
        routes = load_routes()
        keys = [(r.provider, r.model_id) for r in routes]
        assert keys == sorted(keys)

    def test_paid_vendor_models_filtered(self):
        """Paid vendor model patterns are filtered from routes."""
        routes = load_routes()
        route_ids = [r.model_id for r in routes]
        # No claude-*, gpt-5.*, gemini-*, grok-*, glm-5.*, minimax-* in free routes
        for rid in route_ids:
            assert not any(
                rid.startswith(p) for p in ("claude-", "gpt-5.", "gemini-", "grok-", "glm-5.", "minimax-")
            ), f"Paid vendor model {rid} should be filtered"

    def test_openai_compatible_url_used(self):
        """Providers with openai_compatible_url use it as api_base."""
        routes = load_routes()
        cohere_routes = [r for r in routes if r.provider == "cohere"]
        if cohere_routes:
            assert cohere_routes[0].api_base == "https://api.cohere.ai/compatibility/v1"


# ── Rate limit parsing tests ──


class TestRateLimitParsing:
    """Test rate limit string parsing."""

    def test_parse_rpm(self):
        """RPM values are parsed correctly."""
        assert _parse_rate_limit("15 RPM") == 15
        assert _parse_rate_limit("20 RPM") == 20
        assert _parse_rate_limit("30 RPM, 1,000 RPD") == 30
        assert _parse_rate_limit("40 RPM, 10,000 RPD") == 40
        assert _parse_rate_limit("60 RPM, 250 req/hr (free token)") == 60

    def test_parse_rpm_returns_none_for_unparseable(self):
        """Unparseable rate limits return None."""
        assert _parse_rate_limit("-") is None
        assert _parse_rate_limit("Shared w/ context") is None
        assert _parse_rate_limit("Varies") is None
        assert _parse_rate_limit("1 concurrent request") is None
        assert _parse_rate_limit("") is None

    def test_parse_rpd(self):
        """RPD values are parsed correctly."""
        assert _parse_rpd("30 RPM, 1,000 RPD") == 1000
        assert _parse_rpd("40 RPM, 10,000 RPD") == 10000
        assert _parse_rpd("2,000 RPD total; <=500 RPD/model (dynamic)") == 2000
        assert _parse_rpd("-") is None


# ── Context window parsing tests ──


class TestContextWindowParsing:
    """Test context window string parsing."""

    def test_parse_k_suffix(self):
        """K suffix is parsed as thousands."""
        assert _parse_context_window("128K") == 128000
        assert _parse_context_window("256K") == 256000
        assert _parse_context_window("32K") == 32000

    def test_parse_m_suffix(self):
        """M suffix is parsed as millions."""
        assert _parse_context_window("1M") == 1_000_000

    def test_parse_unparseable_returns_default(self):
        """Unparseable values return default 4096."""
        assert _parse_context_window("-") == 4096
        assert _parse_context_window("Varies") == 4096
        assert _parse_context_window("") == 4096


# ── Paid vendor filtering tests ──


class TestPaidVendorFiltering:
    """Test paid vendor model filtering."""

    def test_filters_paid_vendor_prefixes(self):
        """Models matching paid vendor prefixes are filtered."""
        assert _is_paid_vendor_model("claude-3-5-sonnet-20241022")
        assert _is_paid_vendor_model("gpt-5.0")
        assert _is_paid_vendor_model("gemini-1.5-pro")
        assert _is_paid_vendor_model("grok-2")
        assert _is_paid_vendor_model("glm-5.3-flash")
        assert _is_paid_vendor_model("minimax-01")

    def test_allows_free_models(self):
        """Free models are not filtered."""
        assert not _is_paid_vendor_model("qwen2.5:14b")
        assert not _is_paid_vendor_model("gpt-4o-mini")
        assert not _is_paid_vendor_model("llama-3.1-8b")
        assert not _is_paid_vendor_model("glm-4.7-flash")  # glm-4.x is free, glm-5.x is paid


# ── Router integration tests ──


class TestRouterIntegration:
    """Test wiring catalog routes into the Router."""

    def test_wire_catalog_routes_adds_tier_2_routes(self):
        """wire_catalog_routes adds catalog routes as tier 2 to the router."""
        router = Router()
        initial_count = router.stats()["total_routes"]

        added = wire_catalog_routes(router)

        assert added > 0
        stats = router.stats()
        assert stats["total_routes"] == initial_count + added

        # All catalog routes should be tier 2
        for routes in router.routes.values():
            for r in routes:
                if r.tier == 2 and r.provider != "openai":
                    assert r.provider in [
                        "aion-labs", "cohere", "gemini", "mistral",
                        "cloudflare-workers-ai", "groq", "kilo-code",
                        "llm7", "nvidia-nim", "openrouter", "ovhcloud"
                    ]

    def test_get_catalog_stats(self):
        """get_catalog_stats returns provider and model counts."""
        stats = get_catalog_stats()
        assert "total_providers" in stats
        assert "enabled_providers" in stats
        assert "total_models" in stats
        assert "enabled_models" in stats
        assert stats["total_providers"] == 15
        assert stats["enabled_providers"] == 11

    def test_route_selection_uses_catalog_providers(self):
        """Router.route() can select catalog providers from tier 2."""
        router = Router()
        wire_catalog_routes(router)

        # With all circuits available and budget, should pick tier 1 (local) first
        decision = router.route(
            task_type="default",
            client_budget_tokens_remaining=100000,
            client_cost_remaining_usd=10.0,
            circuit_breaker_available={
                "ollama": True,
                "openrouter": True,
                "groq": True,
                "cohere": True,
                "gemini": True,
                "mistral": True,
            },
        )
        assert decision is not None
        # Tier 1 (local Ollama) should be selected first
        assert decision.provider == "ollama"

    def test_route_falls_back_to_catalog_when_local_unavailable(self):
        """When local circuit is open, router falls back to tier 2 (catalog or openai)."""
        router = Router()
        wire_catalog_routes(router)

        decision = router.route(
            task_type="default",
            client_budget_tokens_remaining=100000,
            client_cost_remaining_usd=10.0,
            circuit_breaker_available={
                "ollama": False,  # Local circuit open
                "openrouter": True,
                "groq": True,
                "openai": True,
            },
        )
        assert decision is not None
        assert decision.tier == 2
        # Any tier-2 provider is acceptable (openai hardcoded or catalog)
        assert decision.provider in ("openai", "openrouter", "groq")


# ── App integration test ──


class TestAppCatalogIntegration:
    """Test that the gateway app can import and wire the catalog."""

    def test_app_imports_with_catalog(self):
        """The gateway app imports cleanly with catalog integration."""
        try:
            from app import app, router
        except ModuleNotFoundError as exc:
            if "fastapi" in str(exc):
                import pytest
                pytest.skip("fastapi not installed — app import test skipped")
            raise
        assert app is not None
        assert router is not None
