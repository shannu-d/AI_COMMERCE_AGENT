"""The four feature scorers. Pure functions: no I/O, no database, no model.

Every one returns a `Decimal` in `[0, 1]`, quantized to `SCORE_PRECISION`.
`Decimal` rather than `float` because R§17 RULE 8 requires the ranking to be
deterministic, and two candidates whose scores differ only in floating-point
noise would sort by that noise (ADR-004).

`architecture.md` specifies two of these four completely (`PreferenceScore` in
R§7, `PriceScore` in R§8), leaves `RelevanceScore` with signals but no formula
(R§9), and makes `CompatibilityScore` binary and normally unused (R§6). ADR-004
fixes the missing arithmetic and every degenerate case. Where a decision was
made rather than transcribed, the docstring says so.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from app.attributes import count_satisfied
from app.canonical import tokenize
from app.domain import ProductRequirement, VariantView

__all__ = [
    "ONE",
    "SCORE_PRECISION",
    "ZERO",
    "compatibility_score",
    "preference_score",
    "price_denominator",
    "price_score",
    "quantize_score",
    "relevance_score",
]

#: Six decimal places. Far finer than any weight, coarse enough that no two
#: genuinely equal scores can be separated by representation noise.
SCORE_PRECISION = Decimal("0.000001")

ZERO = Decimal("0")
ONE = Decimal("1")

# RelevanceScore sub-weights (ADR-004). Kept here rather than in `weights.py`
# because they are the internal shape of one feature score, not a tunable
# ranking policy: `weights.py` decides how much relevance matters, this decides
# what relevance *is*.
RELEVANCE_CATEGORY_WEIGHT = Decimal("0.40")
RELEVANCE_ATTRIBUTE_WEIGHT = Decimal("0.30")
RELEVANCE_TEXT_WEIGHT = Decimal("0.20")
RELEVANCE_TAG_WEIGHT = Decimal("0.10")


def quantize_score(value: Decimal) -> Decimal:
    """Round to `SCORE_PRECISION`, banker's rounding, clamped to `[0, 1]`.

    Clamping is a guard, not arithmetic: every formula below is already bounded,
    so a value outside the range would mean a bug, and a score of 1.4 silently
    outranking everything is a worse way to find out than a clamped one.
    """
    clamped = min(max(value, ZERO), ONE)
    return clamped.quantize(SCORE_PRECISION, rounding=ROUND_HALF_EVEN)


def preference_score(variant: VariantView, preferences: Mapping[str, Any]) -> Decimal:
    """R§7: `matched_preferences / total_preferences`.

    Matched against the variant's *merged* attributes — the product's, overlaid
    with the variant's own (D§27) — because "black" is a property of the variant
    while "leather" is a property of the product, and the buyer who asked for a
    black leather case stated one preference of each kind.

    **No preferences stated yields 0.0, not 1.0** (ADR-004, closing open
    question A4). The consequence is real and worth stating: the term then
    contributes nothing for every candidate, ordering is decided by the price
    and relevance weights alone, and no candidate can score above the sum of
    those weights. Ordering is unaffected, because a constant cannot reorder
    anything. `0.0` is chosen over `1.0` because "the buyer stated no
    preferences" is not evidence that every product matches them, and any future
    threshold written against `FinalScore` must account for the compression.
    """
    total = len(preferences)
    if total == 0:
        return ZERO
    matched = count_satisfied(variant.merged_attributes, preferences)
    return quantize_score(Decimal(matched) / Decimal(total))


def price_denominator(
    candidates: tuple[VariantView, ...] | list[VariantView], budget: Decimal | None
) -> Decimal | None:
    """The value `price_score` normalizes against, or `None` if there is none.

    A stated budget wins: it is the buyer's own scale, it is externally fixed,
    and the budget filter has already removed everything above it, so the ratio
    lands in `[0, 1]` (R§8).

    Without a budget, ADR-004 normalizes against the most expensive candidate in
    the set. That keeps the score comparable within one request and
    deterministic across repeats of it — the same request against the same
    catalog yields the same denominator — while making the term meaningless
    across two different requests, which is fine, because scores are never
    compared across requests.

    `None` is returned for the degenerate sets: an empty or single-candidate
    set, a set whose prices are all equal, or a maximum price of zero. In each
    the ratio carries no ordering information, and in the last it does not
    exist. `price_score` answers `1.0` for all of them (closing open question
    A3) rather than ranking a lone candidate at `0.0`.
    """
    if budget is not None:
        return budget
    prices = {candidate.price for candidate in candidates}
    if len(prices) < 2:
        return None
    highest = max(prices)
    return highest if highest > 0 else None


def price_score(price: Decimal, denominator: Decimal | None) -> Decimal:
    """R§8: `1 - (price / denominator)`. Cheaper is better.

    `denominator is None` is the degenerate case described in
    `price_denominator`, and scores `1.0`.

    A candidate priced exactly at the buyer's budget scores `0.0`. That is the
    specification's own formula and it is kept: the product is still returned,
    still ranked, and still purchasable — it simply earns nothing on price
    attractiveness, which is true.
    """
    if denominator is None:
        return ONE
    if denominator <= 0:
        return ONE
    return quantize_score(ONE - (price / denominator))


def relevance_score(variant: VariantView, requirement: ProductRequirement) -> Decimal:
    """The formula `architecture.md` never gives (R§9), fixed by ADR-004::

        0.40 x category_match + 0.30 x attribute_match
      + 0.20 x text_match     + 0.10 x tag_match

    R§9 lists the signals — category, name, description, tags, requested
    attributes, technical specification — and stops. It does require the result
    be "deterministic and based on structured catalog fields rather than
    allowing the LLM to assign arbitrary scores", which is the property this
    keeps.

    Each term is `0.0` when the buyer supplied nothing for it. That is the same
    choice as `preference_score` and for the same reason: silence is not
    evidence of a match. Because the absent term is then constant across every
    candidate, it cannot change the ordering — only the absolute score.
    """
    return quantize_score(
        RELEVANCE_CATEGORY_WEIGHT * category_match(variant, requirement.category_slug)
        + RELEVANCE_ATTRIBUTE_WEIGHT * attribute_match(variant, requirement.stated_attributes)
        + RELEVANCE_TEXT_WEIGHT * text_match(variant, requirement.query_text)
        + RELEVANCE_TAG_WEIGHT * tag_match(variant, requirement.query_text)
    )


def category_match(variant: VariantView, category_slug: str | None) -> Decimal:
    """`1.0` when the product sits in the requested category, else `0.0`.

    Category is normally already a hard constraint, so this is usually `1.0`
    among survivors. It stays in the formula for the candidate sets where it is
    not — the alternatives produced when a constraint was relaxed, and any later
    relaxed search.
    """
    if category_slug is None:
        return ZERO
    return ONE if variant.category_slug == category_slug else ZERO


def attribute_match(variant: VariantView, stated: Mapping[str, Any]) -> Decimal:
    """The fraction of the buyer's stated attributes the product satisfies.

    "Stated" is requirements *and* preferences (`ProductRequirement.
    stated_attributes`). Requirements alone would make the term a constant among
    survivors — they were all filtered on it — and a constant sub-weight is a
    dead sub-weight.
    """
    total = len(stated)
    if total == 0:
        return ZERO
    return Decimal(count_satisfied(variant.merged_attributes, stated)) / Decimal(total)


def text_match(variant: VariantView, query_text: str | None) -> Decimal:
    """Token overlap between the query and the product's name and description.

    `|query tokens intersect text tokens| / |query tokens|`, over normalized
    tokens (`app.canonical.tokenize`), against the union of the product name,
    the variant name and the description.

    There is no stop-word list and no stemming. Both would be policy invented
    here rather than derived from the specification, and neither is needed: the
    denominator is the same for every candidate in a request, so a chatty query
    dilutes every candidate identically and cannot reorder them. It lowers
    absolute scores, nothing else.
    """
    if not query_text:
        return ZERO
    query_tokens = set(tokenize(query_text))
    if not query_tokens:
        return ZERO
    text = " ".join(
        part for part in (variant.product_name, variant.name, variant.product_description) if part
    )
    document_tokens = set(tokenize(text))
    return Decimal(len(query_tokens & document_tokens)) / Decimal(len(query_tokens))


def tag_match(variant: VariantView, query_text: str | None) -> Decimal:
    """The fraction of the product's tags the query mentions.

    `|query tokens intersect tags| / |tags|`, `0.0` when the product has no tags
    (ADR-004). Dividing by the tag count rather than the query length is
    deliberate: it rewards a product whose tags are *mostly* about what was
    asked for, rather than one carrying twenty tags of which one happened to
    match.

    A multi-word tag counts when every one of its tokens appears in the query,
    which for a single-word tag is exactly the set intersection ADR-004
    describes. Without that, `fast_charging` could never match "fast charging",
    and the tag term would be dead for most of the catalog.
    """
    if not query_text or not variant.tags:
        return ZERO
    query_tokens = set(tokenize(query_text))
    if not query_tokens:
        return ZERO
    matched = sum(
        1 for tag in variant.tags if (tokens := set(tokenize(tag))) and tokens <= query_tokens
    )
    return Decimal(matched) / Decimal(len(variant.tags))


def compatibility_score(is_compatible: bool) -> Decimal:
    """R§6: binary, `1.0` or `0.0`.

    Emitted only under a weight profile that scores compatibility — in practice
    `explainability_demo` — and always `1.0` there, because incompatible
    products are removed before the scorer runs (ADR-005). There is no
    configuration in which this returns `0.0` for a ranked candidate; the
    function accepts the argument so the property is testable rather than
    assumed.
    """
    return ONE if is_compatible else ZERO
