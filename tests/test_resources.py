import tempfile
import unittest
from pathlib import Path

from demo.scenarios import CAPABILITIES, SCENARIOS, resolve_selection, scenarios_by_capability
from dns_manager.policy import Decision, PolicyEngine
from dns_manager.store import QUEUE_LIMIT, EventStore

CONFIG_PATH = Path(__file__).parents[1] / "config" / "policies.json"


class BoundedWritePathTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(str(Path(self.tempdir.name) / "events.db"))
        self.decision = Decision("researcher", "docs.internal", "ALLOW", "10.0.0.21", "ok")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_the_queue_never_grows_past_its_bound(self):
        for _ in range(QUEUE_LIMIT + 500):
            self.store.record("10.0.0.11", self.decision, 0.1)
        stats = self.store.stats()
        self.assertLessEqual(stats["queued"], stats["queue_capacity"])

    def test_shedding_is_counted_when_the_writer_stalls(self):
        # Stop the writer to model a stalled disk: the queue fills, then every
        # further decision sheds exactly one older line.
        self.store.close()
        for _ in range(QUEUE_LIMIT + 50):
            self.store.record("10.0.0.11", self.decision, 0.1)
        stats = self.store.stats()
        self.assertEqual(stats["queued"], stats["queue_capacity"])
        self.assertEqual(stats["dropped"], 50)

    def test_no_decision_is_silently_lost(self):
        # Whatever the timing, every decision is either written, still queued,
        # or counted as shed.
        total = QUEUE_LIMIT + 200
        for _ in range(total):
            self.store.record("10.0.0.11", self.decision, 0.1)
        self.store.flush()
        stats = self.store.stats()
        self.assertEqual(stats["queued"], 0)
        self.assertEqual(self.store.summary()["total"] + stats["dropped"], total)

    def test_the_queue_drains_to_empty(self):
        for _ in range(500):
            self.store.record("10.0.0.11", self.decision, 0.1)
        self.store.flush()
        self.assertEqual(self.store.stats()["queued"], 0)
        self.assertEqual(self.store.stats()["dropped"], 0)


class BoundedPolicyStateTest(unittest.TestCase):
    """Unbounded input must not become unbounded state."""

    def setUp(self):
        self.engine = PolicyEngine(str(CONFIG_PATH))

    def test_invented_names_add_no_per_query_state(self):
        before = self.engine.runtime_stats()
        for index in range(500):
            decision = self.engine.evaluate("172.28.0.11", f"{'a' * 45}-{index}.pypi.org")
            self.assertEqual(decision.action, "BLOCK")
        after = self.engine.runtime_stats()

        for key in ("round_robin_keys", "records", "rate_window_entries"):
            self.assertEqual(after[key], before[key], key)

    def test_blocked_names_do_not_create_records(self):
        self.engine.evaluate("172.28.0.13", "never-heard-of-this.example")
        self.assertEqual(
            self.engine.runtime_stats()["records"],
            len(self.engine._compiled.records),
        )

    def test_rate_window_entries_are_capped_by_the_quota(self):
        # A single agent hammering an allowed name keeps at most its quota's
        # worth of timestamps, not one per query.
        for _ in range(400):
            self.engine.evaluate("172.28.0.14", "docs.internal")
        stats = self.engine.runtime_stats()
        self.assertLessEqual(stats["rate_window_entries"], 10)

    def test_the_alert_buffer_is_capped(self):
        for _ in range(400):
            self.engine.evaluate("172.28.0.12", "api.anthropic.com")
        alerts = self.engine.runtime_stats()["alerts"]
        self.assertLessEqual(alerts["held"], alerts["capacity"])

    def test_runtime_stats_describe_every_in_memory_structure(self):
        stats = self.engine.runtime_stats()
        for key in (
            "agents", "records", "rate_windows", "rate_window_entries",
            "round_robin_keys", "budgets", "alerts", "health_tracked",
        ):
            self.assertIn(key, stats)


class CapabilityCatalogueTest(unittest.TestCase):
    def test_every_scenario_proves_at_least_one_capability(self):
        keys = {key for key, _, _ in CAPABILITIES}
        for scenario in SCENARIOS:
            self.assertTrue(scenario.proves, scenario.id)
            self.assertTrue(set(scenario.proves) <= keys, scenario.id)

    def test_every_capability_has_scenarios_behind_it(self):
        for key, title, _question, scenarios in scenarios_by_capability():
            self.assertTrue(scenarios, f"{title} has no scenarios")

    def test_selecting_a_capability_runs_exactly_its_scenarios(self):
        selected = {scenario.id for scenario in resolve_selection(["resources"])}
        expected = {s.id for s in SCENARIOS if "resources" in s.proves}
        self.assertEqual(selected, expected)

    def test_capabilities_and_acts_can_be_mixed(self):
        selected = {s.id for s in resolve_selection(["observability", "failover"])}
        self.assertIn("audit-trail", selected)
        self.assertIn("failover", selected)

    def test_capability_and_act_names_never_collide(self):
        from demo.scenarios import STAGES

        self.assertFalse(
            {key for key, _, _ in STAGES} & {key for key, _, _ in CAPABILITIES}
        )


if __name__ == "__main__":
    unittest.main()
