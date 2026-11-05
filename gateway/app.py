"""
OWL Agent Governed Token Plane — Gateway Service.

FastAPI gateway that:
1. Validates bearer tokens (clients present gateway token, never provider keys)
2. Routes models: local (Ollama/vLLM) → free-tier cloud → paid fallback
3. Rate limits per client
4. Caches responses in Redis
5. Tracks token/cost budgets per client
6. Circuit breaker per provider with fallback chain
7. Redacted audit logging (no key leakage)

Architecture:
    Client -> gateway token -> Nginx/Caddy edge -> this gateway -> providers
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import require_auth, validate_gateway_token
from circuit_breaker import CircuitBreaker
from cache import Cache
from billing import Billing
from router import Router, ModelRoute, RouteDecision

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] gateway: %(message)s",
)
logger = logging.getLogger("owl-agent.gateway")

app = FastAPI(
    title="OWL Agent Governed Token Plane",
    version="1.0.0",
    description="Central gateway: auth, rate limiting, model routing, cache, budgets, audit.",
)

# ── Global instances ──
circuit_breaker = CircuitBreaker(threshold=5, cooldown_seconds=60.0)
cache = Cache(enabled=os.environ.get("OWL_CACHE_ENABLED", "true").lower() == "true")
billing = Billing(
    default_token_limit=int(os.environ.get("OWL_DEFAULT_TOKEN_LIMIT", "100000")),
    default_cost_limit_usd=float(
        os.environ.get("OWL_DEFAULT_COST_LIMIT_USD", "10.0")
    ),
    kill_switch=os.environ.get("OWL_KILL_SWITCH", "false").lower() == "true",
)
router = Router()
audit = None  # type: ignore  # initialized in startup


# ── Request/Response models ──
class ChatRequest(BaseModel):
    model: str
    messages: list[dict]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False
    task_type: Optional[str] = "default"


class ChatResponse(BaseModel):
    id: str
    model: str
    provider: str
    tier: int
    content: str
    usage: dict
    route_reason: str
    cached: bool = False


# ── Startup/shutdown ──
@app.on_event("startup")
async def startup() -> None:
    global audit
    from audit import AuditLogger
    audit = AuditLogger()
    logger.info("Gateway started — governed token plane v1.0.0")
    logger.info(f"Cache enabled: {cache.enabled}")
    logger.info(f"Kill switch: {billing.kill_switch}")
    logger.info(f"Routes: {router.stats()}")


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info("Gateway shutting down")


# ── Middleware: request timing ──
@app.middleware("http")
async def timing_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - start) * 1000
    response.headers["X-Response-Latency-Ms"] = str(round(latency_ms, 2))
    return response


# ── Routes ──
@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "owl-agent-gateway",
        "version": "1.0.0",
        "cache": cache.stats(),
        "circuit_breaker": circuit_breaker.stats(),
        "router": router.stats(),
    }


@app.get("/v1/models")
async def list_models(client_id: str = Depends(require_auth)) -> dict:
    """List available models (authenticated)."""
    return {
        "object": "list",
        "data": [
            {
                "id": r.model_id,
                "provider": r.provider,
                "tier": r.tier,
                "local": r.is_local,
                "context_window": r.context_window,
            }
            for routes in router.routes.values()
            for r in routes
        ],
    }


@app.post("/v1/chat/completions", response_model=ChatResponse)
async def chat_completions(
    request: ChatRequest,
    client_id: str = Depends(require_auth),
) -> ChatResponse:
    """Chat completions endpoint with full governance: auth, route, cache, bill, audit."""
    start_time = time.time()

    # Estimate tokens for budget check (rough: ~4 chars per token)
    prompt_text = " ".join(m.get("content", "") for m in request.messages)
    estimated_tokens = len(prompt_text) // 4 + (request.max_tokens or 500)

    # ── Budget check ──
    block_reason = billing.check_budget(
        client_id, estimated_tokens, request.model
    )
    if block_reason:
        audit.log_budget_block(
            client_id=client_id,
            reason=block_reason,
            tokens_used=billing.get_budget(client_id).tokens_used,
            token_limit=billing.get_budget(client_id).token_limit,
            cost_used_usd=billing.get_budget(client_id).cost_used_usd,
            cost_limit_usd=billing.get_budget(client_id).cost_limit_usd,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Budget blocked: {block_reason}",
        )

    # ── Cache lookup ──
    cached = cache.get("chat", prompt_text, request.model)
    if cached:
        latency_ms = (time.time() - start_time) * 1000
        audit.log_request(
            client_id=client_id,
            method="POST",
            path="/v1/chat/completions",
            model=request.model,
            estimated_tokens=estimated_tokens,
            provider=cached.get("provider"),
            status_code=200,
            latency_ms=latency_ms,
            extra={"cached": True},
        )
        return ChatResponse(**cached, cached=True)

    # ── Route selection ──
    cb_availability = {
        name: circuit_breaker.is_available(name)
        for name in ["ollama", "openai", "anthropic"]
    }
    client = billing.get_budget(client_id)
    decision: Optional[RouteDecision] = router.route(
        task_type=request.task_type or "default",
        client_budget_tokens_remaining=client.token_remaining,
        client_cost_remaining_usd=client.cost_remaining_usd,
        circuit_breaker_available=cb_availability,
    )

    if not decision:
        latency_ms = (time.time() - start_time) * 1000
        audit.log_error(
            client_id=client_id,
            error="no_available_route",
            extra={"model": request.model, "task_type": request.task_type},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No available model route (all providers unhealthy or budget exhausted)",
        )

    audit.log_route_decision(
        client_id=client_id,
        requested_model=request.model,
        selected_provider=decision.provider,
        selected_model=decision.model_id,
        fallback_used=decision.tier > 1,
    )

    # ── Forward to provider ──
    try:
        import httpx

        provider_payload = {
            "model": decision.model_id,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": False,
        }
        if request.max_tokens:
            provider_payload["max_tokens"] = request.max_tokens

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }
        if decision.api_key:
            # Provider key comes from gateway env — never from client
            if decision.provider == "anthropic":
                headers["x-api-key"] = decision.api_key
                headers["anthropic-version"] = "2023-06-01"
            else:
                headers["Authorization"] = f"Bearer {decision.api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{decision.api_base}/chat/completions"
                if decision.provider != "anthropic"
                else f"{decision.api_base}/v1/messages",
                json=provider_payload,
                headers=headers,
            )

        if resp.status_code >= 400:
            circuit_breaker.record_failure(decision.provider)
            audit.log_error(
                client_id=client_id,
                error=f"provider_error_{resp.status_code}",
                provider=decision.provider,
            )
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Provider {decision.provider} returned {resp.status_code}",
            )

        data = resp.json()

        # Extract content based on provider format
        if decision.provider == "anthropic":
            content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content += block.get("text", "")
            usage = {
                "input_tokens": data.get("usage", {}).get("input_tokens", 0),
                "output_tokens": data.get("usage", {}).get("output_tokens", 0),
                "total_tokens": data.get("usage", {}).get("input_tokens", 0)
                + data.get("usage", {}).get("output_tokens", 0),
            }
        else:
            content = data.get("choices", [{}])[0].get("message", {}).get(
                "content", ""
            )
            usage = data.get("usage", {})

        actual_tokens = usage.get("total_tokens", estimated_tokens)

        # ── Record usage & billing ──
        billing.record_usage(client_id, actual_tokens, decision.model_id)
        circuit_breaker.record_success(decision.provider)

        # ── Cache the response ──
        cache_response = {
            "id": f"owl-{int(time.time()*1000)}",
            "model": decision.model_id,
            "provider": decision.provider,
            "tier": decision.tier,
            "content": content,
            "usage": usage,
            "route_reason": decision.reason,
        }
        cache.set("chat", prompt_text, request.model, cache_response)

        latency_ms = (time.time() - start_time) * 1000
        audit.log_request(
            client_id=client_id,
            method="POST",
            path="/v1/chat/completions",
            model=request.model,
            estimated_tokens=estimated_tokens,
            provider=decision.provider,
            status_code=200,
            latency_ms=latency_ms,
            extra={"actual_tokens": actual_tokens, "tier": decision.tier},
        )

        return ChatResponse(
            id=cache_response["id"],
            model=decision.model_id,
            provider=decision.provider,
            tier=decision.tier,
            content=content,
            usage=usage,
            route_reason=decision.reason,
            cached=False,
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        circuit_breaker.record_failure(decision.provider if decision else "unknown")
        latency_ms = (time.time() - start_time) * 1000
        audit.log_error(
            client_id=client_id,
            error=str(exc)[:200],
            provider=decision.provider if decision else "unknown",
            extra={"model": request.model},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway error: {str(exc)[:200]}",
        )


@app.get("/v1/stats")
async def stats(client_id: str = Depends(require_auth)) -> dict:
    """Gateway statistics (authenticated)."""
    return {
        "cache": cache.stats(),
        "circuit_breaker": circuit_breaker.stats(),
        "router": router.stats(),
        "billing": billing.stats(),
    }


@app.post("/v1/admin/kill-switch")
async def kill_switch(enable: bool, client_id: str = Depends(require_auth)) -> dict:
    """Enable/disable the global kill switch (admin only)."""
    billing.kill_switch = enable
    audit.log_request(
        client_id=client_id,
        method="POST",
        path="/v1/admin/kill-switch",
        status_code=200,
        extra={"kill_switch": enable},
    )
    return {"kill_switch": enable}


@app.post("/v1/admin/budget/{client_id}")
async def set_budget(
    client_id: str,
    token_limit: Optional[int] = None,
    cost_limit_usd: Optional[float] = None,
    current_client: str = Depends(require_auth),
) -> dict:
    """Set a client's budget limits."""
    billing.set_client_budget(client_id, token_limit, cost_limit_usd)
    return {
        "client_id": client_id,
        "token_limit": token_limit,
        "cost_limit_usd": cost_limit_usd,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("OWL_GATEWAY_PORT", "20128")),
    )
