import asyncio
import unittest

from demo.runner import run_scenario
from demo.scenarios import (
    SCENARIOS,
    SCENARIOS_BY_ID,
    STAGES,
    get_scenario,
    resolve_selection,
    scenarios_by_stage,
)
from tests.fake_lab import FakeLab


def run(coroutine):
    return asyncio.run(coroutine)


class CatalogueTest(unittest.TestCase):
    def test_ids_are_unique_and_documented(self):
        self.assertEqual(len(SCENARIOS_BY_ID), len(SCENARIOS))
        for scenario in SCENARIOS:
            self.assertTrue(scenario.challenge, scenario.id)
            self.assertTrue(scenario.capability, scenario.id)
            self.assertTrue(scenario.watch_for, scenario.id)

    def test_every_scenario_belongs_to_exactly_one_act(self):
        stage_keys = {key for key, _, _ in STAGES}
        grouped = [s.id for _, _, _, items in scenarios_by_stage() for s in items]
        self.assertEqual(sorted(grouped), sorted(SCENARIOS_BY_ID))
        for scenario in SCENARIOS:
            self.assertIn(scenario.stage, stage_keys)

    def test_selection_accepts_ids_acts_and_all(self):
        self.assertEqual(
            [s.id for s in resolve_selection(["survive"])],
            ["failover", "incident-response"],
        )
        self.assertEqual(len(resolve_selection(["all", "baseline"])), len(SCENARIOS))
        # Order follows the catalogue and duplicates collapse.
        self.assertEqual(
            [s.id for s in resolve_selection(["audit-trail", "survive", "failover"])],
            ["failover", "incident-response", "audit-trail"],
        )

    def test_selection_rejects_unknown_names(self):
        with self.assertRaises(KeyError):
            resolve_selection(["nope"])

    def test_unknown_scenario_reports_the_known_ones(self):
        with self.assertRaises(KeyError) as context:
            get_scenario("nope")
        self.assertIn("baseline", str(context.exception))


class ScenarioBehaviourTest(unittest.TestCase):
    def test_every_scenario_passes_against_a_healthy_lab(self):
        async def exercise():
            lab = FakeLab()
            results = []
            for scenario in SCENARIOS:
                results.append(await run_scenario(scenario, lab))
            return results

        for result in run(exercise()):
            with self.subTest(scenario=result.id):
                failed = [check.label for check in result.checks if not check.passed]
                self.assertEqual(result.verdict, "PASS", f"{result.error} {failed}")

    def test_a_broken_lab_produces_a_failing_verdict_not_a_crash(self):
        async def exercise():
            lab = FakeLab()
            # Hand the untrusted agent the keys; egress governance must now fail.
            await lab.grant("untrusted", "docs.internal", True)
            return await run_scenario("egress-governance", lab)

        result = run(exercise())
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.error)

    def test_scenario_errors_are_captured(self):
        class ExplodingLab(FakeLab):
            async def results(self, *args, **kwargs):
                raise ConnectionError("agent unreachable")

        result = run(run_scenario("baseline", ExplodingLab()))
        self.assertEqual(result.verdict, "ERROR")
        self.assertIn("agent unreachable", result.error)

    def test_failover_scenario_leaves_the_incident_for_the_responder(self):
        async def exercise():
            lab = FakeLab()
            failover = await run_scenario("failover", lab)
            incident = await run_scenario("incident-response", lab)
            return failover, incident, lab

        failover, incident, lab = run(exercise())
        self.assertEqual(failover.verdict, "PASS")
        self.assertEqual(incident.verdict, "PASS")
        self.assertTrue(all(endpoint["healthy"] for endpoint in lab.engine.endpoints()))


if __name__ == "__main__":
    unittest.main()
