from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

STATE_PATH = Path(".runloop/lab.json")


@dataclass
class LabState:
    """What the last `up` created, so later commands need no arguments."""

    devbox_id: Optional[str] = None
    blueprint_id: Optional[str] = None
    network_policy_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    tunnels: Dict[str, str] = field(default_factory=dict)
    created_at: Optional[str] = None

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "LabState":
        if not path.exists():
            return cls()
        try:
            return cls(**json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError):
            return cls()

    def save(self, path: Path = STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")

    def clear(self, path: Path = STATE_PATH) -> None:
        if path.exists():
            path.unlink()

    def require_devbox(self) -> str:
        if not self.devbox_id:
            raise SystemExit(
                "No devbox recorded. Run `python scripts/runloop_lab.py up` first, "
                "or pass --devbox-id."
            )
        return self.devbox_id
