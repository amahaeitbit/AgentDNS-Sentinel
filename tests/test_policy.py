import json
import tempfile
import unittest
from pathlib import Path

from dns_manager.policy import PolicyEngine


CONFIG = {
    "agents": {
        "researcher": {
            "ip": "10.0.0.11",
            "allowed_domains": ["docs.internal"],
            "requests_per_second": 2,
        },
        "untrusted": {
            "ip": "10.0.0.13",
            "allowed_domains": [],
            "requests_per_second": 1,
        },
    },
    "records": {
        "docs.internal": ["10.0.0.21"],
        "api.internal": ["10.0.0.22", "10.0.0.23"],
    },
    "ttl_seconds": 2,
}


class PolicyEngineTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.config = Path(self.tempdir.name) / "policies.json"
        self.config.write_text(json.dumps(CONFIG))
        self.now = 100.0
        self.engine = PolicyEngine(str(self.config), clock=lambda: self.now)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_allows_authorized_domain(self):
        decision = self.engine.evaluate("10.0.0.11", "docs.internal.")
        self.assertEqual(decision.action, "ALLOW")
        self.assertEqual(decision.answer, "10.0.0.21")

    def test_blocks_unauthorized_and_unknown_agents(self):
        self.assertEqual(
            self.engine.evaluate("10.0.0.13", "docs.internal").reason,
            "domain_not_allowed",
        )
        self.assertEqual(
            self.engine.evaluate("10.0.0.99", "docs.internal").reason,
            "unknown_agent",
        )

    def test_rate_limits_allowed_requests(self):
        self.assertEqual(self.engine.evaluate("10.0.0.11", "docs.internal").action, "ALLOW")
        self.assertEqual(self.engine.evaluate("10.0.0.11", "docs.internal").action, "ALLOW")
        self.assertEqual(self.engine.evaluate("10.0.0.11", "docs.internal").action, "THROTTLE")
        self.now += 1.0
        self.assertEqual(self.engine.evaluate("10.0.0.11", "docs.internal").action, "ALLOW")

    def test_round_robin_and_failover(self):
        self.engine.set_domain_access("researcher", "api.internal", True)
        first = self.engine.evaluate("10.0.0.11", "api.internal")
        second = self.engine.evaluate("10.0.0.11", "api.internal")
        self.assertEqual({first.answer, second.answer}, {"10.0.0.22", "10.0.0.23"})

        self.now += 1.0
        self.engine.set_endpoint_health("10.0.0.22", False)
        for _ in range(2):
            self.assertEqual(
                self.engine.evaluate("10.0.0.11", "api.internal").answer,
                "10.0.0.23",
            )

    def test_live_access_update(self):
        blocked = self.engine.evaluate("10.0.0.11", "api.internal")
        self.assertEqual(blocked.action, "BLOCK")
        self.engine.set_domain_access("researcher", "api.internal", True)
        allowed = self.engine.evaluate("10.0.0.11", "api.internal")
        self.assertEqual(allowed.action, "ALLOW")


if __name__ == "__main__":
    unittest.main()
