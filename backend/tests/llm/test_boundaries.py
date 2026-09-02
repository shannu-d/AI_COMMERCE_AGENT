"""Standing guards on the M4 side of the trust boundary.

`tests/services/test_service_boundaries.py` holds the other half: that no
deterministic package imports `app.llm`. These are the guards pointing the
other way — that the LLM layer defines *what the model may ask for* and never
*what happens when it does*.

The separation is not stylistic. A tool bound to a service inside this package
would be a tool whose authorization, argument validation and execution all live
in the one place a reviewer reads last. A§19's pipeline — parse, validate,
authorize, execute — only means something if the stages are in different rooms.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.config import BACKEND_DIR
from app.llm.tool_schemas import EXPOSED_TOOL_NAMES, FORBIDDEN_TOOL_NAMES, TOOL_SCHEMAS

LLM_DIR = BACKEND_DIR / "app/llm"

#: The trusted side, plus the database itself. This layer talks to the model and
#: to `app.config`; anything else it needs is passed in by the runtime (M5).
FORBIDDEN_IMPORT_ROOTS = (
    "app.services",
    "app.repositories",
    "app.db",
    "app.models",
    "app.seed",
    "app.ranking",
    "sqlalchemy",
    "alembic",
)

#: ADR-011: Razorpay lives behind the Policy Engine. There is no arrangement in
#: which the module that talks to the model also talks to the payment provider.
FORBIDDEN_LIBRARIES = ("razorpay", "openai")


def llm_modules() -> list[pathlib.Path]:
    files = sorted(LLM_DIR.rglob("*.py"))
    assert files, "no modules under app/llm; the guard would pass vacuously"
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


@pytest.mark.parametrize("path", llm_modules(), ids=lambda p: p.name)
def test_the_llm_layer_reaches_no_service_and_no_database(path: pathlib.Path) -> None:
    """It cannot read a price, so it cannot be the thing that states one.

    RULE 1 and RULE 6 put catalog facts in PostgreSQL. Keeping the query out of
    this package is the structural version of that: a module here has no way to
    learn a price, in stock or out, compatible or not.
    """
    for module in imported_modules(path):
        assert not module.startswith(FORBIDDEN_IMPORT_ROOTS), (
            f"{path.name} imports {module}: the LLM layer defines what the model may "
            f"ask for, not what happens when it does"
        )


@pytest.mark.parametrize("path", llm_modules(), ids=lambda p: p.name)
def test_no_payment_provider_is_reachable_from_the_model_layer(path: pathlib.Path) -> None:
    for module in imported_modules(path):
        assert module.split(".")[0] not in FORBIDDEN_LIBRARIES, f"{path.name} imports {module}"


def test_the_layer_defines_no_tool_handler() -> None:
    """Binding a tool to a service is the agent runtime's job (M5, AGENT-02).

    A callable named after a tool, living beside the schema that describes it,
    is how the two quietly become one thing.
    """
    handlers = []
    for path in llm_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.lstrip("_") in EXPOSED_TOOL_NAMES:
                    handlers.append(f"{path.name}:{node.name}")

    assert handlers == []


def test_the_forbidden_tool_is_absent_from_the_source_as_a_definition() -> None:
    """ADR-009: `create_order` is not a schema, not a name, not an entry.

    It is named in comments and in `FORBIDDEN_TOOL_NAMES`, which is the point —
    the exclusion is documented and enforced rather than merely omitted.
    """
    for name in FORBIDDEN_TOOL_NAMES:
        assert name not in TOOL_SCHEMAS
        assert name not in EXPOSED_TOOL_NAMES


def test_nothing_in_the_layer_writes_to_a_file_or_opens_a_socket() -> None:
    """Except `client.py`, whose whole job is the one network call.

    A second I/O path here would be a second place model output could escape to
    without passing through the runtime.
    """
    offenders = []
    for path in llm_modules():
        if path.name == "client.py":
            continue
        for module in imported_modules(path):
            if module.split(".")[0] in {"socket", "http", "httpx", "requests", "urllib"}:
                offenders.append(f"{path.name}:{module}")

    assert offenders == []


# --------------------------------------------------------------------------
# ADR-018: Groq is the locked model provider
# --------------------------------------------------------------------------

#: Model SDKs that are not the configured provider. **Inverted, not deleted,**
#: when ADR-018 replaced ADR-016: this guard is what caught the drift it was
#: written for, and the lesson survives the reversal of the decision. Only the
#: allowed name changed.
#:
#: `anthropic` is on this list now. The provider is Groq (ADR-018), and a second
#: model SDK reappearing under any name is the failure being prevented.
OTHER_MODEL_SDKS = (
    "anthropic",
    "openai",
    "cohere",
    "mistralai",
    "litellm",
    "ollama",
    "transformers",
)


def test_groq_is_the_only_model_sdk_in_the_repository() -> None:
    """ADR-018. The companion to the single-importer guard in `test_client.py`.

    That one asserts `groq` is imported from exactly one file. This one asserts
    nothing *else* is imported at all — the case it missed, and the case that
    actually happened: a second client sat beside the first for a commit, and
    the single-importer guard stayed green throughout, because "one importer of
    *this* SDK" was never the same claim as "one model SDK".

    Note `openai` is forbidden even though the configured model is named
    `openai/gpt-oss-120b`. That is a model served **by Groq**, reached through
    the Groq SDK; importing OpenAI's client would mean talking to a different
    provider entirely.
    """
    offenders = []
    for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
        for module in imported_modules(path):
            if module.split(".")[0] in OTHER_MODEL_SDKS:
                offenders.append(f"{path.relative_to(BACKEND_DIR).as_posix()}:{module}")

    assert offenders == []


def test_no_test_named_module_lives_outside_the_test_suite() -> None:
    """ADR-016 obligation 3 (carried forward by ADR-018), and the reason it is worth asserting.

    `testpaths = ["tests"]` means a `test_`-named script at the backend root is
    never collected, so it is never reviewed as a test and never run as one —
    while looking exactly like both. The two that existed made live API calls,
    which ADR-015 forbids of anything the suite might ever pick up.
    """
    strays = [
        path.relative_to(BACKEND_DIR).as_posix()
        for path in sorted(BACKEND_DIR.rglob("test_*.py"))
        if "tests" not in path.relative_to(BACKEND_DIR).parts and ".venv" not in path.parts
    ]

    assert strays == []
