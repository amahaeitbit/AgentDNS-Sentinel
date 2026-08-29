import unittest

from dashboard import tokens, view_model
from demo.scenarios import STAGES, scenarios_by_stage

SUMMARY = {"total": 20, "allowed": 12, "blocked": 5, "throttled": 2, "failures": 1}

AGENTS = [
    {"name": "researcher", "ip": "172.28.0.11", "allowed_domains": ["docs.internal"], "requests_per_second": 5},
    {"name": "untrusted", "ip": "172.28.0.13", "allowed_domains": [], "requests_per_second": 2},
    {"name": "deployer", "ip": "172.28.0.12", "allowed_domains": ["api.internal"], "requests_per_second": 10},
]

# Newest first, exactly as the control API returns them.
EVENTS = [
    {"agent": "researcher", "action": "THROTTLE"},
    {"agent": "researcher", "action": "ALLOW"},
    {"agent": "untrusted", "action": "BLOCK"},
]


class CompositionTest(unittest.TestCase):
    def test_segments_keep_the_validated_colour_order(self):
        labels = [segment["label"] for segment in view_model.composition(SUMMARY)]
        self.assertEqual(labels, ["Allowed", "Throttled", "Blocked", "Failed"])

    def test_colours_are_the_fixed_status_palette(self):
        colors = [segment["color"] for segment in view_model.composition(SUMMARY)]
        self.assertEqual(
            colors, [tokens.GOOD, tokens.WARNING, tokens.CRITICAL, tokens.SERIOUS]
        )

    def test_widths_are_shares_of_the_total(self):
        segments = {s["label"]: s for s in view_model.composition(SUMMARY)}
        self.assertEqual(segments["Allowed"]["width"], "60.00%")
        self.assertEqual(segments["Allowed"]["share"], "60%")
        self.assertEqual(segments["Blocked"]["width"], "25.00%")

    def test_only_wide_segments_carry_a_direct_label(self):
        segments = {s["label"]: s for s in view_model.composition(SUMMARY)}
        self.assertTrue(segments["Allowed"]["wide"])       # 60%
        self.assertTrue(segments["Blocked"]["wide"])       # 25%
        self.assertFalse(segments["Throttled"]["wide"])    # 10%
        self.assertFalse(segments["Failed"]["wide"])       # 5%

    def test_an_empty_lab_renders_no_width_and_no_share(self):
        for segment in view_model.composition({"total": 0}):
            self.assertEqual(segment["width"], "0.00%")
            self.assertEqual(segment["share"], "—")
            self.assertEqual(segment["min_width"], "0px")

    def test_a_present_but_tiny_segment_stays_visible(self):
        segments = {s["label"]: s for s in view_model.composition(SUMMARY)}
        self.assertEqual(segments["Failed"]["min_width"], "4px")

    def test_missing_summary_fields_do_not_crash(self):
        self.assertEqual(len(view_model.composition({})), 4)


class TopologyTest(unittest.TestCase):
    def test_each_agent_shows_its_most_recent_decision(self):
        rows = {row["name"]: row for row in view_model.agent_rows(AGENTS, EVENTS)}
        self.assertEqual(rows["researcher"]["action"], "THROTTLE")
        self.assertEqual(rows["researcher"]["label"], "Throttled")
        self.assertEqual(rows["untrusted"]["label"], "Blocked")
        self.assertEqual(rows["untrusted"]["color"], tokens.CRITICAL)

    def test_an_agent_with_no_traffic_is_neutral_not_green(self):
        row = {r["name"]: r for r in view_model.agent_rows(AGENTS, EVENTS)}["deployer"]
        self.assertEqual(row["action"], "NONE")
        self.assertEqual(row["label"], "No traffic yet")
        self.assertEqual(row["color"], tokens.NEUTRAL)

    def test_an_empty_allowlist_says_so(self):
        rows = {row["name"]: row for row in view_model.agent_rows(AGENTS, [])}
        self.assertEqual(rows["untrusted"]["domains"], "no domains allowed")
        self.assertEqual(rows["researcher"]["domains"], "docs.internal")
        self.assertEqual(rows["researcher"]["quota"], "5 q/s")

    def test_endpoints_report_health_and_its_source(self):
        rows = view_model.endpoint_rows(
            [
                {"domain": "api.internal", "address": "172.28.0.22", "healthy": True, "overridden": False},
                {"domain": "api.internal", "address": "172.28.0.23", "healthy": False, "overridden": True},
            ]
        )
        self.assertEqual(rows[0]["label"], "Healthy")
        self.assertEqual(rows[0]["source"], "health probe")
        self.assertEqual(rows[0]["action_label"], "Take down")
        self.assertTrue(rows[0]["fail"])

        self.assertEqual(rows[1]["label"], "Down")
        self.assertEqual(rows[1]["source"], "operator override")
        self.assertEqual(rows[1]["action_label"], "Restore")
        self.assertFalse(rows[1]["fail"])

    def test_health_summary_counts_the_pool(self):
        self.assertEqual(
            view_model.health_summary([{"healthy": True}, {"healthy": False}]), "1/2 healthy"
        )


class AuditTrailTest(unittest.TestCase):
    def test_actions_get_a_readable_label_and_a_status_colour(self):
        rows = view_model.control_event_rows(
            [
                {
                    "action": "FAILURE_INJECTED",
                    "actor": "dashboard",
                    "scenario_id": "failover",
                    "resource": "endpoint:172.28.0.22",
                    "before": {"healthy": True},
                    "after": {"healthy": False},
                    "created_at": "2026-08-29T10:00:00Z",
                }
            ]
        )
        self.assertEqual(rows[0]["label"], "Service taken down")
        self.assertEqual(rows[0]["color"], tokens.CRITICAL)
        self.assertEqual(rows[0]["change"], "healthy=true → healthy=false")
        self.assertEqual(rows[0]["scenario"], "failover")

    def test_a_change_with_no_scenario_is_attributed_to_a_person(self):
        rows = view_model.control_event_rows(
            [{"action": "LAB_RESET", "actor": "operator", "resource": "lab", "created_at": "t"}]
        )
        self.assertEqual(rows[0]["scenario"], "manual")
        self.assertEqual(rows[0]["change"], "")

    def test_an_unknown_action_still_renders(self):
        rows = view_model.control_event_rows(
            [{"action": "SOMETHING_NEW", "actor": "x", "resource": "y", "created_at": "t"}]
        )
        self.assertEqual(rows[0]["label"], "Something new")
        self.assertEqual(rows[0]["color"], tokens.NEUTRAL)

    def test_list_and_scalar_changes_are_summarised(self):
        rows = view_model.control_event_rows(
            [
                {
                    "action": "ACCESS_GRANTED",
                    "actor": "x",
                    "resource": "agent:researcher:api.internal",
                    "before": {"allowed_domains": []},
                    "after": {"allowed_domains": ["docs.internal", "api.internal"]},
                    "created_at": "t",
                }
            ]
        )
        self.assertEqual(
            rows[0]["change"],
            "allowed_domains=none → allowed_domains=docs.internal, api.internal",
        )


class AgentTallyTest(unittest.TestCase):
    def test_the_tally_skips_outcomes_that_never_happened(self):
        agents = [
            {
                "name": "researcher",
                "ip": "172.28.0.11",
                "allowed_domains": ["docs.internal"],
                "requests_per_second": 5,
                "requests_total": 4,
                "allowed": 4,
                "blocked": 0,
                "throttled": 0,
            }
        ]
        self.assertEqual(view_model.agent_rows(agents, [])[0]["tally"], "4 queries · 4 allowed")

    def test_an_untouched_agent_says_so(self):
        self.assertEqual(view_model.agent_rows(AGENTS, [])[0]["tally"], "no queries yet")


class AlertRowsTest(unittest.TestCase):
    def test_severity_gets_a_label_and_a_status_colour(self):
        rows = view_model.alert_rows(
            [
                {"agent": "deployer", "severity": "critical", "message": "spent",
                 "spent": 50, "limit": 50, "percent": 100.0},
                {"agent": "researcher", "severity": "warning", "message": "nearly",
                 "spent": 30, "limit": 40, "percent": 75.0},
            ]
        )
        self.assertEqual(rows[0]["label"], "Critical")
        self.assertEqual(rows[0]["color"], tokens.CRITICAL)
        self.assertEqual(rows[0]["usage"], "50 / 50 units")
        self.assertEqual(rows[1]["label"], "Warning")
        self.assertEqual(rows[1]["color"], tokens.WARNING)

    def test_an_unknown_severity_still_renders(self):
        rows = view_model.alert_rows([{"agent": "x", "severity": "odd"}])
        self.assertEqual(rows[0]["label"], "Notice")
        self.assertEqual(rows[0]["color"], tokens.NEUTRAL)


class SpendRowsTest(unittest.TestCase):
    def test_the_meter_changes_colour_as_the_budget_is_used(self):
        rows = view_model.spend_rows(
            [
                {"agent": "a", "spent": 5, "limit": 50, "window_seconds": 60, "percent": 10.0},
                {"agent": "b", "spent": 42, "limit": 50, "window_seconds": 60, "percent": 84.0},
                {"agent": "c", "spent": 50, "limit": 50, "window_seconds": 60,
                 "percent": 100.0, "exhausted": True},
            ]
        )
        self.assertEqual([row["color"] for row in rows],
                         [tokens.GOOD, tokens.WARNING, tokens.CRITICAL])
        self.assertEqual(rows[0]["label"], "5 / 50 units in 60s")

    def test_the_bar_never_overflows_its_track(self):
        rows = view_model.spend_rows(
            [{"agent": "a", "spent": 90, "limit": 50, "window_seconds": 60,
              "percent": 180.0, "exhausted": True}]
        )
        self.assertEqual(rows[0]["width"], "100%")


class ActsTest(unittest.TestCase):
    def test_acts_report_progress_against_their_own_scenarios(self):
        rows = view_model.act_rows(scenarios_by_stage(), {})
        self.assertEqual([row["title"] for row in rows], [title for _, title, _ in STAGES])
        # Defend comes straight after Govern: decide who may talk to what, then
        # close the paths an attacker would use anyway.
        self.assertEqual([row["title"] for row in rows][:2], ["Govern", "Defend"])
        self.assertTrue(all(row["status"] == "not run" for row in rows))

        verdicts = {"failover": "PASS", "incident-response": "FAIL"}
        survive = [row for row in view_model.act_rows(scenarios_by_stage(), verdicts) if row["key"] == "survive"][0]
        self.assertEqual(survive["ran"], 2)
        self.assertEqual(survive["passed"], 1)
        self.assertEqual(survive["status"], "1/2 passed")
        self.assertFalse(survive["complete"])

    def test_an_act_is_complete_only_when_every_scenario_passed(self):
        verdicts = {"failover": "PASS", "incident-response": "PASS"}
        survive = [row for row in view_model.act_rows(scenarios_by_stage(), verdicts) if row["key"] == "survive"][0]
        self.assertTrue(survive["complete"])

    def test_acts_use_distinct_categorical_colours(self):
        colors = [row["color"] for row in view_model.act_rows(scenarios_by_stage(), {})]
        self.assertEqual(len(set(colors)), len(colors))

    def test_there_is_a_categorical_slot_for_every_act(self):
        # Hues are assigned in fixed order and never cycled, so adding an act
        # means adding a slot rather than reusing act one's colour.
        self.assertLessEqual(len(STAGES), len(tokens.ACT_COLORS))


if __name__ == "__main__":
    unittest.main()
