"""Compatibility targets and compatibility rules (ADR-003)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CompatibilityRule, CompatibilityTarget, Product


class CompatibilityRepository:
    """Reads from `compatibility_targets` and `compatibility_rules`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- the identifier vocabulary ------------------------------------------

    def find_targets_by_token(
        self, token: str, *, target_type: str | None = None
    ) -> list[CompatibilityTarget]:
        """Active targets whose canonical identifier or aliases match `token`.

        `aliases.contains([token])` compiles to `aliases @> ARRAY[token]`, which
        is what the GIN index on that column serves — `= ANY(aliases)` would not
        use it.

        Returns a list rather than one row on purpose: more than one match is
        ambiguity, and ADR-003 requires the caller to ask rather than pick.
        """
        statement = select(CompatibilityTarget).where(
            CompatibilityTarget.is_active.is_(True),
            (CompatibilityTarget.canonical_identifier == token)
            | (CompatibilityTarget.aliases.contains([token])),
        )
        if target_type is not None:
            statement = statement.where(CompatibilityTarget.target_type == target_type)
        return list(
            self._session.execute(
                statement.order_by(
                    CompatibilityTarget.target_type,
                    CompatibilityTarget.canonical_identifier,
                )
            )
            .scalars()
            .all()
        )

    def list_targets(self, *, target_type: str | None = None) -> list[CompatibilityTarget]:
        statement = select(CompatibilityTarget).where(CompatibilityTarget.is_active.is_(True))
        if target_type is not None:
            statement = statement.where(CompatibilityTarget.target_type == target_type)
        return list(
            self._session.execute(
                statement.order_by(
                    CompatibilityTarget.target_type,
                    CompatibilityTarget.canonical_identifier,
                )
            )
            .scalars()
            .all()
        )

    # -- the rules -----------------------------------------------------------

    def rules_for_target(
        self,
        merchant_id: uuid.UUID,
        identifier: str,
        rule_types: Sequence[str],
        *,
        product_ids: Sequence[uuid.UUID] | None = None,
        include_inactive: bool = False,
    ) -> list[tuple[CompatibilityRule, Product]]:
        """Compatibility rules matching a canonical identifier, with their product.

        `rule_types` is the type expansion from ADR-003: a phone resolves to
        rules of type `phone_model` *or* the broader `device` the specification
        uses for chargers. Passing it explicitly keeps that mapping in the
        service, where it is documented, rather than hidden in SQL.

        The product is returned alongside because a rule's `constraints` are
        predicates on **the product's own attributes** (ADR-003, open question
        B3), so the caller cannot evaluate compatibility without it. Fetching
        both in one query avoids a second round trip per candidate.

        `compatibility_rules` carries no `merchant_id`; scoping comes from the
        join to `products`.
        """
        statement = (
            select(CompatibilityRule, Product)
            .join(Product, Product.id == CompatibilityRule.product_id)
            .where(
                CompatibilityRule.target_identifier == identifier,
                CompatibilityRule.rule_type == "compatible",
                CompatibilityRule.target_type.in_(rule_types),
                Product.merchant_id == merchant_id,
            )
        )
        if not include_inactive:
            statement = statement.where(Product.is_active.is_(True))
        if product_ids is not None:
            if not product_ids:
                return []
            statement = statement.where(Product.id.in_(product_ids))

        return [
            (rule, product)
            for rule, product in self._session.execute(
                statement.order_by(Product.slug, CompatibilityRule.target_type)
            ).all()
        ]
