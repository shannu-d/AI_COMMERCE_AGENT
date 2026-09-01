"""The Policy Engine's ten rules (M9; P§6, P§7, ADR-011).

Every one of these runs without a database, because the engine is pure — and
that purity is the point rather than a convenience. A component that decides
whether money may move should be checkable exhaustively, and it can only be
checked exhaustively if constructing an adversarial state costs one dataclass.

M9's exit condition is that *price drift and out of stock both FAIL with the
right reason code*, and both are here. So is the property those two depend on:
each rule is broken **alone**, with everything else valid, because a rule that
only fires when several things are wrong at once is a rule that never fires by
itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.policy import LineContext, PolicyDecision, PolicyEngine, ReasonCode, TransactionContext

MERCHANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
SESSION = uuid.UUID("22222222-2222-2222-2222-222222222222")
CART = uuid.UUID("33333333-3333-3333-3333-333333333333")
APPROVAL = uuid.UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
FINGERPRINT = "f" * 64


def line(**overrides) -> LineContext:
    fields = {
        "variant_id": uuid.UUID(int=7),
        "product_id": uuid.UUID(int=8),
        "sku": "CASE-IP16-BLK",
        "quantity": 1,
        "unit_price": Decimal("999.00"),
        "currency": "INR",
        "available_quantity": 5,
        "product_is_active": True,
        "variant_is_active": True,
        "merchant_id": MERCHANT,
        **overrides,
    }
    return LineContext(**fields)


def context(**overrides) -> TransactionContext:
    """A context that passes every rule, so a test can break exactly one."""
    lines = overrides.pop("lines", (line(),))
    total = sum((item.line_total for item in lines), Decimal("0.00"))
    fields = {
        "merchant_id": MERCHANT,
        "session_id": SESSION,
        "cart_id": CART,
        "cart_version": 2,
        "current_cart_version": 2,
        "cart_status": "ACTIVE",
        "currency": "INR",
        "lines": lines,
        "approval_id": APPROVAL,
        "approval_status": "APPROVED",
        "approval_cart_version": 2,
        "approved_total": total,
        "approval_currency": "INR",
        "approval_fingerprint": FINGERPRINT,
        "current_fingerprint": FINGERPRINT,
        "approval_expires_at": NOW + timedelta(minutes=10),
        "approval_superseded": False,
        "existing_order_ids": (),
        "idempotency_status": None,
        "evaluated_at": NOW,
        **overrides,
    }
    return TransactionContext(**fields)


@pytest.fixture
def engine() -> PolicyEngine:
    """A ₹10,000 limit — P§13's default, stated here so these tests do not
    depend on the production configuration."""
    return PolicyEngine(spending_limit=Decimal("10000.00"))


# --------------------------------------------------------------------------
# The baseline
# --------------------------------------------------------------------------


def test_a_wholly_valid_transaction_passes(engine):
    """Without this, every FAIL test below could be passing for the wrong reason."""
    decision = engine.evaluate(context())

    assert decision.decision == "PASS"
    assert decision.reason_codes == ()
    assert decision.validated_total == Decimal("999.00")


def test_a_pass_carries_no_reasons_and_a_fail_carries_at_least_one():
    """A verdict nobody can act on is not a verdict."""
    with pytest.raises(ValueError):
        PolicyDecision(
            decision="PASS",
            validated_total=Decimal("1"),
            currency="INR",
            reason_codes=(ReasonCode.OUT_OF_STOCK,),
        )
    with pytest.raises(ValueError):
        PolicyDecision(decision="FAIL", validated_total=Decimal("1"), currency="INR")


# --------------------------------------------------------------------------
# Rule 1 — user approval
# --------------------------------------------------------------------------


def test_no_approval_fails(engine):
    decision = engine.evaluate(context(approval_id=None, approval_status=None))

    assert ReasonCode.APPROVAL_REQUIRED in decision.reason_codes


def test_a_pending_approval_does_not_authorize(engine):
    """ADR-007: the agent asking is not the buyer answering."""
    decision = engine.evaluate(context(approval_status="PENDING"))

    assert ReasonCode.APPROVAL_REQUIRED in decision.reason_codes


def test_a_superseded_approval_does_not_authorize(engine):
    decision = engine.evaluate(context(approval_superseded=True))

    assert ReasonCode.APPROVAL_REQUIRED in decision.reason_codes


def test_an_expired_approval_does_not_authorize(engine):
    """Expiry is evaluated here, at the moment of use, whether or not any
    sweeper ever marked the row."""
    decision = engine.evaluate(
        context(approval_expires_at=NOW - timedelta(seconds=1), approval_status="APPROVED")
    )

    assert ReasonCode.APPROVAL_REQUIRED in decision.reason_codes


def test_an_approval_for_a_different_cart_version_does_not_authorize(engine):
    decision = engine.evaluate(context(approval_cart_version=1))

    assert ReasonCode.APPROVAL_REQUIRED in decision.reason_codes


def test_conversation_state_cannot_reach_the_engine():
    """ADR-007, closing C7. A session says APPROVED only because the agent set
    it, and there is no field here through which that could arrive."""
    fields = set(TransactionContext.__dataclass_fields__)

    assert not any("conversation" in name for name in fields)
    assert "state" not in fields


# --------------------------------------------------------------------------
# Rule 2 — cart validity
# --------------------------------------------------------------------------


def test_an_empty_cart_fails(engine):
    decision = engine.evaluate(context(lines=(), approved_total=Decimal("0.00")))

    assert ReasonCode.INVALID_CART in decision.reason_codes


@pytest.mark.parametrize("status", ["ORDERED", "ABANDONED"])
def test_a_cart_that_is_not_active_fails(engine, status):
    decision = engine.evaluate(context(cart_status=status))

    assert ReasonCode.INVALID_CART in decision.reason_codes


def test_a_claimed_version_that_is_not_current_fails(engine):
    """`cart_version` from the client is a claim to be checked, not an
    instruction (ADR-011)."""
    decision = engine.evaluate(context(cart_version=1))

    assert ReasonCode.INVALID_CART in decision.reason_codes


def test_a_changed_composition_fails_even_when_the_total_matches(engine):
    """The case the fingerprint exists for: two carts can reach one total."""
    decision = engine.evaluate(context(current_fingerprint="a" * 64))

    assert ReasonCode.INVALID_CART in decision.reason_codes
    assert "items changed" in decision.details["INVALID_CART"]


# --------------------------------------------------------------------------
# Rules 3 and 4 — product and variant validity
# --------------------------------------------------------------------------


def test_a_deactivated_product_fails(engine):
    decision = engine.evaluate(context(lines=(line(product_is_active=False),)))

    assert ReasonCode.INVALID_PRODUCT in decision.reason_codes


def test_a_deactivated_variant_fails(engine):
    decision = engine.evaluate(context(lines=(line(variant_is_active=False),)))

    assert ReasonCode.INVALID_PRODUCT in decision.reason_codes


def test_a_product_belonging_to_another_merchant_fails(engine):
    """Checked rather than assumed. The query was merchant-scoped and a leak
    there would be silent."""
    decision = engine.evaluate(context(lines=(line(merchant_id=uuid.uuid4()),)))

    assert ReasonCode.INVALID_PRODUCT in decision.reason_codes


def test_one_bad_line_is_reported_once(engine):
    """A deactivated product fails rules 3 and 4; the buyer hears it once."""
    decision = engine.evaluate(
        context(lines=(line(product_is_active=False, variant_is_active=False),))
    )

    assert decision.reason_codes.count(ReasonCode.INVALID_PRODUCT) == 1


# --------------------------------------------------------------------------
# Rule 5 — current price. M9's exit condition, half one.
# --------------------------------------------------------------------------


def test_a_price_increase_fails_with_price_changed(engine):
    """The flagship scenario (A§28). The live total no longer equals what was
    approved, so the request is refused before any money moves."""
    decision = engine.evaluate(
        context(lines=(line(unit_price=Decimal("1299.00")),), approved_total=Decimal("999.00"))
    )

    assert decision.decision == "FAIL"
    assert ReasonCode.PRICE_CHANGED in decision.reason_codes


def test_a_price_decrease_also_fails_with_price_changed(engine):
    """ADR-007 rule 2, closing D2 — and the one a reasonable person gets wrong.

    The buyer approved a specific amount. Charging a different one, cheaper or
    not, is charging an amount that was never authorized.
    """
    decision = engine.evaluate(
        context(lines=(line(unit_price=Decimal("799.00")),), approved_total=Decimal("999.00"))
    )

    assert ReasonCode.PRICE_CHANGED in decision.reason_codes


def test_the_decision_carries_the_new_total_so_the_buyer_can_be_shown_it(engine):
    """P§7's own example: FAIL with PRICE_CHANGED and `validated_total: 1998`.

    The number that caused the refusal is exactly the number the buyer must now
    be shown, so a failed decision without it would force a second query.
    """
    decision = engine.evaluate(
        context(lines=(line(unit_price=Decimal("1299.00")),), approved_total=Decimal("999.00"))
    )

    assert decision.validated_total == Decimal("1299.00")
    assert "1299.00" in decision.details["PRICE_CHANGED"]


def test_a_currency_change_fails(engine):
    decision = engine.evaluate(context(approval_currency="USD"))

    assert ReasonCode.PRICE_CHANGED in decision.reason_codes


def test_an_exact_match_to_the_paisa_passes(engine):
    """Equality, not tolerance. A rounding allowance would be a licence to
    charge a little more than was approved."""
    lines = (line(unit_price=Decimal("1500.10")),)
    decision = engine.evaluate(context(lines=lines, approved_total=Decimal("1500.10")))

    assert decision.decision == "PASS"


# --------------------------------------------------------------------------
# Rule 6 — current inventory. M9's exit condition, half two.
# --------------------------------------------------------------------------


def test_insufficient_stock_fails_with_out_of_stock(engine):
    decision = engine.evaluate(
        context(
            lines=(line(quantity=3, available_quantity=2, unit_price=Decimal("999.00")),),
            approved_total=Decimal("2997.00"),
        )
    )

    assert decision.decision == "FAIL"
    assert ReasonCode.OUT_OF_STOCK in decision.reason_codes


def test_zero_stock_fails(engine):
    decision = engine.evaluate(context(lines=(line(available_quantity=0),)))

    assert ReasonCode.OUT_OF_STOCK in decision.reason_codes


def test_exactly_enough_stock_passes(engine):
    """`available >= requested` (D§29 step 6), not `>`."""
    lines = (line(quantity=2, available_quantity=2, unit_price=Decimal("999.00")),)
    decision = engine.evaluate(context(lines=lines, approved_total=Decimal("1998.00")))

    assert decision.decision == "PASS"


def test_every_short_line_is_named(engine):
    """One round-trip, not one per problem."""
    lines = (
        line(sku="A", available_quantity=0),
        line(sku="B", variant_id=uuid.UUID(int=9), available_quantity=0),
    )
    decision = engine.evaluate(context(lines=lines, approved_total=Decimal("1998.00")))

    assert "A" in decision.details["OUT_OF_STOCK"]
    assert "B" in decision.details["OUT_OF_STOCK"]


# --------------------------------------------------------------------------
# Rule 7 — quantity
# --------------------------------------------------------------------------


@pytest.mark.parametrize("quantity", [0, -1, 100])
def test_a_quantity_outside_the_bounds_fails(engine, quantity):
    """Re-checked here even though the Cart Service already enforced it. This is
    the check that runs when money is about to move, and it does not trust that
    the earlier one happened."""
    lines = (line(quantity=quantity, available_quantity=1000),)
    decision = engine.evaluate(context(lines=lines, approved_total=Decimal("999.00") * quantity))

    assert ReasonCode.INVALID_CART in decision.reason_codes


# --------------------------------------------------------------------------
# Rule 8 — spending limit
# --------------------------------------------------------------------------


def test_a_total_above_the_limit_fails(engine):
    """P§13's ₹10,000 per transaction, closing D3."""
    lines = (line(quantity=20, unit_price=Decimal("999.00"), available_quantity=100),)
    decision = engine.evaluate(context(lines=lines, approved_total=Decimal("19980.00")))

    assert ReasonCode.SPENDING_LIMIT_EXCEEDED in decision.reason_codes


def test_a_total_exactly_at_the_limit_passes(engine):
    """The limit is a ceiling, not an exclusive bound."""
    lines = (line(quantity=10, unit_price=Decimal("1000.00"), available_quantity=100),)
    decision = engine.evaluate(context(lines=lines, approved_total=Decimal("10000.00")))

    assert decision.decision == "PASS"


def test_the_limit_is_configuration_not_a_literal():
    """So this test does not depend on the production default."""
    strict = PolicyEngine(spending_limit=Decimal("500.00"))

    decision = strict.evaluate(context())

    assert ReasonCode.SPENDING_LIMIT_EXCEEDED in decision.reason_codes


# --------------------------------------------------------------------------
# Rules 9 and 10 — order state and idempotency
# --------------------------------------------------------------------------


def test_a_cart_that_already_has_an_order_fails(engine):
    decision = engine.evaluate(context(existing_order_ids=(uuid.uuid4(),)))

    assert ReasonCode.ORDER_ALREADY_EXISTS in decision.reason_codes


def test_a_spent_idempotency_key_fails(engine):
    """Reported rather than silently honoured: the *route* decides to return the
    stored response, and it needs to know this is a replay (ADR-013)."""
    decision = engine.evaluate(context(idempotency_status="COMPLETED"))

    assert ReasonCode.ORDER_ALREADY_EXISTS in decision.reason_codes


def test_a_reserved_idempotency_key_does_not_fail(engine):
    """RESERVED is the key this very request took before starting work."""
    decision = engine.evaluate(context(idempotency_status="RESERVED"))

    assert decision.decision == "PASS"


# --------------------------------------------------------------------------
# All rules are evaluated
# --------------------------------------------------------------------------


def test_evaluation_does_not_stop_at_the_first_failure(engine):
    """ADR-011. A buyer who fixes the first problem only to meet the second has
    been served badly by a system that knew about both."""
    lines = (line(unit_price=Decimal("5000.00"), available_quantity=0, quantity=3),)
    decision = engine.evaluate(
        context(
            lines=lines,
            approved_total=Decimal("999.00"),
            approval_status="PENDING",
            existing_order_ids=(uuid.uuid4(),),
        )
    )

    assert {
        ReasonCode.APPROVAL_REQUIRED,
        ReasonCode.PRICE_CHANGED,
        ReasonCode.OUT_OF_STOCK,
        ReasonCode.SPENDING_LIMIT_EXCEEDED,
        ReasonCode.ORDER_ALREADY_EXISTS,
    } <= set(decision.reason_codes)


def test_the_verdict_is_deterministic(engine):
    """RULE 8. The same context evaluates the same way, codes in the same order."""
    ctx = context(
        lines=(line(available_quantity=0, unit_price=Decimal("2.00")),),
        approved_total=Decimal("999.00"),
    )

    first = engine.evaluate(ctx)
    second = engine.evaluate(ctx)

    assert first.reason_codes == second.reason_codes
    assert first.validated_total == second.validated_total


def test_the_engine_has_no_side_effects(engine):
    """It reads state and returns a verdict. Evaluating twice changes nothing,
    which is what lets the caller evaluate speculatively."""
    ctx = context()

    engine.evaluate(ctx)

    assert ctx.lines[0].unit_price == Decimal("999.00")
    assert engine.evaluate(ctx).decision == "PASS"
