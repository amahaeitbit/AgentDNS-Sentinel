#!/usr/bin/env python3
"""Launch Runloop's MCP server with credentials from this project's .env."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runloop_lab.config import load_env_file  # noqa: E402


def find_rli() -> str | None:
    """Find rli on PATH or in npm's active global prefix."""
    executable = shutil.which("rli")
    if executable:
        return executable

    npm = shutil.which("npm")
    if not npm:
        return None
    result = subprocess.run(
        [npm, "prefix", "-g"], capture_output=True, check=False, text=True
    )
    if result.returncode:
        return None
    bin_dir = Path(result.stdout.strip()) / "bin"
    for name in ("rli", "rli.cmd"):
        candidate = bin_dir / name
        if candidate.is_file():
            return str(candidate)
    return None


def prerequisites() -> str:
    """Return the rli executable or stop with a safe, actionable error."""
    load_env_file(ROOT / ".env")
    key = os.getenv("RUNLOOP_API_KEY", "")
    if not key or key.startswith("replace-with"):
        raise SystemExit("Set RUNLOOP_API_KEY in the project's ignored .env file.")

    executable = find_rli()
    if not executable:
        raise SystemExit(
            "Runloop CLI is missing. Install it with: "
            "npm install -g @runloop/rl-cli"
        )
    return executable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate credentials and the rli installation"
    )
    parser.add_argument(
        "--cli",
        nargs=argparse.REMAINDER,
        help="run an rli command with credentials from the project .env",
    )
    args = parser.parse_args()
    executable = prerequisites()
    if args.check:
        print(f"Runloop MCP prerequisites passed ({executable})")
        return

    if args.cli:
        os.execv(executable, [executable, *args.cli])

    os.execv(executable, [executable, "mcp", "start"])


if __name__ == "__main__":
    main()
