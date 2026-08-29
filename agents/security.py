from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


def require_agent(request: Request) -> None:
    token = os.getenv("AGENT_TOKEN", "demo-agent-token")
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied, f"Bearer {token}"):
        raise HTTPException(
            status_code=401,
            detail="A valid agent bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
