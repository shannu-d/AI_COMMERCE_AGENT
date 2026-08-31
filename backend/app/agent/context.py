"""What a turn has available, and what it remembers while it runs (A§50, A§38).

Two objects, with deliberately different lifetimes.

`AgentContext` is the services a tool may reach and the merchant it may reach
them for. It is constructed once per request from a database session. Every
service on it is merchant-scoped by ADR-002, and the merchant is resolved
server-side — never read from model output, never taken from a request body.

`TurnMemory` is A§50: "the Runtime may retain relevant tool results during a
single agent turn". It lives for one turn and is discarded. That bound is the
point. Retaining tool results across turns would mean a later turn could answer
from a price read earlier, which is precisely the staleness ADR-014 exists to
prevent; and the accumulated `BuyerIntent` already carries what should persist.

Nothing here is a cache. `get_variant` called twice makes two queries, because a
tool that reports stock must report stock now.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session as DbSession

from app.services.cart_service import CartService
from app.services.catalog_service import CatalogService
from app.services.compatibility_service import CompatibilityService
from app.services.inventory_service import InventoryService
from app.services.recommendation_service import RecommendationService
from app.services.session_service import SessionService

__all__ = ["AgentContext", "TurnMemory"]


@dataclass(frozen=True)
class AgentContext:
    """The services one turn may use, scoped to one merchant."""

    merchant_id: uuid.UUID
    catalog: CatalogService
    carts: CartService
    compatibility: CompatibilityService
    inventory: InventoryService
    recommendations: RecommendationService
    sessions: SessionService

    @classmethod
    def from_session(cls, db: DbSession, merchant_id: uuid.UUID) -> AgentContext:
        """Build every service from one database session.

        One session, so everything a turn reads is read inside one transaction
        and a tool cannot observe a half-applied write.
        """
        return cls(
            merchant_id=merchant_id,
            catalog=CatalogService(db),
            carts=CartService(db),
            compatibility=CompatibilityService(db),
            inventory=InventoryService(db),
            recommendations=RecommendationService(db),
            sessions=SessionService(db),
        )


@dataclass
class TurnMemory:
    """Tool results retained for the duration of one turn (A§50).

    `recommendations` is the one that matters. ADR-010 requires the response's
    `recommendations[]` to come from the ranking engine rather than from model
    output, so the runtime keeps what the ranker produced and serializes *that*,
    regardless of what the model then says in prose. The model can describe the
    results; it cannot edit them on the way out.
    """

    #: Ranked results, keyed by the requirement label that produced them. Written
    #: by the search tools, read by the response builder.
    recommendations: dict[str, Any] = field(default_factory=dict)
    #: Every tool call made this turn, in order, for the ADR-010 trace.
    calls: list[dict[str, Any]] = field(default_factory=list)
    #: Devices resolved this turn, so a second tool call for the same phrase does
    #: not re-ask the buyer a question already answered.
    resolved_devices: dict[str, Any] = field(default_factory=dict)
    #: Whose turn this is. Set by the runtime from the loaded session, **never**
    #: from a tool argument - no tool schema has a `session_id` field, so a model
    #: has no way to write to somebody else's cart. A MEDIUM-tier tool is refused
    #: outright when this is `None`, because a write with no established session
    #: is a write with no owner.
    session_id: uuid.UUID | None = None

    def record(self, name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        """Append one call to the trace.

        Arguments and results are stored as the structured values they already
        are. A§39 wants the trace to show what was asked and what came back; a
        rendered sentence would lose the distinction between a tool that found
        nothing and one that failed.
        """
        self.calls.append({"tool": name, "arguments": arguments, "result": result})

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def require_session(self) -> uuid.UUID:
        """The session this turn belongs to, or a refusal.

        Raising rather than returning `None` keeps the check at one site: a tool
        that needs a session gets one or does not run.
        """
        if self.session_id is None:
            raise LookupError("this turn has no established session")
        return self.session_id
