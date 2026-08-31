"""Standing guards on the runtime, the one package that touches both sides.

`tests/llm/test_boundaries.py` asserts the model side defines what may be asked
for and never what happens when it is. `tests/services/test_service_boundaries.py`
asserts the trusted side cannot see the model at all. This file covers the place
they meet, where the rules are different in kind: the runtime is *supposed* to
import both, so the guards here are about what it may do with them.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.agent.errors import API_ERROR_CODES, ApiErrorCode, ToolErrorCode, to_api_code
from app.agent.registry import build_registry
from app.config import BACKEND_DIR
from app.llm.tool_schemas import FORBIDDEN_TOOL_NAMES

AGENT_DIR = BACKEND_DIR / "app/agent"


def agent_modules() -> list[pathlib.Path]:
    files = sorted(AGENT_DIR.rglob("*.py"))
    assert files, "no modules under app/agent; the guard would pass vacuously"
    return files


def imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


# --------------------------------------------------------------------------
# What the runtime may not reach
# --------------------------------------------------------------------------


#: `context.py` builds every service from one database session, so it needs the
#: `Session` *type* to say so. That is a signature, not a query. The exemption is
#: narrowed to one file and one name by the test below it, so it cannot widen
#: into "the runtime does some SQL where it is convenient".
SESSION_TYPE_IMPORTER = "context.py"


@pytest.mark.parametrize("path", agent_modules(), ids=lambda p: p.name)
def test_the_runtime_reaches_no_repository_and_no_model(path: pathlib.Path) -> None:
    """It composes services; it does not write SQL.

    A query here would be a query outside the merchant scoping, the domain types
    and the tests that cover them - and it would be the one query nobody thought
    to check for a `WHERE merchant_id`.
    """
    for module in imported_modules(path):
        assert not module.startswith(("alembic", "app.repositories", "app.db")), (
            f"{path.name} imports {module}"
        )


@pytest.mark.parametrize("path", agent_modules(), ids=lambda p: p.name)
def test_only_the_composition_site_names_sqlalchemy_and_only_for_a_type(
    path: pathlib.Path,
) -> None:
    """The narrow exemption above, asserted rather than assumed.

    `AgentContext.from_session` takes a session and hands it to five service
    constructors; naming its parameter requires the import. Every other module
    here must have no route to the database at all, and even this one may not
    reach for `select`, `text` or a session factory - the moment it does, it has
    stopped composing services and started querying.
    """
    sqlalchemy_imports = {
        module for module in imported_modules(path) if module.startswith("sqlalchemy")
    }
    if path.name != SESSION_TYPE_IMPORTER:
        assert sqlalchemy_imports == set(), f"{path.name} imports {sqlalchemy_imports}"
        return

    assert sqlalchemy_imports == {"sqlalchemy.orm"}
    source = path.read_text(encoding="utf-8")
    for query_tool in ("select(", "text(", "sessionmaker", "create_engine", ".execute("):
        assert query_tool not in source, f"{path.name} uses {query_tool}"


@pytest.mark.parametrize("path", agent_modules(), ids=lambda p: p.name)
def test_no_payment_library_reaches_the_runtime(path: pathlib.Path) -> None:
    """ADR-011: Razorpay lives behind the Policy Engine.

    There is no arrangement in which the loop that executes a model's requests
    also talks to the payment provider.
    """
    for module in imported_modules(path):
        assert module.split(".")[0] not in {"razorpay", "stripe"}, f"{path.name}: {module}"


@pytest.mark.parametrize("path", agent_modules(), ids=lambda p: p.name)
def test_only_the_client_module_is_the_runtimes_route_to_a_model(path: pathlib.Path) -> None:
    """ADR-015, ADR-016: the runtime depends on the protocol, not on an SDK."""
    for module in imported_modules(path):
        assert module.split(".")[0] not in {"anthropic", "groq", "openai"}, (
            f"{path.name} imports a model SDK directly"
        )


def test_no_commerce_module_has_appeared_in_the_runtime() -> None:
    """M5 is the read-only agent. A cart, an order or a policy module here would
    mean the money path was started before its milestone (D§36, D§39)."""
    premature = [
        path.name
        for path in agent_modules()
        if any(word in path.stem for word in ("cart", "order", "payment", "policy", "approval"))
    ]

    assert premature == []


def test_no_tool_module_is_named_for_a_forbidden_tool() -> None:
    """ADR-009, closing D6. Not registered, and not present as a file either."""
    modules = {path.stem for path in (AGENT_DIR / "tools").glob("*.py")}

    assert modules & FORBIDDEN_TOOL_NAMES == set()


# --------------------------------------------------------------------------
# The error vocabulary
# --------------------------------------------------------------------------


def test_the_api_error_codes_are_exactly_f25s_eleven() -> None:
    """A code outside the list is a code no client knows how to render."""
    assert len(API_ERROR_CODES) == 11
    assert set(API_ERROR_CODES) == {
        "VALIDATION_ERROR",
        "PRODUCT_NOT_FOUND",
        "VARIANT_NOT_FOUND",
        "OUT_OF_STOCK",
        "PRICE_CHANGED",
        "APPROVAL_REQUIRED",
        "POLICY_FAILED",
        "ORDER_CREATION_FAILED",
        "PAYMENT_FAILED",
        "PAYMENT_PENDING",
        "SERVER_ERROR",
    }


@pytest.mark.parametrize("code", list(ToolErrorCode))
def test_every_internal_code_narrows_onto_a_published_one(code: ToolErrorCode) -> None:
    """The two vocabularies are separate so the internal one can grow without
    the public contract growing with it."""
    assert to_api_code(code) in set(ApiErrorCode)


def test_an_internal_failure_never_narrows_onto_a_business_code() -> None:
    """`UNKNOWN_TOOL` is a bug on this side, not an out-of-stock product.

    Mapping it onto a business code would tell a client to run a recovery flow
    for something no buyer action can fix.
    """
    for code in (
        ToolErrorCode.UNKNOWN_TOOL,
        ToolErrorCode.FORBIDDEN_TOOL,
        ToolErrorCode.INTERNAL_ERROR,
        ToolErrorCode.TOOL_LIMIT_REACHED,
    ):
        assert to_api_code(code) is ApiErrorCode.SERVER_ERROR


# --------------------------------------------------------------------------
# What the model is offered
# --------------------------------------------------------------------------


def test_the_model_is_offered_only_tools_that_can_run() -> None:
    """A tool without a handler is a capability the model plans around and then
    cannot use, which is worse than not offering it."""
    from app.agent.registry import HANDLERS

    registry = build_registry()

    assert set(registry.names()) <= set(HANDLERS)


def test_the_tool_payload_carries_real_category_slugs() -> None:
    """ADR-009, closing B2: the model can only name a category that exists."""
    from app.llm.tool_schemas import build_tool_definitions

    payload = build_tool_definitions(
        category_slugs=("phone_case", "charger"), names=("search_catalog",)
    )
    category = payload[0]["input_schema"]["properties"]["category"]

    assert set(category["enum"]) == {"phone_case", "charger", None}
