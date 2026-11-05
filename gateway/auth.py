"""
Gateway authentication module.

Validates bearer tokens at the gateway level. Clients present only a
gateway token — real provider keys never leave the gateway.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Gateway token — clients authenticate with this, NOT provider keys.
# In production, load from secrets manager or env file.
GATEWAY_TOKEN = os.environ.get("OWL_GATEWAY_TOKEN")

if not GATEWAY_TOKEN:
    # Generate a one-time token for local development. Log it once so the
    # operator can configure clients.
    import base64
    GATEWAY_TOKEN = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    print(f"[auth] Generated one-time gateway token: {GATEWAY_TOKEN}")
    print("[auth] Set OWL_GATEWAY_TOKEN env var for persistent token.")

security = HTTPBearer(auto_error=False)


def validate_gateway_token(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> str:
    """
    Validate the bearer token presented by the client.

    Returns the token subject (client identifier) on success.
    Raises HTTPException 401 on missing or invalid token.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <gateway-token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    if not secrets.compare_digest(token, GATEWAY_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid gateway token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In production, map token -> client_id from a registry.
    # For now, the token itself is the client identifier.
    return "gateway-client"


def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """FastAPI dependency: enforce gateway auth on protected routes."""
    return validate_gateway_token(credentials)
