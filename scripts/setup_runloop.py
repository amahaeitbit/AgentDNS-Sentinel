#!/usr/bin/env python3
"""Create AgentDNS Sentinel's local Runloop configuration and virtualenv."""

from __future__ import annotations

import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TOKEN_NAMES = (
    "CONTROL_TOKEN",
    "SERVICE_CONTROL_TOKEN",
    "RESEARCHER_AGENT_TOKEN",
    "DEPLOYER_AGENT_TOKEN",
    "UNTRUSTED_AGENT_TOKEN",
    "LOAD_TESTER_AGENT_TOKEN",
    "INCIDENT_RESPONDER_AGENT_TOKEN",
)


def existing_names() -> set[str]:
    if not ENV_PATH.exists():
        return set()
    return {
        line.split("=", 1)[0].strip()
        for line in ENV_PATH.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def configure_environment() -> None:
    names = existing_names()
    additions: list[str] = []
    if "RUNLOOP_API_KEY" not in names:
        additions.append("RUNLOOP_API_KEY=replace-with-your-runloop-api-key")
    if "RUNLOOP_TUNNEL_AUTH" not in names:
        additions.append("RUNLOOP_TUNNEL_AUTH=open")
    for name in TOKEN_NAMES:
        if name not in names:
            additions.append(f"{name}={secrets.token_urlsafe(32)}")

    if additions:
        prefix = "\n" if ENV_PATH.exists() and ENV_PATH.stat().st_size else ""
        with ENV_PATH.open("a") as stream:
            stream.write(prefix + "\n".join(additions) + "\n")
    ENV_PATH.chmod(0o600)
    print(f"Configured ignored secret file: {ENV_PATH}")


def main() -> None:
    venv = ROOT / ".venv"
    if not (venv / "bin" / "python").exists():
        subprocess.run(["python3", "-m", "venv", str(venv)], check=True)
        print(f"Created virtual environment: {venv}")
    else:
        print(f"Using existing virtual environment: {venv}")
    configure_environment()


if __name__ == "__main__":
    main()
