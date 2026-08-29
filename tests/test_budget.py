import json
import tempfile
import unittest
from pathlib import Path

from dns_manager.budget import Alert, AlertCenter, Budget, BudgetLedger
from dns_manager.policy import PolicyEngine
from dns_manager.rules import CostTable

CONFIG = {
    "agents": {
        "deployer": {
            "ip": "10.0.0.12",
            "allowed_domains": ["api.anthropic.com", "docs.internal"],
            "requests_per_second": 1000,
            "budget": {"window_seconds": 60, "max_cost": 50, "warn_at": 0.8},
        },
        "researcher": {
            "ip": "10.0.0.11",
            "allowed_domains": ["api.anthropic.com"],
            "requests_per_second": 1000,
        },
    },
    "costs": {"api.anthropic.com": 10},
    "records": {"api.anthropic.com": ["10.0.0.22"], "docs.internal": ["10.0.0.21"]},
    "ttl_seconds": 2,
}


class CostTableTest(unittest.TestCase):
    def test_unlisted_destinations_are_free(self):
        table = CostTable.build({"api.anthropic.com": 10})
        self.assertEqual(table.cost_of("docs.internal"), 0.0)

    def test_a_specific_rule_beats_a_broader_one(self):
        table = CostTable.build({"*.example.com": 1, "*.api.example.com": 9})
        self.assertEqual(table.cost_of("v1.api.example.com"), 9.0)
        self.assertEqual(table.cost_of("www.example.com"), 1.0)

    def test_an_absent_cost_table_costs_nothing(self):
        self.assertEqual(CostTable.build(None).cost_of("anything"), 0.0)


class BudgetLedgerTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.ledger = BudgetLedger(lambda: self.now)
        self.budget = Budget(window_seconds=60, max_cost=50, warn_at=0.8)

    def test_spend_accumulates_until_the_limit(self):
        for _ in range(5):
            self.assertFalse(self.ledger.would_exceed("d", self.budget, 10))
            self.ledger.charge("d", 10)
        self.assertTrue(self.ledger.would_exceed("d", self.budget, 10))

    def test_spend_ages_out_of_the_window(self):
        for _ in range(5):
            self.ledger.charge("d", 10)
        self.assertEqual(self.ledger.spent("d", 60), 50)
        self.now += 61
        self.assertEqual(self.ledger.spent("d", 60), 0)
        self.assertFalse(self.ledger.would_exceed("d", self.budget, 10))

    def test_a_partially_aged_window_keeps_recent_spend(self):
        self.ledger.charge("d", 10)
        self.now += 30
        self.ledger.charge("d", 10)
        self.now += 31  # the first charge is now outside the window
        self.assertEqual(self.ledger.spent("d", 60), 10)

    def test_agents_have_separate_ledgers(self):
        self.ledger.charge("a", 50)
        self.assertEqual(self.ledger.spent("b", 60), 0)

    def test_budgets_are_optional(self):
        self.assertIsNone(Budget.from_config(None))
        self.assertIsNone(Budget.from_config({"max_cost": 0}))
        self.assertEqual(Budget.from_config({"max_cost": 5}).warn_threshold, 4.0)


class AlertCenterTest(unittest.TestCase):
    def make(self, agent="d", kind="budget_warning", at=0.0):
        return Alert(at, agent, kind, "warning", "message", 40, 50)

    def test_repeat_alerts_are_suppressed_inside_the_cooldown(self):
        center = AlertCenter(cooldown_seconds=30)
        self.assertTrue(center.raise_alert(self.make(at=0)))
        self.assertFalse(center.raise_alert(self.make(at=10)))
        self.assertTrue(center.raise_alert(self.make(at=31)))
        self.assertEqual(len(center.recent()), 2)

    def test_different_agents_and_kinds_alert_independently(self):
        center = AlertCenter(cooldown_seconds=30)
        self.assertTrue(center.raise_alert(self.make(agent="a", at=0)))
        self.assertTrue(center.raise_alert(self.make(agent="b", at=0)))
        self.assertTrue(center.raise_alert(self.make(agent="a", kind="budget_exhausted", at=0)))

    def test_newest_alert_comes_first(self):
        center = AlertCenter(cooldown_seconds=0)
        center.raise_alert(self.make(kind="first", at=0))
        center.raise_alert(self.make(kind="second", at=1))
        self.assertEqual(center.recent()[0]["kind"], "second")

    def test_the_buffer_is_bounded(self):
        center = AlertCenter(cooldown_seconds=0, capacity=3)
        for index in range(10):
            center.raise_alert(self.make(kind=f"k{index}", at=index))
        self.assertEqual(len(center.recent(50)), 3)


class BudgetEnforcementTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        config = Path(self.tempdir.name) / "policies.json"
        config.write_text(json.dumps(CONFIG))
        self.now = 1000.0
        self.engine = PolicyEngine(str(config), clock=lambda: self.now)

    def tearDown(self):
        self.tempdir.cleanup()

    def spend_all(self):
        return [self.engine.evaluate("10.0.0.12", "api.anthropic.com") for _ in range(6)]

    def test_the_budget_stops_a_sustained_spend(self):
        decisions = self.spend_all()
        self.assertEqual([d.action for d in decisions[:5]], ["ALLOW"] * 5)
        self.assertEqual(decisions[5].action, "THROTTLE")
        self.assertEqual(decisions[5].reason, "budget_exhausted")

    def test_a_warning_precedes_the_refusal(self):
        self.spend_all()
        kinds = [alert["kind"] for alert in self.engine.alerts.recent()]
        self.assertIn("budget_warning", kinds)
        self.assertIn("budget_exhausted", kinds)
        # Newest first: the exhaustion came after the warning.
        self.assertLess(kinds.index("budget_exhausted"), kinds.index("budget_warning"))

    def test_free_destinations_are_unaffected_by_an_exhausted_budget(self):
        self.spend_all()
        self.assertEqual(self.engine.evaluate("10.0.0.12", "docs.internal").action, "ALLOW")

    def test_an_agent_without_a_budget_is_not_metered(self):
        for _ in range(20):
            decision = self.engine.evaluate("10.0.0.11", "api.anthropic.com")
        self.assertEqual(decision.action, "ALLOW")
        self.assertEqual(self.engine.alerts.recent(), [])

    def test_a_refused_call_is_not_charged(self):
        self.spend_all()
        for _ in range(5):
            self.engine.evaluate("10.0.0.12", "api.anthropic.com")
        report = {row["agent"]: row for row in self.engine.spend_report()}
        self.assertEqual(report["deployer"]["spent"], 50.0)

    def test_the_budget_recovers_when_the_window_rolls(self):
        self.spend_all()
        self.now += 61
        self.assertEqual(
            self.engine.evaluate("10.0.0.12", "api.anthropic.com").action, "ALLOW"
        )

    def test_spend_can_be_reset_so_a_demo_runs_twice(self):
        self.spend_all()
        self.engine.reset_budgets()
        self.assertEqual(self.engine.alerts.recent(), [])
        self.assertEqual(
            self.engine.evaluate("10.0.0.12", "api.anthropic.com").action, "ALLOW"
        )

    def test_the_spend_report_describes_the_window(self):
        self.spend_all()
        report = {row["agent"]: row for row in self.engine.spend_report()}
        self.assertEqual(report["deployer"]["percent"], 100.0)
        self.assertTrue(report["deployer"]["exhausted"])
        self.assertNotIn("researcher", report)  # no budget, no row


class ShippedBudgetTest(unittest.TestCase):
    def test_the_metered_api_is_priced_and_budgeted(self):
        engine = PolicyEngine(str(Path(__file__).parents[1] / "config" / "policies.json"))
        self.assertGreater(engine._compiled.costs.cost_of("api.anthropic.com"), 0)
        self.assertEqual(engine._compiled.costs.cost_of("docs.internal"), 0)
        budgeted = {row["agent"] for row in engine.spend_report()}
        self.assertIn("deployer", budgeted)


if __name__ == "__main__":
    unittest.main()
