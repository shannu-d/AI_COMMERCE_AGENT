"""The structured buyer intent (L§5), as Pydantic.

L§5 gives a conceptual shape and says outright that "the exact schema should be
defined during implementation and validated using Pydantic". This is that
schema. Two departures from its example are deliberate and load-bearing.

**Requirements and preferences are separate fields.** L§5 has one `preferences`
object. ADR-005 needs two, because the difference between "must be USB-C" and
"prefers USB-C" is the difference between eliminating a product and ranking it
lower, and that classification has to be explicit and inspectable rather than
inferred from phrasing. Where the model is unsure, the safe field is
`preferences`: over-filtering hides real products silently, under-filtering only
reorders them.

**A device is a phrase, not an identifier.** L§5's example carries
`"target_identifier": "iphone_16"`, which looks canonical. ADR-003 forbids
trusting that: `iphone_15` is an equally well-formed token and a completely
wrong answer. So `DeviceReference` holds the buyer's words, the model's
`target_identifier` is accepted only as an alias for them, and resolution
against `compatibility_targets` happens later, in code. Nothing downstream can
skip that step, because the ranker's `ProductRequirement` demands a
`ResolvedTarget` that only the database can mint.

Everything here is **untrusted input**. It is what the model claims the buyer
wants. It carries no price, no SKU, no stock and no compatibility fact, and it
never will — those come from PostgreSQL (RULE 1, RULE 2, RULE 6, RULE 7).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.llm.errors import LLMOutputError

__all__ = [
    "MAX_QUANTITY",
    "SUPPORTED_CURRENCIES",
    "Budget",
    "BuyerIntent",
    "DeviceReference",
    "IntentExtraction",
    "ProductRequest",
    "loads_decimal",
]

#: A§18/ADR-009: `1 <= quantity <= 99`. A four-digit quantity from a chat
#: message is a mistake or an attack, never a purchase.
MAX_QUANTITY = 99

#: The seed catalog is INR throughout, and ADR-008 defines no conversion
#: anywhere. A currency the application cannot price in is rejected rather than
#: assumed.
SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"INR"})

Quantity = Annotated[int, Field(ge=1, le=MAX_QUANTITY)]


def loads_decimal(payload: str) -> Any:
    """`json.loads`, but money survives.

    The reason this exists is the same one that makes seed and API money a
    string (ADR-008): plain `json.loads("1500.50")` produces a `float` before
    any validator can intervene, and a float that has already lost precision
    cannot be repaired by converting it to `Decimal` afterwards.

    The model emits JSON numbers — it will write `"max": 1500`, not
    `"max": "1500"` — so this is the only place that loss can be prevented.
    `parse_float=Decimal` catches the decimal case; integers are exact in both
    representations.
    """
    try:
        return json.loads(payload, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"model output is not valid JSON: {exc.msg}") from exc


class _Strict(BaseModel):
    """Reject unknown fields.

    A key the schema does not define is either a model hallucination or a
    protocol drift, and silently dropping it hides both.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DeviceReference(_Strict):
    """A device the buyer mentioned, in the buyer's words.

    Never resolved, never trusted. `text` is matched against
    `compatibility_targets` by `CompatibilityService` (ADR-003), which either
    returns a canonical identifier or refuses — and refusing means asking the
    buyer, not guessing.
    """

    #: What the buyer called it: "iPhone 16", "my MacBook", "usb c".
    text: str = Field(min_length=1, max_length=120, validation_alias="text")
    #: What kind of thing the model thinks it is. A hint that narrows
    #: resolution; wrong values cost a lookup, never a wrong product.
    target_type: Literal["phone_model", "laptop_model", "device_port"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_the_specifications_own_field_name(cls, data: Any) -> Any:
        """Accept L§5's `target_identifier` as a source of `text`.

        The specification's example uses that name, so the model may well emit
        it. Accepting it costs nothing and changes nothing: whatever arrives is
        treated as free text and re-resolved from scratch. A canonical-looking
        value gets no more credence than "my phone".
        """
        if isinstance(data, dict) and "text" not in data and "target_identifier" in data:
            data = dict(data)
            data["text"] = data.pop("target_identifier")
        return data


class Budget(_Strict):
    """A spending ceiling, in major units (ADR-008)."""

    max: Decimal = Field(gt=0)
    currency: str = "INR"

    @field_validator("max", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        """A `float` here means `loads_decimal` was bypassed.

        Rejected loudly rather than coerced: `Decimal(1500.1)` is
        `1500.0999999...`, and money that is quietly wrong is the failure
        ADR-008 exists to prevent.
        """
        if isinstance(value, float):
            raise ValueError(
                "budget must not arrive as a float; parse model JSON with "
                "app.llm.schemas.loads_decimal (ADR-008)"
            )
        return value

    @field_validator("currency")
    @classmethod
    def _supported(cls, value: str) -> str:
        upper = value.upper()
        if upper not in SUPPORTED_CURRENCIES:
            supported = sorted(SUPPORTED_CURRENCIES)
            raise ValueError(f"unsupported currency {value!r}; supported: {supported}")
        return upper


class ProductRequest(_Strict):
    """One product type the buyer asked for.

    `product_type` is a *candidate* category slug. It is not validated against
    the catalog here, because this layer has no catalog; the tool schema's
    enumerated categories (ADR-009, open question B2) and the services do that.
    """

    product_type: str = Field(min_length=1, max_length=64)
    quantity: Quantity = 1
    #: Eliminating (ADR-005). A product failing one of these is removed.
    required_attributes: dict[str, Any] = Field(default_factory=dict)
    #: Scored, never eliminating.
    preferences: dict[str, Any] = Field(default_factory=dict)
    #: Per-item ceiling, when the buyer set one for this product specifically.
    max_price: Decimal | None = Field(default=None, gt=0)

    @field_validator("max_price", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("max_price must not arrive as a float (ADR-008)")
        return value


class BuyerIntent(_Strict):
    """Everything the model believes the buyer wants, validated.

    This is the object L§5 describes and the one L§26 updates across turns. It
    is the *only* thing the model contributes to a recommendation: the candidate
    set, the prices, the stock, the compatibility and the ordering are all
    produced by deterministic code from this.
    """

    product_requirements: list[ProductRequest] = Field(default_factory=list)
    compatibility_requirements: list[DeviceReference] = Field(default_factory=list)
    budget: Budget | None = None
    #: Preferences that apply across every requested product.
    preferences: dict[str, Any] = Field(default_factory=dict)
    #: A named ranking profile the model may select (ADR-004). It may **not**
    #: emit weights; an unknown name is rejected when the profile is looked up.
    weight_profile: str | None = None

    @property
    def is_actionable(self) -> bool:
        """Whether there is enough here to search for something.

        L§6's distinction: required information is what makes a search
        meaningful, optional information only improves ranking. Without a
        product type there is nothing to search *for*.
        """
        return bool(self.product_requirements)

    @property
    def device(self) -> DeviceReference | None:
        """The first stated device, if any."""
        return self.compatibility_requirements[0] if self.compatibility_requirements else None


class IntentExtraction(_Strict):
    """The result of one extraction: an intent, a question, or both.

    Both is normal and is why this is not a union. "I need a case for my iPhone
    16, something slim" yields a usable intent *and* no question; "I need a
    case" yields a partial intent *and* the question L§7 requires. Discarding
    the partial intent when clarifying would throw away what the buyer already
    said and force them to repeat it.
    """

    intent: BuyerIntent
    #: L§7: ask when ambiguity "can materially change the product or financial
    #: action". Do not ask when the answer is already known.
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _a_clarification_needs_a_question(self) -> IntentExtraction:
        """A flag without a question is not a clarification, it is a dead end."""
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("needs_clarification is set but no clarification_question was given")
        return self
