"""Conversation state — the first of the three state machines (ADR-006, ADR-007).

A§25 lists the states conceptually and then says outright that "the exact state
machine is an implementation design that should be finalized during Agent Runtime
development". This module is that finalization.

**This enum is display state.** ADR-010 says so and ADR-007 depends on it: the
Policy Engine never reads it, the approval record never derives from it, and a
session sitting in ``APPROVED`` authorizes nothing. Only an ``approvals`` row
does. The three enums share value names — ``APPROVED`` here, ``APPROVED`` on
``approvals.status``, ``PAYMENT_CONFIRMED`` here and on ``orders.status`` — and
none is ever computed from another.

It lives in ``app/domain`` rather than in ``app/agent`` because two layers need
it and neither may depend on the other: ``app/db/models/session.py`` builds its
``CHECK`` constraint from ``CONVERSATION_STATES``, and the agent runtime drives
transitions with it. A domain enum imports nothing, so it can sit under both.

**Every state is defined now, though most are unreachable until a later
milestone.** The column is ``VARCHAR(48)`` with a ``CHECK`` against these
values, and widening a ``CHECK`` costs a migration; defining the closed set once
is cheaper than one migration per milestone. `REACHABLE_FROM` records which
milestone first produces each value, so "unreachable" stays a fact someone can
check rather than a comment that rots.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CONVERSATION_STATES",
    "REACHABLE_FROM",
    "TERMINAL_STATES",
    "ConversationState",
]


class ConversationState(StrEnum):
    """Where a conversation has got to, for the UI to render (A§25, ADR-010)."""

    # -- the progression A§25 draws ----------------------------------------
    NEW_SESSION = "NEW_SESSION"
    UNDERSTANDING_INTENT = "UNDERSTANDING_INTENT"
    SEARCHING_PRODUCTS = "SEARCHING_PRODUCTS"
    VALIDATING_PRODUCTS = "VALIDATING_PRODUCTS"
    RECOMMENDING = "RECOMMENDING"
    PRODUCT_SELECTED = "PRODUCT_SELECTED"
    CART_PROPOSED = "CART_PROPOSED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    APPROVED = "APPROVED"
    POLICY_VALIDATION = "POLICY_VALIDATION"
    ORDER_CREATED = "ORDER_CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"

    # -- the failure states A§25 lists separately --------------------------
    NEED_CLARIFICATION = "NEED_CLARIFICATION"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PRICE_CHANGED = "PRICE_CHANGED"
    POLICY_REJECTED = "POLICY_REJECTED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    TOOL_ERROR = "TOOL_ERROR"
    ORDER_FAILED = "ORDER_FAILED"


#: Every value, for the ``CHECK`` constraint and for tests that assert the
#: constraint and the enum have not drifted apart.
CONVERSATION_STATES: tuple[str, ...] = tuple(state.value for state in ConversationState)

#: The milestone that first produces each state. A state absent from an earlier
#: milestone's output is not an oversight; it is a state whose machinery does
#: not exist yet.
REACHABLE_FROM: dict[ConversationState, str] = {
    ConversationState.NEW_SESSION: "M5",
    ConversationState.UNDERSTANDING_INTENT: "M5",
    ConversationState.SEARCHING_PRODUCTS: "M5",
    ConversationState.VALIDATING_PRODUCTS: "M5",
    ConversationState.RECOMMENDING: "M5",
    ConversationState.NEED_CLARIFICATION: "M5",
    ConversationState.TOOL_ERROR: "M5",
    ConversationState.OUT_OF_STOCK: "M5",
    ConversationState.PRODUCT_SELECTED: "M7",
    ConversationState.CART_PROPOSED: "M7",
    ConversationState.WAITING_FOR_APPROVAL: "M8",
    ConversationState.APPROVED: "M8",
    ConversationState.POLICY_VALIDATION: "M9",
    ConversationState.POLICY_REJECTED: "M9",
    ConversationState.ORDER_CREATED: "M10",
    ConversationState.ORDER_FAILED: "M10",
    ConversationState.PRICE_CHANGED: "M10",
    ConversationState.PAYMENT_PENDING: "M11",
    ConversationState.PAYMENT_CONFIRMED: "M12",
    ConversationState.PAYMENT_FAILED: "M12",
}

#: States from which no further agent turn follows on its own. A buyer may still
#: send another message — that starts the progression again — but the runtime
#: does not advance out of these by itself.
TERMINAL_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.PAYMENT_CONFIRMED,
        ConversationState.PAYMENT_FAILED,
    }
)
