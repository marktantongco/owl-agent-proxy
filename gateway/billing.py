"""
Token/cost budget tracking with per-user budgets and kill switch.

Tracks token usage and estimated cost per client. When a budget is
exceeded, requests are blocked until the budget resets or is increased.
A global kill switch can halt all traffic for runaway agents.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("owl-agent.gateway.billing")


@dataclass
class Budget:
    """Per-client budget state."""

    client_id: str
    token_limit: int
    cost_limit_usd: float
    tokens_used: int = 0
    cost_used_usd: float = 0.0
    window_start: float = field(default_factory=time.time)
    window_seconds: int = 86400  # 24-hour window by default
    blocked: bool = False

    @property
    def window_expired(self) -> bool:
        return time.time() - self.window_start > self.window_seconds

    def reset_if_expired(self) -> None:
        if self.window_expired:
            self.tokens_used = 0
            self.cost_used_usd = 0.0
            self.window_start = time.time()
            self.blocked = False

    @property
    def token_remaining(self) -> int:
        return max(0, self.token_limit - self.tokens_used)

    @property
    def cost_remaining_usd(self) -> float:
        return max(0.0, self.cost_limit_usd - self.cost_used_usd)

    @property
    def token_utilization(self) -> float:
        if self.token_limit == 0:
            return 0.0
        return self.tokens_used / self.token_limit

    @property
    def cost_utilization(self) -> float:
        if self.cost_limit_usd == 0:
            return 0.0
        return self.cost_used_usd / self.cost_limit_usd


class Billing:
    """Tracks token usage and cost per client with budget enforcement."""

    # Estimated cost per 1K tokens per provider/model (USD).
    # These are planning estimates — replace with actual provider pricing.
    ESTIMATED_COST_PER_1K_TOKENS: Dict[str, float] = {
        "ollama": 0.0,          # Local — hardware cost only
        "vllm": 0.0,            # Local — hardware cost only
        "gpt-4o-mini": 0.15,    # Free tier burst estimate
        "gpt-4o": 5.00,
        "claude-3-5-haiku": 0.80,
        "claude-3-5-sonnet": 3.00,
    }

    def __init__(
        self,
        default_token_limit: int = 100_000,
        default_cost_limit_usd: float = 10.0,
        window_seconds: int = 86400,
        kill_switch: bool = False,
    ) -> None:
        self.default_token_limit = default_token_limit
        self.default_cost_limit_usd = default_cost_limit_usd
        self.window_seconds = window_seconds
        self.kill_switch = kill_switch
        self._budgets: Dict[str, Budget] = {}

    def get_budget(self, client_id: str) -> Budget:
        """Get or create a budget for a client."""
        if client_id not in self._budgets:
            self._budgets[client_id] = Budget(
                client_id=client_id,
                token_limit=self.default_token_limit,
                cost_limit_usd=self.default_cost_limit_usd,
                window_seconds=self.window_seconds,
            )
        return self._budgets[client_id]

    def check_budget(
        self,
        client_id: str,
        estimated_tokens: int,
        model: str,
    ) -> Optional[str]:
        """
        Check if a request would exceed the client's budget.

        Returns None if allowed, or a rejection reason string if blocked.
        """
        if self.kill_switch:
            return "kill_switch_active"

        budget = self.get_budget(client_id)
        budget.reset_if_expired()

        if budget.blocked:
            return "budget_blocked"

        # Check token budget
        if budget.tokens_used + estimated_tokens > budget.token_limit:
            budget.blocked = True
            return "token_budget_exceeded"

        # Check cost budget
        cost_per_1k = self.ESTIMATED_COST_PER_1K_TOKENS.get(model, 0.01)
        estimated_cost = (estimated_tokens / 1000.0) * cost_per_1k
        if budget.cost_used_usd + estimated_cost > budget.cost_limit_usd:
            budget.blocked = True
            return "cost_budget_exceeded"

        return None  # allowed

    def record_usage(
        self,
        client_id: str,
        tokens_used: int,
        model: str,
    ) -> None:
        """Record actual token usage and cost after a request completes."""
        budget = self.get_budget(client_id)
        budget.reset_if_expired()

        budget.tokens_used += tokens_used
        cost_per_1k = self.ESTIMATED_COST_PER_1K_TOKENS.get(model, 0.01)
        budget.cost_used_usd += (tokens_used / 1000.0) * cost_per_1k

    def set_client_budget(
        self,
        client_id: str,
        token_limit: Optional[int] = None,
        cost_limit_usd: Optional[float] = None,
    ) -> None:
        """Override a client's budget limits."""
        budget = self.get_budget(client_id)
        if token_limit is not None:
            budget.token_limit = token_limit
        if cost_limit_usd is not None:
            budget.cost_limit_usd = cost_limit_usd

    def block_client(self, client_id: str, reason: str = "manual") -> None:
        """Manually block a client (kill switch per client)."""
        budget = self.get_budget(client_id)
        budget.blocked = True

    def unblock_client(self, client_id: str) -> None:
        """Unblock a previously blocked client."""
        budget = self.get_budget(client_id)
        budget.blocked = False

    def stats(self) -> dict:
        """Return billing statistics for all clients."""
        return {
            "kill_switch": self.kill_switch,
            "clients": {
                cid: {
                    "tokens_used": b.tokens_used,
                    "token_limit": b.token_limit,
                    "token_utilization": round(b.token_utilization, 4),
                    "cost_used_usd": round(b.cost_used_usd, 4),
                    "cost_limit_usd": b.cost_limit_usd,
                    "cost_utilization": round(b.cost_utilization, 4),
                    "blocked": b.blocked,
                }
                for cid, b in self._budgets.items()
            },
        }
