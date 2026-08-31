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


def test_the_registry_is_the_read_tools_plus_propose_cart() -> None:
    """M5 registered the five read tools; M7 adds `propose_cart`.

    Nothing that authorizes anything is registered, and nothing that moves money
    is registered at any milestone.
    """
    registry = build_registry()

    assert registry.names() == tuple(sorted((*READ_ONLY_TOOL_NAMES, "propose_cart")))


def test_every_read_tool_is_low_tier_and_propose_cart_is_medium() -> None:
    """A§23's grading, asserted rather than assumed.

    The tier is what the executor branches on: MEDIUM requires an established
    session before it may write, and a `propose_cart` that had drifted to LOW
    would skip that check entirely.
    """
    registry = build_registry()

    for name in READ_ONLY_TOOL_NAMES:
        assert registry.get(name).tier is RiskTier.LOW
    assert registry.get("propose_cart").tier is RiskTier.MEDIUM


def test_nothing_registered_is_above_medium() -> None:
    """There is no HIGH tier in this system. `create_order` would have been the
    only one and it is not a tool at all (ADR-009, closing D6)."""
    registry = build_registry()

    assert all(
        registry.get(name).tier in (RiskTier.LOW, RiskTier.MEDIUM) for name in registry.names()
    )


@pytest.mark.parametrize("name", READ_ONLY_TOOL_NAMES)
def test_every_read_tool_has_both_a_schema_and_a_handler(name: str) -> None:
    """The two halves live in different packages and must not drift apart."""
    assert name in TOOL_SCHEMAS
    assert name in HANDLERS


def test_a_tool_is_exposed_only_once_it_can_run() -> None:
    """`request_approval` has a schema from M4 and no handler until M8.

    Exposing it now would offer the model a tool that fails on arrival, which is
    worse than not offering it: the model would plan around a capability that
    does not exist.
    """
    assert "request_approval" in TOOL_SCHEMAS
    assert "request_approval" not in HANDLERS

    with pytest.raises(KeyError, match="no handler"):
        build_registry(("request_approval",))


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
