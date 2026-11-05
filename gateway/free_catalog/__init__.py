"""
Free LLM API catalog package.

Vendored catalog from marktantongco/awesome-free-llm-apis providing
15 free LLM providers for the governed token plane's free-tier (tier 2) routing.
"""

from .loader import load_catalog, load_routes, FreeCatalogError

__all__ = ["load_catalog", "load_routes", "FreeCatalogError"]
