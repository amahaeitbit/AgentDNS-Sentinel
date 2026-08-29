from __future__ import annotations

import logging
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List

LOGGER = logging.getLogger(__name__)


class HealthTracker:
    """Debounces raw probe results into stable healthy/unhealthy transitions.

    A single failed probe should not evict an endpoint from the DNS pool, and a
    single successful probe should not put a flapping endpoint back into it.
    """

    def __init__(self, failure_threshold: int = 2, success_threshold: int = 1):
        self.failure_threshold = max(int(failure_threshold), 1)
        self.success_threshold = max(int(success_threshold), 1)
        self._state: Dict[str, bool] = {}
        self._failures: Dict[str, int] = {}
        self._successes: Dict[str, int] = {}

    def state(self, address: str) -> bool:
        return self._state.get(address, True)

    def consecutive_failures(self, address: str) -> int:
        return self._failures.get(address, 0)

    def record(self, address: str, reachable: bool) -> bool | None:
        """Feed one probe result. Returns the new state on a transition, else None."""
        self._state.setdefault(address, True)
        if reachable:
            self._failures[address] = 0
            self._successes[address] = self._successes.get(address, 0) + 1
            if not self._state[address] and self._successes[address] >= self.success_threshold:
                self._state[address] = True
                return True
        else:
            self._successes[address] = 0
            self._failures[address] = self._failures.get(address, 0) + 1
            if self._state[address] and self._failures[address] >= self.failure_threshold:
                self._state[address] = False
                return False
        return None


def http_probe(address: str, port: int, path: str, timeout: float) -> bool:
    """A probe succeeds only on a 2xx response from the endpoint's health path."""
    url = f"http://{address}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as error:
        return 200 <= error.code < 300
    except (urllib.error.URLError, OSError):
        return False


class HealthMonitor:
    """Background thread that keeps the policy engine's health view current."""

    def __init__(
        self,
        engine,
        probe: Callable[[str, int, str, float], bool] = http_probe,
        on_transition: Callable[[str, bool], None] | None = None,
    ):
        self.engine = engine
        self.probe = probe
        self.on_transition = on_transition
        settings = engine.health_check
        self.tracker = HealthTracker(
            failure_threshold=settings["failure_threshold"],
            success_threshold=settings["success_threshold"],
        )
        self.interval = float(settings["interval_seconds"])
        self.port = int(settings["port"])
        self.path = str(settings["path"])
        self.timeout = float(settings["timeout_seconds"])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Probes run concurrently: a sequential sweep of unreachable endpoints
        # costs one timeout each, which would push a cycle past its interval.
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="probe")

    def check_once(self) -> List[tuple[str, bool]]:
        """Probe every known endpoint once. Returns the transitions that occurred."""
        transitions: List[tuple[str, bool]] = []
        addresses = self.engine.addresses()
        results = list(
            self._pool.map(
                lambda address: self.probe(address, self.port, self.path, self.timeout),
                addresses,
            )
        )
        for address, reachable in zip(addresses, results):
            transition = self.tracker.record(address, reachable)
            self.engine.record_probe(address, self.tracker.state(address))
            if transition is not None:
                transitions.append((address, transition))
                LOGGER.info(
                    "endpoint %s is now %s",
                    address,
                    "healthy" if transition else "unhealthy",
                )
                if self.on_transition:
                    self.on_transition(address, transition)
        return transitions

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:  # a probe loop must never take the resolver down
                LOGGER.exception("health probe cycle failed")
            self._stop.wait(self.interval)

    def start(self) -> "HealthMonitor":
        self._thread = threading.Thread(target=self._run, name="health-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + self.timeout + 1)
        self._pool.shutdown(wait=False)
