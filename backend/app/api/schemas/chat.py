"""`POST /api/chat` request and response (ADR-010).

The union of A§48's shape and F§8-F§9's, which is what ADR-010 settles: the
document specifies the same endpoint twice and both halves have a consumer. A§48
gives `state` and `trace`, which drive the UI's affordances and the demo; F§9
gives `recommendations[]`, and states the reason it must exist —

> This allows the frontend to render proper product cards instead of trying to
> extract product information from prose.

Three rules the models below enforce rather than describe.

**Every field is always present.** Absent data is `null` or `[]`, never a missing
key, so no client tests for key existence. Pydantic emits every field because
none is `exclude_none`.

**Money is a fixed-scale string** — `"999.00"`, never `999.0` (ADR-008). The
field is typed `str` here, not `Decimal`, because a `Decimal` field would still
be serialized as a JSON number by most encoders and the whole point is that a
client's parser never sees one.

**`message` carries no commerce fact the structured fields do not.** A client
that parses it for a price is doing something the contract forbids. Nothing in
this module invites that: the prose and the data are separate fields, and the
data is the authoritative half.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.errors import ApiErrorCode
from app.domain.conversation import ConversationState

__all__ = ["ChatError", "ChatRequest", "ChatResponse", "Recommendation", "ScoreBreakdown"]


class ChatRequest(BaseModel):
    """One buyer message.

    `session_id` is omitted on the first turn and echoed back thereafter. It is
    server-minted: a client-supplied value that does not correspond to an
    existing session is rejected rather than silently creating one, so a typo
    cannot strand a conversation somewhere the buyer cannot get back to.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID | None = Field(
        default=None,
        description="Omit on the first turn. Server-minted; never chosen by the client.",
    )
    message: str = Field(
        min_length=1,
        max_length=2000,
        description="The buyer's message, verbatim.",
    )


class ScoreBreakdown(BaseModel):
    """The component scores that produced the ordering (ADR-010).

    Present so the ranking is inspectable and the demo is explainable. A client
    may ignore it entirely; nothing renders incorrectly without it.
    """

    model_config = ConfigDict(extra="forbid")

    final: str = Field(description="FinalScore, six decimal places, as a string.")
    profile: str = Field(description="The weight profile that produced it.")
    components: dict[str, str] = Field(
        default_factory=dict,
        description="Each feature score, before its weight was applied.",
    )


class Recommendation(BaseModel):
    """One ranked product (F§9, ADR-010).

    Emitted by the ranking engine, never extracted from prose and never authored
    by the model. `reason` in particular is the engine's own deterministic label
    (closing A7): the model may paraphrase it in `message`, but a model-written
    reason would be an ungrounded claim about arithmetic it did not perform.
    """

    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    variant_id: uuid.UUID
    sku: str
    name: str
    variant_name: str
    category: str
    #: A fixed-scale string. See the module docstring.
    price: str
    currency: str
    #: Coarse only — exact quantities never appear in a buyer-facing payload
    #: (ADR-009, ADR-010, closing E5).
    stock_status: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    brand: str | None = None
    rank: int
    reason: str
    reason_code: str
    score: ScoreBreakdown | None = None


class ChatError(BaseModel):
    """A business or technical failure, in F§25's closed vocabulary."""

    model_config = ConfigDict(extra="forbid")

    code: ApiErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """One agent turn.

    Returned with HTTP 200 for any turn the agent completed, **including one
    that ends in a business failure** (ADR-010). A policy refusal or an
    out-of-stock outcome is a successful conversational turn carrying an `error`
    body; 4xx is for malformed requests and unknown sessions, 5xx for genuine
    server faults. That keeps outcomes the frontend must render as recovery
    flows out of the client's network-error path.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    state: ConversationState = Field(
        description="Display state (A§25). Never read by the Policy Engine (ADR-007)."
    )
    message: str = Field(description="Natural language only. Carries no commerce fact.")
    recommendations: list[Recommendation] = Field(default_factory=list)
    #: The authoritative cart, from M7. Always backend-computed; the frontend
    #: never sums line items (F§12).
    cart: dict[str, Any] | None = None
    #: A§39's trace, per turn and never persisted (ADR-010, closing E6). `null`
    #: unless AGENT_TRACE_ENABLED.
    trace: dict[str, Any] | None = None
    error: ChatError | None = None
