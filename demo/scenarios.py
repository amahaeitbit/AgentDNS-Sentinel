"""The demonstration catalogue.

Each scenario is one *shape*: a challenge from the project brief, the capability
that answers it, the traffic that exercises it, and the checks that turn the run
into evidence. The dashboard and `scripts/demo.py` both drive this catalogue, so
the story a reviewer sees in the browser is the story the CLI verifies.
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Sequence, Tuple

# Every scenario belongs to one act in this narrative sequence.
STAGES: Tuple[Tuple[str, str, str], ...] = (
    ("govern", "Govern", "Decide who may talk to what."),
    ("defend", "Defend", "Close the egress paths attackers actually use."),
    ("contain", "Contain", "Stop one agent from hurting the others."),
    ("survive", "Survive", "Keep serving when a dependency fails."),
    ("operate", "Operate", "Change policy and prove what happened."),
)
STAGE_TITLES = {key: title for key, title, _ in STAGES}

# The second axis: what a scenario proves. Acts tell the story in order;
# capabilities let a reviewer ask one question and run only what answers it.
CAPABILITIES: Tuple[Tuple[str, str, str], ...] = (
    ("security", "Security", "Can an agent reach something it should not?"),
    ("availability", "Availability", "Does the lab keep serving when a dependency fails?"),
    ("observability", "Observability", "Can you prove afterwards what happened, and why?"),
    ("resources", "Resource validity", "Do cost and memory stay bounded under abuse?"),
)
CAPABILITY_TITLES = {key: title for key, title, _ in CAPABILITIES}

DOCS = "172.28.0.21"
API_A = "172.28.0.22"
API_B = "172.28.0.23"


@dataclass(frozen=True)
class Check:
    label: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"label": self.label, "passed": self.passed, "detail": self.detail}


@dataclass
class ScenarioResult:
    id: str
    title: str
    challenge: str
    stage: str = ""
    headline: str = ""
    checks: List[Check] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def verdict(self) -> str:
        if self.error:
            return "ERROR"
        return "PASS" if self.passed else "FAIL"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "stage": self.stage,
            "title": self.title,
            "challenge": self.challenge,
            "headline": self.headline,
            "verdict": self.verdict,
            "passed": self.passed,
            "error": self.error,
            "checks": [check.to_dict() for check in self.checks],
        }


Outcome = Tuple[str, List[Check]]
Runner = Callable[["Lab"], Awaitable[Outcome]]  # noqa: F821 - Lab lives in runner.py


@dataclass(frozen=True)
class Scenario:
    id: str
    stage: str
    proves: Tuple[str, ...]
    title: str
    challenge: str
    capability: str
    watch_for: str
    run: Runner

    @property
    def stage_title(self) -> str:
        return STAGE_TITLES[self.stage]

    @property
    def proves_titles(self) -> Tuple[str, ...]:
        return tuple(CAPABILITY_TITLES[key] for key in self.proves)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "stage": self.stage,
            "stage_title": self.stage_title,
            "proves": list(self.proves),
            "title": self.title,
            "challenge": self.challenge,
            "capability": self.capability,
            "watch_for": self.watch_for,
        }


# ---------------------------------------------------------------------------
# Scenario bodies. Each takes a Lab (see demo/runner.py) and returns a headline
# plus the checks that back it up.
# ---------------------------------------------------------------------------


async def _baseline(lab) -> Outcome:
    researcher = await lab.answers("researcher", "docs.internal")
    deployer = await lab.answers("deployer", "api.internal", count=2, interval_ms=80)
    untrusted = await lab.results("untrusted", "docs.internal")
    tester = await lab.answers("load-tester", "docs.internal")
    responder = await lab.investigate()

    checks = [
        Check(
            "Researcher resolves docs.internal",
            researcher == [DOCS],
            f"answers={researcher or 'denied'}",
        ),
        Check(
            "Deployer resolves api.internal",
            all(answer in {API_A, API_B} for answer in deployer) and len(deployer) == 2,
            f"answers={deployer or 'denied'}",
        ),
        Check(
            "Untrusted agent is refused",
            all(not result["ok"] for result in untrusted),
            "resolver returned REFUSED",
        ),
        Check(
            "Load tester resolves within its quota",
            tester == [DOCS],
            f"answers={tester or 'denied'}",
        ),
        Check(
            "Incident responder confirms a healthy API pool",
            responder.get("action") == "NO_INCIDENT"
            and bool(responder.get("answers")),
            f"action={responder.get('action')}",
        ),
    ]
    return "Every agent acted inside its own identity and policy.", checks


async def _egress_governance(lab) -> Outcome:
    docs = await lab.results("untrusted", "docs.internal")
    api = await lab.results("untrusted", "api.internal")
    events = await lab.events(limit=20)
    denials = [
        event
        for event in events
        if event["agent"] == "untrusted" and event["action"] == "BLOCK"
    ]

    return "The untrusted agent could not resolve a single internal service.", [
        Check("docs.internal denied", all(not r["ok"] for r in docs)),
        Check("api.internal denied", all(not r["ok"] for r in api)),
        Check(
            "Denials are logged with a reason",
            len(denials) >= 2
            and all(event["reason"] == "domain_not_allowed" for event in denials[:2]),
            f"{len(denials)} BLOCK records, reason=domain_not_allowed",
        ),
    ]


async def _isolation(lab) -> Outcome:
    research_attempt = await lab.results("researcher", "api.internal")
    deploy_attempt = await lab.answers("deployer", "api.internal")

    return "The research agent cannot reach the deployment API; the deployer can.", [
        Check(
            "Researcher blocked from the deployment API",
            all(not result["ok"] for result in research_attempt),
        ),
        Check(
            "Deployer still reaches the deployment API",
            bool(deploy_attempt) and deploy_attempt[0] in {API_A, API_B},
            f"answer={deploy_attempt[:1]}",
        ),
    ]


async def _metadata_ssrf(lab) -> Outcome:
    """The deploy agent's allowlist is deliberately over-broad: `*.internal`."""
    agents = {agent["name"]: agent for agent in await lab.agents()}
    allowlist = agents["deployer"]["allowed_domains"]
    over_broad = any(pattern.startswith("*.") for pattern in allowlist)

    metadata = await lab.results("deployer", "metadata.internal")
    admin = await lab.results("deployer", "admin.internal")
    legitimate = await lab.answers("deployer", "api.internal")
    reasons = await lab.reasons_for("deployer", "metadata.internal")

    return (
        "A wildcard allowlist did not become a route to the metadata service.",
        [
            Check(
                "The deploy agent really is allowed a wildcard",
                over_broad,
                f"allowlist={allowlist}",
            ),
            Check(
                "The cloud metadata name is refused anyway",
                all(not result["ok"] for result in metadata),
            ),
            Check("The admin plane is refused too", all(not result["ok"] for result in admin)),
            Check(
                "The denial is recorded as a deny-rule hit, not a missing allowlist entry",
                "domain_denied" in reasons,
                f"reasons={sorted(reasons)}",
            ),
            Check(
                "Legitimate internal traffic still resolves",
                bool(legitimate) and legitimate[0] in {API_A, API_B},
                f"api.internal={legitimate[:1]}",
            ),
        ],
    )


async def _dns_exfiltration(lab) -> Outcome:
    """Payload smuggled in a subdomain of a domain the agent may resolve."""
    payload = "5ca1ab1e" * 6  # 48 characters, as a tunnelling client would send
    tunnelled = await lab.results("researcher", f"{payload}.pypi.org")
    deep = await lab.results("researcher", "a.b.c.d.e.f.g.h.i.pypi.org")
    normal = await lab.answers("researcher", "pypi.org")
    reasons = await lab.reasons_for("researcher", f"{payload}.pypi.org")

    return (
        "The allowlist permitted the domain; the query-shape guard stopped the tunnel.",
        [
            Check(
                "The oversized label is refused",
                all(not result["ok"] for result in tunnelled),
                f"{len(payload)}-character label",
            ),
            Check(
                "The reason names the tunnelling guard, not the allowlist",
                "label_too_long" in reasons,
                f"reasons={sorted(reasons)}",
            ),
            Check(
                "A deeply nested name is refused",
                all(not result["ok"] for result in deep),
            ),
            Check(
                "The same domain still resolves normally",
                normal == [DOCS],
                f"pypi.org={normal}",
            ),
        ],
    )


async def _lookalike_domains(lab) -> Outcome:
    """`*.pypi.org` must not be fooled by names that merely contain it."""
    apex = await lab.answers("researcher", "pypi.org")
    suffixed = await lab.results("researcher", "pypi.org.evil.example")
    prefixed = await lab.results("researcher", "notpypi.org")

    return (
        "Wildcard matching is anchored on a label boundary, so lookalikes fail.",
        [
            Check(
                "The real package mirror resolves",
                apex == [DOCS],
                f"pypi.org={apex}",
            ),
            Check(
                "An attacker domain ending in the allowed name is refused",
                all(not result["ok"] for result in suffixed),
                "pypi.org.evil.example",
            ),
            Check(
                "A domain merely containing the allowed name is refused",
                all(not result["ok"] for result in prefixed),
                "notpypi.org",
            ),
        ],
    )


async def _supply_chain(lab) -> Outcome:
    """Package registries are scoped to the agents that actually build."""
    researcher_pypi = await lab.answers("researcher", "pypi.org")
    researcher_npm = await lab.results("researcher", "registry.npmjs.org")
    deployer_npm = await lab.answers("deployer", "registry.npmjs.org")
    untrusted_pypi = await lab.results("untrusted", "pypi.org")

    return (
        "Each agent reaches the registries its job needs, and no others.",
        [
            Check(
                "The research agent reaches the Python mirror",
                researcher_pypi == [DOCS],
                f"pypi.org={researcher_pypi}",
            ),
            Check(
                "It cannot reach the npm registry",
                all(not result["ok"] for result in researcher_npm),
            ),
            Check(
                "The deploy agent can",
                deployer_npm == [DOCS],
                f"registry.npmjs.org={deployer_npm}",
            ),
            Check(
                "The untrusted agent reaches no registry at all",
                all(not result["ok"] for result in untrusted_pypi),
            ),
        ],
    )


async def _rate_limit(lab) -> Outcome:
    before = await lab.summary()
    results = await lab.results("load-tester", "docs.internal", count=20)
    after = await lab.summary()

    succeeded = sum(1 for result in results if result["ok"])
    throttled = after["throttled"] - before["throttled"]

    return (
        f"{succeeded} of 20 burst queries were answered; the rest were throttled.",
        [
            Check("Some queries were served", succeeded > 0, f"{succeeded} answered"),
            Check(
                "The burst was throttled",
                throttled > 0,
                f"{throttled} THROTTLE decisions recorded",
            ),
            Check(
                "The agent stayed within its quota",
                succeeded < 20,
                "the 3 queries-per-second limit held",
            ),
        ],
    )


async def _cost_budget(lab) -> Outcome:
    """A polite, sustained spend against a metered API - no burst to catch."""
    await lab.reset_budgets()

    calls = await lab.results("deployer", "api.anthropic.com", count=7, interval_ms=60)
    unmetered = await lab.answers("deployer", "api.internal")
    reasons = await lab.reasons_for("deployer", "api.anthropic.com")
    alerts = [alert for alert in await lab.alerts() if alert["agent"] == "deployer"]
    kinds = {alert["kind"] for alert in alerts}
    spend = {row["agent"]: row for row in await lab.spend()}

    served = sum(1 for call in calls if call["ok"])

    return (
        f"{served} of 7 calls to the metered API were served; the budget stopped the rest.",
        [
            Check(
                "The agent got real work done first",
                0 < served < 7,
                f"{served} calls served before the budget ran out",
            ),
            Check(
                "The refusal names the budget, not the rate limit",
                "budget_exhausted" in reasons,
                f"reasons={sorted(reasons)}",
            ),
            Check(
                "A warning was raised before the budget ran out",
                "budget_warning" in kinds,
                next(
                    (a["message"] for a in alerts if a["kind"] == "budget_warning"),
                    "no warning alert",
                ),
            ),
            Check(
                "A critical alert was raised when it did",
                "budget_exhausted" in kinds,
                f"{len(alerts)} alerts for this agent",
            ),
            Check(
                "The spend report shows the agent at its limit",
                bool(spend.get("deployer", {}).get("exhausted")),
                f"spend={spend.get('deployer')}",
            ),
            Check(
                "Unmetered work carries on",
                bool(unmetered) and unmetered[0] in {API_A, API_B},
                f"api.internal={unmetered[:1]}",
            ),
        ],
    )


async def _memory_bounds(lab) -> Outcome:
    """Unbounded input must not become unbounded state.

    A tunnelling client invents a new name for every query. If any per-query
    state were keyed by the queried name, that alone would exhaust the
    resolver's memory - no allowlist bypass required.
    """
    before = await lab.runtime()
    payload = "7f" * 24  # 48 characters: refused by the query-shape guard
    names = [f"{payload}-{index}.pypi.org" for index in range(40)]
    batches = await asyncio.gather(
        *(lab.results("researcher", name) for name in names)
    )
    after = await lab.runtime()

    refused = sum(1 for batch in batches for result in batch if not result["ok"])
    policy_before, policy_after = before["policy"], after["policy"]
    store_after = after["store"]

    growth = {
        key: policy_after[key] - policy_before[key]
        for key in ("round_robin_keys", "records", "rate_window_entries")
    }

    return (
        f"{len(names)} never-before-seen names refused, with no new per-query state.",
        [
            Check(
                "Every invented name was refused",
                refused == len(names),
                f"{refused}/{len(names)} refused",
            ),
            Check(
                "No state is keyed by the queried name",
                growth["round_robin_keys"] == 0 and growth["records"] == 0,
                f"round-robin keys +{growth['round_robin_keys']}, records +{growth['records']}",
            ),
            Check(
                "Refused queries do not consume the agent's quota",
                growth["rate_window_entries"] == 0,
                f"rate-window entries +{growth['rate_window_entries']}",
            ),
            Check(
                "The decision-log queue stayed inside its bound",
                store_after["queued"] <= store_after["queue_capacity"],
                f"{store_after['queued']}/{store_after['queue_capacity']} queued, "
                f"{store_after['dropped']} shed",
            ),
            Check(
                "The alert buffer is capped, not growing",
                policy_after["alerts"]["held"] <= policy_after["alerts"]["capacity"],
                f"{policy_after['alerts']['held']}/{policy_after['alerts']['capacity']} alerts held",
            ),
        ],
    )


async def _load_balance(lab) -> Outcome:
    answers = await lab.answers("deployer", "api.internal", count=6, interval_ms=120)
    distinct = sorted(set(answers))

    return f"api.internal spread across {len(distinct)} endpoints.", [
        Check("Six queries were answered", len(answers) == 6, f"answers={answers}"),
        Check(
            "Both API replicas received traffic",
            distinct == [API_A, API_B],
            f"endpoints={distinct}",
        ),
    ]


async def _failover(lab) -> Outcome:
    await lab.inject(API_A, fail=True)
    detected = await lab.wait_for_health(API_A, healthy=False, timeout=15)
    answers = await lab.answers("deployer", "api.internal", count=4, interval_ms=120)
    investigation = await lab.investigate()

    return (
        "API-A really went down; DNS steered every query to API-B.",
        [
            Check(
                "The probe detected the failure",
                detected,
                f"{API_A} marked unhealthy by the health monitor",
            ),
            Check(
                "No query was sent to the failed endpoint",
                bool(answers) and set(answers) == {API_B},
                f"answers={answers}",
            ),
            Check(
                "The incident responder confirmed failover",
                bool(investigation.get("failover_verified")),
                f"action={investigation.get('action')}",
            ),
        ],
    )


async def _incident_response(lab) -> Outcome:
    endpoints = await lab.endpoints()
    if all(endpoint["healthy"] for endpoint in endpoints):
        await lab.inject(API_A, fail=True)
        await lab.wait_for_health(API_A, healthy=False, timeout=15)

    remediation = await lab.remediate()
    recovered = await lab.wait_for_health(API_A, healthy=True, timeout=15)
    answers = await lab.answers("deployer", "api.internal", count=4, interval_ms=120)

    return (
        "The incident responder repaired the service and traffic returned to both replicas.",
        [
            Check(
                "The responder restored the failed endpoint",
                API_A in remediation.get("restored", []),
                f"restored={remediation.get('restored')}",
            ),
            Check("The probe sees the endpoint as healthy again", recovered),
            Check(
                "Round-robin resumed across both replicas",
                set(answers) == {API_A, API_B},
                f"answers={answers}",
            ),
        ],
    )


async def _live_policy(lab) -> Outcome:
    before = await lab.results("researcher", "api.internal")
    await lab.grant("researcher", "api.internal", allowed=True)
    during = await lab.answers("researcher", "api.internal")
    await lab.grant("researcher", "api.internal", allowed=False)
    after = await lab.results("researcher", "api.internal")

    return "Access was granted and revoked without restarting the resolver.", [
        Check("Denied before the grant", all(not result["ok"] for result in before)),
        Check(
            "Allowed immediately after the grant",
            bool(during) and during[0] in {API_A, API_B},
            f"answer={during[:1]}",
        ),
        Check("Denied again after the revoke", all(not result["ok"] for result in after)),
    ]


async def _audit_trail(lab) -> Outcome:
    await lab.answers("researcher", "docs.internal")
    await lab.results("untrusted", "docs.internal")
    events = await lab.events(limit=25)
    controls = await lab.control_events(limit=25)

    required = {"created_at", "agent", "source_ip", "domain", "action", "reason"}
    complete = [event for event in events if required <= set(event) and all(
        event[field] not in (None, "") for field in required
    )]
    actions = sorted({event["action"] for event in events})
    attributed_controls = [
        event
        for event in controls
        if event.get("actor") and event.get("action") and event.get("resource")
    ]

    return (
        f"The last {len(events)} decisions are attributable to an agent and a reason.",
        [
            Check("Decisions were recorded", len(events) >= 2, f"{len(events)} records"),
            Check(
                "Every record is fully attributed",
                len(complete) == len(events),
                "agent, source IP, domain, decision, reason and timestamp present",
            ),
            Check(
                "Both allow and deny decisions are visible",
                {"ALLOW", "BLOCK"} <= set(actions),
                f"actions={actions}",
            ),
            Check(
                "Control actions are attributed",
                bool(attributed_controls)
                and len(attributed_controls) == len(controls),
                f"{len(attributed_controls)} attributed control records",
            ),
        ],
    )


SCENARIOS: Tuple[Scenario, ...] = (
    Scenario(
        id="baseline",
        proves=('security', 'observability'),
        stage="govern",
        title="Baseline: identity-bound agents",
        challenge="Unclear agent responsibility",
        capability="Fixed identity and policy per agent",
        watch_for="Five agents, five different outcomes, from one resolver.",
        run=_baseline,
    ),
    Scenario(
        id="egress-governance",
        proves=('security',),
        stage="govern",
        title="Egress governance",
        challenge="Agents accessing unauthorized services",
        capability="Per-agent DNS allowlists",
        watch_for="Every untrusted lookup ends in BLOCK / domain_not_allowed.",
        run=_egress_governance,
    ),
    Scenario(
        id="isolation",
        proves=('security',),
        stage="govern",
        title="Multi-agent isolation",
        challenge="A research agent reaching deployment systems",
        capability="Role-scoped allowlists inside one shared sandbox",
        watch_for="The same domain is allowed for one agent and denied for another.",
        run=_isolation,
    ),
    Scenario(
        id="metadata-ssrf",
        proves=('security',),
        stage="defend",
        title="Cloud metadata is unreachable",
        challenge="An over-broad allowlist becomes a credential-theft path",
        capability="Deny rules that beat any allowlist",
        watch_for="A wildcard-allowed agent is still refused metadata.internal.",
        run=_metadata_ssrf,
    ),
    Scenario(
        id="dns-exfiltration",
        proves=('security', 'resources'),
        stage="defend",
        title="DNS tunnelling blocked",
        challenge="Data leaving through DNS queries themselves",
        capability="Query-shape limits on label length, depth and total length",
        watch_for="An allowed domain, refused because the name carries a payload.",
        run=_dns_exfiltration,
    ),
    Scenario(
        id="lookalike-domains",
        proves=('security',),
        stage="defend",
        title="Lookalike domains rejected",
        challenge="Typosquats and suffix confusion against an allowlist",
        capability="Wildcards anchored on a label boundary",
        watch_for="pypi.org resolves; pypi.org.evil.example and notpypi.org do not.",
        run=_lookalike_domains,
    ),
    Scenario(
        id="supply-chain",
        proves=('security',),
        stage="defend",
        title="Package registries, scoped per agent",
        challenge="Every agent reaching every package registry",
        capability="Role-scoped registry access",
        watch_for="The same registry is allowed for one agent and denied for another.",
        run=_supply_chain,
    ),
    Scenario(
        id="rate-limit",
        proves=('availability', 'resources'),
        stage="contain",
        title="Traffic quota under burst",
        challenge="One agent generating excessive traffic",
        capability="Agent-specific rate limits",
        watch_for="THROTTLE decisions appear once the per-second quota is spent.",
        run=_rate_limit,
    ),
    Scenario(
        id="cost-budget",
        proves=('resources', 'observability'),
        stage="contain",
        title="Runaway API cost stopped",
        challenge="An agent quietly burning through a metered API budget",
        capability="Per-destination cost weights against a rolling per-agent budget",
        watch_for="A warning at 80%, a refusal at 100%, and free destinations unaffected.",
        run=_cost_budget,
    ),
    Scenario(
        id="memory-bounds",
        stage="contain",
        proves=("resources", "availability"),
        title="Memory bounded under abuse",
        challenge="Unbounded input becoming unbounded state",
        capability="State keyed by agent and configured record, never by the query",
        watch_for="Forty invented names, and not one byte of new per-query state.",
        run=_memory_bounds,
    ),
    Scenario(
        id="load-balance",
        proves=('availability',),
        stage="contain",
        title="Round-robin distribution",
        challenge="Uneven traffic distribution",
        capability="Round-robin load balancing",
        watch_for="Consecutive answers for api.internal alternate between replicas.",
        run=_load_balance,
    ),
    Scenario(
        id="failover",
        proves=('availability',),
        stage="survive",
        title="Endpoint failure and failover",
        challenge="Service endpoint failure",
        capability="Health-based DNS failover",
        watch_for="API-A is really taken down; answers switch to API-B only.",
        run=_failover,
    ),
    Scenario(
        id="incident-response",
        proves=('availability', 'observability'),
        stage="survive",
        title="Automated incident response",
        challenge="Slow incident recovery",
        capability="An agent that detects the outage and restores the endpoint",
        watch_for="The responder repairs the service, not just the health flag.",
        run=_incident_response,
    ),
    Scenario(
        id="live-policy",
        proves=('security', 'observability'),
        stage="operate",
        title="Live policy update",
        challenge="Policy testing without redeploys",
        capability="Grant and revoke access at runtime",
        watch_for="The same agent flips from BLOCK to ALLOW and back with no restart.",
        run=_live_policy,
    ),
    Scenario(
        id="audit-trail",
        proves=('observability',),
        stage="operate",
        title="Audit trail",
        challenge="Security audits and agent-network debugging",
        capability="Timestamped agent, domain, decision and reason records",
        watch_for="Each row answers who asked, for what, and why it was allowed.",
        run=_audit_trail,
    ),
)

SCENARIOS_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}


def scenarios_by_stage() -> List[Tuple[str, str, str, List[Scenario]]]:
    """The catalogue grouped into its acts, in narrative order."""
    return [
        (key, title, subtitle, [s for s in SCENARIOS if s.stage == key])
        for key, title, subtitle in STAGES
    ]


def scenarios_by_capability() -> List[Tuple[str, str, str, List[Scenario]]]:
    """The catalogue grouped by what each scenario proves."""
    return [
        (key, title, question, [s for s in SCENARIOS if key in s.proves])
        for key, title, question in CAPABILITIES
    ]


def get_scenario(scenario_id: str) -> Scenario:
    try:
        return SCENARIOS_BY_ID[scenario_id]
    except KeyError:
        known = ", ".join(SCENARIOS_BY_ID)
        raise KeyError(f"Unknown scenario '{scenario_id}'. Known scenarios: {known}")


def resolve_selection(names: Sequence[str]) -> List[Scenario]:
    """Turn a mix of 'all', act names and scenario ids into an ordered run list.

    Order always follows the catalogue, and a scenario named twice runs once,
    so `run survive failover` is the act, not the act plus a repeat.
    """
    stage_keys = {key for key, _, _ in STAGES}
    capability_keys = {key for key, _, _ in CAPABILITIES}
    selected: set = set()
    for name in names:
        if name == "all":
            return list(SCENARIOS)
        if name in stage_keys:
            selected.update(s.id for s in SCENARIOS if s.stage == name)
        elif name in capability_keys:
            selected.update(s.id for s in SCENARIOS if name in s.proves)
        else:
            selected.add(get_scenario(name).id)
    return [scenario for scenario in SCENARIOS if scenario.id in selected]
