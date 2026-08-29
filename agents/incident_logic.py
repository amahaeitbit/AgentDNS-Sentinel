from __future__ import annotations

from typing import Iterable, Sequence


def unhealthy_addresses(endpoints: Iterable[dict]) -> list[str]:
    return [
        str(endpoint["address"])
        for endpoint in endpoints
        if not bool(endpoint["healthy"])
    ]


def incident_action(endpoints: Iterable[dict]) -> str:
    return "FAILOVER_VERIFIED" if unhealthy_addresses(endpoints) else "NO_INCIDENT"


def failover_verified(answers: Sequence[str], unhealthy: Sequence[str]) -> bool:
    """True when a batch of DNS answers avoided every unhealthy endpoint."""
    if not answers:
        return False
    return not set(answers) & set(unhealthy)
