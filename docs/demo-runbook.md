# Demo runbook

This is a seven-minute path through AgentDNS Sentinel. It
works locally or through the dashboard URL printed by `runloop-up`.

## Before the audience joins

```bash
cp .env.example .env                 # replace the values for a shared demo
make demo-ready                      # local: validate, build, and smoke-test
```

For Runloop, export the same token variables in your shell, then run:

```bash
make runloop-setup
# Add RUNLOOP_API_KEY to .env; optionally use authenticated tunnel mode.
make runloop-e2e
```

Keep the printed dashboard URL, `make logs`, and a terminal for the CLI open.
The Runloop evidence lands in `artifacts/` even if you present only the UI.

## The live story

1. **Orient (45 seconds).** Start with the
   **[real-world architecture](agentdns-sentinel-reference-architecture.png)**.
   Solid paths are running in the demo; dashed paths show the production
   integrations. Then show the five rows in **Agent policies**. Point out
   runtime status, fixed sandbox identity, allowlist, QPS budget, request count,
   and last-seen time. Show that service health identifies probe versus manual
   override.
2. **Govern (90 seconds).** Run `baseline`, then `isolation`. The researcher can
   resolve documentation but not the deployment API; the deployer can. Every
   card gives a PASS/FAIL verdict backed by individual checks.
3. **Contain (60 seconds).** Run `rate-limit`. Filter **Live DNS decisions** to
   `THROTTLE`; the load tester is contained without affecting the other roles.
4. **Survive (90 seconds).** Run `failover`, then `incident-response`. API-A is
   genuinely put into failure, probes remove it, DNS sends traffic only to
   API-B, and the responder restores API-A.
5. **Operate and prove (90 seconds).** Run `live-policy`, then `audit-trail`.
   Show the DNS decision table and the separate **Control-plane audit** table.
   The first proves traffic outcomes; the second proves who changed what and
   which scenario caused it.

Finish with the boundary statement: DNS policy is the visible, fine-grained
internal control. Runloop Network Policy is the outer deny-by-default boundary
for non-allowlisted egress. DNS alone is not presented as a firewall.

## Backup CLI

If the browser is unavailable, the same catalogue remains demonstrable:

```bash
make demo
docker compose exec -T dashboard python scripts/demo.py run failover incident-response
```

Every command exits non-zero on a failed scenario, so the output is also useful
as a CI gate. On Runloop, `make runloop-demo` downloads three timestamped JSON
files: scenario verdicts, DNS decisions, and control-plane actions.

## Reset and clean up

Use **Reset** in the dashboard between rehearsals. When finished:

```bash
make down             # local
make runloop-down     # Runloop: also stops billing for the Devbox
```
