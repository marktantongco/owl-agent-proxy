"""
Free catalog → router integration.

Wires vendored awesome-free-llm-apis catalog routes into the gateway
Router as tier-1 (free catalog) entries. Keeps Router free of catalog
knowledge to avoid circular imports.
"""

from __future__ import annotations

import logging
from typing import Optional

from free_catalog.loader import load_routes, FreeCatalogError
from router import Router

logger = logging.getLogger("owl-agent.gateway.free-catalog.integration")


def wire_catalog_routes(
    router: Router,
    enabled_providers: Optional[set[str]] = None,
    cost_per_1k_tokens: float = 0.0,
    task_types: Optional[list[str]] = None,
) -> int:
    """
    Load catalog routes and add them to the router as tier-1 (free catalog).

    Catalog routes are added to each specified task type (default: ["default"]),
    positioned before tier-2 (paid fallback) and tier-3 (local Ollama/vLLM)
    routes. Within tier 1, routes are sorted by provider then model ID for
    deterministic selection — the Router's existing route() method picks the
    first available (cheapest healthy) provider.

    Args:
        router: Router instance to extend.
        enabled_providers: Optional set of provider IDs to enable.
        cost_per_1k_tokens: Estimated cost per 1K tokens for free-tier models.
        task_types: Task types to extend with catalog routes. Defaults to ["default"].

    Returns:
        Number of catalog routes added.

    Raises:
        FreeCatalogError: If the catalog cannot be loaded.
    """
    if task_types is None:
        task_types = ["default"]

    routes = load_routes(
        enabled_providers=enabled_providers,
        cost_per_1k_tokens=cost_per_1k_tokens,
    )

    added = 0
    for task_type in task_types:
        for route in routes:
            router.add_route(task_type, route)
            added += 1

    logger.info(
        f"Wired {added} catalog routes into router across {len(task_types)} "
        f"task type(s): {task_types}"
    )
    return added


def get_catalog_stats() -> dict:
    """Return statistics about the loaded free catalog."""
    from free_catalog.loader import load_catalog, FreeCatalogError

    try:
        providers = load_catalog()
    except FreeCatalogError as exc:
        return {"error": str(exc)}

    total_models = sum(len(p.models) for p in providers)
    enabled_providers = [p for p in providers if p.enabled]
    enabled_models = sum(len(p.models) for p in enabled_providers)

    return {
        "total_providers": len(providers),
        "enabled_providers": len(enabled_providers),
        "disabled_providers": len(providers) - len(enabled_providers),
        "total_models": total_models,
        "enabled_models": enabled_models,
        "provider_ids": [p.id for p in providers],
        "enabled_provider_ids": [p.id for p in enabled_providers],
    }
