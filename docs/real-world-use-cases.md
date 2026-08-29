# Real-world challenges and tool mapping

AgentDNS Sentinel is useful when several autonomous or semi-autonomous agents
share infrastructure but should not share the same network permissions. It
provides a visible decision point between an agent's intent and the services it
is allowed to discover.

## The strongest use case

Consider a software-delivery sandbox containing a researcher, a deployer, and
an incident responder. The researcher needs internal documentation but must not
reach the deployment API. The deployer needs that API, while the responder
needs it only during recovery.

When the researcher tries to resolve `api.internal`, AgentDNS Sentinel returns
`BLOCK`, records the workload identity and policy reason, and shows the event in
the dashboard. The deployer continues to resolve the same domain normally.
This contains a mistaken prompt, compromised tool, or agent hallucination
without stopping the whole sandbox.

## Challenges it addresses

| Operational challenge | AgentDNS Sentinel response | Demonstration |
|---|---|---|
| Agents inherit excessive access | A domain allowlist is evaluated for each agent identity | `isolation` and `egress-governance` |
| A wildcard exposes cloud credentials | Explicit deny rules take precedence over broad grants | `metadata-ssrf` |
| DNS becomes a data-exfiltration channel | Query-shape guards reject suspicious labels before allowlist evaluation | `dns-exfiltration` |
| Agents reach a lookalike dependency | Exact and label-anchored wildcard matching prevents suffix confusion | `lookalike-domains` |
| Every agent can reach every registry | Supply-chain destinations are scoped by agent role | `supply-chain` |
| One agent overwhelms a dependency | Independent per-agent request budgets produce explicit `THROTTLE` decisions | `rate-limit` |
| A polite agent quietly increases cost | Rolling destination-cost budgets warn and stop metered traffic | `cost-budget` |
| A service replica fails | Health probes remove failed endpoints and route to healthy replicas | `failover` |
| Recovery depends on a human noticing | The incident-responder agent observes the failure and restores the service | `incident-response` |
| A temporary grant becomes permanent | Access can be granted and revoked at runtime, with both changes audited | `live-policy` |
| Teams cannot explain agent traffic | Every DNS outcome records agent, source, domain, reason, latency, and time | `audit-trail` |

## How the tools map to the solution

| Tool or component | Responsibility | It does not do |
|---|---|---|
| **AgentDNS policy engine** | Identifies the requesting agent; evaluates deny rules, query safety, domain policy, quota, and cost; then chooses a healthy endpoint | It does not prevent direct-IP or alternate-resolver traffic by itself |
| **Runloop Devbox** | Supplies the isolated, reproducible execution environment for the agents and services | It does not define the fine-grained per-agent DNS rules |
| **Runloop Network Policy** | Provides the outer deny-by-default egress boundary, including protection against raw-IP bypass | It does not provide the AgentDNS decision history or service-aware routing |
| **Reflex dashboard** | Gives operators live topology, scenario controls, policy outcomes, budgets, service health, and audit visibility | It is an operations interface, not the traffic enforcement layer |
| **Control API** | Applies runtime access changes, health overrides, budget resets, and failure injection with actor attribution | It should not be exposed without authentication and authorization |
| **Health monitor** | Probes dependencies, debounces failures, and removes unhealthy endpoints from DNS answers | It is not a full application-performance monitoring system |
| **Evidence store** | Preserves DNS decisions and control-plane changes for demonstration and investigation | The SQLite demo store is not a production SIEM or long-term archive |
| **Five role agents** | Reproduce research, deployment, untrusted, load, and incident-response traffic | They are deterministic integration workloads, not five continuously running LLMs |

## What Reflex contributes

Reflex turns the traffic-control backend into an operator experience. It shows
which agent made a request, whether the request was allowed, blocked, or
throttled, which endpoint was selected, and why. It also runs the fourteen
named scenarios and presents their checks as evidence rather than relying on a
verbal claim.

This separation is intentional:

```text
Runloop        isolates the workload and enforces the outer network boundary
AgentDNS       makes identity-aware DNS, quota, cost, and routing decisions
Reflex         makes those decisions understandable and operable
Evidence store preserves what happened for review
```

## When to use it

AgentDNS Sentinel is a good fit when:

- multiple agents with different roles share a sandbox or CI environment;
- agents call internal services whose access should be restricted by role;
- a team needs request attribution and an auditable reason for every decision;
- traffic bursts or cost from one workload must not harm other workloads;
- services have replicas and agents should route around failures; or
- security reviewers need a repeatable demonstration of agent network policy.

It is not sufficient as a standalone production firewall. DNS can be bypassed
with a raw IP address or another resolver. A production deployment should keep
the Runloop Network Policy boundary, use authenticated workload identity such
as mTLS or SPIFFE, put permitted external traffic through an authenticated L7
egress proxy, and export events to the organization's SIEM.

## Production adoption path

1. Replace fixed source-IP identity with cryptographic workload identity.
2. Store service and control credentials in a secrets manager.
3. Manage policy through version control, review, and approval.
4. Enforce public-service access through an authenticated egress proxy.
5. Export decisions, policy changes, alerts, and health events to telemetry.
6. Use the scenario runner as a CI policy-conformance test before deployment.

The [reference architecture](agentdns-sentinel-reference-architecture.png)
shows the implemented demo path with solid lines and production additions with
dashed lines.
