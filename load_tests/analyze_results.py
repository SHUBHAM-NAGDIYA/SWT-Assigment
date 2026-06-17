"""
Phase 11 — Load Test Results Analyzer
======================================
Reads Locust CSV output files and prints a pass/fail report against
the assignment's performance targets.

Usage
-----
    python analyze_results.py results/

Expects files named:  run_50u_stats.csv, run_100u_stats.csv, etc.
"""

from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Performance targets (assignment requirements)
# ---------------------------------------------------------------------------

TARGETS = {
    "max_avg_response_ms": 1_000,   # avg well under 2 s
    "max_p95_ms":          2_000,   # P95 must be < 2 s (hard requirement)
    "max_failure_rate_pct": 1.0,    # < 1% failure rate
    "min_rps":             10.0,    # minimum acceptable throughput
}

USER_LEVELS = [50, 100, 200, 500]


@dataclass
class EndpointResult:
    name: str
    requests: int
    failures: int
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    rps: float

    @property
    def failure_rate(self) -> float:
        return (self.failures / self.requests * 100) if self.requests else 0.0

    @property
    def passes(self) -> bool:
        return (
            self.avg_ms <= TARGETS["max_avg_response_ms"]
            and self.p95_ms <= TARGETS["max_p95_ms"]
            and self.failure_rate <= TARGETS["max_failure_rate_pct"]
        )


@dataclass
class RunResult:
    user_level: int
    endpoints: list[EndpointResult] = field(default_factory=list)
    aggregated: Optional[EndpointResult] = None

    @property
    def passes(self) -> bool:
        return self.aggregated is not None and self.aggregated.passes


def _parse_csv(path: Path, user_level: int) -> RunResult:
    """Parse a Locust *_stats.csv file into a ``RunResult``."""
    result = RunResult(user_level=user_level)
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ep = EndpointResult(
                name=row.get("Name", ""),
                requests=int(row.get("Request Count", 0)),
                failures=int(row.get("Failure Count", 0)),
                avg_ms=float(row.get("Average Response Time", 0)),
                p50_ms=float(row.get("50%", 0)),
                p95_ms=float(row.get("95%", 0)),
                p99_ms=float(row.get("99%", 0)),
                rps=float(row.get("Requests/s", 0)),
            )
            if ep.name == "Aggregated":
                result.aggregated = ep
            else:
                result.endpoints.append(ep)
    return result


def _status(passes: bool) -> str:
    return "✅ PASS" if passes else "❌ FAIL"


def print_summary_table(runs: list[RunResult]) -> None:
    header = (
        f"{'Users':>6} | {'Avg ms':>7} | {'P95 ms':>7} | "
        f"{'RPS':>6} | {'Fail%':>6} | {'Status'}"
    )
    separator = "-" * len(header)
    print("\n" + separator)
    print("  Load Test Results vs Targets")
    print(f"  P95 target < {TARGETS['max_p95_ms']} ms  |  "
          f"Avg target < {TARGETS['max_avg_response_ms']} ms  |  "
          f"Failure < {TARGETS['max_failure_rate_pct']}%")
    print(separator)
    print(header)
    print(separator)

    for run in runs:
        ag = run.aggregated
        if ag is None:
            print(f"{run.user_level:>6} | {'N/A':>7} | {'N/A':>7} | "
                  f"{'N/A':>6} | {'N/A':>6} | ⚠  No data")
            continue
        print(
            f"{run.user_level:>6} | {ag.avg_ms:>7.0f} | {ag.p95_ms:>7.0f} | "
            f"{ag.rps:>6.1f} | {ag.failure_rate:>5.1f}% | {_status(run.passes)}"
        )
    print(separator)


def print_endpoint_detail(run: RunResult) -> None:
    print(f"\n  Endpoint breakdown — {run.user_level} users")
    print(f"  {'Endpoint':<40} {'Avg':>7} {'P95':>7} {'Fail%':>6} {'Status'}")
    print("  " + "-" * 72)
    for ep in sorted(run.endpoints, key=lambda e: e.p95_ms, reverse=True):
        if ep.requests == 0:
            continue
        print(
            f"  {ep.name:<40} {ep.avg_ms:>6.0f}ms {ep.p95_ms:>6.0f}ms "
            f"{ep.failure_rate:>5.1f}% {_status(ep.passes)}"
        )


def print_checklist(runs: list[RunResult]) -> None:
    all_pass = all(r.passes for r in runs if r.aggregated)

    checks = {
        "Response time P95 < 2 000 ms at all user levels":
            all(r.aggregated.p95_ms < 2000 for r in runs if r.aggregated),
        "Average response time < 1 000 ms at all user levels":
            all(r.aggregated.avg_ms < 1000 for r in runs if r.aggregated),
        "Failure rate < 1% at all user levels":
            all(r.aggregated.failure_rate < 1.0 for r in runs if r.aggregated),
        "System sustains 50 concurrent users":
            any(r.user_level == 50 and r.passes for r in runs),
        "System sustains 100 concurrent users":
            any(r.user_level == 100 and r.passes for r in runs),
        "System sustains 200 concurrent users":
            any(r.user_level == 200 and r.passes for r in runs),
        "System sustains 500 concurrent users":
            any(r.user_level == 500 and r.passes for r in runs),
    }

    print("\n" + "=" * 60)
    print("  Pass/Fail Checklist")
    print("=" * 60)
    for desc, ok in checks.items():
        print(f"  {'✅' if ok else '❌'}  {desc}")
    print("=" * 60)
    overall = "✅  SYSTEM PASSES assignment requirements" if all_pass \
              else "❌  SYSTEM FAILS — investigate failing endpoints"
    print(f"\n  OVERALL: {overall}\n")


def main(results_dir: str) -> None:
    base = Path(results_dir)
    runs: list[RunResult] = []

    for level in USER_LEVELS:
        csv_path = base / f"run_{level}u_stats.csv"
        if not csv_path.exists():
            print(f"  ⚠  Missing: {csv_path} — skipping {level} users")
            continue
        runs.append(_parse_csv(csv_path, level))

    if not runs:
        print("No result files found. Run the load tests first.")
        sys.exit(1)

    print_summary_table(runs)

    for run in runs:
        if run.endpoints:
            print_endpoint_detail(run)

    print_checklist(runs)


if __name__ == "__main__":
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    main(results_dir)
