"""The tool registry (ADR-009).

The registry is where "which tools exist" stops being a design statement and
becomes a fact the code can be asked about. These tests ask it.

The most important one is the shortest: `create_order` is not in it. ADR-009
names that as M5's standing regression test against the most likely dangerous
edit, and it is deliberately asserted several ways — absent from the registry,
absent from the handler table, and refused by `build_registry` even when
explicitly requested — because each is a different way someone could put it back.
"""

from __future__ import annotations

import pytest

from app.agent.registry import HANDLERS, build_registry
from app.llm.tool_schemas import (
    EXPOSED_TOOL_NAMES,
    FORBIDDEN_TOOL_NAMES,
    READ_ONLY_TOOL_NAMES,
    TOOL_SCHEMAS,
    RiskTier,
)

# --------------------------------------------------------------------------
# create_order (ADR-009, closing D6)
# --------------------------------------------------------------------------


def test_create_order_is_not_in_the_registry() -> None:
    """ADR-009's named M5 regression test.

    Not registered-and-failing. Absent. A registered tool with a hard-failing
    handler is still a tool the model can reason about and try to route around.
    """
    registry = build_registry()

    assert "create_order" not in registry


def test_create_order_has_no_handler() -> None:
    """The second way it could come back: a handler wired without a schema."""
    assert "create_order" not in HANDLERS


def test_build_registry_refuses_to_register_a_forbidden_tool() -> None:
    """The third way: someone passes it explicitly, believing they have a reason."""
    with pytest.raises(ValueError, match="never be registered"):
        build_registry(("search_catalog", "create_order"))


def test_no_handler_module_is_named_for_a_forbidden_tool() -> None:
    """And the fourth: a file that exists but is not wired up yet."""
    from app.config import BACKEND_DIR

    modules = {path.stem for path in (BACKEND_DIR / "app/agent/tools").glob("*.py")}

    assert modules & FORBIDDEN_TOOL_NAMES == set()


# --------------------------------------------------------------------------
# What M5 registers
# --------------------------------------------------------------------------


def test_the_registry_is_exactly_the_read_only_tools() -> None:
    """M5 is the read-only agent. Nothing that writes state is registered."""
    registry = build_registry()

    assert registry.names() == tuple(sorted(READ_ONLY_TOOL_NAMES))


def test_every_registered_tool_is_low_tier() -> None:
    """A§23. A MEDIUM tool arriving before its milestone would be one whose
    business validation has not been written."""
    registry = build_registry()

    assert all(registry.get(name).tier is RiskTier.LOW for name in registry.names())


@pytest.mark.parametrize("name", READ_ONLY_TOOL_NAMES)
def test_every_read_tool_has_both_a_schema_and_a_handler(name: str) -> None:
    """The two halves live in different packages and must not drift apart."""
    assert name in TOOL_SCHEMAS
    assert name in HANDLERS


def test_a_tool_is_exposed_only_once_it_can_run() -> None:
    """`propose_cart` has a schema from M4 and no handler until M7.

    Exposing it now would offer the model a tool that fails on arrival, which is
    worse than not offering it: the model would plan around a capability that
    does not exist.
    """
    assert "propose_cart" in TOOL_SCHEMAS
    assert "propose_cart" not in HANDLERS

    with pytest.raises(KeyError, match="no handler"):
        build_registry(("propose_cart",))


def test_the_registry_is_a_strict_subset_of_what_m4_defined() -> None:
    """The runtime binds handlers; it never invents a tool the model was not told about."""
    registry = build_registry()

    assert set(registry.names()) <= set(EXPOSED_TOOL_NAMES)


def test_tool_names_are_sorted_so_the_payload_is_byte_stable() -> None:
    """A registry that reordered between runs would change the prompt and make
    two otherwise identical turns incomparable."""
    registry = build_registry()

    assert list(registry.names()) == sorted(registry.names())


def test_the_registry_cannot_be_added_to_after_construction() -> None:
    """A registry mutable at runtime is a registry whose contents at the moment
    of a call are not the ones that were reviewed."""
    registry = build_registry()

    assert not hasattr(registry, "register")
    assert not hasattr(registry, "add")
