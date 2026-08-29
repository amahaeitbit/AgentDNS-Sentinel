"""Dashboard state: talks to the control API, runs scenarios, derives view data.

Everything the UI needs is computed here, so the components stay declarative
and no logic has to be expressed as JavaScript-side Var arithmetic.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx
import reflex as rx

from demo.runner import DEFAULT_AGENT_URLS, Lab
from demo.runner import run_scenario as execute_scenario
from demo.scenarios import SCENARIOS, scenarios_by_stage

from . import theme, view_model

CONTROL_API = os.getenv("CONTROL_API", "http://dns-manager:8053")
AGENT_URLS = DEFAULT_AGENT_URLS
ACTOR = os.getenv("LAB_ACTOR", "dashboard")
POLL_SECONDS = 3.0
EMPTY_SUMMARY = {"total": 0, "allowed": 0, "blocked": 0, "throttled": 0, "failures": 0}
ACTION_FILTERS = ["ALL", "ALLOW", "BLOCK", "THROTTLE", "SERVFAIL", "NXDOMAIN"]


class DashboardState(rx.State):
    # -- data from the control API
    events: list[dict] = []
    control_events: list[dict] = []
    alerts: list[dict] = []
    spend: list[dict] = []
    agents: list[dict] = []
    endpoints: list[dict] = []
    summary: dict = dict(EMPTY_SUMMARY)

    # -- connection
    lab_online: bool = False
    last_refresh: str = ""
    auto_refresh: bool = True
    polling: bool = False

    # -- interaction
    message: str = "Run an act, or the whole demonstration, and watch the decisions land."
    busy: bool = False
    running_id: str = ""
    action_filter: str = "ALL"

    # -- scenario results
    verdicts: dict[str, str] = {}
    progress_done: int = 0
    progress_total: int = 0
    result_id: str = ""
    result_title: str = ""
    result_stage: str = ""
    result_challenge: str = ""
    result_headline: str = ""
    result_verdict: str = ""
    result_checks: list[dict] = []

    # ---------------------------------------------------------------- data
    @staticmethod
    def _lab(client: httpx.AsyncClient) -> Lab:
        """Every call goes through the authenticated lab client."""
        return Lab(client, CONTROL_API, AGENT_URLS, actor=ACTOR)

    async def _fetch(self, client: httpx.AsyncClient | None = None) -> dict | None:
        try:
            if client is not None:
                return await self._lab(client).dashboard_snapshot()
            async with httpx.AsyncClient(timeout=8) as owned_client:
                return await self._lab(owned_client).dashboard_snapshot()
        except Exception:
            return None

    def _apply_snapshot(self, data: dict | None) -> None:
        if data is None:
            self.lab_online = False
            return
        self.events = data["events"]
        self.summary = data["summary"]
        self.agents = data["agents"]
        self.endpoints = data["endpoints"]
        self.control_events = data["control_events"]
        self.alerts = data["alerts"]
        self.spend = data["spend"]
        self.lab_online = True
        self.last_refresh = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    async def refresh(self):
        self._apply_snapshot(await self._fetch())

    @rx.event(background=True)
    async def poll(self):
        """Keep the page live while the switch is on."""
        async with self:
            if self.polling:
                return
            self.polling = True
        try:
            while True:
                await asyncio.sleep(POLL_SECONDS)
                async with self:
                    if not self.auto_refresh:
                        return
                    skip = self.busy
                if skip:
                    continue
                data = await self._fetch()
                async with self:
                    self._apply_snapshot(data)
        finally:
            async with self:
                self.polling = False

    @rx.event
    def toggle_auto_refresh(self, value: bool):
        self.auto_refresh = value
        if value:
            return DashboardState.poll

    def set_filter(self, action: str):
        self.action_filter = action

    # ----------------------------------------------------------- scenarios
    def _apply_result(self, result) -> None:
        self.verdicts = {**self.verdicts, result.id: result.verdict}
        self.result_id = result.id
        self.result_title = result.title
        self.result_stage = result.stage
        self.result_challenge = result.challenge
        self.result_headline = result.headline or result.error
        self.result_verdict = result.verdict
        self.result_checks = [check.to_dict() for check in result.checks]

    @rx.event(background=True)
    async def run_scenario(self, scenario_id: str):
        async with self:
            if self.busy:
                return
            scenario = next(item for item in SCENARIOS if item.id == scenario_id)
            self.busy = True
            self.running_id = scenario_id
            self.progress_total = 0
            self.result_checks = []
            self.result_verdict = ""
            self.message = f"{scenario.title} — {scenario.watch_for}"

        async with httpx.AsyncClient() as client:
            result = await execute_scenario(scenario_id, self._lab(client))

        async with self:
            self._apply_result(result)
            self.message = f"{result.title}: {result.verdict}"
            self.busy = False
            self.running_id = ""
            self._apply_snapshot(await self._fetch())

    @rx.event(background=True)
    async def run_stage(self, stage_key: str):
        scenarios = [item for item in SCENARIOS if item.stage == stage_key]
        await self._run_many(scenarios, f"act: {scenarios[0].stage_title}")

    @rx.event(background=True)
    async def run_all(self):
        await self._run_many(list(SCENARIOS), "the full demonstration")

    async def _run_many(self, scenarios, label: str) -> None:
        async with self:
            if self.busy:
                return
            self.busy = True
            self.progress_done = 0
            self.progress_total = len(scenarios)
            for scenario in scenarios:
                self.verdicts.pop(scenario.id, None)
            self.verdicts = dict(self.verdicts)
            self.message = f"Running {label}..."

        passed = 0
        async with httpx.AsyncClient() as client:
            lab = self._lab(client)
            # A dashboard run must be repeatable even when the previous CLI or UI
            # demonstration left rolling quotas and budgets populated.
            await lab.reset()
            for scenario in scenarios:
                async with self:
                    self.running_id = scenario.id
                result = await execute_scenario(scenario, lab)
                data = await self._fetch(client)
                async with self:
                    self._apply_result(result)
                    self.progress_done += 1
                    self._apply_snapshot(data)
                passed += 1 if result.passed else 0

        async with self:
            self.message = f"Finished {label}: {passed}/{len(scenarios)} scenarios passed."
            self.busy = False
            self.running_id = ""

    @rx.event(background=True)
    async def set_endpoint_failure(self, address: str, fail: bool):
        """Take a real service down, or bring it back, and wait for the probe."""
        async with self:
            if self.busy:
                return
            self.busy = True
            self.message = (
                f"Taking {address} offline..." if fail else f"Restoring {address}..."
            )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                await self._lab(client).inject(address, fail)
            for _ in range(20):
                data = await self._fetch()
                async with self:
                    self._apply_snapshot(data)
                    matched = [
                        endpoint
                        for endpoint in self.endpoints
                        if endpoint["address"] == address
                        and endpoint["healthy"] is not fail
                    ]
                if matched:
                    break
                await asyncio.sleep(0.5)
            async with self:
                self.message = (
                    f"The health monitor marked {address} unhealthy; DNS is routing around it."
                    if fail
                    else f"{address} is back in the pool."
                )
        finally:
            async with self:
                self.busy = False

    @rx.event(background=True)
    async def reset_demo(self):
        async with self:
            self.busy = True
            self.message = "Restoring the starting policy and reviving every service..."
        async with httpx.AsyncClient(timeout=60) as client:
            await self._lab(client).reset()
        data = await self._fetch()
        async with self:
            self.verdicts = {}
            self.progress_done = 0
            self.progress_total = 0
            self.result_title = ""
            self.result_headline = ""
            self.result_verdict = ""
            self.result_checks = []
            self.summary = dict(EMPTY_SUMMARY)
            self.control_events = []
            self.alerts = []
            self.spend = []
            self._apply_snapshot(data)
            self.message = "Lab reset. Run an act, or the whole demonstration."
            self.busy = False

    # ------------------------------------------------------- derived views
    @rx.var
    def filtered_events(self) -> list[dict]:
        if self.action_filter == "ALL":
            return self.events
        return [event for event in self.events if event["action"] == self.action_filter]

    @rx.var
    def composition(self) -> list[dict]:
        return view_model.composition(self.summary)

    @rx.var
    def has_traffic(self) -> bool:
        return int(self.summary.get("total", 0) or 0) > 0

    @rx.var
    def topology_agents(self) -> list[dict]:
        return view_model.agent_rows(self.agents, self.events)

    @rx.var
    def topology_endpoints(self) -> list[dict]:
        return view_model.endpoint_rows(self.endpoints)

    @rx.var
    def healthy_summary(self) -> str:
        return view_model.health_summary(self.endpoints)

    @rx.var
    def all_healthy(self) -> bool:
        return bool(self.endpoints) and all(e["healthy"] for e in self.endpoints)

    @rx.var
    def acts(self) -> list[dict]:
        return view_model.act_rows(scenarios_by_stage(), self.verdicts)

    @rx.var
    def alert_rows(self) -> list[dict]:
        return view_model.alert_rows(self.alerts)

    @rx.var
    def spend_rows(self) -> list[dict]:
        return view_model.spend_rows(self.spend)

    @rx.var
    def alert_headline(self) -> str:
        critical = [a for a in self.alerts if a.get("severity") == "critical"]
        if critical:
            return f"{len(critical)} agent budget(s) exhausted"
        if self.alerts:
            return f"{len(self.alerts)} budget warning(s)"
        return ""

    @rx.var
    def alert_color(self) -> str:
        if any(a.get("severity") == "critical" for a in self.alerts):
            return theme.CRITICAL
        return theme.WARNING

    @rx.var
    def audit_rows(self) -> list[dict]:
        return view_model.control_event_rows(self.control_events)

    @rx.var
    def scoreboard(self) -> str:
        passed = sum(1 for verdict in self.verdicts.values() if verdict == "PASS")
        return f"{passed}/{len(SCENARIOS)}"

    @rx.var
    def verdict_color(self) -> str:
        return {
            "PASS": theme.GOOD,
            "FAIL": theme.CRITICAL,
            "ERROR": theme.SERIOUS,
        }.get(self.result_verdict, theme.INK_MUTED)
