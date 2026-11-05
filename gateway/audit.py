"""
Redacted audit logging for gateway decisions.

Logs gateway decisions (routing, auth, rate limiting, budget blocks)
WITHOUT leaking provider API keys, client secrets, or sensitive prompt data.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional, Dict

# Redact these fields from all log output
REDACTED_FIELDS = {
    "api_key",
    "authorization",
    "proxy_authorization",
    "x-api-key",
    "x-owl-protocol",
    "cookie",
    "set-cookie",
    "secret",
    "token",
    "password",
    "credential",
}

logger = logging.getLogger("owl-agent.gateway.audit")
logger.setLevel(logging.INFO)

# Ensure a stream handler exists
if not logger.handlers:
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] gw-audit: %(message)s"
    )
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)


def redact(value: Any, max_len: int = 64) -> Any:
    """Redact sensitive values, returning a truncated placeholder."""
    if isinstance(value, str):
        if len(value) <= max_len:
            return "***REDACTED***"
        return f"***REDACTED***({len(value)} chars)"
    if isinstance(value, dict):
        return {k: redact(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, max_len) for v in value]
    return value


def sanitize_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Return headers with sensitive fields redacted."""
    if not headers:
        return {}
    result = {}
    for k, v in headers.items():
        if k.lower() in REDACTED_FIELDS:
            result[k] = "***REDACTED***"
        else:
            result[k] = v
    return result


class AuditLogger:
    """Structured audit logger for gateway events."""

    def __init__(self, name: str = "owl-agent.gateway.audit") -> None:
        self.logger = logging.getLogger(name)

    def log_request(
        self,
        client_id: str,
        method: str,
        path: str,
        model: Optional[str] = None,
        estimated_tokens: Optional[int] = None,
        provider: Optional[str] = None,
        status_code: Optional[int] = None,
        latency_ms: Optional[float] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Log a gateway request with redacted sensitive fields."""
        entry: Dict[str, Any] = {
            "event": "gateway_request",
            "client_id": client_id,
            "method": method,
            "path": path,
            "timestamp": time.time(),
        }
        if model:
            entry["model"] = model
        if estimated_tokens is not None:
            entry["estimated_tokens"] = estimated_tokens
        if provider:
            entry["provider"] = provider
        if status_code is not None:
            entry["status_code"] = status_code
        if latency_ms is not None:
            entry["latency_ms"] = round(latency_ms, 2)
        if extra:
            entry["extra"] = redact(extra)

        self.logger.info(json.dumps(entry, default=str))

    def log_auth(
        self,
        client_id: str,
        success: bool,
        reason: Optional[str] = None,
    ) -> None:
        """Log an authentication event."""
        entry: Dict[str, Any] = {
            "event": "gateway_auth",
            "client_id": client_id,
            "success": success,
            "timestamp": time.time(),
        }
        if reason:
            entry["reason"] = reason
        self.logger.info(json.dumps(entry, default=str))

    def log_budget_block(
        self,
        client_id: str,
        reason: str,
        tokens_used: int,
        token_limit: int,
        cost_used_usd: float,
        cost_limit_usd: float,
    ) -> None:
        """Log a budget block event."""
        entry: Dict[str, Any] = {
            "event": "gateway_budget_block",
            "client_id": client_id,
            "block_reason": reason,
            "tokens_used": tokens_used,
            "token_limit": token_limit,
            "cost_used_usd": round(cost_used_usd, 4),
            "cost_limit_usd": cost_limit_usd,
            "timestamp": time.time(),
        }
        self.logger.warning(json.dumps(entry, default=str))

    def log_route_decision(
        self,
        client_id: str,
        requested_model: str,
        selected_provider: str,
        selected_model: str,
        fallback_used: bool,
    ) -> None:
        """Log a model routing decision."""
        entry: Dict[str, Any] = {
            "event": "gateway_route",
            "client_id": client_id,
            "requested_model": requested_model,
            "selected_provider": selected_provider,
            "selected_model": selected_model,
            "fallback_used": fallback_used,
            "timestamp": time.time(),
        }
        self.logger.info(json.dumps(entry, default=str))

    def log_error(
        self,
        client_id: str,
        error: str,
        provider: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Log a gateway error without leaking sensitive data."""
        entry: Dict[str, Any] = {
            "event": "gateway_error",
            "client_id": client_id,
            "error": error,
            "timestamp": time.time(),
        }
        if provider:
            entry["provider"] = provider
        if extra:
            entry["extra"] = redact(extra)
        self.logger.error(json.dumps(entry, default=str))
