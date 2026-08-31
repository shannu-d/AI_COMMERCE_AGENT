"""The A§19 validation pipeline (ADR-009).

    parse -> schema validation -> authorization -> business validation -> execute

Every stage is asserted by what it *refuses*, because the pipeline's value is
entirely in the calls it does not let through. A test that only checked the happy
path would pass against an executor that ran everything.
"""

from __future__ import annotations

from app.agent.errors import ToolError, ToolErrorCode
from app.agent.executor import ToolExecutor
from app.agent.registry import RegisteredTool, ToolRegistry, build_registry
from app.llm.tool_schemas import TOOL_SCHEMAS, RiskTier
from tests.agent.conftest import make_ranked, make_recommendation, make_variant


def executor(context, registry=None, *, limit: int = 8) -> ToolExecutor:
    return ToolExecutor(registry or build_registry(), context, max_calls_per_turn=limit)


# --------------------------------------------------------------------------
# Stage 1: the loop bound (A§36, ADR-009 closing E1)
# --------------------------------------------------------------------------


def test_the_ninth_call_in_a_turn_is_refused(context, memory, recommendations):
    """Eight per turn. The ninth is stopped before it is even validated."""
    recommendations.result = make_recommendation(make_ranked(make_variant()))
    ex = executor(context, limit=8)

    for _ in range(8):
        assert ex.execute("search_catalog", {"category": "phone_case"}, memory)["success"]

    ninth = ex.execute("search_catalog", {"category": "phone_case"}, memory)

    assert ninth["success"] is False
    assert ninth["error"]["code"] == ToolErrorCode.TOOL_LIMIT_REACHED.value


def test_the_limit_is_checked_before_the_tool_is_looked_up(context, memory):
    """A call that cannot be afforded is not validated, authorized or run.

    Asserted with a *nonexistent* tool: if the limit were checked after the
    registry lookup, the answer would be UNKNOWN_TOOL instead.
    """
    ex = executor(context, limit=0)

    result = ex.execute("no_such_tool", {}, memory)

    assert result["error"]["code"] == ToolErrorCode.TOOL_LIMIT_REACHED.value


def test_a_failed_call_still_consumes_one_of_the_eight(context, memory):
    """Otherwise a model that only makes bad calls loops forever."""
    ex = executor(context, limit=8)

    ex.execute("no_such_tool", {}, memory)

    assert memory.call_count == 1
    assert ex.remaining(memory) == 7


# --------------------------------------------------------------------------
# Stage 2: parse
# --------------------------------------------------------------------------


def test_create_order_is_reported_as_forbidden_rather_than_unknown(context, memory):
    """ADR-009, closing D6. The attempt must be visible in a log.

    `create_order` is not registered, so an executor that simply looked it up
    would answer UNKNOWN_TOOL — indistinguishable from a typo. Naming it
    forbidden is what makes an injection attempt legible afterwards.
    """
    result = executor(context).execute("create_order", {}, memory)

    assert result["success"] is False
    assert result["error"]["code"] == ToolErrorCode.FORBIDDEN_TOOL.value


def test_an_unknown_tool_is_refused_and_told_what_does_exist(context, memory):
    result = executor(context).execute("search_products", {}, memory)

    assert result["error"]["code"] == ToolErrorCode.UNKNOWN_TOOL.value
    # F§6 calls it `search_products`; ADR-009 makes `search_catalog` canonical
    # (closing E4). Listing the real names is how the model recovers.
    assert "search_catalog" in result["error"]["details"]["available"]


def test_arguments_that_are_not_an_object_are_refused(context, memory):
    result = executor(context).execute("search_catalog", ["phone_case"], memory)  # type: ignore[arg-type]

    assert result["error"]["code"] == ToolErrorCode.INVALID_ARGUMENTS.value


# --------------------------------------------------------------------------
# Stage 3: schema validation
# --------------------------------------------------------------------------


def test_a_hallucinated_field_fails_validation_rather_than_being_dropped(context, memory):
    """The argument models are `extra="forbid"`.

    A silently-dropped `price` would be a tool call that looked like it had been
    honoured. Failing is what makes the attempt visible.
    """
    result = executor(context).execute(
        "search_catalog", {"category": "phone_case", "price": "1.00"}, memory
    )

    assert result["error"]["code"] == ToolErrorCode.INVALID_ARGUMENTS.value
    assert "price" in result["error"]["message"]


def test_a_validation_failure_names_the_field_without_echoing_the_input(context, memory):
    """The model just produced the input; repeating it is noise, not help."""
    result = executor(context).execute("check_inventory", {"quantity": 500}, memory)

    assert result["error"]["code"] == ToolErrorCode.INVALID_ARGUMENTS.value
    assert "quantity" in result["error"]["message"]
    assert "500" not in result["error"]["message"]


def test_get_product_requires_exactly_one_lookup_key(context, memory):
    both = executor(context).execute("get_product", {"product_id": "x", "sku": "Y"}, memory)
    neither = executor(context).execute("get_product", {}, memory)

    assert both["error"]["code"] == ToolErrorCode.INVALID_ARGUMENTS.value
    assert neither["error"]["code"] == ToolErrorCode.INVALID_ARGUMENTS.value


# --------------------------------------------------------------------------
# Stage 4: authorization by tier (A§22, A§23)
# --------------------------------------------------------------------------


def test_a_medium_tier_tool_is_refused_even_when_registered(context, memory):
    """A§22: a tool being available does not mean it may be executed.

    M5 registers only LOW-tier read tools. This wires a MEDIUM one in by hand to
    prove the tier check is real and not merely implied by which tools happen to
    be registered this milestone.
    """
    registry = ToolRegistry(
        {
            "propose_cart": RegisteredTool(
                definition=TOOL_SCHEMAS["propose_cart"],
                handler=lambda ctx, mem, args: {"never": "reached"},
            )
        }
    )
    assert TOOL_SCHEMAS["propose_cart"].tier is RiskTier.MEDIUM

    result = executor(context, registry).execute(
        "propose_cart", {"items": [{"variant_id": "x", "quantity": 1}]}, memory
    )

    assert result["error"]["code"] == ToolErrorCode.FORBIDDEN_TOOL.value


# --------------------------------------------------------------------------
# Failure containment (A§42, F§25)
# --------------------------------------------------------------------------


def test_an_unexpected_exception_never_reaches_the_model(context, memory):
    """F§25: never a traceback, never a database message.

    A stack trace in the context window is an invitation to reason about
    internals, and the exception text is the one thing that must not travel.
    """

    def explode(ctx, mem, args):
        raise RuntimeError('relation "product_variants" does not exist')

    registry = ToolRegistry(
        {"search_catalog": RegisteredTool(TOOL_SCHEMAS["search_catalog"], explode)}
    )

    result = executor(context, registry).execute("search_catalog", {}, memory)

    assert result["error"]["code"] == ToolErrorCode.INTERNAL_ERROR.value
    assert "relation" not in result["error"]["message"]
    assert "RuntimeError" not in result["error"]["message"]


def test_the_executor_returns_failures_rather_than_raising(context, memory):
    """One conversion site, so the rule can only be wrong in one place."""
    result = executor(context).execute("nope", {}, memory)

    assert result["success"] is False


def test_every_call_is_recorded_whether_it_succeeded_or_failed(context, memory, recommendations):
    """A§39's trace has to show the attempts as well as the answers."""
    recommendations.result = make_recommendation(make_ranked(make_variant()))
    ex = executor(context)

    ex.execute("search_catalog", {"category": "phone_case"}, memory)
    ex.execute("nope", {}, memory)

    assert [call["tool"] for call in memory.calls] == ["search_catalog", "nope"]
    assert memory.calls[0]["result"]["success"] is True
    assert memory.calls[1]["result"]["success"] is False


def test_a_tool_error_is_raised_as_a_structured_result(context, memory):
    error = ToolError(ToolErrorCode.OUT_OF_STOCK, "no stock", details={"sku": "X"})

    payload = error.as_result()

    assert payload == {
        "success": False,
        "error": {"code": "OUT_OF_STOCK", "message": "no stock", "details": {"sku": "X"}},
    }
