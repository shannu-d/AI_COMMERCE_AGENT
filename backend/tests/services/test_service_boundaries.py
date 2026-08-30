"""Standing guards on the M2 trust boundary.

These do not test behaviour; they test that the shape of the code still matches
ADR-001. They exist because the most likely way this project goes wrong is not a
failing assertion — it is a well-meaning edit that quietly puts the model, or a
payment call, on the deterministic side of the boundary.

None of them needs a database.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.config import BACKEND_DIR
from app.services import CatalogService, CompatibilityService, InventoryService

DETERMINISTIC_PACKAGES = ("app/services", "app/repositories", "app/domain")
FORBIDDEN_IMPORT_ROOTS = ("app.llm", "app.agent")
FORBIDDEN_LIBRARIES = ("anthropic", "razorpay", "openai")


def python_files(*relative: str) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for rel in relative:
        files.extend(sorted((BACKEND_DIR / rel).rglob("*.py")))
    assert files, f"no modules found under {relative}; the guard would pass vacuously"
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


@pytest.mark.parametrize("path", python_files(*DETERMINISTIC_PACKAGES), ids=lambda p: p.name)
def test_deterministic_code_does_not_import_the_probabilistic_side(
    path: pathlib.Path,
) -> None:
    """ADR-001: the model proposes; deterministic code decides.

    `app.services`, `app.repositories` and `app.domain` are the trusted side and
    must remain importable, testable and reasonable-about without a model.
    """
    for module in imported_modules(path):
        assert not module.startswith(FORBIDDEN_IMPORT_ROOTS), (
            f"{path.name} imports {module}: deterministic code must not depend on "
            f"the agent or LLM layer (ADR-001)"
        )


@pytest.mark.parametrize("path", python_files(*DETERMINISTIC_PACKAGES), ids=lambda p: p.name)
def test_no_payment_or_model_library_reaches_the_read_services(
    path: pathlib.Path,
) -> None:
    """M2 is a read milestone.

    Razorpay belongs behind the Policy Engine (ADR-011); the Anthropic client
    belongs to M4. Neither has any business in a catalog read path.
    """
    for module in imported_modules(path):
        root = module.split(".")[0]
        assert root not in FORBIDDEN_LIBRARIES, f"{path.name} imports {module}"


def test_no_commerce_module_has_been_created_early() -> None:
    """M2 must not have grown a cart, an order, a policy or a payment.

    ADR-006 designs the commerce schema for M6; ADR-011 and ADR-012 own the
    money path from M9. A module appearing here before its milestone means the
    boundary moved without a decision.
    """
    premature = [
        name
        for name in ("cart", "order", "payment", "policy", "approval", "checkout", "webhook")
        if list((BACKEND_DIR / "app").rglob(f"*{name}*.py"))
    ]

    assert premature == [], f"premature commerce modules: {premature}"


def test_no_llm_or_agent_package_exists_yet() -> None:
    for package in ("app/llm", "app/agent"):
        assert not (BACKEND_DIR / package).exists(), f"{package} belongs to M4/M5"


@pytest.mark.parametrize("service", [CatalogService, CompatibilityService, InventoryService])
def test_every_public_read_method_requires_an_explicit_merchant(service: type) -> None:
    """ADR-002: merchant scoping is injected, never defaulted.

    A method that could be called without a merchant is a method that eventually
    will be. Resolution-only and pure helpers are exempt, since they touch no
    merchant-owned rows.
    """
    exempt = {"resolve_target", "list_targets", "rule_types_for"}

    for name, member in inspect.getmembers(service, predicate=inspect.isfunction):
        if name.startswith("_") or name in exempt:
            continue
        parameters = inspect.signature(member).parameters
        assert "merchant_id" in parameters, f"{service.__name__}.{name} takes no merchant_id"
        assert parameters["merchant_id"].default is inspect.Parameter.empty, (
            f"{service.__name__}.{name} defaults merchant_id; it must be supplied"
        )


@pytest.mark.parametrize("service", [CatalogService, CompatibilityService, InventoryService])
def test_services_are_constructed_from_a_session_only(service: type) -> None:
    """No service reaches for a connection, a client, or global state itself."""
    parameters = list(inspect.signature(service.__init__).parameters)

    assert parameters[1] == "session"
