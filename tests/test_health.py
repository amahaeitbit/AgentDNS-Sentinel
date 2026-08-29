import json
import tempfile
import unittest
from pathlib import Path

from dns_manager.health import HealthMonitor, HealthTracker
from dns_manager.policy import PolicyEngine

CONFIG = {
    "agents": {
        "deployer": {
            "ip": "10.0.0.12",
            "allowed_domains": ["api.internal"],
            "requests_per_second": 50,
        }
    },
    "records": {"api.internal": ["10.0.0.22", "10.0.0.23"]},
    "ttl_seconds": 2,
    "health_check": {"failure_threshold": 2, "success_threshold": 2, "interval_seconds": 0.01},
}


class HealthTrackerTest(unittest.TestCase):
    def test_single_failure_does_not_evict_an_endpoint(self):
        tracker = HealthTracker(failure_threshold=2, success_threshold=1)
        self.assertIsNone(tracker.record("a", False))
        self.assertTrue(tracker.state("a"))

    def test_repeated_failures_transition_once(self):
        tracker = HealthTracker(failure_threshold=2, success_threshold=1)
        tracker.record("a", False)
        self.assertIs(tracker.record("a", False), False)
        self.assertIsNone(tracker.record("a", False))
        self.assertFalse(tracker.state("a"))

    def test_recovery_needs_the_success_threshold(self):
        tracker = HealthTracker(failure_threshold=1, success_threshold=2)
        tracker.record("a", False)
        self.assertIsNone(tracker.record("a", True))
        self.assertIs(tracker.record("a", True), True)
        self.assertTrue(tracker.state("a"))

    def test_a_success_resets_the_failure_streak(self):
        tracker = HealthTracker(failure_threshold=3, success_threshold=1)
        tracker.record("a", False)
        tracker.record("a", True)
        tracker.record("a", False)
        tracker.record("a", False)
        self.assertTrue(tracker.state("a"))
        self.assertEqual(tracker.consecutive_failures("a"), 2)


class HealthMonitorTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        config = Path(self.tempdir.name) / "policies.json"
        config.write_text(json.dumps(CONFIG))
        self.engine = PolicyEngine(str(config))
        self.reachable = {"10.0.0.22": True, "10.0.0.23": True}
        self.monitor = HealthMonitor(
            self.engine,
            probe=lambda address, port, path, timeout: self.reachable[address],
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_probe_failure_removes_the_endpoint_from_dns_answers(self):
        self.reachable["10.0.0.22"] = False
        self.assertEqual(self.monitor.check_once(), [], "one failure must not evict")

        transitions = self.monitor.check_once()
        self.assertEqual(transitions, [("10.0.0.22", False)])
        for _ in range(4):
            self.assertEqual(
                self.engine.evaluate("10.0.0.12", "api.internal").answer, "10.0.0.23"
            )

    def test_recovery_returns_the_endpoint_to_the_pool(self):
        self.reachable["10.0.0.22"] = False
        self.monitor.check_once()
        self.monitor.check_once()
        self.reachable["10.0.0.22"] = True
        self.monitor.check_once()
        self.monitor.check_once()

        answers = {self.engine.evaluate("10.0.0.12", "api.internal").answer for _ in range(4)}
        self.assertEqual(answers, {"10.0.0.22", "10.0.0.23"})

    def test_operator_override_beats_the_probe(self):
        self.engine.set_endpoint_health("10.0.0.22", False)
        self.monitor.check_once()
        self.monitor.check_once()
        self.assertEqual(self.engine.evaluate("10.0.0.12", "api.internal").answer, "10.0.0.23")

        endpoint = next(e for e in self.engine.endpoints() if e["address"] == "10.0.0.22")
        self.assertEqual(endpoint["source"], "override")
        self.assertTrue(endpoint["probe_healthy"])

        self.engine.clear_endpoint_override("10.0.0.22")
        answers = {self.engine.evaluate("10.0.0.12", "api.internal").answer for _ in range(4)}
        self.assertEqual(answers, {"10.0.0.22", "10.0.0.23"})

    def test_all_endpoints_down_yields_servfail(self):
        self.reachable = {address: False for address in self.reachable}
        self.monitor.check_once()
        self.monitor.check_once()
        decision = self.engine.evaluate("10.0.0.12", "api.internal")
        self.assertEqual(decision.action, "SERVFAIL")
        self.assertEqual(decision.reason, "no_healthy_endpoint")


if __name__ == "__main__":
    unittest.main()
