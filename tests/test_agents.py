import unittest
from pathlib import Path

from agents.incident_logic import incident_action, unhealthy_addresses
from dns_manager.policy import PolicyEngine


class FiveAgentConfigurationTest(unittest.TestCase):
    def setUp(self):
        config = Path(__file__).parents[1] / "config" / "policies.json"
        self.now = 100.0
        self.engine = PolicyEngine(str(config), clock=lambda: self.now)

    def test_has_five_role_specific_agents(self):
        names = {agent["name"] for agent in self.engine.agents()}
        self.assertEqual(
            names,
            {
                "researcher",
                "deployer",
                "untrusted",
                "load-tester",
                "incident-responder",
            },
        )

    def test_load_tester_has_dedicated_rate_limit(self):
        for _ in range(3):
            self.assertEqual(
                self.engine.evaluate("172.28.0.14", "docs.internal").action,
                "ALLOW",
            )
        self.assertEqual(
            self.engine.evaluate("172.28.0.14", "docs.internal").action,
            "THROTTLE",
        )

    def test_incident_responder_can_verify_api_failover(self):
        self.engine.set_endpoint_health("172.28.0.22", False)
        decision = self.engine.evaluate("172.28.0.15", "api.internal")
        self.assertEqual(decision.action, "ALLOW")
        self.assertEqual(decision.answer, "172.28.0.23")


class IncidentLogicTest(unittest.TestCase):
    def test_detects_unhealthy_endpoints(self):
        endpoints = [
            {"address": "172.28.0.22", "healthy": False},
            {"address": "172.28.0.23", "healthy": True},
        ]
        self.assertEqual(unhealthy_addresses(endpoints), ["172.28.0.22"])
        self.assertEqual(incident_action(endpoints), "FAILOVER_VERIFIED")


if __name__ == "__main__":
    unittest.main()
