"""
Free catalog loader.

Loads the vendored awesome-free-llm-apis catalog from providers.json,
validates its structure, and converts provider+model entries into
gateway.router.ModelRoute objects for tier-2 (free cloud) routing.

All provider data is vendored locally — no runtime network dependency,
suitable for bare-metal laptop deployment.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from router import ModelRoute

logger = logging.getLogger("owl-agent.gateway.free-catalog")

# Providers that require special verification (phone, real-name, mainland China docs)
# and are disabled by default. Operator must opt in explicitly.
PROVIDERS_DISABLED_BY_DEFAULT = {
    "z-ai",
    "gonka-broker",
    "modelscope",
    "siliconflow",
}

# Models that should never be treated as free-tier candidates even if a
# provider advertises them. Mirrors the is_paid_vendor_model concept from
# litellm-free-models investigation.
PAID_VENDOR_MODEL_PREFIXES = (
    "claude-",
    "gpt-5.",
    "gemini-",
    "grok-",
    "glm-5.",
    "minimax-",
)

# Catalog file path relative to this module's directory
CATALOG_FILE = Path(__file__).resolve().parent / "providers.json"


class FreeCatalogError(Exception):
    """Raised when the free catalog cannot be loaded or validated."""


@dataclass
class FreeProvider:
    """A free LLM provider from the catalog."""

    id: str
    name: str
    category: str  # "provider_api" or "inference_provider"
    country: str
    base_url: str
    openai_compatible_url: Optional[str]
    api_key_env: Optional[str]  # Env var name for the provider's key (gateway-side only)
    enabled: bool
    models: list[dict]


@dataclass
class FreeModel:
    """A free model entry from the catalog."""

    provider_id: str
    model_id: str
    name: str
    context: str
    max_output: str
    modality: str
    rate_limit: str


def _parse_rate_limit(rate_limit: str) -> Optional[int]:
    """
    Extract an RPM (requests per minute) value from a rate limit string.

    Returns None if no RPM can be parsed (e.g. "-", "Shared w/ context",
    "1 concurrent request").
    """
    if not rate_limit or rate_limit in ("-", "Shared w/ context", "Varies"):
        return None

    # Patterns like "15 RPM", "20 RPM", "30 RPM", "40 RPM", "60 RPM"
    # Remove commas, then look for a number token followed by "RPM"
    cleaned = rate_limit.replace(",", "")
    tokens = cleaned.split()
    for i, token in enumerate(tokens):
        if token == "RPM" and i > 0:
            try:
                return int(tokens[i - 1])
            except ValueError:
                return None
    return None


def _parse_rpd(rate_limit: str) -> Optional[int]:
    """Extract RPD (requests per day) from a rate limit string."""
    if not rate_limit or rate_limit in ("-", "Shared w/ context", "Varies"):
        return None
    cleaned = rate_limit.replace(",", "")
    tokens = cleaned.split()
    for i, token in enumerate(tokens):
        if token == "RPD" and i > 0:
            try:
                return int(tokens[i - 1])
            except ValueError:
                return None
    return None


def _is_paid_vendor_model(model_id: str) -> bool:
    """Check if a model ID matches a paid vendor pattern that should not be
    treated as a free-tier candidate."""
    model_lower = model_id.lower()
    return any(model_lower.startswith(p) for p in PAID_VENDOR_MODEL_PREFIXES)


def load_catalog(
    catalog_file: Path = CATALOG_FILE,
    enabled_providers: Optional[set[str]] = None,
) -> list[FreeProvider]:
    """
    Load and validate the free catalog from providers.json.

    Args:
        catalog_file: Path to the vendored catalog JSON.
        enabled_providers: Optional set of provider IDs to enable.
                           If None, all providers not in the disabled-by-default
                           set are enabled.

    Returns:
        List of FreeProvider objects.

    Raises:
        FreeCatalogError: If the file cannot be read or is malformed.
    """
    if not catalog_file.exists():
        raise FreeCatalogError(f"Catalog file not found: {catalog_file}")

    try:
        with open(catalog_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise FreeCatalogError(f"Failed to read catalog: {exc}") from exc

    if "providers" not in data or not isinstance(data["providers"], list):
        raise FreeCatalogError("Catalog missing 'providers' list")

    providers: list[FreeProvider] = []
    for entry in data["providers"]:
        provider_id = entry.get("id")
        if not provider_id:
            logger.warning("Skipping catalog entry without 'id'")
            continue

        base_url = entry.get("base_url")
        if not base_url:
            logger.warning(f"Skipping provider {provider_id}: no base_url")
            continue

        # Determine OpenAI-compatible URL
        openai_url = entry.get("openai_compatible_url") or base_url

        # Determine API key env var name
        api_key_env = _provider_api_key_env(provider_id)

        # Determine enabled state
        is_disabled_by_default = provider_id in PROVIDERS_DISABLED_BY_DEFAULT
        if enabled_providers is not None:
            is_enabled = provider_id in enabled_providers
        else:
            is_enabled = not is_disabled_by_default

        # Filter models: remove paid vendor models and entries without model IDs
        raw_models = entry.get("models", [])
        valid_models = []
        for model in raw_models:
            model_id = model.get("id")
            if not model_id:
                continue
            if _is_paid_vendor_model(model_id):
                logger.info(
                    f"Filtering paid vendor model {model_id} from {provider_id}"
                )
                continue
            valid_models.append(model)

        providers.append(
            FreeProvider(
                id=provider_id,
                name=entry.get("name", provider_id),
                category=entry.get("category", "inference_provider"),
                country=entry.get("country", ""),
                base_url=base_url,
                openai_compatible_url=openai_url,
                api_key_env=api_key_env,
                enabled=is_enabled,
                models=valid_models,
            )
        )

    logger.info(
        f"Loaded free catalog: {len(providers)} providers, "
        f"{sum(len(p.models) for p in providers)} models"
    )
    return providers


def _provider_api_key_env(provider_id: str) -> Optional[str]:
    """Map a provider ID to its gateway-side API key environment variable name.

    Returns None for providers that don't require an API key (anonymous tiers).
    """
    env_map = {
        "aion-labs": "AION_API_KEY",
        "cohere": "COHERE_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "z-ai": "Z_AI_API_KEY",
        "cloudflare-workers-ai": "CLOUDFLARE_API_TOKEN",
        "gonka-broker": "GONKA_API_KEY",
        "groq": "GROQ_API_KEY",
        "kilo-code": None,  # No API key required
        "llm7": "LLM7_API_KEY",
        "modelscope": "MODELSCOPE_API_KEY",
        "nvidia-nim": "NVIDIA_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "ovhcloud": None,  # Anonymous tier, no key required
        "siliconflow": "SILICONFLOW_API_KEY",
    }
    return env_map.get(provider_id)


def load_routes(
    catalog_file: Path = CATALOG_FILE,
    enabled_providers: Optional[set[str]] = None,
    cost_per_1k_tokens: float = 0.0,
) -> list[ModelRoute]:
    """
    Convert the free catalog into a list of gateway.router.ModelRoute objects.

    Each model in the catalog becomes a separate ModelRoute with tier=2
    (free cloud). Routes are sorted by provider then model ID for deterministic
    selection.

    Args:
        catalog_file: Path to the vendored catalog JSON.
        enabled_providers: Optional set of provider IDs to enable.
        cost_per_1k_tokens: Estimated cost per 1K tokens for free-tier models
                           (0.0 for truly free providers).

    Returns:
        List of ModelRoute objects suitable for Router.add_route().

    Raises:
        FreeCatalogError: If the catalog cannot be loaded.
    """
    providers = load_catalog(catalog_file, enabled_providers)
    routes: list[ModelRoute] = []

    for provider in providers:
        if not provider.enabled:
            continue

        # Use OpenAI-compatible URL if available, otherwise base URL
        api_base = provider.openai_compatible_url or provider.base_url

        for model in provider.models:
            model_id = model.get("id", "")
            model_name = model.get("name", model_id)

            route = ModelRoute(
                name=f"{provider.name}/{model_name}",
                provider=provider.id,
                model_id=model_id,
                tier=2,
                api_base=api_base,
                api_key_env=provider.api_key_env,
                cost_per_1k_tokens=cost_per_1k_tokens,
                enabled=True,
                context_window=_parse_context_window(model.get("context", "0")),
            )
            routes.append(route)

    # Sort by provider ID then model ID for deterministic selection
    routes.sort(key=lambda r: (r.provider, r.model_id))

    logger.info(
        f"Generated {len(routes)} free-tier routes from {len(providers)} providers"
    )
    return routes


def _parse_context_window(context_str: str) -> int:
    """Parse a context window string like '128K' or '1M' into an integer token count."""
    if not context_str or context_str in ("-", "Varies"):
        return 4096  # Default fallback
    s = context_str.replace(",", "").upper()
    try:
        if s.endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("K"):
            return int(float(s[:-1]) * 1_000)
        return int(s)
    except ValueError:
        return 4096
