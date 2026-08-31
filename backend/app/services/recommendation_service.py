"""Recommendation Service — where the ranking engine meets PostgreSQL.

`app.ranking` is pure: it filters and scores whatever candidate set it is
handed. This service is what hands it one. It is the only place in M3 that
opens a query, and it exists so that the ranker never has to.

R§20 divides the responsibilities and this respects the division exactly:

| Service | Owns |
| --- | --- |
| Catalog | product facts, authoritative price |
| Compatibility | whether a product fits the buyer's device |
| Inventory | current stock |
| Ranking | normalized scores, weights, Top-K |

None of them owns more than one of those, and the model owns none of them.

**What this service will not do.** It will not resolve a device phrase.
`ProductRequirement.compatibility_target` is a `ResolvedTarget`, so resolution —
and the clarification an unresolvable phrase demands (ADR-003) — happens before
a requirement exists. Burying resolution here would turn "I did not understand
your phone" into "we have nothing for you", which is the exact confusion ADR-003
was written to prevent.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain import (
    CrossSellCandidate,
    MultiProductRecommendation,
    ProductCombination,
    ProductRequirement,
    Recommendation,
    ResolvedTarget,
    StockView,
    VariantView,
)
from app.ranking import combine, recommend
from app.ranking.weights import WeightProfile, get_profile
from app.repositories.variant_repository import VariantQuery
from app.services.catalog_service import CatalogService
from app.services.compatibility_service import CompatibilityService
from app.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)

__all__ = ["RecommendationService"]

#: Relationship types that R§15 treats as an offer to make alongside a purchase.
CROSS_SELL_RELATIONSHIP_TYPES: tuple[str, ...] = ("cross_sell", "bundle")


class RecommendationService:
    """Turns a `ProductRequirement` into ranked, grounded recommendations."""

    def __init__(
        self,
        session: Session,
        *,
        profile: WeightProfile | str | None = None,
        top_k: int | None = None,
    ) -> None:
        settings = get_settings()
        self._catalog = CatalogService(session)
        self._compatibility = CompatibilityService(session)
        self._inventory = InventoryService(session)
        self._profile = (
            profile
            if isinstance(profile, WeightProfile)
            else get_profile(profile or settings.ranking_profile)
        )
        self._top_k = top_k if top_k is not None else settings.ranking_top_k

    @property
    def profile(self) -> WeightProfile:
        return self._profile

    # -- single-product requests --------------------------------------------

    def recommend(
        self,
        merchant_id: uuid.UUID,
        requirement: ProductRequirement,
        *,
        profile: WeightProfile | str | None = None,
        top_k: int | None = None,
    ) -> Recommendation:
        """The full pipeline for one requested product type (R§2, R§16)."""
        candidates = self._candidates(merchant_id, requirement)
        stock = self._stock(merchant_id, candidates)
        compatible = self._compatible_product_ids(merchant_id, requirement, candidates)

        result = recommend(
            candidates,
            requirement,
            merchant_id=merchant_id,
            stock=stock,
            compatible_product_ids=compatible,
            profile=self._resolve_profile(profile),
            top_k=self._top_k if top_k is None else top_k,
        )
        logger.info(
            "recommendation computed",
            extra={
                "label": requirement.label,
                "outcome": result.outcome.value,
                "candidates": len(result.candidates),
                "alternatives": len(result.alternatives),
                "profile": result.profile_name,
            },
        )
        return result

    def recommend_many(
        self,
        merchant_id: uuid.UUID,
        requirements: Sequence[ProductRequirement],
        *,
        total_budget: Decimal | None = None,
        profile: WeightProfile | str | None = None,
        top_k: int | None = None,
    ) -> MultiProductRecommendation:
        """R§13: one pipeline per product type, then one combination for the total.

        The per-type recommendations are returned whole alongside the
        combination, so a request that cannot be satisfied as a set still shows
        the buyer what does exist for each half of it.
        """
        results = tuple(
            self.recommend(merchant_id, requirement, profile=profile, top_k=top_k)
            for requirement in requirements
        )
        combination: ProductCombination = combine(results, total_budget=total_budget)
        return MultiProductRecommendation(recommendations=results, combination=combination)

    # -- cross-sell ----------------------------------------------------------

    def cross_sell_candidates(
        self,
        merchant_id: uuid.UUID,
        product_id: uuid.UUID,
        *,
        target: ResolvedTarget | None = None,
        quantity: int = 1,
        limit: int = 3,
        relationship_types: Sequence[str] = CROSS_SELL_RELATIONSHIP_TYPES,
    ) -> list[CrossSellCandidate]:
        """R§15's cross-sell pipeline, with every one of its checks applied.

        R§15 lists them: the product exists, it is compatible with the device, it
        is in stock, it has a price, and it is relevant to the current purchase.
        The last is what the `product_relationships` row *is* — which is why this
        starts from a relationship and filters, rather than searching the catalog
        for something to add. R§15's closing line is the rule: "The system must
        not recommend random products merely because they increase revenue."

        One variant per related product: the cheapest available one, since the
        offer is "add the compatible screen protector for ₹299" and that price
        has to be a real, purchasable SKU.
        """
        if quantity < 1:
            raise ValueError("quantity must be at least 1")

        related = self._catalog.get_related_products(
            merchant_id, product_id, relationship_types=relationship_types
        )
        if not related:
            return []

        variants = self._catalog.get_variants_for_products(
            merchant_id, [item.product.id for item in related]
        )
        if target is not None:
            variants = self._compatibility.filter_variants(merchant_id, variants, target)
        if not variants:
            return []

        stock = self._inventory.get_stock_map(merchant_id, [variant.id for variant in variants])
        # Cheapest purchasable variant per product; `search`/`for_products`
        # already order by (price, sku), so the first hit is the cheapest and the
        # tie between equal prices is broken the same way every time.
        cheapest: dict[uuid.UUID, VariantView] = {}
        for variant in sorted(variants, key=lambda v: (v.price, v.sku)):
            if stock[variant.id].available_quantity < quantity:
                continue
            cheapest.setdefault(variant.product_id, variant)

        candidates = [
            CrossSellCandidate(
                product=item.product,
                variant=cheapest[item.product.id],
                relationship_type=item.relationship_type,
                priority=item.priority,
                stock_status=stock[cheapest[item.product.id].id].status,
            )
            for item in related
            if item.product.id in cheapest
        ]
        return candidates[:limit]

    # -- internals -----------------------------------------------------------

    def _resolve_profile(self, profile: WeightProfile | str | None) -> WeightProfile:
        if profile is None:
            return self._profile
        return profile if isinstance(profile, WeightProfile) else get_profile(profile)

    def _candidates(
        self, merchant_id: uuid.UUID, requirement: ProductRequirement
    ) -> list[VariantView]:
        """Fetch the candidate set for a requirement.

        Only the category is pushed into SQL, and deliberately so:

        * **budget is not**, because a product just over the ceiling is exactly
          what an honest alternative is made of (ADR-005). Filtering it away in
          the query would leave the no-match path with nothing real to offer;
        * **text is not**, because free text is a relevance *signal* (R§9), not
          a hard constraint. Eliminating on it would silently hide products
          whose description happens to use different words;
        * **attributes are not**, because the eliminating ones are checked by
          `check_required_specification` against merged product-and-variant
          attributes, and the rest are preferences that must never eliminate.

        The cost of loading a category instead of a filtered slice is a few
        dozen rows on a 32-SKU catalog. At a scale where that stops being true,
        the budget filter can move into SQL for the match query while a second
        query supplies alternatives.
        """
        return self._catalog.search(
            merchant_id, VariantQuery(category_slug=requirement.category_slug)
        )

    def _stock(
        self, merchant_id: uuid.UUID, candidates: Sequence[VariantView]
    ) -> dict[uuid.UUID, StockView]:
        return self._inventory.get_stock_map(merchant_id, [variant.id for variant in candidates])

    def _compatible_product_ids(
        self,
        merchant_id: uuid.UUID,
        requirement: ProductRequirement,
        candidates: Sequence[VariantView],
    ) -> set[uuid.UUID] | None:
        """Compatible product ids, or `None` when no device was stated.

        `None` and `set()` mean different things and the difference matters: the
        first is "the buyer named no device", the second is "the buyer named a
        device and nothing in the catalog fits it". The second is R§14's
        legitimate no-match — `pixel_9` is seeded precisely to exercise it — and
        it must not be flattened into "compatibility does not apply".
        """
        if requirement.compatibility_target is None:
            return None
        return self._compatibility.compatible_product_ids(
            merchant_id,
            requirement.compatibility_target,
            candidate_product_ids=[variant.product_id for variant in candidates],
        )
