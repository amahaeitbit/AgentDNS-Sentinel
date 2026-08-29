"""Cost budgets and the alerts they raise.

A per-second rate limit stops a burst; it does nothing about an agent that
spends all day calling an expensive API at a polite pace. Destinations carry a
cost weight - a unit can stand for tokens, cents, or calls, whatever the
deployment meters - and each agent spends against a rolling budget.

Unmetered destinations cost nothing, so an agent that has exhausted its model
budget can still read its documentation.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, List, Optional, Tuple

WARNING = "warning"
CRITICAL = "critical"


@dataclass(frozen=True)
class Budget:
    window_seconds: float = 60.0
    max_cost: float = 0.0
    warn_at: float = 0.8

    @classmethod
    def from_config(cls, config: dict | None) -> Optional["Budget"]:
        if not config:
            return None
        max_cost = float(config.get("max_cost", 0) or 0)
        if max_cost <= 0:
            return None
        return cls(
            window_seconds=float(config.get("window_seconds", 60) or 60),
            max_cost=max_cost,
            warn_at=float(config.get("warn_at", 0.8) or 0.8),
        )

    @property
    def warn_threshold(self) -> float:
        return self.max_cost * self.warn_at


@dataclass(frozen=True)
class Alert:
    created_at: float
    agent: str
    kind: str
    severity: str
    message: str
    spent: float
    limit: float

    @property
    def percent(self) -> float:
        return (self.spent / self.limit * 100) if self.limit else 0.0

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "spent": round(self.spent, 2),
            "limit": round(self.limit, 2),
            "percent": round(self.percent, 1),
            "monotonic_at": round(self.created_at, 3),
        }


class AlertCenter:
    """Recent alerts, de-duplicated so one runaway agent is not one alert per query."""

    def __init__(self, cooldown_seconds: float = 30.0, capacity: int = 100):
        self.cooldown_seconds = cooldown_seconds
        self.capacity = capacity
        self._lock = threading.Lock()
        self._alerts: Deque[Alert] = deque(maxlen=capacity)
        self._last_raised: Dict[Tuple[str, str], float] = {}

    def raise_alert(self, alert: Alert) -> bool:
        """Record the alert unless the same kind fired recently. True if recorded."""
        key = (alert.agent, alert.kind)
        with self._lock:
            previous = self._last_raised.get(key)
            if previous is not None and alert.created_at - previous < self.cooldown_seconds:
                return False
            self._last_raised[key] = alert.created_at
            self._alerts.appendleft(alert)
            return True

    def recent(self, limit: int = 50) -> List[dict]:
        with self._lock:
            return [alert.to_dict() for alert in list(self._alerts)[:limit]]

    def clear(self) -> None:
        with self._lock:
            self._alerts.clear()
            self._last_raised.clear()


class BudgetLedger:
    """Rolling per-agent spend, evaluated on the resolver's hot path."""

    def __init__(self, clock: Callable[[], float]):
        self.clock = clock
        self._spend: Dict[str, Deque[Tuple[float, float]]] = {}

    def spent(self, agent: str, window_seconds: float) -> float:
        entries = self._spend.get(agent)
        if not entries:
            return 0.0
        cutoff = self.clock() - window_seconds
        while entries and entries[0][0] <= cutoff:
            entries.popleft()
        return sum(cost for _, cost in entries)

    def would_exceed(self, agent: str, budget: Budget, cost: float) -> bool:
        return self.spent(agent, budget.window_seconds) + cost > budget.max_cost

    def charge(self, agent: str, cost: float) -> float:
        """Record a spend and return the agent's new running total."""
        entries = self._spend.setdefault(agent, deque())
        entries.append((self.clock(), cost))
        return sum(item for _, item in entries)

    def reset(self) -> None:
        self._spend.clear()
