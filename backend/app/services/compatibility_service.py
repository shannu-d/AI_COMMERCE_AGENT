"""Compatibility Service — resolution and validation (ADR-003).

The pipeline, in full:

    user text → [LLM] a phrase ("iPhone 16")
              → normalize_token()            deterministic, pure
              → resolve against compatibility_targets
              → canonical identifier ("iphone_16")
              → compatibility_rules
              → compatible products

The model contributes the first arrow only. It supplies a human-readable phrase;
everything after that is a database lookup. Any canonical-looking identifier the
model volunteers is treated as free text and re-resolved from scratch, because a
plausible-but-wrong identifier (`iphone_15` for an iPhone 16 buyer) is a valid
token and a completely wrong answer.

**Resolution never guesses.** No substring matching, no nearest match, no
"probably". An unresolvable or ambiguous phrase returns `UnresolvedTarget`, and
the caller asks the buyer (R§5, L§18).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.attributes import attributes_satisfy
from app.canonical import normalize_token
from app.db.models import COMPATIBILITY_TARGET_KINDS
from app.domain import (
    CompatibilityTargetView,
    ResolutionFailure,
    ResolvedTarget,
    TargetResolution,
    UnresolvedTarget,
    VariantView,
)
from app.repositories import CompatibilityRepository
from app.services._mapping import to_compatibility_target_view

logger = logging.getLogger(__name__)

#: How a resolved target's kind maps onto the rule types that can match it.
#:
#: ADR-003: `compatibility_targets.target_type` says what an identifier *is*;
#: `compatibility_rules.target_type` says how a product *relates* to it, and
#: includes the broader `device` the specification uses for chargers (D§14). A
#: phone therefore matches both `phone_model` rules (cases) and `device` rules
#: (chargers), which is what lets the specification's own examples coexist.
RULE_TYPE_EXPANSION: dict[str, tuple[str, ...]] = {
    "phone_model": ("phone_model", "device"),
    "laptop_model": ("laptop_model", "device"),
    "device_port": ("device_port",),
}


class CompatibilityService:
    """Resolves device phrases and validates compatibility against the catalog."""

    def __init__(self, session: Session) -> None:
        self._repository = CompatibilityRepository(session)

    # -- resolution ----------------------------------------------------------

    def resolve_target(self, text: str, *, target_type: str | None = None) -> TargetResolution:
        """Turn a device phrase into a canonical identifier, or refuse to.

        `target_type` optionally narrows the search to one kind of thing, for
        the case where the caller already knows it is looking for a phone.

        Exactly one active match resolves. Zero is `UNKNOWN_TARGET`, more than
        one is `AMBIGUOUS_TARGET`, and both are returned for the caller to turn
        into a question.
        """
        normalized = normalize_token(text)

        if not normalized:
            return UnresolvedTarget(
                reason=ResolutionFailure.EMPTY,
                requested_text=text,
                normalized_text=normalized,
            )

        if target_type is not None and target_type not in COMPATIBILITY_TARGET_KINDS:
            # Not a value the vocabulary can hold, so nothing can match it.
            # Failing loudly here beats returning an empty result that reads as
            # "no such device".
            raise ValueError(
                f"target_type {target_type!r} is not one of {COMPATIBILITY_TARGET_KINDS}"
            )

        matches = self._repository.find_targets_by_token(normalized, target_type=target_type)

        if not matches:
            logger.info(
                "compatibility target unresolved",
                extra={"normalized": normalized, "target_type": target_type},
            )
            return UnresolvedTarget(
                reason=ResolutionFailure.UNKNOWN_TARGET,
                requested_text=text,
                normalized_text=normalized,
            )

        if len(matches) > 1:
            logger.info(
                "compatibility target ambiguous",
                extra={"normalized": normalized, "match_count": len(matches)},
            )
            return UnresolvedTarget(
                reason=ResolutionFailure.AMBIGUOUS_TARGET,
                requested_text=text,
                normalized_text=normalized,
                candidates=tuple(to_compatibility_target_view(m) for m in matches),
            )

        match = matches[0]
        return ResolvedTarget(
            canonical_identifier=match.canonical_identifier,
            target_type=match.target_type,
            display_name=match.display_name,
            requested_text=text,
            normalized_text=normalized,
        )

    def list_targets(self, *, target_type: str | None = None) -> list[CompatibilityTargetView]:
        """The known vocabulary — useful for offering the buyer real choices."""
        return [
            to_compatibility_target_view(t)
            for t in self._repository.list_targets(target_type=target_type)
        ]

    @staticmethod
    def rule_types_for(target_type: str) -> tuple[str, ...]:
        """Rule types that can match a target of this kind. See RULE_TYPE_EXPANSION."""
        return RULE_TYPE_EXPANSION.get(target_type, (target_type,))

    # -- validation ----------------------------------------------------------

    def compatible_product_ids(
        self,
        merchant_id: uuid.UUID,
        target: ResolvedTarget,
        *,
        candidate_product_ids: Sequence[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        """Products compatible with `target`, as a set of product ids.

        A set, not a list: a product can carry more than one rule matching the
        same identifier across the expanded rule types, and returning a list
        would let the same product appear twice in a candidate set and be
        counted twice downstream.

        Constraint predicates are evaluated here, so a rule whose predicates its
        own product does not satisfy does not make the product compatible.
        """
        rows = self._repository.rules_for_target(
            merchant_id,
            target.canonical_identifier,
            self.rule_types_for(target.target_type),
            product_ids=candidate_product_ids,
        )
        return {
            product.id
            for rule, product in rows
            if constraints_satisfied(product.attributes, rule.constraints)
        }

    def is_compatible(
        self, merchant_id: uuid.UUID, product_id: uuid.UUID, target: ResolvedTarget
    ) -> bool:
        return product_id in self.compatible_product_ids(
            merchant_id, target, candidate_product_ids=[product_id]
        )

    def filter_variants(
        self,
        merchant_id: uuid.UUID,
        variants: Iterable[VariantView],
        target: ResolvedTarget,
    ) -> list[VariantView]:
        """Keep only variants whose product is compatible with `target`.

        Compatibility attaches to the product; price and stock attach to the
        variant (D§13 vs D§8; ADR-003 open question B5). This keeps that
        separation explicit: the rule is checked at product level, the surviving
        rows are still variants, and their order is preserved so an upstream
        deterministic ordering survives the filter.

        Removal, never demotion — D§15 and R§17 RULE 4 forbid an incompatible
        product competing on price.
        """
        variants = list(variants)
        if not variants:
            return []
        compatible = self.compatible_product_ids(
            merchant_id, target, candidate_product_ids=[v.product_id for v in variants]
        )
        return [v for v in variants if v.product_id in compatible]


def constraints_satisfied(product_attributes: dict[str, Any], constraints: dict[str, Any]) -> bool:
    """Evaluate a rule's `constraints` against the product's own attributes.

    ADR-003 (open question B3): `constraints` are predicates on the product, not
    a description of what the target device needs. `{"minimum_wattage": 20,
    "fast_charge": true}` on a charger reads "compatible with this device
    provided this product supplies at least 20W and supports fast charging".

    The predicate forms and the missing-attribute rule live in `app.attributes`,
    because the ranking engine's required-specification constraint (ADR-005) has
    to evaluate exactly the same thing and the two must not drift apart. A
    missing attribute fails: a rule asserting a requirement the catalog cannot
    evidence is a rule that has not been shown to hold, and compatibility is the
    one constraint that is never relaxed to produce a result.
    """
    return attributes_satisfy(product_attributes, constraints)
