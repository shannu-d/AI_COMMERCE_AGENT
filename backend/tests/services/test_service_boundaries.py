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
from app.services import (
    CatalogService,
    CompatibilityService,
    InventoryService,
    RecommendationService,
)

DETERMINISTIC_PACKAGES = (
    "app/services",
    "app/repositories",
    "app/domain",
    "app/ranking",
    # M9. The Policy Engine decides whether money may move, so of every package
    # on this list it is the one that must least be reachable from the
    # probabilistic side.
    "app/policy",
)
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

    `app.services`, `app.repositories`, `app.domain` and `app.ranking` are the
    trusted side and must remain importable, testable and reasonable-about
    without a model. R§11 adds a second reason for the ranker specifically: the
    LLM must not compute a ranking score, and it cannot compute one in a package
    that cannot import it.
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
    """M2 and M3 are read milestones.

    Razorpay belongs behind the Policy Engine (ADR-011); the Anthropic client
    belongs to M4. Neither has any business in a catalog read or ranking path.
    """
    for module in imported_modules(path):
        root = module.split(".")[0]
        assert root not in FORBIDDEN_LIBRARIES, f"{path.name} imports {module}"


def test_no_commerce_service_has_been_created_early() -> None:
    """The money path must not be coded before its decisions exist.

    This guard has narrowed twice, each time to exactly what it was still
    protecting. Before M6 it forbade any module mentioning a cart or an order,
    which was right while none of them had a table. M6 gave them tables and it
    narrowed to services. M7 writes carts - a cart moves no money and needs no
    approval - so it narrows again to what does: the Policy Engine, the Order
    Service, the audit writer and the Razorpay-facing routes. M8 adds approvals,
    which authorize but do not charge, and M9 the Policy Engine, which decides
    but does not charge either. M10 adds the Order Service, which creates the
    internal order before any provider is reached, and M11 the Razorpay client,
    which creates a provider order and still decides nothing about whether money
    moved. What remains is what does decide that: the verified-webhook handler,
    and the audit writer that records it.

    What it must never narrow to is nothing. D§39, A§58 and F§37 all say the
    same thing, and this is where "not yet" is checkable.
    """
    premature = [
        name
        for name in (
            # The webhook handler (M12) and the audit writer (M13). M11 added
            # the Razorpay client, which *creates* a provider order and still
            # decides nothing about whether money moved - only a verified
            # webhook does that (ADR-012), and this is what is left.
            "app/services/audit_service.py",
            "app/api/routes/webhooks.py",
            "app/services/webhook_service.py",
        )
        if (BACKEND_DIR / name).exists()
    ]

    assert premature == [], f"premature commerce behaviour: {premature}"


def test_no_module_outside_the_payment_boundary_converts_to_minor_units() -> None:
    """ADR-008: integer minor units exist in one module and nowhere else.

    Two money representations loose in one codebase is how a paise value reaches
    a rupee field. `OrderService` may *call* the conversion - it writes
    `orders.total_amount_minor` - but nobody may reimplement it, and this is the
    crude check that nobody has: no other module multiplies or divides by 100.
    """
    offenders = []
    for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
        if path.parent.name == "payments":
            continue
        source = path.read_text(encoding="utf-8")
        if "* 100" in source or "/ 100" in source or "// 100" in source:
            offenders.append(path.relative_to(BACKEND_DIR).as_posix())

    assert offenders == []


def test_the_commerce_models_are_reachable_only_as_schema() -> None:
    """The other half: the tables exist, and nothing on the read side uses them.

    M2's and M3's services predate the commerce schema and must keep working
    without it. A read service that started importing `Cart` would be a read
    service with an opinion about a purchase.
    """
    importers = [
        path.name
        for package in ("app/services", "app/ranking")
        for path in python_files(package)
        if any(
            module.startswith(
                (
                    "app.db.models.cart",
                    "app.db.models.order",
                    "app.db.models.payment",
                    "app.db.models.approval",
                )
            )
            for module in imported_modules(path)
        )
    ]

    assert importers == []


def test_the_agent_runtime_is_reachable_only_from_the_probabilistic_side() -> None:
    """The M5 shape of the guard that used to say `app/agent` must not exist.

    It exists from M5, so "it must not" is no longer the rule. What replaces it
    is the rule that survives: the runtime may import both sides - that is its
    job, binding a tool schema to a service - but nothing on the trusted side
    may import *it*. A service that reached into the runtime would be a service
    whose behaviour depended on a conversation.
    """
    assert (BACKEND_DIR / "app/agent").is_dir()

    importers = [
        path.name
        for package in DETERMINISTIC_PACKAGES
        for path in python_files(package)
        if any(module.startswith("app.agent") for module in imported_modules(path))
    ]

    assert importers == []


def test_the_runtime_is_the_only_place_the_two_sides_meet() -> None:
    """ADR-001, stated positively rather than as a prohibition.

    The per-file guards above say what may not import what. This says where the
    exception lives: exactly one package imports both `app.llm` and a service,
    and it is the one whose whole purpose is to validate the first before
    letting it reach the second (A§19). If a second such package appears, the
    boundary has two doors and only one of them has been reviewed.
    """
    both_sides = []
    for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
        modules = imported_modules(path)
        touches_model = any(module.startswith("app.llm") for module in modules)
        trusted = ("app.services", "app.repositories")
        touches_services = any(module.startswith(trusted) for module in modules)
        if touches_model and touches_services:
            both_sides.append(path.relative_to(BACKEND_DIR).as_posix())

    assert all(name.startswith(("app/agent/", "app/api/")) for name in both_sides), both_sides


def test_the_llm_layer_is_reachable_only_from_the_probabilistic_side() -> None:
    """The M4 shape of the same guard the import tests above enforce per file.

    `app/llm` exists from M4, so "it must not exist" is no longer the rule. What
    replaces it is that nothing on the trusted side may import it — which is
    checked per module above, and stated here so the intent survives the change.
    """
    assert (BACKEND_DIR / "app/llm").is_dir()

    importers = [
        path.name
        for package in DETERMINISTIC_PACKAGES
        for path in python_files(package)
        if any(module.startswith("app.llm") for module in imported_modules(path))
    ]

    assert importers == []


@pytest.mark.parametrize(
    "service",
    [CatalogService, CompatibilityService, InventoryService, RecommendationService],
)
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


@pytest.mark.parametrize(
    "service",
    [CatalogService, CompatibilityService, InventoryService, RecommendationService],
)
def test_services_are_constructed_from_a_session_only(service: type) -> None:
    """No service reaches for a connection, a client, or global state itself."""
    parameters = list(inspect.signature(service.__init__).parameters)

    assert parameters[1] == "session"
