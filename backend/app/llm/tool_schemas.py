"""The tools Claude is offered, and the validation their arguments must pass.

This module defines the **interface** — names, descriptions, argument schemas
and the rules those arguments must satisfy. It deliberately contains no
handlers: binding a tool to a service is the agent runtime's job (M5 onward),
and the two are separated so that "what the model may ask for" can be reviewed
without reading "what happens when it does".

The registry follows ADR-009 exactly. Two entries in it are worth reading
carefully, because both are places the specification contradicts itself and the
safer reading won:

**`create_order` is not here.** A§17 lists it among the tools Claude receives;
A§15 says it "must NOT be freely available to the LLM". A§15 is the
safety-bearing statement, so order creation is not a tool at all — no schema, no
name, no entry. A registered tool with a hard-failing handler would still be a
tool whose existence the model can reason about and whose failure it can try to
route around. `FORBIDDEN_TOOL_NAMES` and a standing test keep it out.

**`request_approval` cannot approve.** It moves conversation state and records a
`PENDING` row. Approval is an act the buyer performs through
`POST /api/cart/approve` (ADR-007). The tool's schema has no field that could
express "approved", which is the structural half of that guarantee.

Across every tool, A§13 and ADR-009 hold: **no tool accepts a product's price,
stock level or compatibility as input.** `propose_cart` takes `(variant_id,
quantity)` pairs and nothing else, and the backend reads the authoritative price
itself. `max_price` is not an exception — it is the buyer's ceiling, a
constraint the buyer stated, never a claim about what something costs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.llm.errors import LLMOutputError
from app.llm.schemas import MAX_QUANTITY, SUPPORTED_CURRENCIES

__all__ = [
    "EXPOSED_TOOL_NAMES",
    "FORBIDDEN_TOOL_NAMES",
    "READ_ONLY_TOOL_NAMES",
    "TOOL_SCHEMAS",
    "RiskTier",
    "ToolDefinition",
    "build_tool_definitions",
    "validate_tool_arguments",
]

#: Tools that must never be registered, whatever a later edit intends.
#: ADR-009, closing open question D6. The safest tool is one that does not exist.
FORBIDDEN_TOOL_NAMES: frozenset[str] = frozenset({"create_order"})

#: A ceiling on any money value a model may state. Not a business rule — a
#: sanity bound, so a hallucinated `1e30` fails validation instead of reaching
#: `NUMERIC(12,2)` and failing much further in.
MAX_STATED_AMOUNT = Decimal("10000000.00")

#: How many attribute names may be advertised per category (see
#: `_inject_attribute_vocabulary`).
#:
#: Six, and the number is a budget rather than a preference. Groq refuses any
#: single request over 8,000 tokens, and on a 200-product catalogue the system
#: prompt and the eight tool schemas already spend most of it. The repository
#: orders each category's names so that the six most filter-like survive - the
#: ones products actually differ on, cheapest to state first - and
#: `get_product` still returns any one product's attributes in full.
MAX_ATTRIBUTE_NAMES_PER_CATEGORY = 6


class RiskTier(StrEnum):
    """A§23's grading. Drives what the executor checks before running a tool."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"


def _money_from_model(value: Any) -> Any:
    """Coerce a model-supplied amount to `Decimal` without losing precision.

    Tool arguments arrive from the Anthropic SDK **already JSON-decoded**, so a
    number in the model's output is a `float` before this application sees it.
    Unlike the intent payload — which `app.llm.schemas.loads_decimal` parses with
    `parse_float=Decimal`, and where a float therefore means a bug — there is no
    opportunity here to intercept the parse.

    `Decimal(str(x))` is exact for this: `str()` on a float produces the
    shortest representation that round-trips, so `1500.5` becomes
    `Decimal("1500.5")` and not `Decimal("1500.499999999999954525264911353588104248046875")`.
    What ADR-008 forbids is *arithmetic* and *storage* in binary floating point,
    not a single bounded conversion at an input boundary.
    """
    if isinstance(value, float):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise ValueError("not a usable amount") from None
    return value


Amount = Annotated[Decimal, Field(ge=0, le=MAX_STATED_AMOUNT)]
Quantity = Annotated[int, Field(ge=1, le=MAX_QUANTITY)]


class _ToolArgs(BaseModel):
    """Base for every tool's arguments.

    `extra="forbid"`: an argument the schema does not define is a hallucination
    or a protocol drift, and A§19 requires the call to be rejected before
    execution rather than executed with the surplus quietly dropped.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _CurrencyMixin(_ToolArgs):
    #: Enumerated in the schema as well as validated, for the same reason the
    #: category is (ADR-009, B2). Left as a bare `str | None`, a model fills it
    #: in from its own assumptions — a live turn volunteered `"USD"` — and the
    #: validator then refuses the whole call, so a correct search fails on a
    #: field the buyer never mentioned. The enum makes the wrong value
    #: unavailable rather than merely rejected.
    currency: str | None = Field(
        default=None,
        description="Omit unless the buyer named a currency; the merchant prices in one only.",
    )

    @field_validator("currency")
    @classmethod
    def _supported(cls, value: str | None) -> str | None:
        """A§18: "currency is valid"."""
        if value is None:
            return None
        upper = value.upper()
        if upper not in SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency {value!r}")
        return upper


# --------------------------------------------------------------------------
# Argument models — one per tool
# --------------------------------------------------------------------------


class SearchCatalogArgs(_CurrencyMixin):
    """A§18's own input list: category, search_query, max_price, currency, attributes.

    **`attributes` eliminates; `search_query` only ranks.** That is the whole
    difference between "I need noise cancellation" and "ideally black", and it
    is invisible unless the schema says so — which is why every field here now
    carries a `description`. A property the model is shown as a bare `object`
    titled "Attributes" is a property it will not use, and a live turn failed
    exactly there: "find noise-cancelling earbuds" put the requirement in
    `search_query`, which R§9 defines as a relevance signal and never a filter,
    so nothing was eliminated and three products without ANC came back.
    """

    #: Constrained to real slugs at build time (ADR-009, open question B2), so
    #: the model cannot name a category that does not exist.
    category: str | None = Field(
        default=None,
        description=(
            "The category to search, from the enumerated list. Omit it only "
            "when the buyer has not indicated a product type."
        ),
    )
    search_query: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Free text describing what the buyer is looking for. This is a "
            "RELEVANCE signal only: it influences the ordering and never "
            "removes a product. Put wishes here — 'ideally slim', 'something "
            "smart'. A requirement placed here alone is silently ignored as a "
            "filter; state requirements in `attributes`."
        ),
    )
    max_price: Amount | None = Field(
        default=None,
        description=(
            "A hard ceiling in major units, as a decimal string such as "
            "'1500.00'. Products above it are eliminated, never merely ranked "
            "lower."
        ),
    )
    #: Structural attributes only — "material": "leather". A§18: "attributes
    #: have valid structure". The usable names are injected per category at
    #: build time from the merchant's own rows (`_inject_attribute_vocabulary`).
    attributes: dict[str, str | int | bool] = Field(
        default_factory=dict,
        description=(
            "Attributes the buyer stated as REQUIREMENTS. These eliminate: a "
            "product that does not satisfy every entry is removed before "
            "ranking. 'I need noise cancellation' is {'anc': true}; 'at least "
            "30W' is {'minimum_wattage': 30}. Three forms only: "
            "'minimum_<name>' (>=), 'maximum_<name>' (<=), bare '<name>' "
            "(equals). Use only the names listed for the category you are "
            "searching — an unrecorded name matches nothing. For a mere "
            "preference leave this empty and use search_query."
        ),
    )

    _coerce = field_validator("max_price", mode="before")(_money_from_model)


class GetProductArgs(_ToolArgs):
    """Look up one product by id or SKU.

    Both are **lookup keys, never facts** (A§30, ADR-009). A value that does not
    resolve is an error, not a warning, and never a product invented to match.
    """

    product_id: str | None = None
    sku: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _exactly_one_key(self) -> GetProductArgs:
        if bool(self.product_id) == bool(self.sku):
            raise ValueError("supply exactly one of product_id or sku")
        return self


class GetCompatibleProductsArgs(_CurrencyMixin):
    """Products that fit a device the buyer named.

    `device` is the buyer's phrase — "iPhone 16", "my MacBook Air". It is
    resolved against `compatibility_targets` by the application (ADR-003); an
    unresolvable or ambiguous phrase becomes a question for the buyer, never a
    guess, and never a silent widening of the search.
    """

    device: str = Field(min_length=1, max_length=120)
    category: str | None = None
    max_price: Amount | None = None

    _coerce = field_validator("max_price", mode="before")(_money_from_model)


class CheckInventoryArgs(_ToolArgs):
    """Whether `quantity` of a variant can be bought right now."""

    variant_id: str | None = None
    sku: str | None = Field(default=None, max_length=64)
    quantity: Quantity = 1

    @model_validator(mode="after")
    def _exactly_one_key(self) -> CheckInventoryArgs:
        if bool(self.variant_id) == bool(self.sku):
            raise ValueError("supply exactly one of variant_id or sku")
        return self


class GetUpsellCandidatesArgs(_ToolArgs):
    """Cross-sell candidates for a product the buyer is considering (R§15).

    Grounded in `product_relationships`, then filtered by compatibility and
    stock. R§15's closing rule: the system must not recommend random products
    merely because they increase revenue.
    """

    product_id: str = Field(min_length=1)
    device: str | None = Field(default=None, max_length=120)


class CartItemArg(_ToolArgs):
    """One line of a proposed cart. `(variant_id, quantity)` and nothing else."""

    variant_id: str = Field(min_length=1)
    quantity: Quantity = 1


class ProposeCartArgs(_ToolArgs):
    """Propose a cart. **Computes nothing** (A§13, ADR-009).

    There is deliberately no price, no subtotal and no total field. The backend
    reads the authoritative price for each variant and computes the total; a
    model-supplied amount would be an unverified claim about money, and the one
    the buyer would then be asked to approve.
    """

    items: list[CartItemArg] = Field(min_length=1, max_length=20)


class RequestApprovalArgs(_ToolArgs):
    """Ask the buyer to approve the current cart.

    Moves conversation state to `WAITING_FOR_APPROVAL` and records a `PENDING`
    approval (ADR-007, ADR-009). **There is no field here that can express
    approval**, because approval is an act the buyer performs through
    `POST /api/cart/approve` and not a conclusion the model may reach.
    """

    #: Optional; the session's active cart is used when omitted.
    cart_id: str | None = None


class GetOrderStatusArgs(_ToolArgs):
    """Read the status of an order the buyer already placed."""

    order_id: str = Field(min_length=1)


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One tool as the model sees it, plus what the application needs to police it."""

    name: str
    description: str
    tier: RiskTier
    arguments: type[BaseModel]
    #: The milestone whose handler makes this tool executable. The schema exists
    #: from M4; exposing a tool before its handler exists is the registry's
    #: decision, not this module's.
    milestone: str

    def json_schema(
        self,
        *,
        category_slugs: Sequence[str] | None = None,
        attribute_vocabulary: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, Any]:
        """The JSON Schema sent to the model, with the merchant's own vocabulary in it."""
        schema = self.arguments.model_json_schema()
        schema.pop("title", None)
        _constrain_currency(schema)
        if category_slugs:
            _inject_category_enum(schema, category_slugs)
        if attribute_vocabulary:
            _inject_attribute_vocabulary(schema, attribute_vocabulary)
        return schema

    def to_tool_definition(
        self,
        *,
        category_slugs: Sequence[str] | None = None,
        attribute_vocabulary: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, Any]:
        """The provider-neutral tool definition.

        Deliberately *not* the provider's wire shape. Translating to what Groq's
        OpenAI-compatible API expects is `client.py`'s job (`_to_groq_tool`), so
        the tool catalogue stays readable as a description of what the model may
        ask for rather than as a payload (ADR-018).
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.json_schema(
                category_slugs=category_slugs,
                attribute_vocabulary=attribute_vocabulary,
            ),
        }


def _inject_category_enum(schema: dict[str, Any], slugs: Sequence[str]) -> None:
    """Constrain any `category` property to the merchant's real slugs.

    ADR-009, closing open question B2: enumerating the actual
    `categories.slug` values means the model can only select a category that
    exists, and an unknown value fails schema validation before it reaches a
    service. The enum is built at registry time from the database, so it cannot
    drift from the catalog the way a hard-coded list would.
    """
    prop = (schema.get("properties") or {}).get("category")
    if prop is None:
        return
    prop.pop("anyOf", None)
    prop.pop("type", None)
    prop["enum"] = [*slugs, None]


def _constrain_currency(schema: dict[str, Any]) -> None:
    """Enumerate the currencies the application accepts.

    Unconditional, because unlike the categories this is not merchant data —
    `SUPPORTED_CURRENCIES` is an application constant, and ADR-008 is explicit
    that a mismatch is an error rather than something to convert.

    Without it the property reaches the model as a bare optional string, and a
    model filling in a field it was never asked about is a model volunteering
    `"USD"` — which `_supported` then refuses, failing an otherwise correct
    search on a value the buyer never mentioned.
    """
    prop = (schema.get("properties") or {}).get("currency")
    if prop is None:
        return
    prop.pop("anyOf", None)
    prop.pop("type", None)
    prop["enum"] = [*sorted(SUPPORTED_CURRENCIES), None]


def _inject_attribute_vocabulary(
    schema: dict[str, Any], vocabulary: Mapping[str, Sequence[str]]
) -> None:
    """List the merchant's real attribute names, per category, on `attributes`.

    The same argument as `_inject_category_enum`, one level down. A category the
    model names is checked against the merchant's slugs; an *attribute* it names
    was, until this, checked against nothing it could see. And the failure is
    silent in the worst direction: a missing attribute always fails
    (`app.attributes`), so a plausible guess — `noise_cancelling` where the
    catalogue records `anc` — eliminates every product rather than raising.

    A description rather than an enum, because the values matter as much as the
    keys and because the three predicate forms (`minimum_`, `maximum_`, bare)
    are not enumerable. The schema still validates the *shape*; this only makes
    the choice informed.

    Kept to one line per category, to names alone, and to
    `MAX_ATTRIBUTE_NAMES_PER_CATEGORY` of them: this is sent on every turn, and
    L§27 warns against paying for context nobody uses. The cap is not a nicety.
    Groq refuses a request over 8,000 tokens outright, and on a 200-product
    catalogue the uncapped vocabulary ran to 484 names — enough, with the system
    prompt and the tool payload, to make the second leg of a turn fail with a
    413 after the search had already succeeded. The repository orders the names
    by how many products in the category carry them, so what survives the cut is
    what a buyer is most likely to ask to filter on; a name only one product
    records is a fact about that product rather than a filter.
    """
    prop = (schema.get("properties") or {}).get("attributes")
    if prop is None:
        return
    lines = "; ".join(
        f"{slug}: {', '.join(names[:MAX_ATTRIBUTE_NAMES_PER_CATEGORY])}"
        for slug, names in vocabulary.items()
        if names
    )
    if not lines:
        return
    existing = prop.get("description", "")
    prop["description"] = f"{existing} Attribute names by category — {lines}.".strip()


TOOL_SCHEMAS: dict[str, ToolDefinition] = {
    definition.name: definition
    for definition in (
        ToolDefinition(
            name="search_catalog",
            description=(
                "Search the merchant catalog using the buyer's stated requirements. "
                "Returns one row per sellable variant, each with its authoritative "
                "price, SKU and coarse stock status. This is the only way to learn "
                "what the merchant sells; nothing in your training data applies."
            ),
            tier=RiskTier.LOW,
            arguments=SearchCatalogArgs,
            milestone="M5",
        ),
        ToolDefinition(
            name="get_product",
            description=(
                "Retrieve one product and its variants by product id or SKU. Use it "
                "to confirm details before proposing a cart. An id or SKU that does "
                "not exist returns an error — it is never a product you may describe."
            ),
            tier=RiskTier.LOW,
            arguments=GetProductArgs,
            milestone="M5",
        ),
        ToolDefinition(
            name="get_compatible_products",
            description=(
                "Find products compatible with a device the buyer named, using the "
                "merchant's recorded compatibility rules. Pass the buyer's own words "
                "for the device. If the device cannot be identified you will be told, "
                "and you should ask the buyer which model they have rather than guess."
            ),
            tier=RiskTier.LOW,
            arguments=GetCompatibleProductsArgs,
            milestone="M5",
        ),
        ToolDefinition(
            name="check_inventory",
            description=(
                "Check whether a specific quantity of a variant is currently "
                "available. Never state that something is in stock without calling "
                "this and being told so."
            ),
            tier=RiskTier.LOW,
            arguments=CheckInventoryArgs,
            milestone="M5",
        ),
        ToolDefinition(
            name="get_upsell_candidates",
            description=(
                "Get accessories the merchant has explicitly related to a product, "
                "already filtered to those compatible with the buyer's device and in "
                "stock. Offer these only when they genuinely suit the purchase."
            ),
            tier=RiskTier.LOW,
            arguments=GetUpsellCandidatesArgs,
            milestone="M5",
        ),
        ToolDefinition(
            name="propose_cart",
            description=(
                "Propose a cart of variants and quantities for the buyer to review. "
                "You supply only variant ids and quantities: the application looks up "
                "every price and computes the total itself. This does not purchase "
                "anything and does not charge anyone."
            ),
            tier=RiskTier.MEDIUM,
            arguments=ProposeCartArgs,
            milestone="M7",
        ),
        ToolDefinition(
            name="request_approval",
            description=(
                "Present the current cart and its authoritative total to the buyer and "
                "ask them to approve it. This records that approval was requested. It "
                "does not approve anything — only the buyer can do that, in the "
                "application."
            ),
            tier=RiskTier.MEDIUM,
            arguments=RequestApprovalArgs,
            milestone="M8",
        ),
        ToolDefinition(
            name="get_order_status",
            description=(
                "Look up the current status of an order the buyer has already placed. "
                "Payment status comes from the payment provider's verified webhook, "
                "never from this conversation."
            ),
            tier=RiskTier.LOW,
            arguments=GetOrderStatusArgs,
            milestone="M11",
        ),
    )
}

#: Sorted, so the payload sent to the model is byte-stable between runs.
EXPOSED_TOOL_NAMES: tuple[str, ...] = tuple(sorted(TOOL_SCHEMAS))

#: The tools whose handlers exist once M5 lands — the read-only agent. A registry
#: may expose this subset before the cart and order milestones arrive.
READ_ONLY_TOOL_NAMES: tuple[str, ...] = (
    "search_catalog",
    "get_product",
    "get_compatible_products",
    "check_inventory",
    "get_upsell_candidates",
)


def build_tool_definitions(
    *,
    category_slugs: Sequence[str] = (),
    attribute_vocabulary: Mapping[str, Sequence[str]] | None = None,
    names: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """The tool payload for one conversation, in Anthropic's format.

    `category_slugs` come from the merchant's actual categories and are injected
    into every `category` parameter as an enum. `attribute_vocabulary` is the
    same idea for `attributes`: the names each category actually uses, so a
    requirement can be stated as a filter instead of guessed at. Both are read
    from the database at call time, so neither can drift from the catalog the
    way a hard-coded list would.

    `names` selects a subset — which is how M5 exposes the read-only tools
    before the cart exists — and is validated, so a typo cannot silently offer
    nothing.
    """
    selected = EXPOSED_TOOL_NAMES if names is None else tuple(names)
    unknown = [name for name in selected if name not in TOOL_SCHEMAS]
    if unknown:
        raise KeyError(f"unknown tool(s): {sorted(unknown)}")
    return [
        TOOL_SCHEMAS[name].to_tool_definition(
            category_slugs=category_slugs,
            attribute_vocabulary=attribute_vocabulary,
        )
        for name in selected
    ]


def validate_tool_arguments(name: str, arguments: dict[str, Any]) -> BaseModel:
    """Stage two of the A§19 pipeline: schema validation.

    Raises `LLMOutputError` for an unknown tool or invalid arguments. It never
    returns partially-valid arguments and never repairs them — A§19 is explicit
    that raw model output is not executed, and a "helpful" coercion is exactly
    how a malformed call becomes a real one.

    A call to a forbidden tool is reported as forbidden rather than as unknown,
    so the attempt is visible in logs instead of blending into typos.
    """
    if name in FORBIDDEN_TOOL_NAMES:
        raise LLMOutputError(f"tool {name!r} is not available to the model (ADR-009)")
    definition = TOOL_SCHEMAS.get(name)
    if definition is None:
        raise LLMOutputError(f"unknown tool {name!r}")
    try:
        return definition.arguments.model_validate(arguments)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in exc.errors()
        )
        raise LLMOutputError(f"invalid arguments for {name!r}: {problems}") from exc
