"""Builders for the agent-runtime tests.

The runtime is the one package that touches both sides of the boundary, so
testing it means faking both — and the two fakes are deliberately different in
kind.

**The model is faked at the `LLMClient` protocol**, exactly as in `tests/llm`
(ADR-015). `FakeClient` is imported from there rather than re-implemented: two
fakes of one protocol would be two things to keep in step, and the one that
drifts is the one whose tests still pass.

**The services are faked at their own surface**, not at the database. A stub
that answers `get_variant` from a dict is not pretending to be PostgreSQL; it is
standing in for a service whose own behaviour is already covered by 145
`requires_db` tests in `tests/services`. What is under test here is the pipeline
around the call — validation, authorization, the loop bound, what reaches the
buyer — and none of that becomes more true for having run a query.

Tests that genuinely need the database are marked `requires_db` and live in
`test_tools_db.py`, where a real catalog is the point.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.agent.context import AgentContext, TurnMemory
from app.domain.cart import CartItemView, CartView
from app.domain.catalog import ProductDetail, VariantView
from app.domain.commerce import CartStatus
from app.domain.compatibility import (
    CompatibilityTargetView,
    ResolutionFailure,
    ResolvedTarget,
    UnresolvedTarget,
)
from app.domain.conversation import ConversationState
from app.domain.inventory import AvailabilityCheck, StockStatus, StockView
from app.domain.ranking import (
    Explanation,
    RankedCandidate,
    Recommendation,
    RecommendationLabel,
    RecommendationOutcome,
    ScoreBreakdown,
    WeightedComponent,
)
from app.llm.models import Message, ModelResponse, StopReason, ToolCall
from tests.llm.conftest import FakeClient

MERCHANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


# --------------------------------------------------------------------------
# Catalog values
# --------------------------------------------------------------------------


def make_variant(
    *,
    sku: str = "CASE-IP16-BLK",
    name: str = "Black",
    price: str = "999.00",
    product_name: str = "AeroCase Pro",
    category: str = "phone_case",
    variant_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    attributes: dict[str, Any] | None = None,
) -> VariantView:
    return VariantView(
        id=variant_id or uuid.uuid5(uuid.NAMESPACE_DNS, sku),
        sku=sku,
        name=name,
        price=Decimal(price),
        currency="INR",
        merchant_id=MERCHANT_ID,
        product_id=product_id or uuid.uuid5(uuid.NAMESPACE_DNS, product_name),
        product_slug=product_name.lower().replace(" ", "-"),
        product_name=product_name,
        category_slug=category,
        attributes=attributes or {"material": "TPU", "color": "black"},
    )


def make_ranked(variant: VariantView, *, rank: int = 1, score: str = "0.796800") -> RankedCandidate:
    breakdown = ScoreBreakdown(
        profile_name="default",
        components=(
            WeightedComponent(name="preference", score=Decimal("0.8"), weight=Decimal("0.5")),
            WeightedComponent(name="price", score=Decimal("0.334"), weight=Decimal("0.3")),
            WeightedComponent(name="relevance", score=Decimal("0.9"), weight=Decimal("0.2")),
        ),
        final_score=Decimal(score),
    )
    return RankedCandidate(
        rank=rank,
        variant=variant,
        score=breakdown,
        explanation=Explanation(
            label=RecommendationLabel.BEST_OVERALL,
            winning_component="preference",
            margin=None,
        ),
        stock_status=StockStatus.IN_STOCK,
    )


def make_recommendation(
    *candidates: RankedCandidate,
    outcome: RecommendationOutcome = RecommendationOutcome.EXACT_MATCH,
) -> Recommendation:
    from app.domain.ranking import ProductRequirement

    return Recommendation(
        requirement=ProductRequirement(label="phone_case", category_slug="phone_case"),
        outcome=outcome,
        profile_name="default",
        candidates=tuple(candidates),
    )


# --------------------------------------------------------------------------
# Service stubs
# --------------------------------------------------------------------------


@dataclass
class StubCatalog:
    """Answers the handful of catalog questions the tools ask."""

    variants_by_sku: dict[str, VariantView] = field(default_factory=dict)
    variants_by_id: dict[uuid.UUID, VariantView] = field(default_factory=dict)
    products: dict[uuid.UUID, ProductDetail] = field(default_factory=dict)
    categories: tuple[str, ...] = ("phone_case", "charger", "usb_cable", "earbuds")
    calls: list[str] = field(default_factory=list)

    def get_variant_by_sku(self, merchant_id: uuid.UUID, sku: str) -> VariantView | None:
        self.calls.append(f"get_variant_by_sku:{sku}")
        return self.variants_by_sku.get(sku)

    def get_variant(self, merchant_id: uuid.UUID, variant_id: uuid.UUID) -> VariantView | None:
        self.calls.append(f"get_variant:{variant_id}")
        return self.variants_by_id.get(variant_id)

    def get_product(self, merchant_id: uuid.UUID, product_id: uuid.UUID) -> ProductDetail | None:
        self.calls.append(f"get_product:{product_id}")
        return self.products.get(product_id)

    def category_exists(self, merchant_id: uuid.UUID, slug: str) -> bool:
        return slug in self.categories

    def category_slugs(self, merchant_id: uuid.UUID) -> tuple[str, ...]:
        return self.categories

    def attribute_vocabulary(self, merchant_id: uuid.UUID) -> dict[str, tuple[str, ...]]:
        """The attribute names each category uses, as the real service reports them.

        Small and fixed here; `test_catalog_service.py` checks the query that
        produces it against a real catalog. What the agent tests need is only
        that the runtime asks for it and sends it.
        """
        return {
            "phone_case": ("color", "material", "protection"),
            "charger": ("fast_charge", "port_type", "wattage"),
            "earbuds": ("anc", "battery_hours"),
        }


@dataclass
class StubCompatibility:
    """Resolves device phrases, or refuses to."""

    targets: dict[str, ResolvedTarget] = field(default_factory=dict)
    ambiguous: dict[str, tuple[CompatibilityTargetView, ...]] = field(default_factory=dict)

    def resolve_target(self, text: str, *, target_type: str | None = None):
        if text in self.ambiguous:
            return UnresolvedTarget(
                reason=ResolutionFailure.AMBIGUOUS_TARGET,
                requested_text=text,
                normalized_text=text.lower(),
                candidates=self.ambiguous[text],
            )
        if text in self.targets:
            return self.targets[text]
        return UnresolvedTarget(
            reason=ResolutionFailure.UNKNOWN_TARGET,
            requested_text=text,
            normalized_text=text.lower(),
        )


@dataclass
class StubInventory:
    stock: dict[uuid.UUID, StockView] = field(default_factory=dict)

    def get_stock_map(
        self, merchant_id: uuid.UUID, variant_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, StockView]:
        return {
            variant_id: self.stock.get(variant_id, StockView.missing(variant_id))
            for variant_id in variant_ids
        }

    def check_availability(
        self, merchant_id: uuid.UUID, variant_id: uuid.UUID, quantity: int = 1
    ) -> AvailabilityCheck:
        stock = self.stock.get(variant_id, StockView.missing(variant_id))
        return AvailabilityCheck(
            variant_id=variant_id,
            requested_quantity=quantity,
            available_quantity=stock.available_quantity,
            status=stock.status,
            available=stock.available_quantity >= quantity,
        )


@dataclass
class StubRecommendations:
    """Returns a scripted `Recommendation`, and records what it was asked for."""

    result: Recommendation | None = None
    cross_sell: list[Any] = field(default_factory=list)
    requirements: list[Any] = field(default_factory=list)

    def recommend(self, merchant_id: uuid.UUID, requirement, **kwargs) -> Recommendation:
        self.requirements.append(requirement)
        assert self.result is not None, "no recommendation scripted"
        return self.result

    def cross_sell_candidates(self, merchant_id: uuid.UUID, product_id: uuid.UUID, **kwargs):
        return self.cross_sell


@dataclass
class StubCarts:
    """An in-memory stand-in for `CartService`.

    It keeps the two properties the runtime and the tools depend on and nothing
    else: the totals are summed *here* from the lines, never taken from a
    caller, and `version` increments on every mutation. A stub that accepted a
    total would let a test pass against a service that accepted one too.
    """

    carts: dict[uuid.UUID, Any] = field(default_factory=dict)
    variants: dict[uuid.UUID, VariantView] = field(default_factory=dict)
    unavailable: set[uuid.UUID] = field(default_factory=set)

    def get_active(self, merchant_id: uuid.UUID, session_id: uuid.UUID):
        return self.carts.get(session_id)

    def replace_items(self, merchant_id: uuid.UUID, session_id: uuid.UUID, lines):
        from app.services.cart_service import CartError

        resolved = []
        for variant_id, quantity in lines:
            variant = self.variants.get(variant_id)
            if variant is None:
                raise CartError("VARIANT_NOT_FOUND", "that product is not in this catalog")
            if variant_id in self.unavailable:
                raise CartError("OUT_OF_STOCK", f"{variant.sku} is not available")
            resolved.append((variant, quantity))

        previous = self.carts.get(session_id)
        items = tuple(
            CartItemView(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, f"item-{variant.sku}"),
                variant_id=variant.id,
                product_id=variant.product_id,
                sku=variant.sku,
                product_name=variant.product_name,
                variant_name=variant.name,
                quantity=quantity,
                unit_price=variant.price,
                line_total=variant.price * quantity,
                currency=variant.currency,
                stock_status=StockStatus.IN_STOCK.value,
            )
            for variant, quantity in resolved
        )
        subtotal = sum((item.line_total for item in items), Decimal("0.00"))
        cart = CartView(
            id=previous.id if previous else uuid.uuid4(),
            session_id=session_id,
            status=CartStatus.ACTIVE,
            version=(previous.version + 1) if previous else 2,
            currency=resolved[0][0].currency if resolved else "INR",
            subtotal=subtotal,
            total=subtotal,
            items=items,
        )
        self.carts[session_id] = cart
        return cart


@dataclass
class StubApprovals:
    """An in-memory stand-in for `ApprovalService`.

    It keeps the one property `request_approval` must not be able to violate:
    `request` writes PENDING and has no parameter through which any other status
    could arrive. A stub that accepted a status would let a test pass against a
    service that accepted one too.
    """

    requested: list[Any] = field(default_factory=list)

    def request(self, session_id: uuid.UUID, cart):
        from app.domain.approval import ApprovalView, items_fingerprint, lines_from
        from app.domain.commerce import ApprovalStatus
        from app.services.approval_service import ApprovalError

        if cart.is_empty:
            raise ApprovalError.__new__(ApprovalError) if False else _empty_cart_error()

        now = datetime.now(UTC)
        view = ApprovalView(
            id=uuid.uuid4(),
            session_id=session_id,
            cart_id=cart.id,
            cart_version=cart.version,
            approved_total=cart.total,
            currency=cart.currency,
            items_fingerprint=items_fingerprint(lines_from(cart.items)),
            status=ApprovalStatus.PENDING,
            created_at=now,
            approved_at=None,
            expires_at=now + timedelta(minutes=15),
        )
        self.requested.append(view)
        return view

    def current(self, cart_id: uuid.UUID):
        return None


def _empty_cart_error():
    from app.domain.approval import ApprovalFailure
    from app.services.approval_service import ApprovalError

    return ApprovalError(ApprovalFailure.CART_EMPTY, "there is nothing in the cart")


@dataclass
class StubSessions:
    """An in-memory stand-in for `SessionService`.

    In tests only. ADR-006 settles that real session state is PostgreSQL, and
    `test_session_service.py` exercises the real one against a real database;
    this exists so the *loop* can be tested without one.
    """

    state: ConversationState = ConversationState.NEW_SESSION
    intent: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    known: set[uuid.UUID] = field(default_factory=lambda: {SESSION_ID})
    touched: int = 0

    def get(self, merchant_id: uuid.UUID, session_id: uuid.UUID):
        if session_id not in self.known:
            return None
        from app.services.session_service import SessionView

        return SessionView(
            id=session_id,
            merchant_id=merchant_id,
            conversation_state=self.state,
            intent=dict(self.intent),
        )

    def create(self, merchant_id: uuid.UUID):
        from app.services.session_service import SessionView

        new_id = uuid.uuid4()
        self.known.add(new_id)
        return SessionView(
            id=new_id,
            merchant_id=merchant_id,
            conversation_state=ConversationState.NEW_SESSION,
            intent={},
        )

    def touch(self, merchant_id: uuid.UUID, session_id: uuid.UUID) -> None:
        self.touched += 1

    def set_state(
        self, merchant_id: uuid.UUID, session_id: uuid.UUID, state: ConversationState
    ) -> None:
        self.state = state

    def set_intent(
        self, merchant_id: uuid.UUID, session_id: uuid.UUID, intent: dict[str, Any]
    ) -> None:
        self.intent = dict(intent)

    def append_message(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        role: str,
        content: str | None = None,
        tool_payload: dict[str, Any] | None = None,
    ) -> None:
        self.messages.append({"role": role, "content": content, "tool_payload": tool_payload})

    def history(self, merchant_id: uuid.UUID, session_id: uuid.UUID, **kwargs):
        @dataclass
        class Row:
            role: str
            content: str | None

        return [
            Row(role=m["role"], content=m["content"])
            for m in self.messages
            if m["role"] in ("user", "assistant")
        ]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def catalog() -> StubCatalog:
    return StubCatalog()


@pytest.fixture
def compatibility() -> StubCompatibility:
    return StubCompatibility()


@pytest.fixture
def inventory() -> StubInventory:
    return StubInventory()


@pytest.fixture
def recommendations() -> StubRecommendations:
    return StubRecommendations()


@pytest.fixture
def sessions() -> StubSessions:
    return StubSessions()


@pytest.fixture
def carts() -> StubCarts:
    return StubCarts()


@pytest.fixture
def approvals() -> StubApprovals:
    return StubApprovals()


@pytest.fixture
def context(
    catalog, carts, approvals, compatibility, inventory, recommendations, sessions
) -> AgentContext:
    """An `AgentContext` whose services are stubs.

    Constructed field-by-field rather than through `from_session`, because that
    classmethod's whole job is to build real services from a database session
    and there is no database here.
    """
    return AgentContext(
        merchant_id=MERCHANT_ID,
        catalog=catalog,  # type: ignore[arg-type]
        carts=carts,  # type: ignore[arg-type]
        approvals=approvals,  # type: ignore[arg-type]
        compatibility=compatibility,  # type: ignore[arg-type]
        inventory=inventory,  # type: ignore[arg-type]
        recommendations=recommendations,  # type: ignore[arg-type]
        sessions=sessions,  # type: ignore[arg-type]
    )


@pytest.fixture
def memory() -> TurnMemory:
    return TurnMemory()


def text_reply(text: str) -> ModelResponse:
    return ModelResponse(text=text, stop_reason=StopReason.END_TURN)


def tool_reply(name: str, arguments: dict[str, Any], *, call_id: str = "call_1") -> ModelResponse:
    return ModelResponse(
        text="",
        tool_calls=(ToolCall(id=call_id, name=name, arguments=arguments),),
        stop_reason=StopReason.TOOL_USE,
    )


__all__ = [
    "MERCHANT_ID",
    "SESSION_ID",
    "FakeClient",
    "Message",
    "make_ranked",
    "make_recommendation",
    "make_variant",
    "text_reply",
    "tool_reply",
]
