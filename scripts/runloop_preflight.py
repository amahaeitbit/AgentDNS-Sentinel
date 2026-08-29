#!/usr/bin/env python3
"""Fail fast on missing Runloop prerequisites before creating paid resources."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runloop_lab.config import LabConfig, load_env_file  # noqa: E402
from runloop_lab.spec import network_policy_spec  # noqa: E402


def main() -> int:
    load_env_file(ROOT / ".env")
    errors: list[str] = []

    key = os.getenv("RUNLOOP_API_KEY", "")
    if not key or key.startswith("replace-with"):
        errors.append("Set RUNLOOP_API_KEY in .env (never paste it into chat).")

    try:
        import runloop_api_client
    except ImportError:
        errors.append("Runloop SDK missing; run `make runloop-setup`.")
        sdk_version = "missing"
    else:
        sdk_version = getattr(runloop_api_client, "__version__", "installed")

    config = LabConfig.from_env()
    if config.tunnel_auth not in {"open", "authenticated"}:
        errors.append("RUNLOOP_TUNNEL_AUTH must be 'open' or 'authenticated'.")
    policy = network_policy_spec(config)
    if policy["allow_all"] or policy["allow_devbox_to_devbox"]:
        errors.append("The Runloop network policy is not deny-by-default.")
    if "runloop/universal-ubuntu" not in (ROOT / "Dockerfile").read_text():
        errors.append("The root Dockerfile is not based on a Runloop Devbox image.")

    if errors:
        print("Runloop preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("Runloop preflight passed")
    print(f"  SDK:       {sdk_version}")
    print(f"  Blueprint: {config.blueprint_name}")
    print(f"  Devbox:    {config.devbox_name}")
    print(f"  Policy:    {config.policy_name} (deny by default)")
    print(f"  Tunnel:    {config.tunnel_auth}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
