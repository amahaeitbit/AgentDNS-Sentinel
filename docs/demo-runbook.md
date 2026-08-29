# Demo runbook

Two paths through AgentDNS Sentinel: a **three-minute** version for a hallway
conversation, and a **ten-minute** version for a scheduled review. Both work
locally or through the dashboard URL printed by `runloop-up`.

## Before the audience joins

Do this **well ahead of time**, not minutes before. On a cold build the
dashboard compiles its frontend, which takes minutes.

```bash
cp .env.example .env                 # replace the values for a shared demo
make demo-ready                      # validate, build, start, wait, smoke-test
```

`make up` now blocks until the control API answers *and* the dashboard is
actually serving, printing what it is waiting on. If something is wrong you will
see it here rather than in front of an audience. `make up-fast` skips the
dashboard wait when you only need the CLI.

For Runloop, export the same token variables in your shell, then run:

```bash
make runloop-setup
# Add RUNLOOP_API_KEY to .env; optionally use authenticated tunnel mode.
make runloop-e2e
```

Keep the printed dashboard URL, `make logs`, and a terminal for the CLI open.
The Runloop evidence lands in `artifacts/` even if you present only the UI.

Rehearse **Reset** once. It restores the starting policy, revives every service,
clears both logs, and lets you run the whole thing again cleanly.

---

## The three-minute path

Lead with the attack, not the architecture. Run one act:

```bash
make demo-security
```

While it runs, say three sentences:

1. Each of these five agents has a fixed identity, and every DNS answer is a
   policy decision made against that identity.
2. The deploy agent holds a deliberately over-broad `*.internal` grant — the
   mistake everyone makes — and is **still** refused `metadata.internal`,
   because deny rules run before the allowlist.
3. The research agent is allowed `*.pypi.org`, and is still refused a
   48-character label under it, because an allowlist alone never catches
   tunnelling.

Land on the decision log: **who asked, for what, what was decided, and why** —
eight scenarios, every one PASS, each backed by its individual checks.

---

## The ten-minute path

1. **Orient (45 seconds).** Start with the
   **[real-world architecture](agentdns-sentinel-reference-architecture.png)**.
   Solid paths run in the demo; dashed paths are the production integrations.
   Then the **Live topology**: five agents with fixed identity, allowlist, quota
   and running tally; the six-stage policy pipeline; the services with health
   and whether that health came from a probe or an operator override.

2. **Govern (60 seconds).** Run `baseline`, then `isolation`. The researcher
   resolves documentation but not the deployment API; the deployer does. Same
   resolver, same domain, different answer — because identity differs.

3. **Defend (2 minutes — the heart of it).** Run the act:
   `metadata-ssrf` → a wildcard grant does not become a credential-theft path.
   `dns-exfiltration` → an *allowed* domain refused because the name carries a
   payload. `lookalike-domains` → `pypi.org` resolves, `pypi.org.evil.example`
   and `notpypi.org` do not. `supply-chain` → registries scoped per agent.

4. **Contain (2 minutes).** Run `rate-limit`, then `cost-budget`. Filter the log
   to `THROTTLE` and show the two different reasons: `rate_limit_exceeded`
   stops a burst, `budget_exhausted` stops a *polite, sustained* spend against a
   metered API — the one that actually runs up a bill. Point at the **Budget
   alerts** panel: a warning at 80%, critical at 100%, and note that unmetered
   destinations keep working, so the agent can still read its docs.
   If anyone asks about resource safety, run `memory-bounds`: forty invented
   names refused, and not one byte of new per-query state.

5. **Survive (90 seconds).** Run `failover`. API-A is genuinely taken down —
   press **Take down** on the service card to do it by hand — probes evict it,
   DNS sends traffic to API-B only. Then `incident-response`: the responder
   repairs the *service*, not just the health flag.

6. **Operate and prove (90 seconds).** Run `live-policy`, then `audit-trail`.
   Show the DNS decision log and the separate **Control-plane audit trail**. The
   first proves traffic outcomes; the second proves who changed what, and which
   scenario caused it.

Finish with the boundary statement: DNS policy is the visible, fine-grained
internal decision layer. Runloop Network Policy is the outer deny-by-default
enforcement boundary. DNS alone is not presented as a firewall.

---

## Run only what answers the question

If a reviewer arrives with one question, run only what answers it:

```bash
make demo-security         # can an agent reach something it should not?
make demo-availability     # does it keep serving when a dependency fails?
make demo-observability    # can you prove afterwards what happened, and why?
make demo-resources        # do cost and memory stay bounded under abuse?
```

## Questions you should expect

- **"Can't an agent just use a different resolver, or spoof its source IP?"**
  Yes. This is the decision layer; Runloop Network Policy is the enforcement
  layer, and production adds an authenticated egress proxy. Say it first —
  owning it reads far better than being caught by it.
- **"Is source-IP identity production-ready?"** No. The architecture diagram
  marks the path: workload certificates, mTLS/SPIFFE.
- **"What does this cost in latency?"** `python3 scripts/benchmark.py` —
  roughly 6,800 decisions/second with the log queued, p99 around 8 ms. The
  decision log is written off the request path precisely so a DNS answer never
  waits on disk.
- **"What happens when the log can't keep up?"** The queue is bounded, sheds
  its oldest lines, and counts every one. `GET /runtime` shows the depth, the
  shed count, and every other in-memory structure.

## Backup CLI

If the browser is unavailable, the same catalogue remains demonstrable:

```bash
make demo
docker compose exec -T dashboard python scripts/demo.py run defend
docker compose exec -T dashboard python scripts/demo.py run failover incident-response
```

Every command exits non-zero on a failed scenario, so the output is also useful
as a CI gate. On Runloop, `make runloop-demo` downloads timestamped JSON files:
scenario verdicts, DNS decisions, and control-plane actions.

## If something breaks mid-demo

1. **Reset** in the dashboard — fixes almost everything, including a service you
   took down and forgot to restore.
2. `make logs` in the spare terminal names the failing container.
3. Fall back to the CLI path above; it needs no frontend.
4. Last resort: `make down && make up-fast`, then present from the CLI while the
   dashboard rebuilds.

## Reset and clean up

```bash
make down             # local
make runloop-down     # Runloop: also stops billing for the Devbox
```
