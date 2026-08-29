import tempfile
import unittest
from pathlib import Path

from dns_manager.policy import Decision
from dns_manager.store import EventStore


class EventStoreTest(unittest.TestCase):
    def test_records_and_summarizes_events(self):
        with tempfile.TemporaryDirectory() as tempdir:
            store = EventStore(str(Path(tempdir) / "events.db"))
            store.record(
                "10.0.0.11",
                Decision("researcher", "docs.internal", "ALLOW", "10.0.0.21"),
                1.25,
            )
            store.record(
                "10.0.0.13",
                Decision("untrusted", "docs.internal", "BLOCK", reason="domain_not_allowed"),
                0.5,
            )
            self.assertEqual(len(store.events()), 2)
            self.assertEqual(
                store.summary(),
                {"total": 2, "allowed": 1, "blocked": 1, "throttled": 0, "failures": 0},
            )
            activity = store.agent_activity()
            self.assertEqual(activity["researcher"]["requests_total"], 1)
            store.control_event(
                "reflex-dashboard",
                "ACCESS_GRANTED",
                "agent:researcher:api.internal",
                before={"allowed": False},
                after={"allowed": True},
                scenario_id="live-policy",
            )
            control = store.control_events()
            self.assertEqual(control[0]["actor"], "reflex-dashboard")
            self.assertEqual(control[0]["scenario_id"], "live-policy")
            self.assertEqual(control[0]["after"], {"allowed": True})


if __name__ == "__main__":
    unittest.main()
