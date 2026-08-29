from __future__ import annotations

import atexit
import json
import queue
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .policy import Decision

# A DNS answer must not wait on disk. Decisions are handed to a writer thread
# that batches them, and readers flush the queue before they query.
BATCH_SIZE = 128
FLUSH_INTERVAL_SECONDS = 0.05
_SHUTDOWN = object()


class EventStore:
    def __init__(self, database_path: str, async_writes: bool = True):
        self.database_path = database_path
        self._lock = threading.Lock()
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()
        self._queue: "queue.Queue[object]" = queue.Queue()
        self._writer: Optional[threading.Thread] = None
        self._async_writes = async_writes
        if async_writes:
            self._writer = threading.Thread(
                target=self._drain, name="event-writer", daemon=True
            )
            self._writer.start()
            atexit.register(self.close)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dns_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    source_ip TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    action TEXT NOT NULL,
                    answer TEXT,
                    reason TEXT NOT NULL,
                    latency_ms REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS control_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT
                )
                """
            )
            # The dashboard polls the aggregates every few seconds; these keep
            # those scans off the whole table as the log grows.
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_dns_events_action ON dns_events(action)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_dns_events_agent ON dns_events(agent)"
            )

    INSERT_EVENT = """
        INSERT INTO dns_events
            (created_at, source_ip, agent, domain, action, answer, reason, latency_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """

    def record(self, source_ip: str, decision: Decision, latency_ms: float) -> None:
        """Queue one decision. Returns without touching the disk."""
        row: Tuple = (
            datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            source_ip,
            decision.agent,
            decision.domain,
            decision.action,
            decision.answer,
            decision.reason,
            latency_ms,
        )
        if not self._async_writes:
            with self._lock, self.connect() as connection:
                connection.execute(self.INSERT_EVENT, row)
            return
        self._queue.put(row)

    def _drain(self) -> None:
        """Writer thread: one long-lived connection, batched commits."""
        connection = self.connect()
        connection.execute("PRAGMA journal_mode=WAL")
        # WAL plus NORMAL is durable across process crashes, which is the
        # failure this log needs to survive.
        connection.execute("PRAGMA synchronous=NORMAL")
        try:
            while True:
                item = self._queue.get()
                if item is _SHUTDOWN:
                    self._queue.task_done()
                    return
                batch = [item]
                while len(batch) < BATCH_SIZE:
                    try:
                        extra = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if extra is _SHUTDOWN:
                        self._write(connection, batch)
                        for _ in batch:
                            self._queue.task_done()
                        self._queue.task_done()
                        return
                    batch.append(extra)
                self._write(connection, batch)
                for _ in batch:
                    self._queue.task_done()
        finally:
            connection.close()

    def _write(self, connection: sqlite3.Connection, batch: List[Tuple]) -> None:
        try:
            with connection:
                connection.executemany(self.INSERT_EVENT, batch)
        except sqlite3.Error:
            # Losing a log line must never take the resolver down.
            pass

    def flush(self) -> None:
        """Wait for queued decisions to land, so reads see every answer given."""
        if self._async_writes:
            self._queue.join()

    def close(self) -> None:
        if self._async_writes and self._writer and self._writer.is_alive():
            self._queue.put(_SHUTDOWN)
            self._writer.join(timeout=5)

    def events(self, limit: int = 100) -> List[dict]:
        self.flush()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM dns_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def control_event(
        self,
        actor: str,
        action: str,
        resource: str,
        before: object = None,
        after: object = None,
        scenario_id: str = "",
    ) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO control_events
                    (created_at, actor, scenario_id, action, resource, before_json, after_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    actor,
                    scenario_id,
                    action,
                    resource,
                    json.dumps(before) if before is not None else None,
                    json.dumps(after) if after is not None else None,
                ),
            )

    def control_events(self, limit: int = 100) -> List[dict]:
        self.flush()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM control_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["before"] = (
                json.loads(event.pop("before_json")) if event["before_json"] else None
            )
            event["after"] = (
                json.loads(event.pop("after_json")) if event["after_json"] else None
            )
            events.append(event)
        return events

    def agent_activity(self) -> dict:
        self.flush()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    agent,
                    COUNT(*) AS requests_total,
                    MAX(created_at) AS last_seen,
                    SUM(CASE WHEN action = 'ALLOW' THEN 1 ELSE 0 END) AS allowed,
                    SUM(CASE WHEN action = 'BLOCK' THEN 1 ELSE 0 END) AS blocked,
                    SUM(CASE WHEN action = 'THROTTLE' THEN 1 ELSE 0 END) AS throttled
                FROM dns_events
                GROUP BY agent
                """
            ).fetchall()
        return {row["agent"]: dict(row) for row in rows}

    def summary(self) -> dict:
        self.flush()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT action, COUNT(*) AS count FROM dns_events GROUP BY action"
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM dns_events").fetchone()[0]
        counts = {row["action"]: row["count"] for row in rows}
        return {
            "total": total,
            "allowed": counts.get("ALLOW", 0),
            "blocked": counts.get("BLOCK", 0),
            "throttled": counts.get("THROTTLE", 0),
            "failures": counts.get("SERVFAIL", 0) + counts.get("NXDOMAIN", 0),
        }

    def clear(self) -> None:
        self.flush()
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM dns_events")
            connection.execute("DELETE FROM control_events")
