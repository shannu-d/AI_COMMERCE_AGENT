"""The live tier: the same graders, against a running backend and the real model.

**Not a test, and deliberately outside pytest.** ADR-015 says no test may call a
live model, ever; this is an operator-run script, the backend equivalent of the
frontend's opt-in `npm run test:live`.

## What it adds, and what it cannot

The offline suite scripts the model, which is what makes the adversarial cases
possible and what makes every run reproducible. What it cannot observe is the
half the model actually owns: whether a real Groq turn *chooses* the right tool,
maps "something to protect my phone" onto `phone_case`, carries a budget across
turns, or asks a clarifying question instead of guessing.

This runs the same cases through `POST /api/chat` and applies the same graders
to the answer. Every check it runs is one that is meaningful over an ADR-010
`ChatResponse`:

* `recommendations[]` **is** ranking-engine output by contract, so the
  hard-constraint checks are applied to it directly;
* the prose checks are applied to `message`, which is exactly where the offline
  suite's one open finding lives.

Checks that need tool-level detail - a specific `ToolErrorCode`, the
alternatives payload, the eight-call bound - have no observable form in a
`ChatResponse` and are skipped rather than fudged. Each skip is recorded by
name, so a live report says what it did not check.

## Two rate limits, and the second is the one that bites

The account is on Groq's `on_demand` tier, which caps **8,000 tokens per
minute** and **200,000 tokens per day**. Both matter, and they fail differently:

* **Per minute.** One agent turn is two model calls - the system prompt plus
  every tool schema, then the same again with the tool results - which measures
  about 9,200 tokens. The two calls happen seconds apart, so *no pacing fits
  them*: the second is refused every time. That is what `--tool-call-only`
  exists for.
* **Per day.** At roughly 4,400 tokens a call, the daily budget is about 45
  calls. A morning of evaluation exhausts it, and then every call is refused
  whatever the pacing.

Which of the two was hit is *not* visible here: `client.py` maps a 429 onto
`LLMRateLimitError` with its own sentence and deliberately drops the provider's
body, which carries an organisation identifier. So this runner can only say a
call was refused. To see which limit and for how long, make one direct call with
the SDK and read the error - the body names the limit, the quota, the amount
used and the wait.

So this is for a *sample*, and `--pace` is not optional politeness. A run that
429s is not evidence of anything: a refused call is reported as
`rate_limited_or_unavailable`, never as a failure, because a model that never
answered has not got anything wrong.

## Usage

    # A whole turn, through the running backend. About 9,200 tokens per case,
    # which does not fit this tier's per-minute cap.
    python -m tests.evals.live_eval --base-url http://127.0.0.1:8004 \\
        --cases discovery_001,category_001,compat_001 --pace 90

    # One model call per case, executed by the real application. ~4,400 tokens.
    python -m tests.evals.live_eval --tool-call-only \\
        --cases spec_004,spec_009 --pace 420
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).parent
DEFAULT_OUT = HERE / "live-results.json"

#: Checks with an observable form in an ADR-010 `ChatResponse`. Everything else
#: is skipped by name rather than approximated.
LIVE_CHECKS = frozenset(
    {
        "products_exist",
        "prices_are_authoritative",
        "money_is_string",
        "no_fabricated_sku_in_prose",
        "no_fabricated_price_in_prose",
        "stock_is_coarse",
        "results_in_category",
        "results_within_budget",
        "results_compatible_with",
        "results_in_stock",
        "results_have_attributes",
        "results_count",
        "no_results",
        "no_recommendations",
        "results_ranked_consistently",
        "cart_total_is_authoritative",
        "runner_did_not_crash",
    }
)


def _observation(case: dict[str, Any], turns: list[dict[str, Any]]) -> Any:
    """A live turn in the shape the graders read.

    The recommendations are presented as one tool result because that is what
    they are: ADR-010 builds `recommendations[]` from `TurnMemory`, which only
    the tools write. Grading them as ranking-engine output is not a convenience,
    it is the contract.
    """
    from tests.evals.observation import Observation

    final = turns[-1]
    obs = Observation(case_id=case["id"], mode="live")
    obs.message = final.get("message", "")
    obs.recommendations = list(final.get("recommendations") or [])
    obs.cart = final.get("cart")
    obs.error = final.get("error")
    obs.turn_count = 1
    obs.tool_calls = [
        {
            "tool": "live_turn",
            "arguments": {},
            "turn": 0,
            "result": {"success": True, "result": {"results": obs.recommendations}},
        }
    ]
    if obs.cart:
        obs.extras["quotable_totals"] = [obs.cart.get("total"), obs.cart.get("subtotal")]
    obs.extras["states"] = [turn.get("state") for turn in turns]
    return obs


#: Checks meaningful when only the tool call was made — no prose exists yet, so
#: the two prose checks are excluded rather than passed vacuously.
TOOL_CALL_CHECKS = LIVE_CHECKS - {"no_fabricated_sku_in_prose", "no_fabricated_price_in_prose"}


def run_tool_call_case(
    case: dict[str, Any], engine: Any, merchant_id: Any, facts: Any
) -> dict[str, Any]:
    """One model call, then the application executes what it asked for.

    **Why this mode exists.** A full turn is two model calls — the tool payload
    and system prompt, then the same again with the tool results — and on this
    account that is about 9,200 tokens against a ceiling of 8,000 per minute.
    The two calls happen seconds apart, so no amount of pacing fits them: the
    second is refused every time, and `run_live_case` can only report
    `rate_limited_or_unavailable`.

    What that costs is the *second* leg, which is the model turning results it
    already has into a sentence. The first leg is where the behaviour under
    test lives: given the real system prompt and the real tool payload, which
    tool does the model call, and with which arguments? So this makes exactly
    one call, validates the arguments through the same A§19 pipeline the
    runtime uses, executes them against the real services, and grades the real
    results.

    It is a narrower observation than a full turn and it is labelled as one —
    `mode: "live_tool_call"` — but it is the observation that answers whether a
    stated requirement reaches `attributes`, which is the whole of finding F-3.
    """
    from app.agent.context import AgentContext, TurnMemory
    from app.agent.executor import ToolExecutor
    from app.agent.registry import build_registry
    from app.config import get_settings
    from app.llm.client import build_client
    from app.llm.errors import LLMError
    from app.llm.models import Message
    from app.llm.prompts import load_system_prompt
    from app.llm.tool_schemas import build_tool_definitions
    from tests.evals.commerce_eval_runner import isolated_session
    from tests.evals.graders import run_checks
    from tests.evals.harness import _order_count
    from tests.evals.observation import Observation

    settings = get_settings()
    prompt = case.get("prompt") or (case.get("turns") or [{}])[0].get("user", "")

    with isolated_session(engine) as (session, _maker):
        context = AgentContext.from_session(session, merchant_id)
        registry = build_registry()
        payload = build_tool_definitions(
            category_slugs=context.catalog.category_slugs(merchant_id),
            attribute_vocabulary=context.catalog.attribute_vocabulary(merchant_id),
            names=registry.names(),
        )
        try:
            answer = build_client().complete(
                system=load_system_prompt(),
                messages=[Message(role="user", content=prompt)],
                tools=payload,
                max_tokens=512,
            )
        except LLMError as exc:
            return {
                "id": case["id"],
                "status": "rate_limited_or_unavailable",
                "detail": f"{type(exc).__name__}: {exc}",
            }

        obs = Observation(case_id=case["id"], mode="live_tool_call")
        obs.extras["orders_before"] = _order_count(session, merchant_id)
        obs.offered_tools = tuple(tool["name"] for tool in payload)

        memory = TurnMemory(session_id=context.sessions.create(merchant_id).id)
        executor = ToolExecutor(
            registry, context, max_calls_per_turn=settings.max_tool_calls_per_turn
        )
        for call in answer.tool_calls:
            result = executor.execute(call.name, dict(call.arguments), memory)
            obs.tool_calls.append(
                {"tool": call.name, "arguments": dict(call.arguments), "turn": 0, "result": result}
            )
        obs.recommendations = [
            row
            for entry in obs.tool_calls
            for row in (entry["result"].get("result") or {}).get("results", [])
        ]
        obs.extras["orders_after"] = _order_count(session, merchant_id)

    applicable = [spec for spec in case["checks"] if spec["check"] in TOOL_CALL_CHECKS]
    skipped = sorted({spec["check"] for spec in case["checks"]} - TOOL_CALL_CHECKS)
    results = run_checks(obs, facts, applicable)
    failures = [entry for entry in results if not entry["passed"]]

    return {
        "id": case["id"],
        "category": case["category"],
        "status": "graded",
        "mode": "live_tool_call",
        "passed": not failures,
        "prompts": [prompt],
        "message": "",
        "tool_calls": [
            {"tool": entry["tool"], "arguments": entry["arguments"]} for entry in obs.tool_calls
        ],
        "recommendation_skus": [row.get("sku") for row in obs.recommendations],
        "checks_run": [entry["check"] for entry in results],
        "checks_skipped_no_live_form": skipped,
        "failed_checks": failures,
    }


def run_live_case(
    case: dict[str, Any], client: httpx.Client, facts: Any, *, pace: float
) -> dict[str, Any]:
    from tests.evals.graders import run_checks

    prompts = [turn["user"] for turn in case.get("turns", [])] or [case["prompt"]]
    session_id: str | None = None
    answers: list[dict[str, Any]] = []

    for index, prompt in enumerate(prompts):
        if index:
            time.sleep(pace)
        body: dict[str, Any] = {"message": prompt}
        if session_id:
            body["session_id"] = session_id
        try:
            response = client.post("/api/chat", json=body, timeout=120.0)
        except httpx.HTTPError as exc:
            return {"id": case["id"], "status": "transport_error", "detail": str(exc)}
        if response.status_code != 200:
            return {
                "id": case["id"],
                "status": "http_error",
                "detail": f"{response.status_code}: {response.text[:300]}",
            }
        payload = response.json()
        session_id = payload["session_id"]
        answers.append(payload)

    final = answers[-1]
    error = final.get("error") or {}
    # A turn the model never answered is not a wrong answer. The runtime reports
    # an exhausted rate limit as SERVER_ERROR, which is indistinguishable here
    # from any other transport failure - so it is reported as its own outcome
    # rather than counted against the system.
    if error.get("code") == "SERVER_ERROR":
        return {"id": case["id"], "status": "rate_limited_or_unavailable", "detail": error}

    observation = _observation(case, answers)
    applicable = [spec for spec in case["checks"] if spec["check"] in LIVE_CHECKS]
    skipped = sorted({spec["check"] for spec in case["checks"]} - LIVE_CHECKS)
    results = run_checks(observation, facts, applicable)
    failures = [entry for entry in results if not entry["passed"]]

    return {
        "id": case["id"],
        "category": case["category"],
        "status": "graded",
        "passed": not failures,
        "prompts": prompts,
        "message": final.get("message", "")[:500],
        "recommendation_skus": [row.get("sku") for row in final.get("recommendations") or []],
        "checks_run": [entry["check"] for entry in results],
        "checks_skipped_no_live_form": skipped,
        "failed_checks": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run evaluation cases against a live backend.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8004")
    parser.add_argument("--cases", default=None, help="comma-separated case ids")
    parser.add_argument("--category", default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--pace",
        type=float,
        default=90.0,
        help="seconds between model turns. The account allows 8000 tokens/minute.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--database-url", default=os.environ.get("TEST_DATABASE_URL"))
    parser.add_argument(
        "--tool-call-only",
        action="store_true",
        help=(
            "One model call per case instead of a whole turn: the model chooses "
            "the tool and its arguments, the application executes them, and the "
            "real results are graded. Fits the token budget a full two-leg turn "
            "does not, and covers the half of the problem the offline suite "
            "cannot see. Does not use --base-url."
        ),
    )
    args = parser.parse_args(argv)

    if not args.database_url:
        parser.error("set TEST_DATABASE_URL: the graders read the catalogue from the database")

    from sqlalchemy import create_engine

    from app.identifiers import DEFAULT_MERCHANT_ID
    from tests.evals.catalog_facts import load_facts
    from tests.evals.commerce_eval_runner import isolated_session, load_cases

    cases = [case for case in load_cases() if case.get("mode", "agent") == "agent"]
    if args.cases:
        wanted = {name.strip() for name in args.cases.split(",")}
        cases = [case for case in cases if case["id"] in wanted]
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]
    cases = cases[: args.limit]

    engine = create_engine(args.database_url, connect_args={"connect_timeout": 10}, future=True)
    try:
        with isolated_session(engine) as (session, _maker):
            facts = load_facts(session, DEFAULT_MERCHANT_ID)

        results = []
        if args.tool_call_only:
            os.environ.setdefault("ENVIRONMENT", "local")
            for index, case in enumerate(cases):
                if index:
                    time.sleep(args.pace)
                outcome = run_tool_call_case(case, engine, DEFAULT_MERCHANT_ID, facts)
                results.append(outcome)
                print(f"{outcome['id']:<24} {outcome['status']:<28} {outcome.get('passed', '')}")
        else:
            with httpx.Client(base_url=args.base_url) as client:
                for index, case in enumerate(cases):
                    if index:
                        time.sleep(args.pace)
                    outcome = run_live_case(case, client, facts, pace=args.pace)
                    results.append(outcome)
                    print(
                        f"{outcome['id']:<24} {outcome['status']:<28} {outcome.get('passed', '')}"
                    )
    finally:
        engine.dispose()

    graded = [entry for entry in results if entry["status"] == "graded"]
    passed = [entry for entry in graded if entry["passed"]]
    summary = {
        "base_url": None if args.tool_call_only else args.base_url,
        "mode": "live_tool_call" if args.tool_call_only else "live_turn",
        "attempted": len(results),
        "graded": len(graded),
        "passed": len(passed),
        "not_graded": [
            {"id": entry["id"], "status": entry["status"]}
            for entry in results
            if entry["status"] != "graded"
        ],
        "note": (
            "A live sample, not a live suite. The account caps 8,000 tokens per "
            "minute and 200,000 per day; one agent turn is two model calls "
            "totalling about 9,200 tokens, so a full turn does not fit the "
            "per-minute cap at all, and the daily cap is about 45 single calls."
        ),
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_id": str(uuid.uuid4()),
    }
    args.out.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print()
    print(
        f"attempted {summary['attempted']}, graded {summary['graded']}, passed {summary['passed']}"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
