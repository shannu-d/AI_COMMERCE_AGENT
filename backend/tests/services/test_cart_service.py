"""The Cart Service against a real PostgreSQL (M7; A§13, F§12, F§13, A§27).

M7's exit condition is two claims — *the cart total is backend-computed* and *the
version increments on mutation* — and both are asserted here against real catalog
prices rather than fixtures, because "backend-computed" means "computed from what
the database says", and a test that supplied its own prices would be checking
arithmetic rather than authority.

The version tests matter more than they look. A version number is what an
approval binds to (A§27), so every case where it moves and every case where it
does not is a case where a stale approval either is or is not detected. The
subtle one is `refresh`: nothing the buyer did changed, but what they would be
charged did, so the version moves and the old approval goes stale. That is the
primary failure scenario the specification names (A§28).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models.session import Session as SessionRow
from app.domain.commerce import CartStatus
from app.services.cart_service import MAX_LINE_QUANTITY, CartError, CartService

pytestmark = pytest.mark.requires_db


@pytest.fixture
def carts(session: Session) -> CartService:
    return CartService(session)


@pytest.fixture
def conversation(session: Session, merchant_id) -> SessionRow:
    row = SessionRow(merchant_id=merchant_id, intent={})
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def case(catalog, merchant_id, variant_id):
    """A real, in-stock iPhone 16 case from the seeded catalog."""
    return catalog.get_variant(merchant_id, variant_id("CASE-IP16-BLK"))


@pytest.fixture
def charger(catalog, merchant_id, variant_id):
    return catalog.get_variant(merchant_id, variant_id("CHARGER-20W"))


# --------------------------------------------------------------------------
# The total is backend-computed
# --------------------------------------------------------------------------


def test_the_line_total_is_the_catalog_price_times_the_quantity(
    carts, merchant_id, conversation, case
):
    """A§13. The price came from `product_variants`; nobody supplied it."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 3)

    line = cart.items[0]
    assert line.unit_price == case.price
    assert line.line_total == case.price * 3


def test_the_cart_total_is_the_sum_of_its_lines(carts, merchant_id, conversation, case, charger):
    """F§12: the frontend never sums line items, so the backend always has."""
    carts.add_item(merchant_id, conversation.id, case.id, 2)
    cart = carts.add_item(merchant_id, conversation.id, charger.id, 1)

    assert cart.subtotal == case.price * 2 + charger.price
    assert cart.total == cart.subtotal
    assert all(isinstance(item.line_total, Decimal) for item in cart.items)


def test_no_method_accepts_an_amount(carts):
    """The structural half of A§13: there is nowhere to put a price.

    Asserted on the signatures rather than by trying to pass one, because a
    method that quietly ignored a price would still be a method someone could
    believe they had used.
    """
    import inspect

    money_words = {"price", "amount", "total", "subtotal", "cost"}
    for name in ("add_item", "set_quantity", "remove_item", "replace_items", "refresh"):
        parameters = set(inspect.signature(getattr(CartService, name)).parameters)
        assert not (parameters & money_words), f"{name} accepts an amount"


def test_the_stored_total_matches_what_was_returned(
    session, carts, merchant_id, conversation, case
):
    """The computed total is persisted, not merely returned — a later read must
    agree with what the buyer was just shown."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 2)

    stored = session.execute(
        text("SELECT total_amount FROM carts WHERE id = :id"), {"id": cart.id}
    ).scalar_one()
    assert stored == cart.total


# --------------------------------------------------------------------------
# The version increments on mutation
# --------------------------------------------------------------------------


def test_adding_an_item_increments_the_version(carts, merchant_id, conversation, case):
    first = carts.add_item(merchant_id, conversation.id, case.id, 1)
    second = carts.add_item(merchant_id, conversation.id, case.id, 1)

    assert second.version == first.version + 1


def test_changing_a_quantity_increments_the_version(carts, merchant_id, conversation, case):
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)

    updated = carts.set_quantity(merchant_id, conversation.id, cart.items[0].id, 5)

    assert updated.version == cart.version + 1
    assert updated.items[0].quantity == 5


def test_removing_an_item_increments_the_version(carts, merchant_id, conversation, case):
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)

    emptied = carts.remove_item(merchant_id, conversation.id, cart.items[0].id)

    assert emptied.version == cart.version + 1
    assert emptied.is_empty
    assert emptied.total == Decimal("0.00")


def test_a_price_change_increments_the_version(session, carts, merchant_id, conversation, case):
    """A§27, A§28, ADR-014 — the subtle one, and the primary failure scenario.

    Nothing the buyer did changed. What they would be charged did, so the version
    moves and any approval bound to the old one is stale.
    """
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    session.execute(
        text("UPDATE product_variants SET price = price + 300 WHERE id = :id"), {"id": case.id}
    )

    refreshed = carts.refresh(merchant_id, cart.id)

    assert refreshed.version == cart.version + 1
    assert refreshed.total == case.price + Decimal("300")


def test_a_refresh_that_finds_nothing_changed_leaves_the_version_alone(
    carts, merchant_id, conversation, case
):
    """Bumping it for nothing would invalidate a perfectly good approval."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)

    refreshed = carts.refresh(merchant_id, cart.id)

    assert refreshed.version == cart.version


def test_the_version_never_decrements(carts, merchant_id, conversation, case, charger):
    """A reused version number would make a stale approval look current."""
    seen = []
    for variant in (case, charger, case):
        seen.append(carts.add_item(merchant_id, conversation.id, variant.id, 1).version)
    seen.append(
        carts.remove_item(
            merchant_id, conversation.id, carts.get_active(merchant_id, conversation.id).items[0].id
        ).version
    )

    assert seen == sorted(seen)
    assert len(set(seen)) == len(seen)


def test_marking_a_cart_ordered_does_not_move_the_version(carts, merchant_id, conversation, case):
    """The composition did not change, and an approval bound to this version must
    stay matched to the order it authorized."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)

    carts.mark_ordered(merchant_id, cart.id)

    assert carts.get(merchant_id, cart.id).version == cart.version
    assert carts.get(merchant_id, cart.id).status is CartStatus.ORDERED


# --------------------------------------------------------------------------
# Price drift is reported, not silently applied
# --------------------------------------------------------------------------


def test_drift_is_reported_in_both_directions(session, carts, merchant_id, conversation, case):
    """ADR-014: a price change in *either* direction invalidates an approval. A
    cheaper cart is still not the cart the buyer agreed to."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)

    for delta, increased in ((Decimal("300"), True), (Decimal("-600"), False)):
        session.execute(
            text("UPDATE product_variants SET price = price + :d WHERE id = :id"),
            {"d": delta, "id": case.id},
        )
        view = carts.get(merchant_id, cart.id)
        assert view.has_drifted
        assert view.drift[0].increased is increased
        carts.refresh(merchant_id, cart.id)


def test_a_view_shows_drift_without_changing_what_is_stored(
    session, carts, merchant_id, conversation, case
):
    """Correcting it on read would change what the buyer is charged without them
    seeing it happen. `refresh` is the deliberate act."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :id"), {"id": case.id}
    )

    view = carts.get(merchant_id, cart.id)

    assert view.has_drifted
    assert view.total == cart.total  # unchanged until refreshed
    assert view.version == cart.version


# --------------------------------------------------------------------------
# What a cart refuses
# --------------------------------------------------------------------------


def test_a_variant_that_does_not_exist_is_refused(carts, merchant_id, conversation):
    """A§30, ADR-009: a supplied id is a lookup key, never a fact."""
    with pytest.raises(CartError) as error:
        carts.add_item(merchant_id, conversation.id, uuid.uuid4(), 1)

    assert error.value.code == "VARIANT_NOT_FOUND"


def test_an_out_of_stock_variant_cannot_be_added(carts, merchant_id, conversation, variant_id):
    """RULE 5. The seed contains an out-of-stock variant for exactly this."""
    with pytest.raises(CartError) as error:
        carts.add_item(merchant_id, conversation.id, variant_id("CASE-IP16-CLR"), 1)

    assert error.value.code == "OUT_OF_STOCK"


def test_more_than_the_available_quantity_is_refused(
    session, carts, merchant_id, conversation, case
):
    """D§29 step 6: enough for what was asked, not merely non-zero."""
    session.execute(
        text("UPDATE inventory SET quantity = 2 WHERE variant_id = :id"), {"id": case.id}
    )

    carts.add_item(merchant_id, conversation.id, case.id, 2)
    with pytest.raises(CartError) as error:
        carts.add_item(merchant_id, conversation.id, case.id, 1)

    assert error.value.code == "OUT_OF_STOCK"


@pytest.mark.parametrize("quantity", [-1, 0, MAX_LINE_QUANTITY + 1])
def test_a_quantity_outside_the_bounds_cannot_be_added(
    carts, merchant_id, conversation, case, quantity
):
    """Zero is included deliberately. `set_quantity(0)` means "remove this line",
    but `add_item(0)` means nothing at all - adding no units is not an operation,
    and letting it through would leave an empty line with a line total of zero
    sitting in the buyer's cart.
    """
    with pytest.raises(CartError):
        carts.add_item(merchant_id, conversation.id, case.id, quantity)


def test_setting_a_quantity_to_zero_removes_the_line(carts, merchant_id, conversation, case):
    cart = carts.add_item(merchant_id, conversation.id, case.id, 2)

    emptied = carts.set_quantity(merchant_id, conversation.id, cart.items[0].id, 0)

    assert emptied.is_empty


def test_an_unknown_item_cannot_be_changed(carts, merchant_id, conversation, case):
    carts.add_item(merchant_id, conversation.id, case.id, 1)

    with pytest.raises(CartError):
        carts.set_quantity(merchant_id, conversation.id, uuid.uuid4(), 2)


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def test_adding_the_same_variant_twice_makes_one_line(carts, merchant_id, conversation, case):
    """`UNIQUE(cart_id, variant_id)` would refuse a second row anyway, and
    failing there would be a database error where the buyer meant something
    perfectly sensible."""
    carts.add_item(merchant_id, conversation.id, case.id, 1)
    cart = carts.add_item(merchant_id, conversation.id, case.id, 2)

    assert len(cart.items) == 1
    assert cart.items[0].quantity == 3


def test_a_session_reuses_its_active_cart(carts, merchant_id, conversation, case, charger):
    first = carts.add_item(merchant_id, conversation.id, case.id, 1)
    second = carts.add_item(merchant_id, conversation.id, charger.id, 1)

    assert second.id == first.id


def test_a_session_with_no_cart_reads_as_none(carts, merchant_id, conversation):
    """`GET /api/cart` on a fresh session should say so, not mint state."""
    assert carts.get_active(merchant_id, conversation.id) is None


def test_replace_items_sets_the_cart_to_exactly_what_was_proposed(
    carts, merchant_id, conversation, case, charger
):
    """What `propose_cart` calls. A second proposal corrects the first."""
    carts.replace_items(merchant_id, conversation.id, [(case.id, 2), (charger.id, 1)])
    cart = carts.replace_items(merchant_id, conversation.id, [(charger.id, 3)])

    assert [(item.sku, item.quantity) for item in cart.items] == [(charger.sku, 3)]
    assert cart.total == charger.price * 3


def test_a_proposal_naming_one_bad_variant_changes_nothing(carts, merchant_id, conversation, case):
    """Everything is resolved before anything is written, so a bad proposal
    leaves the existing cart intact rather than half-replaced."""
    before = carts.replace_items(merchant_id, conversation.id, [(case.id, 1)])

    with pytest.raises(CartError):
        carts.replace_items(merchant_id, conversation.id, [(case.id, 1), (uuid.uuid4(), 1)])

    after = carts.get_active(merchant_id, conversation.id)
    assert [item.sku for item in after.items] == [item.sku for item in before.items]
    assert after.version == before.version


def test_a_cart_is_invisible_to_another_merchant(carts, merchant_id, conversation, case):
    """ADR-002: scoping excludes, it does not merely filter."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    other = uuid.UUID("00000000-0000-5000-8000-00000000dead")

    assert carts.get(other, cart.id) is None
