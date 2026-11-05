"""
Per-provider circuit breaker with fallback chain support.

Tracks consecutive failures per provider and opens the circuit after a
threshold, routing to the next available provider in the fallback chain.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("owl-agent.gateway.circuit-breaker")


@dataclass
class CircuitState:
    """Circuit breaker state for a single provider."""

    name: str
    threshold: int = 5
    cooldown_seconds: float = 60.0
    failures: int = 0
    open_until: float = 0.0
    total_requests: int = 0
    total_errors: int = 0

    @property
    def is_open(self) -> bool:
        if self.open_until and time.time() < self.open_until:
            return True
        # Cooldown expired — allow a trial request (half-open)
        if self.open_until:
            self.open_until = 0.0
            self.failures = 0
        return False

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_errors / self.total_requests

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = 0.0
        self.total_requests += 1

    def record_failure(self) -> None:
        self.failures += 1
        self.total_requests += 1
        self.total_errors += 1
        if self.failures >= self.threshold:
            self.open_until = time.time() + self.cooldown_seconds
            logger.warning(
                f"Circuit breaker OPEN for provider '{self.name}' "
                f"({self.failures} consecutive failures, {self.cooldown_seconds}s cooldown)"
            )


class CircuitBreaker:
    """Manages circuit breakers for multiple providers with fallback ordering."""

    def __init__(self, threshold: int = 5, cooldown_seconds: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._circuits: Dict[str, CircuitState] = {}

    def get_circuit(self, provider: str) -> CircuitState:
        """Get or create a circuit breaker for a provider."""
        if provider not in self._circuits:
            self._circuits[provider] = CircuitState(
                name=provider,
                threshold=self.threshold,
                cooldown_seconds=self.cooldown_seconds,
            )
        return self._circuits[provider]

    def is_available(self, provider: str) -> bool:
        """Check if a provider's circuit is closed (available for requests)."""
        return not self.get_circuit(provider).is_open

    def record_success(self, provider: str) -> None:
        """Record a successful request through a provider."""
        self.get_circuit(provider).record_success()

    def record_failure(self, provider: str) -> None:
        """Record a failed request through a provider."""
        self.get_circuit(provider).record_failure()

    def select_provider(
        self, fallback_chain: List[str]
    ) -> Optional[str]:
        """
        Select the first available provider from the fallback chain.

        Returns None if all circuits are open.
        """
        for provider in fallback_chain:
            if self.is_available(provider):
                return provider
        return None

    def stats(self) -> dict:
        """Return circuit breaker statistics for all providers."""
        return {
            name: {
                "failures": c.failures,
                "is_open": c.is_open,
                "error_rate": round(c.error_rate, 4),
                "total_requests": c.total_requests,
                "total_errors": c.total_errors,
            }
            for name, c in self._circuits.items()
        }
