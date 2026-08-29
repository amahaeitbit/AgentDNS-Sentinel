from __future__ import annotations

import os
import socket
import time
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import Depends, FastAPI, Query

from .security import require_agent

AGENT_ID = os.getenv("AGENT_ID", "unknown")
app = FastAPI(title=f"{AGENT_ID} traffic generator")


@app.get("/health")
def health():
    return {"status": "ok", "agent": AGENT_ID}


@app.post("/query", dependencies=[Depends(require_agent)])
def query(
    domain: str,
    count: int = Query(default=1, ge=1, le=100),
    interval_ms: int = Query(default=0, ge=0, le=5000),
):
    results = []
    for _ in range(count):
        try:
            answer = socket.gethostbyname(domain)
            results.append({"ok": True, "answer": answer})
        except socket.gaierror as error:
            results.append({"ok": False, "error": str(error)})
        if interval_ms:
            time.sleep(interval_ms / 1000)
    return {"agent": AGENT_ID, "domain": domain, "results": results}


@app.post("/fetch", dependencies=[Depends(require_agent)])
def fetch(domain: str, port: int = 8080):
    try:
        with urlopen(f"http://{domain}:{port}", timeout=3) as response:
            return {
                "agent": AGENT_ID,
                "domain": domain,
                "status": response.status,
                "body": response.read().decode(),
            }
    except (URLError, OSError) as error:
        return {"agent": AGENT_ID, "domain": domain, "error": str(error)}
