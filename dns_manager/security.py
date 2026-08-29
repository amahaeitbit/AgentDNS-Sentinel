from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request

CONTROL_TOKEN = os.getenv("CONTROL_TOKEN", "demo-control-token")


@dataclass(frozen=True)
class ActorContext:
    actor: str
    scenario_id: str


def require_control(request: Request) -> ActorContext:
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {CONTROL_TOKEN}"
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="A valid control-plane bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ActorContext(
        actor=request.headers.get("x-actor", "operator")[:100],
        scenario_id=request.headers.get("x-scenario-id", "")[:100],
    )
