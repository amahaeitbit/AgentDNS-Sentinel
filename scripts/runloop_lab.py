#!/usr/bin/env python3
"""Run AgentDNS Sentinel on Runloop.

The flow, in order:

    policy      create the Devbox egress boundary (Runloop Network Policy)
    blueprint   build the reusable lab image from this repository
    up          start a Devbox, sync the code, bring the lab up, print tunnels
    redeploy    sync changes into the current Devbox and rebuild the lab
    demo        run the scenario catalogue inside the Devbox and save evidence
    snapshot    capture the disk so the exact run can be reopened later
    down        shut the Devbox down

    e2e         all of the above in one command

Requires `make runloop-setup` and a RUNLOOP_API_KEY in the ignored `.env` file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from runloop_lab.config import LabConfig, load_env_file  # noqa: E402
from runloop_lab.lab import LabError, RunloopLab  # noqa: E402
from runloop_lab.state import LabState  # noqa: E402

BOLD, DIM, GREEN, RED, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[0m"


def step(number: int, total: int, text: str) -> None:
    print(f"\n{BOLD}[{number}/{total}] {text}{RESET}")


def load_sdk():
    try:
        from runloop_api_client import AsyncRunloopSDK
    except ImportError:
        raise SystemExit(
            "The Runloop SDK is not installed. Run:\n"
            "    make runloop-setup"
        )
    return AsyncRunloopSDK()


def print_tunnels(urls: dict) -> None:
    print(f"\n{BOLD}Open the lab:{RESET}")
    for label, url in urls.items():
        print(f"  {label:<12} {url}")


def print_results(results: list) -> int:
    stage = ""
    for result in results:
        if result.get("stage") and result["stage"] != stage:
            stage = result["stage"]
            print(f"\n{BOLD}── {stage}{RESET}")
        mark = GREEN + "PASS" + RESET if result["passed"] else RED + result["verdict"] + RESET
        print(f"  [{mark}] {result['title']}")
        print(f"         {DIM}{result['headline']}{RESET}")
        for check in result["checks"]:
            if not check["passed"]:
                print(f"         {RED}- {check['label']}{RESET} {check['detail']}")
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    colour = GREEN if passed == total else RED
    print(f"\n{colour}{passed}/{total} scenarios passed{RESET}")
    return 0 if passed == total else 1


async def resolve_devbox(lab: RunloopLab, state: LabState, devbox_id: str | None):
    return lab.devbox(devbox_id or state.require_devbox())


# -- commands --------------------------------------------------------------


async def cmd_policy(lab: RunloopLab, state: LabState, args) -> int:
    state.network_policy_id = await lab.ensure_network_policy()
    state.save()
    return 0


async def cmd_blueprint(lab: RunloopLab, state: LabState, args) -> int:
    policy_id = None if args.no_policy else (state.network_policy_id or await lab.ensure_network_policy())
    state.network_policy_id = policy_id
    state.blueprint_id = await lab.build_blueprint(REPO_ROOT, policy_id)
    state.save()
    return 0


async def cmd_up(lab: RunloopLab, state: LabState, args) -> int:
    total = 4
    step(1, total, "Applying the egress boundary")
    policy_id = None if args.no_policy else (state.network_policy_id or await lab.ensure_network_policy())
    state.network_policy_id = policy_id

    step(2, total, "Ensuring the Blueprint and creating the Devbox")
    blueprint_name = None
    if not args.no_blueprint:
        state.blueprint_id = await lab.ensure_blueprint(REPO_ROOT, policy_id)
        blueprint_name = lab.config.blueprint_name
        state.save()
    devbox = await lab.create_devbox(
        blueprint_name=blueprint_name,
        network_policy_id=policy_id,
    )
    state.devbox_id = devbox.id
    state.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state.save()

    urls = await lab.tunnel_urls(devbox)
    state.tunnels = urls
    state.save()

    step(3, total, "Syncing the working tree")
    await lab.sync_code(devbox, REPO_ROOT)

    step(4, total, "Starting the lab")
    await lab.start_lab(devbox, urls["dashboard"], rebuild=getattr(args, "rebuild_images", False))

    print_tunnels(urls)
    print(f"\n{DIM}Next: make runloop-demo{RESET}")
    return 0


async def cmd_demo(lab: RunloopLab, state: LabState, args) -> int:
    devbox = await resolve_devbox(lab, state, args.devbox_id)
    results = await lab.run_demo(devbox, args.scenarios, reset=not args.no_reset)
    if args.json:
        print(json.dumps(results, indent=2))
        return 0 if all(result["passed"] for result in results) else 1

    exit_code = print_results(results)
    written = await lab.collect_evidence(devbox, results, REPO_ROOT / "artifacts")
    if written:
        print(f"\n{BOLD}Evidence saved:{RESET}")
        for label, path in written.items():
            print(f"  {label:<12} {path.relative_to(REPO_ROOT)}")
    if state.tunnels:
        print_tunnels(state.tunnels)
    return exit_code


async def cmd_redeploy(lab: RunloopLab, state: LabState, args) -> int:
    devbox = await resolve_devbox(lab, state, args.devbox_id)
    urls = state.tunnels or await lab.tunnel_urls(devbox)
    await lab.sync_code(devbox, REPO_ROOT)
    await lab.start_lab(devbox, urls["dashboard"], rebuild=getattr(args, "rebuild_images", False))
    state.tunnels = urls
    state.save()
    print_tunnels(urls)
    return 0


async def cmd_logs(lab: RunloopLab, state: LabState, args) -> int:
    devbox = await resolve_devbox(lab, state, args.devbox_id)
    print(await lab.logs(devbox, tail=args.tail, service=args.service))
    return 0


async def cmd_status(lab: RunloopLab, state: LabState, args) -> int:
    devboxes = await lab.list_lab_devboxes()
    if not devboxes:
        print("No running lab Devboxes.")
        return 0
    for entry in devboxes:
        marker = " <- current" if entry["id"] == state.devbox_id else ""
        print(f"{entry['id']}  {entry['status']}  {entry['name'] or '-'}{marker}")
    if state.devbox_id:
        devbox = lab.devbox(state.devbox_id)
        print(f"\n{BOLD}Compose services{RESET}")
        print(await lab.compose_status(devbox))
        if state.tunnels:
            print_tunnels(state.tunnels)
    return 0


async def cmd_snapshot(lab: RunloopLab, state: LabState, args) -> int:
    devbox = await resolve_devbox(lab, state, args.devbox_id)
    state.snapshot_id = await lab.snapshot(devbox, args.message)
    state.save()
    print(
        f"{DIM}Reopen this exact lab with: "
        f"sdk.devbox.create_from_snapshot('{state.snapshot_id}'){RESET}"
    )
    return 0


async def cmd_down(lab: RunloopLab, state: LabState, args) -> int:
    devbox = await resolve_devbox(lab, state, args.devbox_id)
    if not args.keep_containers:
        await lab.stop_lab(devbox)
    await lab.shutdown(devbox)
    state.clear()
    print("Devbox shut down and local state cleared.")
    return 0


async def cmd_e2e(lab: RunloopLab, state: LabState, args) -> int:
    try:
        if args.rebuild:
            await cmd_blueprint(lab, state, args)
        await cmd_up(lab, state, args)
        exit_code = await cmd_demo(lab, state, args)
        if args.snapshot:
            await cmd_snapshot(lab, state, args)
        if args.keep:
            print(
                f"\n{DIM}Devbox left running. Shut it down with: "
                f"make runloop-down{RESET}"
            )
        return exit_code
    finally:
        if not args.keep and state.devbox_id:
            try:
                await cmd_down(lab, state, args)
            except Exception as error:
                print(
                    f"{RED}Automatic Devbox cleanup failed: {error}. "
                    "Run `make runloop-down` immediately."
                    f"{RESET}",
                    file=sys.stderr,
                )


COMMANDS = {
    "policy": cmd_policy,
    "blueprint": cmd_blueprint,
    "up": cmd_up,
    "redeploy": cmd_redeploy,
    "demo": cmd_demo,
    "logs": cmd_logs,
    "status": cmd_status,
    "snapshot": cmd_snapshot,
    "down": cmd_down,
    "e2e": cmd_e2e,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--devbox-id", default=None, help="target a specific Devbox")
        return sub

    add("policy", "create or reuse the Runloop network policy")

    blueprint = add("blueprint", "build the reusable lab blueprint")
    blueprint.add_argument("--no-policy", action="store_true")

    up = add("up", "start a Devbox and bring the lab up")
    up.add_argument("--no-policy", action="store_true", help="skip the network policy")
    up.add_argument("--no-blueprint", action="store_true", help="use the default Runloop image")
    up.add_argument(
        "--rebuild-images",
        action="store_true",
        help="rebuild the service images (the blueprint already built them)",
    )

    add("redeploy", "sync changes into the current Devbox and rebuild the lab")

    demo = add("demo", "run the scenario catalogue inside the Devbox")
    demo.add_argument("scenarios", nargs="*", default=["all"])
    demo.add_argument("--no-reset", action="store_true")
    demo.add_argument("--json", action="store_true")

    logs = add("logs", "show Compose logs from inside the Devbox")
    logs.add_argument("--tail", type=int, default=200)
    logs.add_argument("--service", default=None)

    add("status", "list this project's Devboxes and Compose services")

    snapshot = add("snapshot", "snapshot the Devbox disk")
    snapshot.add_argument("--message", default="AgentDNS Sentinel demo run")

    down = add("down", "shut the Devbox down")
    down.add_argument("--keep-containers", action="store_true")

    e2e = add("e2e", "policy, up, demo, snapshot and down in one flow")
    e2e.add_argument("scenarios", nargs="*", default=["all"])
    e2e.add_argument("--rebuild", action="store_true", help="rebuild the blueprint first")
    e2e.add_argument(
        "--rebuild-images",
        action="store_true",
        help="rebuild the service images inside the Devbox",
    )
    e2e.add_argument("--no-policy", action="store_true")
    e2e.add_argument("--no-blueprint", action="store_true")
    e2e.add_argument("--no-reset", action="store_true")
    e2e.add_argument("--json", action="store_true")
    e2e.add_argument("--snapshot", action="store_true", help="snapshot before shutting down")
    e2e.add_argument("--keep", action="store_true", help="leave the Devbox running")
    e2e.add_argument("--keep-containers", action="store_true")
    e2e.add_argument("--message", default="AgentDNS Sentinel demo run")
    return parser


async def main() -> int:
    load_env_file(REPO_ROOT / ".env")
    args = build_parser().parse_args()
    sdk = load_sdk()
    lab = RunloopLab(sdk, LabConfig.from_env())
    state = LabState.load()
    try:
        return await COMMANDS[args.command](lab, state, args)
    except LabError as error:
        print(f"{RED}{error}{RESET}", file=sys.stderr)
        return 1
    finally:
        await sdk.aclose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted. The Devbox is still running; "
              "shut it down with `make runloop-down`.")
        raise SystemExit(130)
