"""Pure builders for every Runloop request and in-devbox command.

Keeping these free of the SDK means the whole Runloop flow can be unit tested
without an API key, and it keeps `lab.py` readable as a sequence of steps.
"""

from __future__ import annotations

import shlex
from typing import Dict, List, Optional, Sequence

from .config import LabConfig

# Never ship local build output, virtualenvs or the git history to the devbox.
EXCLUDED_PATH_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".web",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".runloop",
        "artifacts",
        ".DS_Store",
        ".env",
    }
)


def is_excluded(relative_path: str) -> bool:
    parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
    if any(part in EXCLUDED_PATH_PARTS for part in parts):
        return True
    return bool(parts) and (parts[-1].endswith(".pyc") or parts[-1].endswith(".db"))


def tar_filter(info):
    """`tarfile` filter that drops everything `is_excluded` rejects."""
    name = info.name
    if name.startswith("./"):
        name = name[2:]
    return None if is_excluded(name) else info


def network_policy_spec(config: LabConfig) -> Dict[str, object]:
    """The outer, non-bypassable egress boundary for the whole Devbox.

    The lab's own agent traffic never leaves the Devbox, so the only egress the
    policy needs to permit is what building the lab requires. General internet
    and devbox-to-devbox traffic die here; explicitly allowlisted build hosts
    remain reachable for the lifetime of the Devbox.
    """
    return {
        "name": config.policy_name,
        "description": (
            "Egress boundary for AgentDNS Sentinel: build dependencies only, "
            "no general internet access for the agents inside."
        ),
        "allow_all": False,
        "allow_devbox_to_devbox": False,
        "allow_runloop_mirrors": True,
        "allowed_hostnames": list(config.allowed_hostnames),
    }


def launch_parameters(config: LabConfig, network_policy_id: Optional[str] = None) -> Dict[str, object]:
    parameters: Dict[str, object] = {
        "architecture": config.architecture,
        "resource_size_request": "CUSTOM_SIZE",
        "custom_cpu_cores": config.cpu_cores,
        "custom_gb_memory": config.memory_gb,
        "custom_disk_size": config.disk_gb,
        "keep_alive_time_seconds": config.keep_alive_seconds,
    }
    if network_policy_id:
        parameters["network_policy_id"] = network_policy_id
    return parameters


def blueprint_params(
    config: LabConfig,
    dockerfile: str,
    build_context: Optional[Dict[str, str]] = None,
    network_policy_id: Optional[str] = None,
) -> Dict[str, object]:
    params: Dict[str, object] = {
        "name": config.blueprint_name,
        "dockerfile": dockerfile,
        "launch_parameters": launch_parameters(config, network_policy_id),
        "metadata": dict(config.metadata),
        # Build the service images into the blueprint. Every Devbox created
        # from it then starts the lab from a warm image cache instead of
        # pulling base layers and running pip on each launch.
        "system_setup_commands": list(config.setup_commands or prebuild_commands(config)),
    }
    if build_context:
        params["build_context"] = build_context
    if network_policy_id:
        # Applies to the build itself; launch_parameters covers the devboxes.
        params["network_policy_id"] = network_policy_id
    return params


def prebuild_commands(config: LabConfig) -> List[str]:
    """Warm the image cache while the blueprint is being built, not at launch."""
    workdir = shlex.quote(config.workdir)
    return [
        f"cd {workdir} && docker compose build --pull",
        f"cd {workdir} && docker image ls",
    ]


def devbox_params(
    config: LabConfig,
    blueprint_name: Optional[str] = None,
    network_policy_id: Optional[str] = None,
) -> Dict[str, object]:
    params: Dict[str, object] = {
        "name": config.devbox_name,
        "tunnel": {"auth_mode": config.tunnel_auth},
        "launch_parameters": launch_parameters(config, network_policy_id),
        "metadata": dict(config.metadata),
    }
    if blueprint_name:
        params["blueprint_name"] = blueprint_name
    return params


# -- commands run inside the devbox ---------------------------------------


def _in_workdir(config: LabConfig, command: str) -> str:
    return f"cd {shlex.quote(config.workdir)} && {command}"


def extract_command(config: LabConfig, tarball_name: str) -> str:
    """Unpack an uploaded source tarball into the working directory.

    Uploads land relative to the user's home directory, so the command starts
    there rather than assuming the shell's working directory.
    """
    workdir = shlex.quote(config.workdir)
    tarball = shlex.quote(tarball_name)
    return (
        f'cd "$HOME" && mkdir -p {workdir} && tar xzf {tarball} -C {workdir} && '
        f"rm -f {tarball} && ls {workdir}"
    )


def compose_up_command(config: LabConfig, public_url: str, rebuild: bool = False) -> str:
    """Start the lab.

    The blueprint already built the images, so the default start does not pass
    `--build`; pass `rebuild=True` after changing a Dockerfile or a dependency.
    """
    environment = {
        "REFLEX_API_URL": public_url,
        "CONTROL_TOKEN": config.control_token,
        "SERVICE_CONTROL_TOKEN": config.service_control_token,
        "RESEARCHER_AGENT_TOKEN": config.researcher_agent_token,
        "DEPLOYER_AGENT_TOKEN": config.deployer_agent_token,
        "UNTRUSTED_AGENT_TOKEN": config.untrusted_agent_token,
        "LOAD_TESTER_AGENT_TOKEN": config.load_tester_agent_token,
        "INCIDENT_RESPONDER_AGENT_TOKEN": config.incident_responder_agent_token,
    }
    assignments = " ".join(
        f"{name}={shlex.quote(value)}" for name, value in environment.items()
    )
    build_flag = " --build" if rebuild else ""
    return _in_workdir(
        config,
        f"{assignments} docker compose up -d{build_flag}",
    )


def wait_command(config: LabConfig, attempts: int = 90, delay: int = 2) -> str:
    """Poll the control API from inside the devbox until the lab answers."""
    url = f"http://localhost:{config.control_port}/health"
    return (
        f"for i in $(seq 1 {attempts}); do "
        f"curl -fsS {shlex.quote(url)} >/dev/null 2>&1 && echo LAB_READY && exit 0; "
        f"sleep {delay}; done; echo LAB_TIMEOUT; exit 1"
    )


def demo_command(
    config: LabConfig,
    scenarios: Sequence[str] = ("all",),
    reset: bool = True,
    as_json: bool = True,
) -> str:
    flags: List[str] = []
    if as_json:
        flags.append("--json")
    if not reset:
        flags.append("--no-reset")
    flags.append("--no-color")
    selection = " ".join(shlex.quote(name) for name in scenarios)
    return _in_workdir(
        config,
        "docker compose exec -T dashboard python scripts/demo.py run "
        f"{selection} {' '.join(flags)}",
    )


def logs_command(config: LabConfig, tail: int = 200, service: Optional[str] = None) -> str:
    target = f" {shlex.quote(service)}" if service else ""
    return _in_workdir(config, f"docker compose logs --tail={int(tail)} --no-color{target}")


def status_command(config: LabConfig) -> str:
    return _in_workdir(config, "docker compose ps --format json")


def export_events_command(config: LabConfig, limit: int = 500) -> str:
    """Print the decision log so the caller can capture it from stdout."""
    url = f"http://localhost:{config.control_port}/events?limit={int(limit)}"
    authorization = shlex.quote(f"Authorization: Bearer {config.control_token}")
    return f"curl -fsS -H {authorization} {shlex.quote(url)}"


def export_control_events_command(config: LabConfig, limit: int = 500) -> str:
    """Print attributed control-plane events for the evidence bundle."""
    url = f"http://localhost:{config.control_port}/control-events?limit={int(limit)}"
    authorization = shlex.quote(f"Authorization: Bearer {config.control_token}")
    return f"curl -fsS -H {authorization} {shlex.quote(url)}"


def down_command(config: LabConfig) -> str:
    return _in_workdir(config, "docker compose down -v --remove-orphans")
