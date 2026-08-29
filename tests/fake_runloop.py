"""A minimal fake of the Runloop SDK surface the lab uses.

It records every call so tests can assert the shape *and the order* of the
Runloop flow without an API key.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

DEMO_RESULTS = [
    {
        "id": "baseline",
        "stage": "Govern",
        "title": "Baseline: identity-bound agents",
        "challenge": "Unclear agent responsibility",
        "headline": "Every agent acted inside its own identity and policy.",
        "verdict": "PASS",
        "passed": True,
        "error": "",
        "checks": [{"label": "Researcher resolves docs.internal", "passed": True, "detail": ""}],
    }
]

EVENTS = [{"agent": "researcher", "domain": "docs.internal", "action": "ALLOW"}]
CONTROL_EVENTS = [
    {
        "actor": "scenario-runner",
        "scenario_id": "baseline",
        "action": "SCENARIO_FINISHED",
        "resource": "scenario:baseline",
    }
]


class FakeInfo:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class FakeExecutionResult:
    def __init__(self, stdout: str, exit_code: int = 0, stderr: str = ""):
        self._stdout = stdout
        self._stderr = stderr
        self.exit_code = exit_code

    async def stdout(self) -> str:
        return self._stdout

    async def stderr(self) -> str:
        return self._stderr


class FakeCommandInterface:
    def __init__(self, devbox: "FakeDevbox"):
        self.devbox = devbox

    async def exec(self, command: str) -> FakeExecutionResult:
        self.devbox.commands.append(command)
        if command in self.devbox.failures:
            return FakeExecutionResult("", exit_code=1, stderr=self.devbox.failures[command])
        if "demo.py run" in command:
            return FakeExecutionResult(
                "time=... level=warning docker noise\n" + json.dumps(self.devbox.demo_results)
            )
        if "LAB_READY" in command:
            return FakeExecutionResult("LAB_TIMEOUT" if self.devbox.never_ready else "LAB_READY")
        if "/control-events" in command:
            return FakeExecutionResult(json.dumps(CONTROL_EVENTS))
        if "/events" in command:
            return FakeExecutionResult(json.dumps(EVENTS))
        return FakeExecutionResult("")


class FakeFileInterface:
    def __init__(self, devbox: "FakeDevbox"):
        self.devbox = devbox

    async def upload(self, path: str, file: Any) -> Dict[str, str]:
        self.devbox.uploads.append((path, file))
        return {"path": path}

    async def read(self, file_path: str) -> str:
        return self.devbox.files.get(file_path, "")


class FakeSnapshot:
    def __init__(self, snapshot_id: str):
        self.id = snapshot_id


class FakeDevbox:
    def __init__(self, devbox_id: str = "dbx_1", params: Optional[dict] = None):
        self.id = devbox_id
        self.params = params or {}
        self.commands: List[str] = []
        self.uploads: List[tuple] = []
        self.files: Dict[str, str] = {}
        self.failures: Dict[str, str] = {}
        self.demo_results = DEMO_RESULTS
        self.never_ready = False
        self.tunnel_key = "abc123"
        self.shutdown_called = False
        self.snapshots: List[dict] = []
        self.cmd = FakeCommandInterface(self)
        self.file = FakeFileInterface(self)

    async def get_tunnel_url(self, port: int) -> str:
        return f"https://{port}-{self.tunnel_key}.tunnel.runloop.ai"

    async def get_info(self) -> FakeInfo:
        return FakeInfo(
            name=self.params.get("name"),
            status="running",
            metadata=self.params.get("metadata", {}),
            blueprint_id=self.params.get("blueprint_name"),
        )

    async def snapshot_disk(self, **params) -> FakeSnapshot:
        self.snapshots.append(params)
        return FakeSnapshot(f"snp_{len(self.snapshots)}")

    async def shutdown(self) -> None:
        self.shutdown_called = True


class FakeDevboxOps:
    def __init__(self, sdk: "FakeSDK"):
        self.sdk = sdk

    async def create(self, **params) -> FakeDevbox:
        devbox = FakeDevbox(f"dbx_{len(self.sdk.devboxes) + 1}", params)
        self.sdk.devboxes.append(devbox)
        self.sdk.calls.append(("devbox.create", params))
        return devbox

    async def create_from_blueprint_name(
        self, blueprint_name: str, **params
    ) -> FakeDevbox:
        params = {**params, "blueprint_name": blueprint_name}
        devbox = FakeDevbox(f"dbx_{len(self.sdk.devboxes) + 1}", params)
        self.sdk.devboxes.append(devbox)
        self.sdk.calls.append(("devbox.create_from_blueprint_name", params))
        return devbox

    def from_id(self, devbox_id: str) -> FakeDevbox:
        for devbox in self.sdk.devboxes:
            if devbox.id == devbox_id:
                return devbox
        devbox = FakeDevbox(devbox_id)
        self.sdk.devboxes.append(devbox)
        return devbox

    async def list(self, **params) -> List[FakeDevbox]:
        self.sdk.calls.append(("devbox.list", params))
        return list(self.sdk.devboxes)


class FakeBlueprint:
    def __init__(self, blueprint_id: str, params: Optional[dict] = None):
        self.id = blueprint_id
        self.params = params or {}

    async def get_info(self) -> FakeInfo:
        return FakeInfo(id=self.id, name=self.params.get("name"))


class FakeBlueprintOps:
    def __init__(self, sdk: "FakeSDK"):
        self.sdk = sdk

    async def create(self, **params) -> FakeBlueprint:
        self.sdk.calls.append(("blueprint.create", params))
        blueprint = FakeBlueprint(f"bpt_{len(self.sdk.blueprints) + 1}", params)
        self.sdk.blueprints.append(blueprint)
        return blueprint

    async def list(self, **params) -> List[FakeBlueprint]:
        return list(self.sdk.blueprints)


class FakeNetworkPolicy:
    def __init__(self, sdk: "FakeSDK", policy_id: str, params: dict):
        self.sdk = sdk
        self.id = policy_id
        self.params = params

    async def get_info(self) -> FakeInfo:
        return FakeInfo(
            id=self.id,
            name=self.params["name"],
            description=self.params.get("description"),
            egress=FakeInfo(
                allow_all=self.params.get("allow_all", False),
                allow_devbox_to_devbox=self.params.get(
                    "allow_devbox_to_devbox", False
                ),
                allow_runloop_mirrors=self.params.get(
                    "allow_runloop_mirrors", False
                ),
                allowed_hostnames=self.params.get("allowed_hostnames", []),
            ),
        )

    async def update(self, **params) -> FakeInfo:
        self.sdk.calls.append(("network_policy.update", params))
        self.params.update(params)
        return await self.get_info()


class FakeNetworkPolicyOps:
    def __init__(self, sdk: "FakeSDK"):
        self.sdk = sdk

    async def create(self, **params) -> FakeNetworkPolicy:
        self.sdk.calls.append(("network_policy.create", params))
        policy = FakeNetworkPolicy(
            self.sdk, f"npol_{len(self.sdk.policies) + 1}", params
        )
        self.sdk.policies.append(policy)
        return policy

    async def list(self, **params) -> List[FakeNetworkPolicy]:
        return list(self.sdk.policies)


class FakeStorageObject:
    def __init__(self, object_id: str):
        self.id = object_id

    def as_build_context(self) -> Dict[str, str]:
        return {"object_id": self.id, "type": "object"}


class FakeStorageObjectOps:
    def __init__(self, sdk: "FakeSDK"):
        self.sdk = sdk

    async def upload_from_bytes(self, **params) -> FakeStorageObject:
        self.sdk.calls.append(("storage_object.upload_from_bytes", params))
        return FakeStorageObject("obj_1")


class FakeSDK:
    def __init__(self):
        self.calls: List[tuple] = []
        self.devboxes: List[FakeDevbox] = []
        self.blueprints: List[FakeBlueprint] = []
        self.policies: List[FakeNetworkPolicy] = []
        self.devbox = FakeDevboxOps(self)
        self.blueprint = FakeBlueprintOps(self)
        self.network_policy = FakeNetworkPolicyOps(self)
        self.storage_object = FakeStorageObjectOps(self)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    def call_names(self) -> List[str]:
        return [name for name, _ in self.calls]
