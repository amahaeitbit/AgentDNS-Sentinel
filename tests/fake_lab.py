"""An in-process stand-in for the lab, used to test the scenario catalogue.

It drives the real PolicyEngine, so allowlists, quotas, round-robin and
failover behave exactly as they do in the containers; only the network,
the DNS wire format and the mock services are simulated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from agents.incident_logic import failover_verified, incident_action, unhealthy_addresses
from dns_manager.health import HealthMonitor
from dns_manager.policy import PolicyEngine

CONFIG = Path(__file__).parents[1] / "config" / "policies.json"


class FakeLab:
    def __init__(self, config_path: Path = CONFIG):
        self.now = 1000.0
        self.engine = PolicyEngine(str(config_path), clock=lambda: self.now)
        self.reachable: Dict[str, bool] = {a: True for a in self.engine.addresses()}
        self.monitor = HealthMonitor(
            self.engine, probe=lambda address, *_: self.reachable[address]
        )
        self.ips = {agent["name"]: agent["ip"] for agent in self.engine.agents()}
        self.log: List[dict] = []
        self.control_log: List[dict] = []
        self.scenario_id = ""
        self.stamp = 0

    # -- clock ------------------------------------------------------------
    def advance(self, seconds: float = 1.0) -> None:
        self.now += seconds

    async def settle_rate_window(self) -> None:
        self.advance(1.05)

    def _settle(self) -> None:
        """Run enough probe cycles for any threshold to be crossed."""
        for _ in range(max(self.monitor.tracker.failure_threshold,
                           self.monitor.tracker.success_threshold)):
            self.monitor.check_once()

    # -- agent traffic ----------------------------------------------------
    async def results(self, agent, domain, count=1, interval_ms=0):
        results = []
        for _ in range(count):
            decision = self.engine.evaluate(self.ips[agent], domain)
            self.stamp += 1
            self.log.insert(0, {
                "id": self.stamp,
                "created_at": f"2026-01-01T00:00:{self.stamp:02d}.000+00:00",
                "source_ip": self.ips[agent],
                "agent": decision.agent,
                "domain": decision.domain,
                "action": decision.action,
                "answer": decision.answer,
                "reason": decision.reason,
                "latency_ms": 0.4,
            })
            if decision.action == "ALLOW":
                results.append({"ok": True, "answer": decision.answer})
            else:
                results.append({"ok": False, "error": decision.reason})
            self.advance(interval_ms / 1000)
        return results

    async def answers(self, agent, domain, count=1, interval_ms=0):
        results = await self.results(agent, domain, count, interval_ms)
        return [result["answer"] for result in results if result["ok"]]

    async def runtime(self):
        return {
            "policy": self.engine.runtime_stats(),
            "store": {"queued": 0, "queue_capacity": 10000, "dropped": 0},
            "process": {"rss_kb": None},
        }

    async def alerts(self, limit=50):
        return self.engine.alerts.recent(limit)

    async def spend(self):
        return self.engine.spend_report()

    async def reset_budgets(self):
        self.engine.reset_budgets()
        return {"status": "reset"}

    async def reasons_for(self, agent, domain, limit=40):
        wanted = domain.rstrip(".").lower()
        return {
            event["reason"]
            for event in await self.events(limit)
            if event["agent"] == agent and event["domain"] == wanted
        }

    async def investigate(self):
        endpoints = await self.endpoints()
        unhealthy = unhealthy_addresses(endpoints)
        answers = await self.answers("incident-responder", "api.internal", count=3, interval_ms=400)
        return {
            "unhealthy": unhealthy,
            "answers": answers,
            "failover_verified": failover_verified(answers, unhealthy),
            "action": incident_action(endpoints),
        }

    async def remediate(self):
        unhealthy = unhealthy_addresses(await self.endpoints())
        for address in unhealthy:
            await self.inject(address, fail=False)
        still = unhealthy_addresses(await self.endpoints())
        return {
            "restored": [a for a in unhealthy if a not in still],
            "still_unhealthy": still,
            "action": "ENDPOINTS_RESTORED" if unhealthy and not still else "NO_ACTION_NEEDED",
        }

    # -- control plane ----------------------------------------------------
    async def endpoints(self):
        return self.engine.endpoints()

    async def agents(self):
        return self.engine.agents()

    async def events(self, limit=50):
        return self.log[:limit]

    async def control_events(self, limit=50):
        return self.control_log[:limit]

    async def activity(self, action, resource, before=None, after=None):
        self.control_log.insert(
            0,
            {
                "actor": "scenario-runner",
                "scenario_id": self.scenario_id,
                "action": action,
                "resource": resource,
                "before": before,
                "after": after,
            },
        )
        return {"recorded": True}

    async def summary(self):
        counts: Dict[str, int] = {}
        for event in self.log:
            counts[event["action"]] = counts.get(event["action"], 0) + 1
        return {
            "total": len(self.log),
            "allowed": counts.get("ALLOW", 0),
            "blocked": counts.get("BLOCK", 0),
            "throttled": counts.get("THROTTLE", 0),
            "failures": counts.get("SERVFAIL", 0) + counts.get("NXDOMAIN", 0),
        }

    async def inject(self, address, fail):
        self.reachable[address] = not fail
        self._settle()
        await self.activity(
            "FAILURE_INJECTED" if fail else "SERVICE_RECOVERY_REQUESTED",
            f"endpoint:{address}",
            after={"fail": fail},
        )
        return {"address": address, "injected": "fail" if fail else "recover"}

    async def grant(self, agent, domain, allowed):
        self.engine.set_domain_access(agent, domain, allowed)
        await self.activity(
            "ACCESS_GRANTED" if allowed else "ACCESS_REVOKED",
            f"agent:{agent}:{domain}",
            after={"allowed": allowed},
        )
        return {"agent": agent, "domain": domain, "allowed": allowed}

    async def reset(self):
        self.engine.reset()
        self.log.clear()
        self.control_log.clear()
        self.reachable = {a: True for a in self.engine.addresses()}
        await self.activity("LAB_RESET", "lab", after={"status": "reset"})
        return {"status": "reset"}

    async def wait_for_health(self, address, healthy, timeout=15.0):
        self._settle()
        return any(
            endpoint["address"] == address and endpoint["healthy"] == healthy
            for endpoint in await self.endpoints()
        )
