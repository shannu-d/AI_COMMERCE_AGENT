# ADR-021 — The catalogue is category-agnostic; clothing and furniture need no schema change

**Status:** Accepted · **Date:** 2026-09-04 · **Supersedes:** nothing · **Superseded by:** nothing

Relates to ADR-002 (PostgreSQL as the source of product truth), ADR-004 / ADR-005 (deterministic
ranking, hard constraints), ADR-009 (agent tool boundaries), and `architecture.md` D§5–D§13, D§26,
R§18.

---

## Context

The project owner asked to (a) expand the product catalogue significantly and (b) add two new
top-level ecommerce families — **Clothing** and **Furniture** — while preserving every existing
electronics category and product.

Two questions had to be answered from the actual schema and services, not assumed:

1. **Can the existing product model represent clothing and furniture cleanly, or is it
   electronics-specific?**
2. **Does anything in the ranking, filtering, tool or seed layer hard-code electronics attributes?**

The audit (Phase A) found:

- `products.attributes` and `product_variants.attributes` are **`JSONB`**, and the model docstring
  states the reason explicitly (D§7, D§26): *"product characteristics vary by industry and hundreds
  of nullable columns would be a bad schema."*
- `categories` is a merchant-scoped hierarchical tree with free-form canonical-token slugs.
- `app/ranking/scorers.py` and `app/ranking/filters.py` score and eliminate on `category_match`,
  `attribute_match` (a generic dict comparison via `app/attributes.py`), `text_match`, `tag_match`,
  `price_score`, `preference_score`, budget and inventory. **No attribute key is hard-coded.**
- `SearchCatalogArgs.attributes` is `dict[str, str | int | bool]`; its docstring example is
  literally `"material": "leather"`.
- Compatibility (`compatibility_targets` / `compatibility_rules`) is **optional** — a product with
  no rules is simply not compatibility-constrained, and `RecommendationService` skips the whole
  compatibility stage when `requirement.compatibility_target is None`.
- The seed validator (`app/seed/schema.py`) already accepts `attributes: dict[str, Any]` and
  `compatibility: []` by default.

## Decision

**Clothing and furniture are added as data only. No migration, no new table, no schema change.**

Specifically:

- **New categories are rows.** Two new top-level trees — `clothing` (→ `t_shirt`, `shirt`, `jeans`,
  `hoodie`, `jacket`, `dress`) and `furniture` (→ `chair`, `table`, `desk`, `sofa`, `bed`,
  `shelving`) — added to `catalog.json`. The electronics tree is untouched.
- **New products use the existing product / variant / JSONB-attribute model.** Clothing carries
  `material` / `fit` / `gender` at product level and `color` / `size` at variant level; furniture
  carries `material` / `room` / `assembly_required` / dimensions. All are ordinary attribute keys.
  Neither family carries a compatibility rule — compatibility stays an electronics concept.
- **`clothing_products` / `furniture_products` tables were rejected.** They would fragment the
  single catalogue query, duplicate every merchant-scoping constraint, and undo the deliberate
  choice D§7/D§26 made. The ranking engine would need a per-type branch it currently does not have.
- **A `category_attributes` / per-category-schema table was rejected for the MVP.** The database
  does not validate attribute shape by category and does not need to — the ranker matches whatever
  keys are present. The merchant dashboard's product form instead carries a **frontend-only
  attribute template per category slug** (`frontend/src/features/merchant/attributeTemplates.ts`):
  it decides which fields the editor *offers*, and still submits a plain `attributes` object.
- **The catalogue grows past R§18's "30–36 SKU prototype" scope**, deliberately, at the owner's
  request. See "Deviation from R§18" below.
- **The merchant display name becomes `EASY BUY`** (the storefront brand). `DEFAULT_MERCHANT_ID` is
  still `uuid5(.../merchant/circuitcraft)` and is **unchanged** — only `merchants.name` and
  `settings.default_merchant_name` change. The seed's electronics rows still say `brand:
  "CircuitCraft"` where the original prototype did; new own-brand products say `EASY BUY`.

### The shipped numbers

| Family | Categories | Products | SKUs |
| --- | --- | --- | --- |
| Electronics (unchanged prototype) | 10 | 21 | 37 |
| Clothing (new) | 6 (+`clothing`) | 16 | 147 |
| Furniture (new) | 6 (+`furniture`) | 14 | 37 |
| **Total** | **24** | **51** | **216** |

The dataset keeps every property the ADR-005 tests depend on: out-of-stock variants in all three
families, products either side of common budget lines, `color` × `size` variant axes, and — in
electronics only — the `iphone_15` exclusion and `pixel_9` no-match paths.

## Deviation from `architecture.md` R§18

R§18 scopes the prototype catalogue to "30–36 SKUs". The expansion to ~216 SKUs across three
families is a **deliberate departure**, made because the project owner explicitly asked for a
larger multi-category catalogue that can exercise the agent and the new merchant dashboard.
`architecture.md` is never edited; the departure is recorded here and in
`docs/notes/deviations.md` (D9). `tests/seed/test_catalog_seed.py` was updated: the old
`test_sku_count_is_within_the_range_the_specification_describes` is replaced by
`test_the_catalog_is_the_expanded_multi_category_storefront` plus
`test_the_original_electronics_prototype_is_preserved`, which pins every architecture.md
worked-example row (AeroCase Pro ₹999.00 / CHARGER-30W ₹1499.00 / SPRO-IP16-1 ₹299.00 /
ShieldCase Premium ₹1299.00 stock 5) so those can never be edited by accident.

## Consequences

**Positive.** The agent answers clothing and furniture queries through the *same* `search_catalog`
tool, the *same* ranking engine and the *same* services, with zero new code on the read path
(verified live: "black t-shirt under ₹1500 size M", "wooden study desk under ₹8000",
"sofa under ₹30000" all return grounded, correctly-ranked results). The schema stays the one D§7
deliberately chose. Adding a fourth family later is again data only.

**Negative, and accepted.** `/api/products` and `/api/merchant/products` are now larger than a
page, so two catalogue-API tests that assumed "the whole catalogue fits in one 60-row response"
were rewritten to assert page size and per-page monotonicity instead. The `catalog.json` file grew
from ~460 to ~2200 lines; it was regenerated by a one-shot authoring script (kept in the session
scratchpad, not committed) and the file remains the reviewed source of truth.

**Unchanged.** PostgreSQL owns product facts. The ranking engine is still pure and category-blind.
`GROQ_API_KEY` is not in the frontend. No tool accepts a price. Compatibility is still the only
place the ADR-003 pipeline runs, and clothing/furniture never reach it.

## Verification

- Seed validates: `python -m app.seed.circuitcraft --validate-only` → 51 products, 216 SKUs, 24
  categories.
- Backend suite **1344 passed** with a database (was 1311 before this work); the seed / catalog /
  ranking / recommendation-service tests all pass against the expanded catalogue.
- Live: the deterministic `RecommendationService` returns correctly-ranked clothing and furniture;
  a real Groq turn ("wooden study desk under 8000") returned three grounded desk variants with a
  concise reply (ADR-020) and no fabricated facts.
