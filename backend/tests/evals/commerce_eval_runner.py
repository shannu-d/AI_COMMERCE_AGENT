"""Runs the evaluation suite and scores it.

Two entry points over one implementation, because a suite whose CI form and
whose report form are different code is a suite that eventually reports one
thing and enforces another:

* `pytest tests/evals` runs every case as one test and fails the build on a P0;
* `python -m tests.evals.commerce_eval_runner` runs the same cases and writes
  `evaluation-results.json` plus the numbers `docs/EVALUATION-REPORT.md` quotes.

**Isolation is per case.** Each case gets a session bound to its own connection
inside a transaction that is rolled back afterwards, with
`join_transaction_mode="create_savepoint"` so that application code committing
its own unit of work behaves exactly as it does in production while nothing
survives. Several cases deliberately move a price or empty a shelf; none of
them may be visible to the next one.

**No case calls a live model.** ADR-015, and also the point: the model's
behaviour is the independent variable here, scripted per case, so that a
misbehaving model can be evaluated on purpose rather than waited for.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

HERE = Path(__file__).parent
CASES_PATH = HERE / "commerce_eval_cases.json"
RESULTS_PATH = HERE / "evaluation-results.json"

#: The four aggregate rates Phase 8 asks for, keyed by the tag a case carries.
DIMENSIONS = ("hard_constraint", "safety", "grounding", "authorization")


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["cases"])


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


@contextmanager
def isolated_session(engine: Engine) -> Iterator[tuple[Session, sessionmaker]]:
    """A session, and a sessionmaker over the same connection, both discarded.

    The sessionmaker is for the MCP tools, which open and commit their own
    unit-of-work sessions. Sharing the connection is what lets an MCP case and
    the evaluator see the same uncommitted world, and rolling the outer
    transaction back is what stops either from leaking into the next case.
    """
    connection = engine.connect()
    outer = connection.begin()
    maker = sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        future=True,
        class_=Session,
    )
    session = maker()
    try:
        yield session, maker
    finally:
        session.close()
        outer.rollback()
        connection.close()


def run_one(
    case: dict[str, Any], engine: Engine, merchant_id: uuid.UUID, facts: Any
) -> dict[str, Any]:
    """One case: run it, grade it, and say what happened either way."""
    from tests.evals.graders import run_checks
    from tests.evals.harness import run_case

    started = time.perf_counter()
    with isolated_session(engine) as (session, maker):
        prepared = dict(case)
        if case.get("mode") == "mcp":
            from app.mcp.server import build_server

            prepared["_server"] = build_server(sessionmaker=maker)
        observation = run_case(prepared, session, merchant_id)
        results = run_checks(observation, facts, case["checks"])

    failures = [entry for entry in results if not entry["passed"]]
    return {
        "id": case["id"],
        "category": case["category"],
        "mode": case.get("mode", "agent"),
        "prompt": case["prompt"],
        "expected_intent": case["expected_intent"],
        "expected_constraints": case["expected_constraints"],
        "expected_behavior": case["expected_behavior"],
        "forbidden_behavior": case["forbidden_behavior"],
        "dimensions": case.get("dimensions", []),
        "severity_if_failed": case.get("severity_if_failed", "P1"),
        "passed": not failures,
        "checks": results,
        "failed_checks": failures,
        "actual": _summarize(observation),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def _summarize(observation: Any) -> dict[str, Any]:
    """What the case actually produced, small enough to put in a report.

    Deliberately not the whole observation: a full tool payload for 270 cases is
    megabytes, and the fields below are the ones a failure is explained by.
    """
    return {
        "message": observation.message[:400],
        "recommendation_skus": [row.get("sku") for row in observation.recommendations],
        "tools_called": [call["tool"] for call in observation.tool_calls],
        "tool_error_codes": observation.error_codes(),
        "result_skus": [row.get("sku") for row in observation.results_of()],
        "cart_total": None if observation.cart is None else observation.cart.get("total"),
        "policy": observation.extras.get("policy"),
        "order_outcome": observation.extras.get("order_outcome"),
        "mcp_result": _trim(observation.extras.get("mcp_result")),
        "orders_created": (
            None
            if observation.extras.get("orders_after") is None
            else observation.extras["orders_after"] - observation.extras["orders_before"]
        ),
        "provider_calls": observation.extras.get("provider_calls", []),
        "crashed": observation.crashed,
    }


def _trim(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    return {
        key: value
        for key, value in payload.items()
        if key
        in {
            "status",
            "stage",
            "code",
            "message",
            "reason_codes",
            "total",
            "razorpay_order_id",
            "raised",
        }
    }


def run_suite(
    cases: list[dict[str, Any]], engine: Engine, merchant_id: uuid.UUID, *, progress: bool = False
) -> list[dict[str, Any]]:
    from tests.evals.catalog_facts import load_facts

    with isolated_session(engine) as (session, _maker):
        facts = load_facts(session, merchant_id)

    results = []
    for index, case in enumerate(cases, start=1):
        outcome = run_one(case, engine, merchant_id, facts)
        results.append(outcome)
        if progress:
            mark = "." if outcome["passed"] else "F"
            sys.stdout.write(mark)
            if index % 70 == 0:
                sys.stdout.write(f" {index}/{len(cases)}\n")
            sys.stdout.flush()
    if progress:
        sys.stdout.write("\n")
    return results


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase 8's numbers, and Phase 9's severities.

    A severity is attached to a *failure*, never to a pass: `severity_if_failed`
    says how bad it would be to get this case wrong, and counting it for a case
    that passed would make the totals meaningless.
    """
    total = len(results)
    passed = sum(1 for entry in results if entry["passed"])

    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
    for entry in results:
        bucket = by_category[entry["category"]]
        bucket["total"] += 1
        bucket["passed"] += int(entry["passed"])

    by_dimension: dict[str, dict[str, int]] = {
        name: {"total": 0, "passed": 0} for name in DIMENSIONS
    }
    for entry in results:
        for name in entry.get("dimensions", []):
            if name in by_dimension:
                by_dimension[name]["total"] += 1
                by_dimension[name]["passed"] += int(entry["passed"])

    severities = Counter(entry["severity_if_failed"] for entry in results if not entry["passed"])

    def rate(bucket: dict[str, int]) -> float | None:
        # `None`, not 0.0, for an empty bucket. A dimension no case carries has
        # no pass rate, and printing 0% for it reads as a total failure.
        return None if not bucket["total"] else round(100 * bucket["passed"] / bucket["total"], 1)

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": 0.0 if not total else round(100 * passed / total, 1),
        "by_category": {
            name: {**bucket, "rate": rate(bucket)} for name, bucket in sorted(by_category.items())
        },
        "by_dimension": {
            name: {**bucket, "rate": rate(bucket)} for name, bucket in by_dimension.items()
        },
        "failures_by_severity": {
            level: severities.get(level, 0) for level in ("P0", "P1", "P2", "P3")
        },
        "p0_failures": [
            entry["id"]
            for entry in results
            if not entry["passed"] and entry["severity_if_failed"] == "P0"
        ],
    }


def print_summary(summary: dict[str, Any]) -> None:
    print()
    print(f"TOTAL CASES:  {summary['total']}")
    print(f"PASSED:       {summary['passed']}")
    print(f"FAILED:       {summary['failed']}")
    print(f"PASS RATE:    {summary['pass_rate']}%")
    print()
    for level, count in summary["failures_by_severity"].items():
        print(f"{level}: {count}")
    print()
    print("Category scores")
    for name, bucket in summary["by_category"].items():
        shown = "n/a" if bucket["rate"] is None else f"{bucket['rate']}%"
        print(f"  {name:24} {bucket['passed']:>4}/{bucket['total']:<4} {shown:>7}")
    print()
    labels = {
        "hard_constraint": "HARD-CONSTRAINT",
        "safety": "SAFETY",
        "grounding": "GROUNDING",
        "authorization": "AUTHORIZATION",
    }
    for name, bucket in summary["by_dimension"].items():
        shown = "n/a" if bucket["rate"] is None else f"{bucket['rate']}%"
        print(f"{labels[name]:>16} PASS RATE: {shown}  ({bucket['passed']}/{bucket['total']})")
    if summary["p0_failures"]:
        print()
        print("P0 FAILURES (money / safety):")
        for case_id in summary["p0_failures"]:
            print(f"  - {case_id}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the commerce evaluation suite.")
    parser.add_argument("--filter", default=None, help="substring match on case id or category")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=RESULTS_PATH)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("TEST_DATABASE_URL"),
        help="PostgreSQL URL. ADR-002: never a different engine.",
    )
    args = parser.parse_args(argv)

    if not args.database_url:
        parser.error(
            "no database. Set TEST_DATABASE_URL or pass --database-url. "
            "ADR-002: the suite is never redirected to a different engine."
        )

    os.environ.setdefault("ENVIRONMENT", "test")

    # The same hermeticity `tests/conftest.py` enforces, for the CLI path.
    # `Settings` hard-codes an `env_file`, so without this the runner reads the
    # developer's real `.env` - and once that holds live Razorpay keys, a
    # commerce case starts making a provider call mid-run.
    from app.config import Settings

    Settings.model_config["env_file"] = None

    from app.identifiers import DEFAULT_MERCHANT_ID

    cases = load_cases()
    if args.filter:
        needle = args.filter.lower()
        cases = [c for c in cases if needle in c["id"].lower() or needle in c["category"].lower()]
    if args.limit:
        cases = cases[: args.limit]

    # `connect_timeout` is not decoration. On this machine a bare `localhost`
    # URL can hang indefinitely resolving IPv6 before falling back; with a
    # timeout psycopg moves on and connects. A run that hangs looks exactly like
    # a run that is slow, which is the worst way for a suite to fail.
    engine = create_engine(args.database_url, connect_args={"connect_timeout": 10}, future=True)
    try:
        results = run_suite(cases, engine, DEFAULT_MERCHANT_ID, progress=True)
    finally:
        engine.dispose()

    summary = score(results)
    args.out.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(summary)
    print(f"\nwrote {args.out}")
    return 1 if summary["failures_by_severity"]["P0"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
