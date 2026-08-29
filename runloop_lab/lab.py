"""Drives the Runloop SDK through the lab's lifecycle.

The SDK object is injected rather than constructed here, so the whole flow can
be exercised against a fake in the test-suite.
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from . import spec
from .config import LabConfig

Printer = Callable[[str], None]


class LabError(RuntimeError):
    """A step of the Runloop flow failed."""


class RunloopLab:
    def __init__(self, sdk, config: Optional[LabConfig] = None, printer: Printer = print):
        self.sdk = sdk
        self.config = config or LabConfig.from_env()
        self.say = printer

    # -- network policy ---------------------------------------------------
    async def find_network_policy(self):
        for policy in await self.sdk.network_policy.list():
            info = await policy.get_info()
            if getattr(info, "name", None) == self.config.policy_name:
                return policy
        return None

    async def ensure_network_policy(self) -> str:
        """Create the Devbox egress boundary, or reuse the one already named."""
        desired = spec.network_policy_spec(self.config)
        existing = await self.find_network_policy()
        if existing:
            info = await existing.get_info()
            egress = getattr(info, "egress", None)
            changed = getattr(info, "description", None) != desired["description"]
            for field in (
                "allow_all",
                "allow_devbox_to_devbox",
                "allow_runloop_mirrors",
                "allowed_hostnames",
            ):
                changed = changed or getattr(egress, field, None) != desired[field]
            if changed:
                await existing.update(**desired)
                self.say(f"Updated network policy '{self.config.policy_name}': {existing.id}")
            else:
                self.say(
                    f"Network policy '{self.config.policy_name}' already exists: {existing.id}"
                )
            return existing.id
        policy = await self.sdk.network_policy.create(**desired)
        self.say(f"Created network policy '{self.config.policy_name}': {policy.id}")
        return policy.id

    # -- blueprint --------------------------------------------------------
    async def find_blueprint(self) -> Optional[str]:
        for blueprint in await self.sdk.blueprint.list():
            info = await blueprint.get_info()
            if getattr(info, "name", None) == self.config.blueprint_name:
                return blueprint.id
        return None

    async def ensure_blueprint(
        self, repo_root: Path, network_policy_id: Optional[str] = None
    ) -> str:
        existing = await self.find_blueprint()
        if existing:
            self.say(f"Blueprint '{self.config.blueprint_name}' already exists: {existing}")
            return existing
        return await self.build_blueprint(repo_root, network_policy_id)

    async def build_blueprint(
        self, repo_root: Path, network_policy_id: Optional[str] = None
    ) -> str:
        """Upload the repository as a build context and build the blueprint."""
        dockerfile = (repo_root / "Dockerfile").read_text()
        self.say("Uploading the build context...")
        context_object = await self.sdk.storage_object.upload_from_bytes(
            data=self._tarball(repo_root),
            name=f"{self.config.blueprint_name}-context.tar.gz",
            content_type="tgz",
            metadata=dict(self.config.metadata),
        )
        self.say(f"Build context uploaded: {context_object.id}")
        self.say(f"Building blueprint '{self.config.blueprint_name}' (this takes a few minutes)...")
        blueprint = await self.sdk.blueprint.create(
            **spec.blueprint_params(
                self.config,
                dockerfile=dockerfile,
                build_context=context_object.as_build_context(),
                network_policy_id=network_policy_id,
            )
        )
        self.say(f"Blueprint ready: {blueprint.id}")
        return blueprint.id

    # -- devbox -----------------------------------------------------------
    async def create_devbox(
        self,
        blueprint_name: Optional[str] = None,
        network_policy_id: Optional[str] = None,
    ):
        self.say("Creating the Devbox and waiting for it to run...")
        params = spec.devbox_params(self.config, blueprint_name, network_policy_id)
        if blueprint_name:
            params.pop("blueprint_name", None)
            devbox = await self.sdk.devbox.create_from_blueprint_name(
                blueprint_name=blueprint_name,
                **params,
            )
        else:
            devbox = await self.sdk.devbox.create(**params)
        self.say(f"Devbox running: {devbox.id}")
        return devbox

    def devbox(self, devbox_id: str):
        return self.sdk.devbox.from_id(devbox_id)

    async def tunnel_urls(self, devbox) -> Dict[str, str]:
        labels = {
            self.config.dashboard_port: "dashboard",
            self.config.control_port: "control_api",
        }
        urls: Dict[str, str] = {}
        for port, label in labels.items():
            url = await devbox.get_tunnel_url(port)
            if url:
                urls[label] = url
        if "dashboard" not in urls:
            raise LabError(
                "The Devbox has no tunnel. Recreate it with a tunnel, or enable one "
                "with devbox.net.enable_tunnel()."
            )
        return urls

    # -- source code ------------------------------------------------------
    def _tarball(self, repo_root: Path) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for path in sorted(repo_root.rglob("*")):
                relative = path.relative_to(repo_root).as_posix()
                if spec.is_excluded(relative):
                    continue
                archive.add(path, arcname=relative, recursive=False)
        return buffer.getvalue()

    async def sync_code(self, devbox, repo_root: Path) -> None:
        """Push the working tree into the Devbox without rebuilding the blueprint."""
        remote_tarball = "lab-source.tar.gz"
        self.say("Syncing the working tree into the Devbox...")
        await devbox.file.upload(
            path=remote_tarball, file=(remote_tarball, self._tarball(repo_root))
        )
        await self._exec(devbox, spec.extract_command(self.config, remote_tarball))
        self.say(f"Source synced to {self.config.workdir}")

    # -- lab lifecycle ----------------------------------------------------
    def _redact_command(self, command: str) -> str:
        secrets = (
            self.config.control_token,
            self.config.service_control_token,
            self.config.researcher_agent_token,
            self.config.deployer_agent_token,
            self.config.untrusted_agent_token,
            self.config.load_tester_agent_token,
            self.config.incident_responder_agent_token,
        )
        for secret in secrets:
            if secret:
                command = command.replace(secret, "<redacted>")
        return command

    async def _exec(self, devbox, command: str, allow_failure: bool = False) -> str:
        result = await devbox.cmd.exec(command)
        stdout = await result.stdout()
        if not allow_failure and result.exit_code not in (0, None):
            stderr = await result.stderr()
            raise LabError(
                f"Command failed (exit {result.exit_code}): "
                f"{self._redact_command(command)}\n{stderr or stdout}"
            )
        return stdout

    async def start_lab(self, devbox, public_url: str, rebuild: bool = False) -> None:
        self.say("Starting the Compose lab inside the Devbox...")
        await self._exec(devbox, spec.compose_up_command(self.config, public_url, rebuild))
        self.say("Waiting for the DNS control API to answer...")
        output = await self._exec(devbox, spec.wait_command(self.config))
        if "LAB_READY" not in output:
            raise LabError("The lab did not become ready in time. Check `runloop_lab.py logs`.")
        self.say("Lab is up.")

    async def run_demo(
        self,
        devbox,
        scenarios: Sequence[str] = ("all",),
        reset: bool = True,
    ) -> List[dict]:
        self.say(f"Running scenarios inside the Devbox: {' '.join(scenarios)}")
        output = await self._exec(
            devbox, spec.demo_command(self.config, scenarios, reset=reset), allow_failure=True
        )
        payload = _extract_json(output)
        if payload is None:
            raise LabError(f"Could not parse scenario results from the Devbox:\n{output}")
        return payload

    async def collect_evidence(self, devbox, results: List[dict], out_dir: Path) -> Dict[str, Path]:
        """Save verdicts, DNS decisions, and control actions next to the repo."""
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        written: Dict[str, Path] = {}

        results_path = out_dir / f"{stamp}-scenarios.json"
        results_path.write_text(json.dumps(results, indent=2) + "\n")
        written["scenarios"] = results_path

        try:
            events = await self._exec(devbox, spec.export_events_command(self.config))
            decoded = _extract_json(events)
            if decoded is not None:
                events_path = out_dir / f"{stamp}-dns-events.json"
                events_path.write_text(json.dumps(decoded, indent=2) + "\n")
                written["events"] = events_path
        except Exception as error:  # evidence is best effort; the verdicts matter more
            self.say(f"Could not export the decision log: {error}")

        try:
            controls = await self._exec(
                devbox, spec.export_control_events_command(self.config)
            )
            decoded = _extract_json(controls)
            if decoded is not None:
                controls_path = out_dir / f"{stamp}-control-events.json"
                controls_path.write_text(json.dumps(decoded, indent=2) + "\n")
                written["control_events"] = controls_path
        except Exception as error:
            self.say(f"Could not export the control-plane audit: {error}")
        return written

    async def logs(self, devbox, tail: int = 200, service: Optional[str] = None) -> str:
        return await self._exec(
            devbox, spec.logs_command(self.config, tail, service), allow_failure=True
        )

    async def compose_status(self, devbox) -> str:
        return await self._exec(devbox, spec.status_command(self.config), allow_failure=True)

    async def snapshot(self, devbox, message: str = "AgentDNS Sentinel demo run") -> str:
        self.say("Snapshotting the Devbox disk...")
        snapshot = await devbox.snapshot_disk(
            name=f"{self.config.devbox_name}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}",
            commit_message=message,
            metadata=dict(self.config.metadata),
        )
        self.say(f"Snapshot ready: {snapshot.id}")
        return snapshot.id

    async def stop_lab(self, devbox) -> None:
        await self._exec(devbox, spec.down_command(self.config), allow_failure=True)

    async def shutdown(self, devbox) -> None:
        self.say("Shutting the Devbox down...")
        await devbox.shutdown()

    async def list_lab_devboxes(self) -> List[dict]:
        """Every running devbox this project created, by metadata."""
        found = []
        for devbox in await self.sdk.devbox.list(status="running"):
            info = await devbox.get_info()
            metadata = getattr(info, "metadata", None) or {}
            if metadata.get("project") == self.config.metadata.get("project"):
                found.append(
                    {
                        "id": devbox.id,
                        "name": getattr(info, "name", None),
                        "status": getattr(info, "status", None),
                        "blueprint_id": getattr(info, "blueprint_id", None),
                    }
                )
        return found


def _extract_json(output: str) -> Optional[List[dict]]:
    """Pull the JSON array out of command output that may carry Docker noise."""
    start = output.find("[")
    end = output.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(output[start : end + 1])
    except json.JSONDecodeError:
        return None
