import asyncio
import unittest

import httpx

from demo.runner import Lab


def run(coroutine):
    return asyncio.run(coroutine)


class DashboardSnapshotClientTest(unittest.TestCase):
    def test_one_authenticated_request_refreshes_the_dashboard(self):
        requests = []
        payload = {
            "events": [],
            "summary": {"total": 7},
            "agents": [],
            "endpoints": [],
            "control_events": [],
            "alerts": [],
            "spend": [],
        }

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=payload)

        async def exercise():
            transport = httpx.MockTransport(respond)
            async with httpx.AsyncClient(transport=transport) as client:
                lab = Lab(
                    client,
                    control_api="http://control.test",
                    control_token="test-control-token",
                )
                return await lab.dashboard_snapshot()

        result = run(exercise())
        self.assertEqual(result, payload)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/dashboard")
        self.assertEqual(requests[0].url.params["events_limit"], "60")
        self.assertEqual(
            requests[0].headers["authorization"], "Bearer test-control-token"
        )


if __name__ == "__main__":
    unittest.main()
