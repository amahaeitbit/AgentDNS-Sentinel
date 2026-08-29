from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Tuple

from .budget import Alert, AlertCenter, BudgetLedger, CRITICAL, WARNING
from .rules import CompiledPolicy, normalize_domain


@dataclass(frozen=True)
class Decision:
    agent: str
    domain: str
    action: str
    answer: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class PolicyEngine:
    """Thread-safe policy, rate-limit, and endpoint selection engine."""

    def __init__(self, config_path: str, clock: Callable[[], float] = time.monotonic):
        self.config_path = Path(config_path)
        self.clock = clock
        self._lock = threading.RLock()
        self._requests: Dict[str, Deque[float]] = defaultdict(deque)
        self._round_robin: Dict[str, int] = defaultdict(int)
        # Probe results are ground truth; an operator override wins while it is set.
        self._probe_health: Dict[str, bool] = {}
        self._overrides: Dict[str, bool] = {}
        self._config: dict = {}
        # Rebuilt whenever the configuration changes; read without the lock.
        self._compiled = CompiledPolicy()
        self.budgets = BudgetLedger(clock)
        self.alerts = AlertCenter()
        self.reload()

    @staticmethod
    def normalize_domain(domain: str) -> str:
        return normalize_domain(domain)

    def _recompile(self) -> None:
        """Rebuild the immutable snapshot the resolver reads on every query."""
        self._compiled = CompiledPolicy.build(self._config)

    def reload(self) -> None:
        with self._lock:
            self._config = json.loads(self.config_path.read_text())
            for addresses in self._config.get("records", {}).values():
                for address in addresses:
                    self._probe_health.setdefault(address, True)
            self._recompile()

    @property
    def ttl(self) -> int:
        return self._compiled.ttl

    @property
    def health_check(self) -> dict:
        defaults = {
            "enabled": True,
            "port": 8080,
            "path": "/health",
            "interval_seconds": 1.0,
            "timeout_seconds": 1.0,
            "failure_threshold": 2,
            "success_threshold": 1,
        }
        with self._lock:
            defaults.update(self._config.get("health_check", {}))
        return defaults

    def addresses(self) -> List[str]:
        with self._lock:
            return sorted(
                {
                    address
                    for addresses in self._config.get("records", {}).values()
                    for address in addresses
                }
            )

    def _effective_health(self, address: str) -> bool:
        if address in self._overrides:
            return self._overrides[address]
        return self._probe_health.get(address, True)

    def _rate_limited(self, agent: str, limit: int) -> bool:
        now = self.clock()
        requests = self._requests[agent]
        while requests and now - requests[0] >= 1.0:
            requests.popleft()
        if len(requests) >= max(limit, 1):
            return True
        requests.append(now)
        return False

    def evaluate(self, source_ip: str, domain: str) -> Decision:
        """Decide one query.

        Order matters: deny rules and the tunnelling guard are checked before
        the allowlist, so an agent cannot reach a forbidden name, or smuggle
        data out through a name it is otherwise allowed to resolve.
        """
        domain = normalize_domain(domain)
        policy = self._compiled  # immutable snapshot; safe to read unlocked

        rules = policy.agents_by_ip.get(source_ip)
        if rules is None:
            return Decision("unknown", domain, "BLOCK", reason="unknown_agent")

        if policy.denies(domain):
            return Decision(rules.name, domain, "BLOCK", reason="domain_denied")
        if rules.denies(domain):
            return Decision(rules.name, domain, "BLOCK", reason="domain_denied_for_agent")

        violation = policy.guard.violation(domain)
        if violation:
            return Decision(rules.name, domain, "BLOCK", reason=violation)

        if not rules.allows(domain):
            return Decision(rules.name, domain, "BLOCK", reason="domain_not_allowed")

        addresses = policy.records.get(domain)

        with self._lock:
            if self._rate_limited(rules.name, rules.limit):
                return Decision(rules.name, domain, "THROTTLE", reason="rate_limit_exceeded")

            cost = policy.costs.cost_of(domain)
            if cost and rules.budget:
                if self.budgets.would_exceed(rules.name, rules.budget, cost):
                    self._raise_budget_alert(rules, CRITICAL, "budget_exhausted")
                    return Decision(rules.name, domain, "THROTTLE", reason="budget_exhausted")
                spent = self.budgets.charge(rules.name, cost)
                if spent >= rules.budget.warn_threshold:
                    self._raise_budget_alert(rules, WARNING, "budget_warning", spent)

            if not addresses:
                return Decision(rules.name, domain, "NXDOMAIN", reason="record_not_found")

            healthy = [address for address in addresses if self._effective_health(address)]
            if not healthy:
                return Decision(rules.name, domain, "SERVFAIL", reason="no_healthy_endpoint")

            index = self._round_robin[domain] % len(healthy)
            self._round_robin[domain] += 1

        return Decision(rules.name, domain, "ALLOW", answer=healthy[index], reason="policy_allowed")

    def _raise_budget_alert(
        self, rules, severity: str, kind: str, spent: float | None = None
    ) -> None:
        """Notify that an agent is burning through its allowance.

        Cheap by design: this runs inside the resolver's lock, so it only
        appends to an in-memory ring buffer.
        """
        budget = rules.budget
        if spent is None:
            spent = self.budgets.spent(rules.name, budget.window_seconds)
        window = int(budget.window_seconds)
        if kind == "budget_exhausted":
            message = (
                f"{rules.name} has spent its {budget.max_cost:g}-unit budget for the "
                f"last {window}s; metered destinations are refused until it recovers."
            )
        else:
            message = (
                f"{rules.name} has used {spent:g} of {budget.max_cost:g} units in the "
                f"last {window}s."
            )
        self.alerts.raise_alert(
            Alert(
                created_at=self.clock(),
                agent=rules.name,
                kind=kind,
                severity=severity,
                message=message,
                spent=spent,
                limit=budget.max_cost,
            )
        )

    def reset_budgets(self) -> None:
        """Clear spend and alerts without touching policy or health."""
        with self._lock:
            self.budgets.reset()
            self.alerts.clear()

    def spend_report(self) -> List[dict]:
        """What each agent has spent inside its own budget window."""
        report = []
        for rules in self._compiled.agents_by_name.values():
            if not rules.budget:
                continue
            with self._lock:
                spent = self.budgets.spent(rules.name, rules.budget.window_seconds)
            report.append(
                {
                    "agent": rules.name,
                    "spent": round(spent, 2),
                    "limit": rules.budget.max_cost,
                    "window_seconds": int(rules.budget.window_seconds),
                    "percent": round(spent / rules.budget.max_cost * 100, 1),
                    "exhausted": spent >= rules.budget.max_cost,
                }
            )
        return report

    def set_endpoint_health(self, address: str, healthy: bool) -> None:
        """Pin an endpoint's health, overriding whatever the probes report."""
        with self._lock:
            if address not in self._probe_health:
                raise KeyError(address)
            self._overrides[address] = healthy

    def clear_endpoint_override(self, address: str) -> None:
        """Hand the endpoint back to probe-driven health."""
        with self._lock:
            if address not in self._probe_health:
                raise KeyError(address)
            self._overrides.pop(address, None)

    def record_probe(self, address: str, healthy: bool) -> None:
        with self._lock:
            self._probe_health[address] = healthy

    def set_domain_access(self, agent: str, domain: str, allowed: bool) -> None:
        domain = self.normalize_domain(domain)
        with self._lock:
            agents = self._config.get("agents", {})
            if agent not in agents:
                raise KeyError(agent)
            allowlist = agents[agent].setdefault("allowed_domains", [])
            normalized = [self.normalize_domain(item) for item in allowlist]
            if allowed and domain not in normalized:
                allowlist.append(domain)
            elif not allowed:
                agents[agent]["allowed_domains"] = [
                    item for item in allowlist if self.normalize_domain(item) != domain
                ]
            self._recompile()

    def agents(self) -> List[dict]:
        with self._lock:
            return [
                {
                    "name": name,
                    "ip": policy["ip"],
                    "allowed_domains": list(policy.get("allowed_domains", [])),
                    "denied_domains": list(policy.get("denied_domains", [])),
                    "budget": policy.get("budget"),
                    "requests_per_second": int(policy.get("requests_per_second", 1)),
                }
                for name, policy in self._config.get("agents", {}).items()
            ]

    def endpoints(self) -> List[dict]:
        with self._lock:
            result = []
            for domain, addresses in self._config.get("records", {}).items():
                for address in addresses:
                    overridden = address in self._overrides
                    result.append(
                        {
                            "domain": domain,
                            "address": address,
                            "healthy": self._effective_health(address),
                            "probe_healthy": self._probe_health.get(address, True),
                            "overridden": overridden,
                            "source": "override" if overridden else "probe",
                        }
                    )
            return result

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self._round_robin.clear()
            self._probe_health.clear()
            self._overrides.clear()
            self.budgets.reset()
            self.alerts.clear()
            self.reload()
