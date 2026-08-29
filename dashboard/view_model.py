"""Turns control-API payloads into the exact rows the dashboard renders.

These are plain functions on plain dictionaries: the Reflex state delegates to
them, so the dashboard's data shaping is unit-tested even though the UI itself
needs a browser.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from . import tokens


def composition(summary: dict) -> list[dict]:
    """The traffic bar's segments, in the validated colour order."""
    total = max(int(summary.get("total", 0) or 0), 0)
    segments = []
    for action, key, color, label, on_fill in tokens.COMPOSITION:
        count = int(summary.get(key, 0) or 0)
        percent = (count / total * 100) if total else 0.0
        segments.append(
            {
                "action": action,
                "label": label,
                "count": count,
                "color": color,
                "on_fill": on_fill,
                "width": f"{percent:.2f}%",
                "share": f"{percent:.0f}%" if total else "—",
                "wide": percent >= tokens.DIRECT_LABEL_MIN_PERCENT,
                "min_width": "4px" if count else "0px",
            }
        )
    return segments


def latest_actions(events: Sequence[dict]) -> dict[str, str]:
    """The most recent decision per agent. `events` is newest-first."""
    latest: dict[str, str] = {}
    for event in events:
        latest.setdefault(event["agent"], event["action"])
    return latest


def agent_rows(agents: Sequence[dict], events: Sequence[dict]) -> list[dict]:
    latest = latest_actions(events)
    rows = []
    for agent in agents:
        action = latest.get(agent["name"], "")
        color, label, _ = tokens.ACTIONS.get(action, tokens.UNKNOWN_ACTION)
        domains = agent.get("allowed_domains") or []
        rows.append(
            {
                "name": agent["name"],
                "ip": agent["ip"],
                "action": action or "NONE",
                "color": color,
                "label": label,
                "domains": ", ".join(domains) if domains else "no domains allowed",
                "quota": f"{agent['requests_per_second']} q/s",
                "requests_total": int(agent.get("requests_total", 0) or 0),
                "allowed": int(agent.get("allowed", 0) or 0),
                "blocked": int(agent.get("blocked", 0) or 0),
                "throttled": int(agent.get("throttled", 0) or 0),
                "tally": _tally(agent),
            }
        )
    return rows


# Control-plane actions, mapped to how they should read and which status they carry.
AUDIT_ACTIONS: dict[str, tuple[str, str]] = {
    "HEALTH_OVERRIDE_SET": ("Health pinned", tokens.WARNING),
    "HEALTH_OVERRIDE_CLEARED": ("Health returned to the probe", tokens.GOOD),
    "FAILURE_INJECTED": ("Service taken down", tokens.CRITICAL),
    "SERVICE_RECOVERY_REQUESTED": ("Service recovery requested", tokens.GOOD),
    "ACCESS_GRANTED": ("Access granted", tokens.WARNING),
    "ACCESS_REVOKED": ("Access revoked", tokens.GOOD),
    "LAB_RESET": ("Lab reset", tokens.NEUTRAL),
}


def describe_change(before, after) -> str:
    """A one-line before/after for the audit row."""
    if before is None and after is None:
        return ""
    if before is None:
        return f"→ {_compact(after)}"
    if after is None:
        return f"{_compact(before)} →"
    return f"{_compact(before)} → {_compact(after)}"


def _compact(value) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={_compact(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(_compact(item) for item in value) or "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def control_event_rows(events: Sequence[dict]) -> list[dict]:
    rows = []
    for event in events:
        action = event.get("action", "")
        label, color = AUDIT_ACTIONS.get(action, (action.replace("_", " ").capitalize(), tokens.NEUTRAL))
        rows.append(
            {
                "action": action,
                "label": label,
                "color": color,
                "actor": event.get("actor", "unknown"),
                "scenario": event.get("scenario_id") or "manual",
                "resource": event.get("resource", ""),
                "change": describe_change(event.get("before"), event.get("after")),
                "created_at": event.get("created_at", ""),
            }
        )
    return rows


def _tally(agent: dict) -> str:
    """`12 queries · 9 allowed · 2 blocked · 1 throttled`, skipping the zeros."""
    total = int(agent.get("requests_total", 0) or 0)
    if not total:
        return "no queries yet"
    parts = [f"{total} queries"]
    for key, label in (("allowed", "allowed"), ("blocked", "blocked"), ("throttled", "throttled")):
        count = int(agent.get(key, 0) or 0)
        if count:
            parts.append(f"{count} {label}")
    return " · ".join(parts)


ALERT_SEVERITY = {
    "critical": (tokens.CRITICAL, "Critical"),
    "warning": (tokens.WARNING, "Warning"),
}


def alert_rows(alerts: Sequence[dict]) -> list[dict]:
    """Notifications about agents overspending, newest first."""
    rows = []
    for alert in alerts:
        color, label = ALERT_SEVERITY.get(
            alert.get("severity", ""), (tokens.NEUTRAL, "Notice")
        )
        rows.append(
            {
                "agent": alert.get("agent", "unknown"),
                "severity": alert.get("severity", ""),
                "label": label,
                "color": color,
                "message": alert.get("message", ""),
                "usage": f"{alert.get('spent', 0):g} / {alert.get('limit', 0):g} units",
                "percent": f"{alert.get('percent', 0):.0f}%",
            }
        )
    return rows


def spend_rows(spend: Sequence[dict]) -> list[dict]:
    """Per-agent budget usage, for the meter beside each agent."""
    rows = []
    for row in spend:
        percent = float(row.get("percent", 0) or 0)
        exhausted = bool(row.get("exhausted"))
        color = tokens.CRITICAL if exhausted else tokens.WARNING if percent >= 80 else tokens.GOOD
        rows.append(
            {
                "agent": row.get("agent", ""),
                "percent": percent,
                "width": f"{min(percent, 100):.0f}%",
                "color": color,
                "label": f"{row.get('spent', 0):g} / {row.get('limit', 0):g} units in {row.get('window_seconds', 0)}s",
                "exhausted": exhausted,
            }
        )
    return rows


def endpoint_rows(endpoints: Sequence[dict]) -> list[dict]:
    rows = []
    for endpoint in endpoints:
        healthy = bool(endpoint["healthy"])
        rows.append(
            {
                "domain": endpoint["domain"],
                "address": endpoint["address"],
                "healthy": healthy,
                "color": tokens.GOOD if healthy else tokens.CRITICAL,
                "label": "Healthy" if healthy else "Down",
                "source": "operator override" if endpoint.get("overridden") else "health probe",
                "action_label": "Take down" if healthy else "Restore",
                # What the button should ask for: fail a healthy one, revive a failed one.
                "fail": healthy,
            }
        )
    return rows


def health_summary(endpoints: Sequence[dict]) -> str:
    healthy = sum(1 for endpoint in endpoints if endpoint["healthy"])
    return f"{healthy}/{len(endpoints)} healthy"


def act_rows(stage_sections: Iterable[tuple], verdicts: dict) -> list[dict]:
    """One row per act, carrying how much of it has run and passed."""
    rows = []
    for index, (key, title, subtitle, scenarios) in enumerate(stage_sections):
        results = [verdicts.get(item.id, "") for item in scenarios]
        passed = sum(1 for verdict in results if verdict == "PASS")
        ran = sum(1 for verdict in results if verdict)
        rows.append(
            {
                "key": key,
                "index": index + 1,
                "title": title,
                "subtitle": subtitle,
                "color": tokens.ACT_COLORS[index % len(tokens.ACT_COLORS)],
                "total": len(scenarios),
                "ran": ran,
                "passed": passed,
                "status": f"{passed}/{len(scenarios)} passed" if ran else "not run",
                "complete": ran == len(scenarios) and passed == len(scenarios),
            }
        )
    return rows
