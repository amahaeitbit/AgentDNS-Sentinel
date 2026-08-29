from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Tuple

# Hosts the lab genuinely needs while it builds itself: container registries,
# the Python index, and the Node/Bun toolchain Reflex compiles its frontend with.
DEFAULT_ALLOWED_HOSTNAMES: Tuple[str, ...] = (
    "*.docker.io",
    "docker.io",
    "*.docker.com",
    "production.cloudflare.docker.com",
    "pypi.org",
    "*.pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "*.npmjs.org",
    "nodejs.org",
    "*.nodejs.org",
    "bun.sh",
    "*.bun.sh",
    "github.com",
    "*.githubusercontent.com",
    "deb.debian.org",
    "security.debian.org",
)


def load_env_file(path: Path) -> None:
    """Load a simple dotenv file without adding a runtime dependency.

    Existing process variables always win, so CI and shell exports can safely
    override the developer's ignored local file.
    """
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        if name and name.replace("_", "").isalnum():
            os.environ.setdefault(name, value)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class LabConfig:
    """Everything the Runloop side of the lab needs to know."""

    blueprint_name: str = "agentdns-sentinel"
    devbox_name: str = "agentdns-sentinel-demo"
    policy_name: str = "agentdns-sentinel-egress"
    workdir: str = "/workspace/agentdns-sentinel"

    dashboard_port: int = 3000
    backend_port: int = 8000
    control_port: int = 8053

    tunnel_auth: str = "open"
    keep_alive_seconds: int = 3600
    cpu_cores: int = 4
    memory_gb: int = 8
    disk_gb: int = 32
    architecture: str = "x86_64"

    control_token: str = "demo-control-token"
    service_control_token: str = "demo-service-control-token"
    researcher_agent_token: str = "demo-researcher-token"
    deployer_agent_token: str = "demo-deployer-token"
    untrusted_agent_token: str = "demo-untrusted-token"
    load_tester_agent_token: str = "demo-load-tester-token"
    incident_responder_agent_token: str = "demo-incident-responder-token"

    allowed_hostnames: Tuple[str, ...] = DEFAULT_ALLOWED_HOSTNAMES
    # Commands run while the blueprint builds. Empty means "warm the image
    # cache" (see runloop_lab.spec.prebuild_commands).
    setup_commands: Tuple[str, ...] = ()
    metadata: Dict[str, str] = field(
        default_factory=lambda: {"project": "agentdns-sentinel", "component": "demo"}
    )

    @classmethod
    def from_env(cls, **overrides) -> "LabConfig":
        config = cls(
            blueprint_name=os.getenv("RUNLOOP_BLUEPRINT", cls.blueprint_name),
            devbox_name=os.getenv("RUNLOOP_DEVBOX_NAME", cls.devbox_name),
            policy_name=os.getenv("RUNLOOP_NETWORK_POLICY", cls.policy_name),
            workdir=os.getenv("RUNLOOP_WORKDIR", cls.workdir),
            tunnel_auth=os.getenv("RUNLOOP_TUNNEL_AUTH", cls.tunnel_auth),
            keep_alive_seconds=_int_env("RUNLOOP_KEEP_ALIVE_SECONDS", cls.keep_alive_seconds),
            cpu_cores=_int_env("RUNLOOP_CPU_CORES", cls.cpu_cores),
            memory_gb=_int_env("RUNLOOP_MEMORY_GB", cls.memory_gb),
            disk_gb=_int_env("RUNLOOP_DISK_GB", cls.disk_gb),
            architecture=os.getenv("RUNLOOP_ARCHITECTURE", cls.architecture),
            control_token=os.getenv("CONTROL_TOKEN", cls.control_token),
            service_control_token=os.getenv(
                "SERVICE_CONTROL_TOKEN", cls.service_control_token
            ),
            researcher_agent_token=os.getenv(
                "RESEARCHER_AGENT_TOKEN", cls.researcher_agent_token
            ),
            deployer_agent_token=os.getenv(
                "DEPLOYER_AGENT_TOKEN", cls.deployer_agent_token
            ),
            untrusted_agent_token=os.getenv(
                "UNTRUSTED_AGENT_TOKEN", cls.untrusted_agent_token
            ),
            load_tester_agent_token=os.getenv(
                "LOAD_TESTER_AGENT_TOKEN", cls.load_tester_agent_token
            ),
            incident_responder_agent_token=os.getenv(
                "INCIDENT_RESPONDER_AGENT_TOKEN",
                cls.incident_responder_agent_token,
            ),
        )
        return replace(config, **overrides) if overrides else config

    @property
    def tunnel_ports(self) -> Tuple[int, int]:
        return (self.dashboard_port, self.control_port)
