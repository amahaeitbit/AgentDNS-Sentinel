#!/usr/bin/env python3
"""Measure the resolver's decision path.

Runs the policy engine and the event store exactly as the DNS server does, and
reports throughput and tail latency. Nothing here needs Docker or the network,
so it is a fair way to compare a change against the commit before it.

    python scripts/benchmark.py
    python scripts/benchmark.py --queries 50000 --threads 8
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dns_manager.policy import PolicyEngine  # noqa: E402
from dns_manager.store import EventStore  # noqa: E402

# A mix that exercises every branch: allowed, denied, throttled, tunnelling,
# lookalike and unknown-agent.
WORKLOAD = [
    ("172.28.0.11", "docs.internal"),
    ("172.28.0.11", "pypi.org"),
    ("172.28.0.12", "api.internal"),
    ("172.28.0.12", "api.anthropic.com"),
    ("172.28.0.12", "metadata.internal"),
    ("172.28.0.13", "docs.internal"),
    ("172.28.0.14", "docs.internal"),
    ("172.28.0.11", "x" * 48 + ".pypi.org"),
    ("172.28.0.11", "pypi.org.evil.example"),
    ("10.0.0.99", "docs.internal"),
]


def unthrottled_config(source: str, tempdir: Path) -> str:
    """A copy of the real policy with quotas lifted.

    Otherwise the benchmark mostly measures how fast the rate limiter says no.
    """
    config = json.loads(Path(source).read_text())
    for policy in config.get("agents", {}).values():
        policy["requests_per_second"] = 10_000_000
    path = tempdir / "benchmark-policies.json"
    path.write_text(json.dumps(config))
    return str(path)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


def run(label: str, decide, queries: int, threads: int) -> dict:
    latencies: list[float] = []
    lock = threading.Lock()
    per_thread = max(queries // threads, 1)

    def worker():
        local: list[float] = []
        for index in range(per_thread):
            source_ip, domain = WORKLOAD[index % len(WORKLOAD)]
            started = time.perf_counter()
            decide(source_ip, domain)
            local.append((time.perf_counter() - started) * 1000)
        with lock:
            latencies.extend(local)

    workers = [threading.Thread(target=worker) for _ in range(threads)]
    started = time.perf_counter()
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join()
    elapsed = time.perf_counter() - started

    return {
        "label": label,
        "queries": len(latencies),
        "seconds": elapsed,
        "per_second": len(latencies) / elapsed if elapsed else 0.0,
        "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
    }


def report(rows: list[dict]) -> None:
    width = max(len(row["label"]) for row in rows)
    print(f"\n{'path':<{width}}  {'queries/s':>10}  {'mean':>8}  {'p50':>8}  {'p95':>8}  {'p99':>8}")
    print("-" * (width + 50))
    for row in rows:
        print(
            f"{row['label']:<{width}}  {row['per_second']:>10,.0f}  "
            f"{row['mean_ms']:>7.3f}m  {row['p50_ms']:>7.3f}m  "
            f"{row['p95_ms']:>7.3f}m  {row['p99_ms']:>7.3f}m"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=int, default=20000)
    parser.add_argument(
        "--inline-queries",
        type=int,
        default=200,
        help="sample size for the inline-write comparison, which commits per query",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--config", default=str(REPO_ROOT / "config" / "policies.json"))
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tempdir:
        engine = PolicyEngine(unthrottled_config(args.config, Path(tempdir)))
        rows = [
            run(
                "policy engine only",
                lambda ip, domain: engine.evaluate(ip, domain),
                args.queries,
                args.threads,
            )
        ]

        for label, async_writes, count in (
            ("+ event log, queued", True, args.queries),
            ("+ event log, inline commit", False, args.inline_queries),
        ):
            store = EventStore(str(Path(tempdir) / f"{async_writes}.db"), async_writes=async_writes)

            def decide(source_ip, domain, store=store):
                started = time.perf_counter()
                decision = engine.evaluate(source_ip, domain)
                store.record(source_ip, decision, (time.perf_counter() - started) * 1000)

            rows.append(run(label, decide, count, args.threads))
            store.flush()
            store.close()

    report(rows)
    queued = next(row for row in rows if "queued" in row["label"])
    inline = next(row for row in rows if "inline" in row["label"])
    if inline["per_second"]:
        print(
            f"\nQueuing the decision log is {queued['per_second'] / inline['per_second']:,.0f}x "
            f"the throughput of committing inline, and takes p99 from "
            f"{inline['p99_ms']:,.1f}ms to {queued['p99_ms']:.3f}ms."
        )
        print(
            "Inline commit cost is dominated by fsync, so it varies with the "
            "filesystem; the queued path does not touch the disk at all."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
