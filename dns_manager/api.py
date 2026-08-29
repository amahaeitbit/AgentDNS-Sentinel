from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from .health import HealthMonitor
from .security import ActorContext, require_control
from .server import build_runtime, start_dns_server

engine, store = build_runtime()
dns_server = None
health_monitor: HealthMonitor | None = None
SERVICE_CONTROL_TOKEN = os.getenv("SERVICE_CONTROL_TOKEN", "demo-service-control-token")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global dns_server, health_monitor
    dns_server = start_dns_server(engine, store)
    if engine.health_check["enabled"]:
        health_monitor = HealthMonitor(engine).start()
    yield
    if health_monitor:
        health_monitor.stop()
    if dns_server:
        dns_server.stop()


app = FastAPI(title="AgentDNS Sentinel Control API", lifespan=lifespan)


class HealthUpdate(BaseModel):
    healthy: bool


class DomainAccessUpdate(BaseModel):
    domain: str
    allowed: bool


class FailureInjection(BaseModel):
    fail: bool


class ActivityEvent(BaseModel):
    action: str
    resource: str
    before: object | None = None
    after: object | None = None


@app.get("/health")
def health():
    settings = engine.health_check
    return {
        "status": "ok",
        "dns_port": 53,
        "health_probes": "on" if settings["enabled"] else "off",
        "probe_interval_seconds": settings["interval_seconds"],
    }


@app.get("/events")
def events(
    limit: int = Query(default=100, ge=1, le=500),
    _: ActorContext = Depends(require_control),
):
    return store.events(limit)


@app.get("/control-events")
def control_events(
    limit: int = Query(default=100, ge=1, le=500),
    _: ActorContext = Depends(require_control),
):
    return store.control_events(limit)


@app.get("/summary")
def summary(_: ActorContext = Depends(require_control)):
    return store.summary()


def _agent_snapshot() -> list[dict]:
    activity = store.agent_activity()
    result = []
    for agent in engine.agents():
        metrics = activity.get(agent["name"], {})
        result.append(
            {
                **agent,
                "requests_total": metrics.get("requests_total", 0),
                "allowed": metrics.get("allowed", 0),
                "blocked": metrics.get("blocked", 0),
                "throttled": metrics.get("throttled", 0),
                "last_seen": metrics.get("last_seen", ""),
            }
        )
    return result


@app.get("/agents")
def agents(_: ActorContext = Depends(require_control)):
    return _agent_snapshot()


def _process_stats() -> dict:
    """Resident memory, where the platform reports it."""
    try:
        with open("/proc/self/status") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return {"rss_kb": int(line.split()[1])}
    except OSError:
        pass
    return {"rss_kb": None}


@app.get("/runtime")
def runtime(_: ActorContext = Depends(require_control)):
    """What the resolver is holding in memory, and how full its buffers are."""
    return {
        "policy": engine.runtime_stats(),
        "store": store.stats(),
        "process": _process_stats(),
    }


@app.get("/alerts")
def alerts(
    limit: int = Query(default=50, ge=1, le=200),
    _: ActorContext = Depends(require_control),
):
    """Notifications raised when an agent is burning through its allowance."""
    return engine.alerts.recent(limit)


@app.get("/spend")
def spend(_: ActorContext = Depends(require_control)):
    """What each budgeted agent has spent inside its own window."""
    return engine.spend_report()


@app.post("/budgets/reset")
def reset_budgets(context: ActorContext = Depends(require_control)):
    """Start a fresh budget window, so a cost demo can be run more than once."""
    before = engine.spend_report()
    engine.reset_budgets()
    store.control_event(
        context.actor,
        "BUDGETS_RESET",
        "budgets",
        {"spend": before},
        {"spend": engine.spend_report()},
        context.scenario_id,
    )
    return {"status": "reset", "spend": engine.spend_report()}


@app.get("/endpoints")
def endpoints(_: ActorContext = Depends(require_control)):
    return engine.endpoints()


@app.get("/dashboard")
def dashboard_snapshot(
    events_limit: int = Query(default=60, ge=1, le=500),
    control_limit: int = Query(default=30, ge=1, le=500),
    alerts_limit: int = Query(default=20, ge=1, le=200),
    _: ActorContext = Depends(require_control),
):
    """One consistent, low-overhead payload for a dashboard refresh."""
    return {
        "events": store.events(events_limit),
        "summary": store.summary(),
        "agents": _agent_snapshot(),
        "endpoints": engine.endpoints(),
        "control_events": store.control_events(control_limit),
        "alerts": engine.alerts.recent(alerts_limit),
        "spend": engine.spend_report(),
    }


@app.post("/endpoints/{address}/health")
def update_health(
    address: str,
    update: HealthUpdate,
    context: ActorContext = Depends(require_control),
):
    """Pin an endpoint healthy or unhealthy, ignoring the probe result."""
    before = next((item for item in engine.endpoints() if item["address"] == address), None)
    try:
        engine.set_endpoint_health(address, update.healthy)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown endpoint")
    result = {"address": address, "healthy": update.healthy, "source": "override"}
    store.control_event(
        context.actor,
        "HEALTH_OVERRIDE_SET",
        f"endpoint:{address}",
        before,
        result,
        context.scenario_id,
    )
    return result


@app.delete("/endpoints/{address}/health")
def clear_health_override(
    address: str, context: ActorContext = Depends(require_control)
):
    """Return the endpoint to probe-driven health."""
    before = next((item for item in engine.endpoints() if item["address"] == address), None)
    try:
        engine.clear_endpoint_override(address)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown endpoint")
    result = {"address": address, "source": "probe"}
    store.control_event(
        context.actor,
        "HEALTH_OVERRIDE_CLEARED",
        f"endpoint:{address}",
        before,
        result,
        context.scenario_id,
    )
    return result


@app.post("/endpoints/{address}/inject")
def inject_failure(
    address: str,
    update: FailureInjection,
    context: ActorContext = Depends(require_control),
):
    """Take the real service behind an endpoint down or bring it back up.

    The control API proxies this so demo drivers outside the lab network never
    need direct access to the mock services.
    """
    if address not in engine.addresses():
        raise HTTPException(status_code=404, detail="Unknown endpoint")
    settings = engine.health_check
    action = "fail" if update.fail else "recover"
    url = f"http://{address}:{settings['port']}/control/{action}"
    request = urllib.request.Request(
        url,
        data=b"",
        headers={"Authorization": f"Bearer {SERVICE_CONTROL_TOKEN}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout_seconds"] + 2) as response:
            body = json.load(response)
    except (urllib.error.URLError, OSError) as error:
        raise HTTPException(
            status_code=502, detail=f"Could not reach service at {address}: {error}"
        )
    result = {"address": address, "injected": action, "service": body}
    store.control_event(
        context.actor,
        "FAILURE_INJECTED" if update.fail else "SERVICE_RECOVERY_REQUESTED",
        f"endpoint:{address}",
        None,
        result,
        context.scenario_id,
    )
    return result


@app.post("/agents/{agent}/access")
def update_access(
    agent: str,
    update: DomainAccessUpdate,
    context: ActorContext = Depends(require_control),
):
    before = next((item for item in engine.agents() if item["name"] == agent), None)
    try:
        engine.set_domain_access(agent, update.domain, update.allowed)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown agent")
    result = {"agent": agent, "domain": update.domain, "allowed": update.allowed}
    after = next((item for item in engine.agents() if item["name"] == agent), None)
    store.control_event(
        context.actor,
        "ACCESS_GRANTED" if update.allowed else "ACCESS_REVOKED",
        f"agent:{agent}:{update.domain}",
        before,
        after,
        context.scenario_id,
    )
    return result


@app.post("/activity")
def record_activity(
    update: ActivityEvent,
    context: ActorContext = Depends(require_control),
):
    store.control_event(
        context.actor,
        update.action[:100],
        update.resource[:200],
        update.before,
        update.after,
        context.scenario_id,
    )
    return {"recorded": True}


def _recover(address: str) -> bool:
    settings = engine.health_check
    request = urllib.request.Request(
        f"http://{address}:{settings['port']}/control/recover",
        data=b"",
        headers={"Authorization": f"Bearer {SERVICE_CONTROL_TOKEN}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout_seconds"] + 2):
            return True
    except (urllib.error.URLError, OSError):
        return False


@app.post("/reset")
def reset(context: ActorContext = Depends(require_control)):
    """Restore the starting policy, revive every service, and clear the log."""
    recovered = [address for address in engine.addresses() if _recover(address)]
    engine.reset()
    if health_monitor:
        health_monitor.tracker = type(health_monitor.tracker)(
            failure_threshold=health_monitor.tracker.failure_threshold,
            success_threshold=health_monitor.tracker.success_threshold,
        )
    store.clear()
    result = {"status": "reset", "recovered": recovered}
    store.control_event(
        context.actor,
        "LAB_RESET",
        "lab",
        None,
        result,
        context.scenario_id,
    )
    return result
