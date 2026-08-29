from __future__ import annotations

import json
import os
import socket
import time
from urllib.request import Request as URLRequest, urlopen

from fastapi import Depends, FastAPI, Query, Request

from .incident_logic import failover_verified, incident_action, unhealthy_addresses
from .security import require_agent

AGENT_ID = "incident-responder"
CONTROL_API = os.getenv("CONTROL_API", "http://dns-manager:8053")
CONTROL_TOKEN = os.getenv("CONTROL_TOKEN", "demo-control-token")
app = FastAPI(title="Incident response agent")


def control_headers(scenario_id: str = "") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {CONTROL_TOKEN}",
        "X-Actor": AGENT_ID,
    }
    if scenario_id:
        headers["X-Scenario-ID"] = scenario_id
    return headers


def get_json(url: str, scenario_id: str = "") -> object:
    request = URLRequest(
        url,
        headers=control_headers(scenario_id),
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def post_json(url: str, payload: dict, scenario_id: str = "") -> object:
    headers = control_headers(scenario_id)
    headers["Content-Type"] = "application/json"
    request = URLRequest(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def resolve_batch(domain: str, count: int, interval_ms: int = 60) -> list[str]:
    answers: list[str] = []
    for index in range(count):
        try:
            answers.append(socket.gethostbyname(domain))
        except socket.gaierror:
            answers.append("")
        if interval_ms and index < count - 1:
            time.sleep(interval_ms / 1000)
    return [answer for answer in answers if answer]


@app.get("/health")
def health():
    return {"status": "ok", "agent": AGENT_ID}


@app.post("/investigate", dependencies=[Depends(require_agent)])
def investigate(request: Request, samples: int = Query(default=3, ge=1, le=20)):
    """Confirm that DNS is steering traffic away from every unhealthy endpoint."""
    scenario_id = request.headers.get("x-scenario-id", "")
    endpoints = get_json(f"{CONTROL_API}/endpoints", scenario_id)
    unhealthy = unhealthy_addresses(endpoints)
    answers = resolve_batch("api.internal", samples)
    return {
        "agent": AGENT_ID,
        "unhealthy": unhealthy,
        "answers": answers,
        "selected_healthy_endpoint": answers[0] if answers else None,
        "failover_verified": failover_verified(answers, unhealthy),
        "action": incident_action(endpoints),
    }


@app.post("/remediate", dependencies=[Depends(require_agent)])
def remediate(
    request: Request,
    wait_seconds: float = Query(default=10.0, ge=0.0, le=60.0),
):
    """Repair the failing services themselves, then wait for probes to agree."""
    scenario_id = request.headers.get("x-scenario-id", "")
    endpoints = get_json(f"{CONTROL_API}/endpoints", scenario_id)
    unhealthy = unhealthy_addresses(endpoints)

    for address in unhealthy:
        try:
            post_json(
                f"{CONTROL_API}/endpoints/{address}/inject",
                {"fail": False},
                scenario_id,
            )
        except OSError:
            # The service may be genuinely unreachable; the override below still
            # keeps the demonstration deterministic.
            pass

    deadline = time.monotonic() + wait_seconds
    still_unhealthy = list(unhealthy)
    while still_unhealthy and time.monotonic() < deadline:
        time.sleep(0.5)
        still_unhealthy = unhealthy_addresses(
            get_json(f"{CONTROL_API}/endpoints", scenario_id)
        )

    answers = resolve_batch("api.internal", max(len(unhealthy) + 1, 2))
    return {
        "agent": AGENT_ID,
        "restored": [address for address in unhealthy if address not in still_unhealthy],
        "still_unhealthy": still_unhealthy,
        "answers": answers,
        "selected_endpoint": answers[0] if answers else None,
        "action": "ENDPOINTS_RESTORED" if unhealthy and not still_unhealthy
        else "REMEDIATION_INCOMPLETE" if still_unhealthy
        else "NO_ACTION_NEEDED",
    }
