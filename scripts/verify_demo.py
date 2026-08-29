#!/usr/bin/env python3
"""End-to-end verification from the host.

Runs the whole scenario catalogue inside the lab network and fails if any
scenario fails, which makes it usable as a CI or pre-demo smoke test:

    python scripts/verify_demo.py
    python scripts/verify_demo.py failover incident-response
"""

from __future__ import annotations

import json
import subprocess
import sys

COMPOSE = ["docker", "compose", "exec", "-T", "dashboard"]


def main(scenarios: list[str]) -> int:
    command = COMPOSE + ["python", "scripts/demo.py", "run", *(scenarios or ["all"]), "--json"]
    process = subprocess.run(command, capture_output=True, text=True)
    if not process.stdout.strip():
        print(process.stderr or "No output from the lab.", file=sys.stderr)
        print("Is the lab running? Start it with `docker compose up --build`.", file=sys.stderr)
        return 2

    try:
        results = json.loads(process.stdout)
    except json.JSONDecodeError:
        print(process.stdout, file=sys.stderr)
        print(process.stderr, file=sys.stderr)
        return 2

    width = max(len(result["title"]) for result in results)
    for result in results:
        print(f"{result['verdict']:<5} {result['title']:<{width}}  {result['headline']}")
        for check in result["checks"]:
            if not check["passed"]:
                print(f"      - failed: {check['label']} {check['detail']}")

    passed = sum(1 for result in results if result["passed"])
    print(f"\n{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
