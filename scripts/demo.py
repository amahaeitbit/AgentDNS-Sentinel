#!/usr/bin/env python3
"""Run the lab's demonstration scenarios and print the evidence.

    python scripts/demo.py list
    python scripts/demo.py run all
    python scripts/demo.py run failover incident-response
    python scripts/demo.py run all --json

The agent and control APIs are internal to the lab network, so run this from
inside the lab:

    docker compose exec dashboard python scripts/demo.py run all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from demo.runner import DEFAULT_CONTROL_API, Lab, run_scenarios  # noqa: E402
from demo.scenarios import STAGES, resolve_selection, scenarios_by_stage  # noqa: E402

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m",
)


def paint(text: str, color: str, enabled: bool) -> str:
    return f"{color}{text}{RESET}" if enabled else text


def print_catalogue(color: bool) -> None:
    print(paint(f"The demonstration, in {len(STAGES)} acts", BOLD, color))
    for index, (_, title, subtitle, scenarios) in enumerate(scenarios_by_stage(), start=1):
        print(f"\n{paint(f'{index}. {title}', BOLD, color)} — {paint(subtitle, DIM, color)}")
        for scenario in scenarios:
            print(f"\n  {paint(scenario.id, BOLD, color)} — {scenario.title}")
            print(f"    {paint('challenge:', DIM, color)}  {scenario.challenge}")
            print(f"    {paint('capability:', DIM, color)} {scenario.capability}")
            print(f"    {paint('watch for:', DIM, color)}  {scenario.watch_for}")


def print_stage_header(title: str, subtitle: str, color: bool) -> None:
    print(f"\n{paint('── ' + title + ' ' + '─' * max(2, 44 - len(title)), BOLD, color)}")
    print(f"   {paint(subtitle, DIM, color)}")


def print_result(result, color: bool) -> None:
    mark = {"PASS": (GREEN, "PASS"), "FAIL": (RED, "FAIL"), "ERROR": (YELLOW, "ERR ")}[
        result.verdict
    ]
    print(f"\n{paint(f'[{mark[1]}]', mark[0], color)} {paint(result.title, BOLD, color)}")
    print(f"       {paint('challenge:', DIM, color)} {result.challenge}")
    if result.headline:
        print(f"       {result.headline}")
    for check in result.checks:
        symbol = paint("ok  ", GREEN, color) if check.passed else paint("fail", RED, color)
        detail = f" {paint('(' + check.detail + ')', DIM, color)}" if check.detail else ""
        print(f"         {symbol} {check.label}{detail}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="show the scenario catalogue")

    run_parser = subparsers.add_parser("run", help="run one or more scenarios")
    run_parser.add_argument(
        "scenarios",
        nargs="+",
        help="scenario ids, act names (%s), or 'all'" % ", ".join(k for k, _, _ in STAGES),
    )
    run_parser.add_argument("--control-api", default=DEFAULT_CONTROL_API)
    run_parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    run_parser.add_argument("--no-reset", action="store_true", help="keep existing events and policy")
    run_parser.add_argument("--no-color", action="store_true")
    run_parser.add_argument("--wait", type=float, default=60.0, help="seconds to wait for the lab")

    args = parser.parse_args()
    color = sys.stdout.isatty() and not getattr(args, "no_color", False)

    if args.command == "list":
        print_catalogue(color)
        return 0

    try:
        selected = resolve_selection(args.scenarios)
    except KeyError as error:
        print(str(error).strip('"'), file=sys.stderr)
        return 2

    async with httpx.AsyncClient() as client:
        lab = Lab(client, control_api=args.control_api)
        if not await lab.wait_until_ready(timeout=args.wait):
            print(
                f"Lab is not reachable at {args.control_api}. "
                "Start it with `docker compose up --build`, then run this from "
                "inside the lab network (`docker compose exec dashboard ...`).",
                file=sys.stderr,
            )
            return 2
        if not args.no_reset:
            await lab.reset()
        results = await run_scenarios(lab, selected)

    if args.json:
        print(json.dumps([result.to_dict() for result in results], indent=2))
    else:
        stage = ""
        for result in results:
            if result.stage != stage:
                stage = result.stage
                subtitle = next(
                    (sub for _, title, sub, _ in scenarios_by_stage() if title == stage), ""
                )
                print_stage_header(stage, subtitle, color)
            print_result(result, color)
        passed = sum(1 for result in results if result.passed)
        total = len(results)
        line = f"\n{passed}/{total} scenarios passed"
        print(paint(line, GREEN if passed == total else RED, color))

    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
