# Running the lab on Runloop

`scripts/runloop_lab.py` drives the whole lifecycle through the Runloop Python
SDK: the egress boundary, the blueprint, the Devbox, the tunnels, the scenario
run, the evidence, and the teardown.

```bash
make runloop-setup
# Edit .env and replace RUNLOOP_API_KEY with your key.
make runloop-preflight
```

`runloop-setup` creates `.venv`, installs the SDK, writes an ignored `.env`, and
generates unique application tokens. The Runloop key is never generated or
printed; obtain it from your Runloop account and put it only in `.env` or an
exported environment variable. Existing shell variables override `.env`.

## Connect local Codex through Runloop MCP

This optional path lets Codex create and inspect Devboxes directly in addition
to running this project's scripted SDK flow:

```bash
npm install -g @runloop/rl-cli
make runloop-mcp-setup
```

`scripts/runloop_mcp.py` loads only this project's ignored `.env` and then
executes `rli mcp start`. This avoids putting `RUNLOOP_API_KEY` in
`~/.codex/config.toml`, `~/.zshrc`, or a command-line argument. Restart Codex
after registration. Verify later with:

```bash
make runloop-mcp-check
```

## The flow

```text
policy ──> blueprint ──> up ──> demo ──> snapshot ──> down
  │            │          │       │          │
  │            │          │       │          └─ reopen this exact lab later
  │            │          │       └─ fourteen scenarios, verdicts + evidence files
  │            │          └─ Devbox + tunnels + Compose lab, ready to click
  │            └─ reusable image built from this repository
  └─ Runloop Network Policy: the non-bypassable outer egress boundary
```

One command runs all of it and leaves the dashboard available:

```bash
make runloop-e2e
```

Or step through it, which is what you want for a live demonstration:

```bash
make runloop-policy       # once per account
make runloop-blueprint    # once per base-image change
make runloop-up           # prints the dashboard tunnel URL
make runloop-demo         # runs the catalogue, saves artifacts/
make runloop-status       # what is running right now
make runloop-snapshot     # freeze the lab as it stands
make runloop-down         # stop paying for it
```

`up` writes the Devbox id and tunnel URLs to `.runloop/lab.json`, so every later
command needs no arguments. Pass `--devbox-id` to target a different one.

## Two boundaries, not one

This is the part worth showing to a security reviewer.

```text
┌─ Runloop Network Policy ─────────────────────────────────────┐
│  Devbox egress: build allowlist only. Enforced outside guest,│
│  so non-allowlisted destinations cannot be bypassed via raw   │
│  IP, another resolver, or a compromised agent.                │
│                                                               │
│   ┌─ DNS manager (this project) ──────────────────────────┐   │
│   │  Per-agent identity, allowlists, quotas, health-based │   │
│   │  failover, and a decision log. Fine-grained, in-band, │   │
│   │  and changeable at runtime — but advisory: it decides │   │
│   │  what agents *resolve*, not what they *can reach*.    │   │
│   └───────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

`runloop_lab/spec.py::network_policy_spec` builds the outer layer: `allow_all`
off, devbox-to-devbox off, and an explicit hostname allowlist covering only what
building the lab needs — container registries, Debian packages, PyPI, and the
Node/Bun toolchain Reflex compiles its frontend with. General public-internet egress and
devbox-to-devbox traffic are denied, but the explicitly allowlisted build hosts
remain reachable at runtime. The fine-grained DNS decisions you watch in the
dashboard govern the lab's internal service names; the outer policy is what
prevents arbitrary non-allowlisted egress and raw-IP bypasses.

Skip it with `--no-policy` if your account already applies one, or if a tight
allowlist is blocking a build you are debugging.

## Startup cost

The blueprint runs `docker compose build --pull` as a setup command, so the
service images are baked into it. A Devbox created from that blueprint starts
the lab from a warm image cache:

```text
blueprint build   pull base images, pip install, build 4 service images   (once)
up                docker compose up -d                                     (every launch)
```

`up` therefore does **not** pass `--build`. After changing a Dockerfile or a
dependency, either rebuild the blueprint, or pass `--rebuild-images` to rebuild
inside the running Devbox:

```bash
python scripts/runloop_lab.py up --rebuild-images
```

## Blueprint versus code sync

The blueprint is the reusable image: the Docker-in-Docker base plus this
repository at `/workspace/agentdns-sentinel`. It is built from a real build context
(the repo is uploaded as a storage object first), so `COPY . .` in the root
`Dockerfile` works exactly as it does locally.

`up` then syncs your current working tree over the top before starting Compose.
That means:

- **Changed a scenario or a policy?** Just `up` again. No blueprint rebuild.
- **Changed the base image or system packages?** Rebuild with `blueprint`.

Both paths exclude `.git`, `.env`, `.venv`, `.web`, `__pycache__`, `artifacts/`
and `.runloop/` — see `runloop_lab/spec.py::is_excluded`. Secrets are passed as
environment variables and are never uploaded in the source archive.

## Evidence

`demo` runs the catalogue *inside* the Devbox and brings the results back:

```text
artifacts/20260829T142211Z-scenarios.json    verdicts and every check
artifacts/20260829T142211Z-dns-events.json   the raw DNS decision log
artifacts/20260829T142211Z-control-events.json scenario/operator actions
```

The command exits non-zero if any scenario failed, so it drops straight into CI
as an agent-network conformance test.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `RUNLOOP_API_KEY` | — | Required. Read by the SDK. |
| `RUNLOOP_BLUEPRINT` | `agentdns-sentinel` | Blueprint name |
| `RUNLOOP_DEVBOX_NAME` | `agentdns-sentinel-demo` | Devbox name |
| `RUNLOOP_NETWORK_POLICY` | `agentdns-sentinel-egress` | Network policy name |
| `RUNLOOP_WORKDIR` | `/workspace/agentdns-sentinel` | Where the lab lives in the Devbox |
| `RUNLOOP_TUNNEL_AUTH` | `open` | Set to `authenticated` for a private demo |
| `RUNLOOP_KEEP_ALIVE_SECONDS` | `3600` | Automatic shutdown timer |
| `RUNLOOP_CPU_CORES` | `4` | Devbox CPU |
| `RUNLOOP_MEMORY_GB` | `8` | Devbox memory |
| `RUNLOOP_DISK_GB` | `32` | Devbox disk |
| `RUNLOOP_ARCHITECTURE` | `x86_64` | Devbox architecture |
| `CONTROL_TOKEN` | `demo-control-token` | Bearer token for the DNS control API |
| `SERVICE_CONTROL_TOKEN` | `demo-service-control-token` | Token used for failure injection against mock services |
| `RESEARCHER_AGENT_TOKEN` | `demo-researcher-token` | Researcher HTTP API token |
| `DEPLOYER_AGENT_TOKEN` | `demo-deployer-token` | Deployer HTTP API token |
| `UNTRUSTED_AGENT_TOKEN` | `demo-untrusted-token` | Untrusted-agent HTTP API token |
| `LOAD_TESTER_AGENT_TOKEN` | `demo-load-tester-token` | Load-tester HTTP API token |
| `INCIDENT_RESPONDER_AGENT_TOKEN` | `demo-incident-responder-token` | Incident-responder HTTP API token |

The `demo-*` defaults make a disposable walkthrough one-command. Set every
token to a unique random value before using an open tunnel or sharing the lab.
For a private presentation, also set `RUNLOOP_TUNNEL_AUTH=authenticated`.

## Cleaning up

Devboxes shut down on their own after `RUNLOOP_KEEP_ALIVE_SECONDS`, but do not
rely on it during a demo:

```bash
make runloop-status   # anything of mine still running?
make runloop-down     # stop it and clear local state
```
