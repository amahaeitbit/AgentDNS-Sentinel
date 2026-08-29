"""Executes the scenario catalogue against a running lab."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, Iterable, List

import httpx

from .scenarios import SCENARIOS, Check, Scenario, ScenarioResult, get_scenario

DEFAULT_CONTROL_API = os.getenv("CONTROL_API", "http://dns-manager:8053")
DEFAULT_CONTROL_TOKEN = os.getenv("CONTROL_TOKEN", "demo-control-token")
RATE_WINDOW_SETTLE_SECONDS = 1.05
DEFAULT_AGENT_URLS: Dict[str, str] = {
    "researcher": os.getenv("RESEARCHER_URL", "http://researcher:9000"),
    "deployer": os.getenv("DEPLOYER_URL", "http://deployer:9000"),
    "untrusted": os.getenv("UNTRUSTED_URL", "http://untrusted:9000"),
    "load-tester": os.getenv("LOAD_TESTER_URL", "http://load-tester:9000"),
    "incident-responder": os.getenv(
        "INCIDENT_RESPONDER_URL", "http://incident-responder:9000"
    ),
}
DEFAULT_AGENT_TOKENS: Dict[str, str] = {
    "researcher": os.getenv("RESEARCHER_AGENT_TOKEN", "demo-researcher-token"),
    "deployer": os.getenv("DEPLOYER_AGENT_TOKEN", "demo-deployer-token"),
    "untrusted": os.getenv("UNTRUSTED_AGENT_TOKEN", "demo-untrusted-token"),
    "load-tester": os.getenv("LOAD_TESTER_AGENT_TOKEN", "demo-load-tester-token"),
    "incident-responder": os.getenv(
        "INCIDENT_RESPONDER_AGENT_TOKEN", "demo-incident-responder-token"
    ),
}


class Lab:
    """A small, readable client for the lab's control and agent APIs."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        control_api: str = DEFAULT_CONTROL_API,
        agent_urls: Dict[str, str] | None = None,
        control_token: str = DEFAULT_CONTROL_TOKEN,
        agent_tokens: Dict[str, str] | None = None,
        actor: str = "scenario-runner",
    ):
        self.client = client
        self.control_api = control_api.rstrip("/")
        self.agent_urls = dict(agent_urls or DEFAULT_AGENT_URLS)
        self.control_token = control_token
        self.agent_tokens = dict(agent_tokens or DEFAULT_AGENT_TOKENS)
        self.actor = actor
        self.scenario_id = ""

    def _control_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.control_token}",
            "X-Actor": self.actor,
        }
        if self.scenario_id:
            headers["X-Scenario-ID"] = self.scenario_id
        return headers

    def _agent_headers(self, agent: str) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.agent_tokens[agent]}"}
        if self.scenario_id:
            headers["X-Scenario-ID"] = self.scenario_id
        return headers

    async def settle_rate_window(self) -> None:
        """Let traffic from the preceding scenario age out of the QPS window."""
        await asyncio.sleep(RATE_WINDOW_SETTLE_SECONDS)

    # -- agent traffic ----------------------------------------------------
    async def results(
        self, agent: str, domain: str, count: int = 1, interval_ms: int = 0
    ) -> List[dict]:
        response = await self.client.post(
            f"{self.agent_urls[agent]}/query",
            params={"domain": domain, "count": count, "interval_ms": interval_ms},
            headers=self._agent_headers(agent),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["results"]

    async def answers(
        self, agent: str, domain: str, count: int = 1, interval_ms: int = 0
    ) -> List[str]:
        results = await self.results(agent, domain, count, interval_ms)
        return [result["answer"] for result in results if result["ok"]]

    async def investigate(self) -> dict:
        response = await self.client.post(
            f"{self.agent_urls['incident-responder']}/investigate",
            headers=self._agent_headers("incident-responder"),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    async def remediate(self) -> dict:
        response = await self.client.post(
            f"{self.agent_urls['incident-responder']}/remediate",
            headers=self._agent_headers("incident-responder"),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    # -- control plane ----------------------------------------------------
    async def _get(self, path: str, **params) -> object:
        response = await self.client.get(
            f"{self.control_api}{path}",
            params=params,
            headers=self._control_headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, payload: dict | None = None) -> object:
        response = await self.client.post(
            f"{self.control_api}{path}",
            json=payload,
            headers=self._control_headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    async def endpoints(self) -> List[dict]:
        return await self._get("/endpoints")

    async def agents(self) -> List[dict]:
        return await self._get("/agents")

    async def summary(self) -> dict:
        return await self._get("/summary")

    async def events(self, limit: int = 50) -> List[dict]:
        return await self._get("/events", limit=limit)

    async def reset_budgets(self) -> dict:
        return await self._post("/budgets/reset")

    async def alerts(self, limit: int = 50) -> List[dict]:
        return await self._get("/alerts", limit=limit)

    async def spend(self) -> List[dict]:
        return await self._get("/spend")

    async def reasons_for(self, agent: str, domain: str, limit: int = 40) -> set:
        """Why the resolver decided as it did, straight from the decision log."""
        wanted = domain.rstrip(".").lower()
        return {
            event["reason"]
            for event in await self.events(limit)
            if event["agent"] == agent and event["domain"] == wanted
        }

    async def control_events(self, limit: int = 50) -> List[dict]:
        return await self._get("/control-events", limit=limit)

    async def activity(
        self,
        action: str,
        resource: str,
        before: object = None,
        after: object = None,
    ) -> dict:
        return await self._post(
            "/activity",
            {
                "action": action,
                "resource": resource,
                "before": before,
                "after": after,
            },
        )

    async def agent_statuses(self) -> Dict[str, dict]:
        async def inspect(name: str, url: str) -> tuple[str, dict]:
            try:
                response = await self.client.get(f"{url}/health", timeout=3)
                payload = response.json() if response.status_code == 200 else {}
                return name, {
                    "runtime_status": "ONLINE" if response.status_code == 200 else "OFFLINE",
                    "runtime_detail": payload.get("status", f"HTTP {response.status_code}"),
                }
            except httpx.HTTPError as error:
                return name, {"runtime_status": "OFFLINE", "runtime_detail": str(error)}

        return dict(
            await asyncio.gather(
                *(inspect(name, url) for name, url in self.agent_urls.items())
            )
        )

    async def inject(self, address: str, fail: bool) -> dict:
        return await self._post(f"/endpoints/{address}/inject", {"fail": fail})

    async def grant(self, agent: str, domain: str, allowed: bool) -> dict:
        return await self._post(
            f"/agents/{agent}/access", {"domain": domain, "allowed": allowed}
        )

    async def reset(self) -> dict:
        return await self._post("/reset")

    async def wait_for_health(
        self, address: str, healthy: bool, timeout: float = 15.0
    ) -> bool:
        """Poll until the probe agrees about an endpoint, or give up."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for endpoint in await self.endpoints():
                if endpoint["address"] == address and endpoint["healthy"] == healthy:
                    return True
            await asyncio.sleep(0.5)
        return False

    async def wait_until_ready(self, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        targets = [f"{self.control_api}/health"] + [
            f"{url}/health" for url in self.agent_urls.values()
        ]
        while time.monotonic() < deadline:
            try:
                responses = await asyncio.gather(
                    *(self.client.get(target, timeout=3) for target in targets)
                )
                if all(response.status_code == 200 for response in responses):
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
        return False


async def run_scenario(scenario: Scenario | str, lab: Lab) -> ScenarioResult:
    if isinstance(scenario, str):
        scenario = get_scenario(scenario)
    result = ScenarioResult(
        id=scenario.id,
        title=scenario.title,
        challenge=scenario.challenge,
        stage=scenario.stage_title,
    )
    previous_scenario = getattr(lab, "scenario_id", "")
    if hasattr(lab, "scenario_id"):
        lab.scenario_id = scenario.id
    try:
        if hasattr(lab, "settle_rate_window"):
            await lab.settle_rate_window()
        if hasattr(lab, "activity"):
            await lab.activity("SCENARIO_STARTED", f"scenario:{scenario.id}")
        headline, checks = await scenario.run(lab)
        result.headline = headline
        result.checks = list(checks)
    except Exception as error:  # a broken scenario must not hide the others
        result.error = f"{type(error).__name__}: {error}"
        result.checks = [Check("Scenario completed", False, result.error)]
    finally:
        if hasattr(lab, "activity"):
            try:
                await lab.activity(
                    "SCENARIO_FINISHED",
                    f"scenario:{scenario.id}",
                    after={"verdict": result.verdict},
                )
            except Exception:
                pass
        if hasattr(lab, "scenario_id"):
            lab.scenario_id = previous_scenario
    return result


async def run_scenarios(
    lab: Lab, scenarios: Iterable[Scenario] = SCENARIOS
) -> List[ScenarioResult]:
    """Run scenarios in catalogue order; they build on one another deliberately."""
    return [await run_scenario(scenario, lab) for scenario in scenarios]
