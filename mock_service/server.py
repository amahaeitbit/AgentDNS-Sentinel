from __future__ import annotations

import json
import hmac
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICE_NAME = os.getenv("SERVICE_NAME", "mock-service")
PORT = int(os.getenv("SERVICE_PORT", "8080"))
CONTROL_TOKEN = os.getenv("SERVICE_CONTROL_TOKEN", "demo-service-control-token")


class ServiceState:
    """Tracks whether the service is pretending to be up or down."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._healthy = True

    @property
    def healthy(self) -> bool:
        with self._lock:
            return self._healthy

    def set_healthy(self, healthy: bool) -> bool:
        with self._lock:
            self._healthy = healthy
            return self._healthy


STATE = ServiceState()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _status_payload(self) -> dict:
        return {
            "service": SERVICE_NAME,
            "status": "healthy" if STATE.healthy else "unhealthy",
        }

    def do_GET(self):
        # /health is what the DNS manager probes; everything else is agent traffic.
        if not STATE.healthy:
            self._reply(503, self._status_payload())
            return
        self._reply(200, self._status_payload())

    def do_POST(self):
        if not hmac.compare_digest(
            self.headers.get("Authorization", ""), f"Bearer {CONTROL_TOKEN}"
        ):
            self._reply(401, {"error": "valid service control token required"})
            return
        if self.path == "/control/fail":
            STATE.set_healthy(False)
        elif self.path == "/control/recover":
            STATE.set_healthy(True)
        else:
            self._reply(404, {"error": "unknown control endpoint", "path": self.path})
            return
        self._reply(200, self._status_payload())

    def log_message(self, *_):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
