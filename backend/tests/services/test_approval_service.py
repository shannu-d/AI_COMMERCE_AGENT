"""The Approval Service against a real PostgreSQL (M8; ADR-007, P§9, P§10).

M8's exit condition is one sentence — *a stale approval is rejected by test* —
and ADR-007 names six of them. All six are here, and the one that matters most is
the shortest: `request_approval` cannot produce an `APPROVED` row, asserted by
walking the method's signature rather than by trying and failing to persuade it.

The rest are about what an approval is a claim *about*. It binds to five things,
and each test below breaks exactly one of them while leaving the others intact —
because a check that only fires when everything changes at once is a check that
never fires.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models.session import Session as SessionRow
from app.domain.approval import ApprovalFailure, FingerprintLine, items_fingerprint
from app.domain.commerce import ApprovalStatus
from app.services.approval_service import ApprovalError, ApprovalService
from app.services.cart_service import CartService

pytestmark = pytest.mark.requires_db


@pytest.fixture
def carts(session: Session) -> CartService:
    return CartService(session)


@pytest.fixture
def approvals(session: Session) -> ApprovalService:
    return ApprovalService(session, ttl_seconds=900)


@pytest.fixture
def conversation(session: Session, merchant_id) -> SessionRow:
    row = SessionRow(merchant_id=merchant_id, intent={})
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def case(catalog, merchant_id, variant_id):
    return catalog.get_variant(merchant_id, variant_id("CASE-IP16-BLK"))


@pytest.fixture
def charger(catalog, merchant_id, variant_id):
    return catalog.get_variant(merchant_id, variant_id("CHARGER-20W"))


@pytest.fixture
def cart(carts, merchant_id, conversation, case):
    return carts.add_item(merchant_id, conversation.id, case.id, 1)


def approve(approvals, conversation, cart):
    return approvals.approve(conversation.id, cart, cart_version=cart.version)


# --------------------------------------------------------------------------
# Only a user action creates an approval (ADR-007, closing D5)
# --------------------------------------------------------------------------


def test_request_writes_pending_and_nothing_else(approvals, conversation, cart):
    approval = approvals.request(conversation.id, cart)

    assert approval.status is ApprovalStatus.PENDING
    assert approval.approved_at is None


def test_a_pending_approval_authorizes_nothing(approvals, conversation, cart):
    """P§9: the agent asking is not the buyer answering."""
    approval = approvals.request(conversation.id, cart)

    assert approval.authorizes(datetime.now(UTC)) is False


def test_request_has_no_parameter_that_could_write_approved():
    """ADR-007's central M8 test, asserted structurally.

    Not "the method declines to" — the method *cannot*. There is no `status`
    argument, so no caller, no refactor and no clever keyword produces an
    authorization from this path. That is what makes the rule a property of the
    type system rather than of the system prompt.
    """
    parameters = set(inspect.signature(ApprovalService.request).parameters)

    assert parameters == {"self", "session_id", "cart"}
    assert "status" not in parameters
    assert "approved" not in str(parameters).lower()


def test_only_approve_ever_writes_the_approved_status(session, approvals, conversation, cart):
    """The other half: the value appears in exactly one method's body."""
    approvals.request(conversation.id, cart)
    statuses = (
        session.execute(text("SELECT status FROM approvals WHERE cart_id = :c"), {"c": cart.id})
        .scalars()
        .all()
    )
    assert statuses == ["PENDING"]

    approve(approvals, conversation, cart)

    assert approvals.current(cart.id) is not None


# --------------------------------------------------------------------------
# A stale cart version is rejected — M8's exit condition
# --------------------------------------------------------------------------


def test_approving_a_stale_version_is_rejected(
    carts, approvals, merchant_id, conversation, cart, charger
):
    """The buyer's screen said version N; the cart is now N+1."""
    stale_version = cart.version
    carts.add_item(merchant_id, conversation.id, charger.id, 1)
    current = carts.get_active(merchant_id, conversation.id)

    with pytest.raises(ApprovalError) as error:
        approvals.approve(conversation.id, current, cart_version=stale_version)

    assert error.value.failure is ApprovalFailure.CART_VERSION_STALE
    assert error.value.details["current_version"] == current.version


def test_approving_the_current_version_succeeds(approvals, conversation, cart):
    approval = approve(approvals, conversation, cart)

    assert approval.status is ApprovalStatus.APPROVED
    assert approval.cart_version == cart.version
    assert approval.approved_at is not None


def test_a_stated_total_that_no_longer_matches_is_rejected(approvals, conversation, cart):
    """The same idea said twice: a client that renders a total should be able to
    say which one it rendered."""
    with pytest.raises(ApprovalError) as error:
        approvals.approve(
            conversation.id, cart, cart_version=cart.version, expected_total=Decimal("1.00")
        )

    assert error.value.failure is ApprovalFailure.TOTAL_CHANGED


# --------------------------------------------------------------------------
# A cart mutation supersedes an existing approval
# --------------------------------------------------------------------------


def test_adding_an_item_supersedes_an_approval(
    carts, approvals, merchant_id, conversation, cart, charger
):
    """ADR-007 invalidation rule 1, performed by the code path that made the
    change. There is no window in which the changed cart is still authorized."""
    approve(approvals, conversation, cart)

    carts.add_item(merchant_id, conversation.id, charger.id, 1)

    assert approvals.current(cart.id) is None


def test_a_price_increase_supersedes_an_approval(
    session, carts, approvals, merchant_id, conversation, cart, case
):
    approve(approvals, conversation, cart)
    session.execute(
        text("UPDATE product_variants SET price = price + 300 WHERE id = :i"), {"i": case.id}
    )

    carts.refresh(merchant_id, cart.id)

    assert approvals.current(cart.id) is None


def test_a_price_decrease_also_supersedes_an_approval(
    session, carts, approvals, merchant_id, conversation, cart, case
):
    """ADR-007 invalidation rule 2, closing D2 — the tempting-and-wrong one.

    The buyer approved a specific total. Charging a different one, cheaper or
    not, is charging an amount that was never authorized. Reconfirming a lower
    price costs one click.
    """
    approve(approvals, conversation, cart)
    session.execute(
        text("UPDATE product_variants SET price = price - 200 WHERE id = :i"), {"i": case.id}
    )

    carts.refresh(merchant_id, cart.id)

    assert approvals.current(cart.id) is None


def test_a_superseded_approval_stays_readable(
    carts, approvals, merchant_id, conversation, cart, charger
):
    """ADR-014's recovery reads it: "you approved ₹1,499 and it is now ₹1,799"
    is a statement about a record, not about a memory."""
    original = approve(approvals, conversation, cart)
    carts.add_item(merchant_id, conversation.id, charger.id, 1)

    history = approvals.history(cart.id)

    assert original.id in {row.id for row in history}
    assert history[-1].status is ApprovalStatus.SUPERSEDED


def test_a_fresh_approval_supersedes_the_previous_one(approvals, conversation, cart):
    """Invalidation rule 4, and the reason the partial unique index does not
    simply reject the second row."""
    first = approve(approvals, conversation, cart)

    second = approve(approvals, conversation, cart)

    assert second.id != first.id
    assert approvals.get(first.id).status is ApprovalStatus.SUPERSEDED
    assert approvals.current(cart.id).id == second.id


def test_two_approvals_of_one_version_cannot_both_be_approved(approvals, conversation, cart):
    """The database's own guarantee, underneath the service's."""
    approve(approvals, conversation, cart)
    approve(approvals, conversation, cart)

    live = [row for row in approvals.history(cart.id) if row.status is ApprovalStatus.APPROVED]
    assert len(live) == 1


# --------------------------------------------------------------------------
# Expiry
# --------------------------------------------------------------------------


def test_an_approval_expires_after_its_ttl(session, conversation, cart):
    """15 minutes (ADR-007, closing D1), stored explicitly rather than computed
    at read time — so changing the TTL never retroactively revives or kills an
    approval that already exists."""
    approvals = ApprovalService(session, ttl_seconds=900)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)

    assert approval.expires_at - approval.approved_at == timedelta(seconds=900)


def test_an_elapsed_approval_authorizes_nothing_even_unswept(session, conversation, cart):
    """Expiry is evaluated at the moment of use. A sweeper is an optimization,
    never the mechanism: an approval that lapsed while nobody was looking must
    still be refused when it is used.
    """
    approvals = ApprovalService(session, ttl_seconds=60)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)

    later = approval.expires_at + timedelta(seconds=1)

    assert approval.authorizes(later) is False
    assert approvals.current(cart.id).status is ApprovalStatus.APPROVED  # unswept


def test_validating_an_expired_approval_fails(session, conversation, cart):
    approvals = ApprovalService(session, ttl_seconds=60)
    approvals.approve(conversation.id, cart, cart_version=cart.version)
    session.execute(
        text("UPDATE approvals SET expires_at = now() - interval '1 minute' WHERE cart_id = :c"),
        {"c": cart.id},
    )
    session.expire_all()

    with pytest.raises(ApprovalError) as error:
        approvals.validate_against(approvals.current(cart.id), cart)

    assert error.value.failure is ApprovalFailure.EXPIRED


# --------------------------------------------------------------------------
# The items fingerprint
# --------------------------------------------------------------------------


def test_the_fingerprint_ignores_the_order_lines_were_added_in():
    a = FingerprintLine(uuid.UUID(int=1), 1, Decimal("999.00"))
    b = FingerprintLine(uuid.UUID(int=2), 2, Decimal("499.00"))

    assert items_fingerprint([a, b]) == items_fingerprint([b, a])


def test_the_fingerprint_ignores_decimal_scale():
    """`Decimal("999")` and `Decimal("999.00")` are equal numbers with different
    reprs; one cart must not produce two fingerprints."""
    line = FingerprintLine(uuid.UUID(int=1), 1, Decimal("999"))
    scaled = FingerprintLine(uuid.UUID(int=1), 1, Decimal("999.00"))

    assert items_fingerprint([line]) == items_fingerprint([scaled])


def test_the_fingerprint_distinguishes_two_carts_with_the_same_total():
    """Why the fingerprint exists at all: a total is not a composition.

    ₹1,499 + ₹299 and ₹1,299 + ₹499 both reach ₹1,798, and they are completely
    different orders.
    """
    one = [
        FingerprintLine(uuid.UUID(int=1), 1, Decimal("1499.00")),
        FingerprintLine(uuid.UUID(int=2), 1, Decimal("299.00")),
    ]
    other = [
        FingerprintLine(uuid.UUID(int=3), 1, Decimal("1299.00")),
        FingerprintLine(uuid.UUID(int=4), 1, Decimal("499.00")),
    ]

    assert sum(line.unit_price for line in one) == sum(line.unit_price for line in other)
    assert items_fingerprint(one) != items_fingerprint(other)


def test_the_fingerprint_notices_a_quantity_change():
    line = FingerprintLine(uuid.UUID(int=1), 1, Decimal("999.00"))
    more = FingerprintLine(uuid.UUID(int=1), 2, Decimal("999.00"))

    assert items_fingerprint([line]) != items_fingerprint([more])


# --------------------------------------------------------------------------
# Validation against a live cart (what the Policy Engine will call)
# --------------------------------------------------------------------------


def test_a_matching_approval_validates(approvals, merchant_id, carts, conversation, cart):
    approval = approve(approvals, conversation, cart)

    approvals.validate_against(approval, carts.get(merchant_id, cart.id))


def test_validation_rejects_a_cart_that_changed(
    carts, approvals, merchant_id, conversation, cart, charger
):
    approval = approve(approvals, conversation, cart)
    carts.add_item(merchant_id, conversation.id, charger.id, 1)

    with pytest.raises(ApprovalError):
        approvals.validate_against(approval, carts.get(merchant_id, cart.id))


def test_validation_rejects_a_pending_approval(approvals, merchant_id, carts, conversation, cart):
    """The Policy Engine reads `approvals.status`, and PENDING is not APPROVED."""
    pending = approvals.request(conversation.id, cart)

    with pytest.raises(ApprovalError) as error:
        approvals.validate_against(pending, carts.get(merchant_id, cart.id))

    assert error.value.failure is ApprovalFailure.NOT_APPROVED


def test_an_empty_cart_cannot_be_approved(carts, approvals, merchant_id, conversation, cart):
    emptied = carts.remove_item(merchant_id, conversation.id, cart.items[0].id)

    with pytest.raises(ApprovalError) as error:
        approvals.approve(conversation.id, emptied, cart_version=emptied.version)

    assert error.value.failure is ApprovalFailure.CART_EMPTY


def test_rejecting_closes_every_pending_ask(approvals, conversation, cart):
    approvals.request(conversation.id, cart)

    approvals.reject(cart.id)

    assert all(row.status is not ApprovalStatus.PENDING for row in approvals.history(cart.id))
