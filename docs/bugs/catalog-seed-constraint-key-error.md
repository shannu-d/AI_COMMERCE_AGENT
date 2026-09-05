# Bug — Incomplete Catalog Seed Replacement Caused Constraint KeyError and Broken Storefront Contracts

**Date:** September 5, 2026  
**Time:** 12:26:03 +0530

### Question

Does the active `backend/app/seed/data/catalog.json` satisfy all internal referential integrity rules and constraint predicates defined in `test_catalog_seed.py`?

### What I Expected

The seed catalog must be structurally sound without requiring a database:
1. Every constraint predicate declared in a product's compatibility rules must be satisfied by that product's own attributes.
2. The catalog must contain the multi-category families (`electronics`, `clothing`, `furniture`) specified in ADR-021.

### What Actually Happened

When running `pytest tests/seed/test_catalog_seed.py`, two tests failed immediately:

1. `test_every_constraint_predicate_is_satisfied_by_its_own_product`:
   ```
   tests\seed\test_catalog_seed.py:266: in test_every_constraint_predicate_is_satisfied_by_its_own_product
       assert product.attributes[attribute] >= expected, (product.slug, key)
   E   KeyError: 'wattage'
   ```
2. `test_the_catalog_is_the_expanded_multi_category_storefront`:
   ```
   tests\seed\test_catalog_seed.py:63: in test_the_catalog_is_the_expanded_multi_category_storefront
       assert {"electronics", "clothing", "furniture"} <= families
   E   AssertionError: assert {'clothing', 'furniture'} <= {'electronics', ...}
   ```

### Why Was This a Problem?

Any customer querying for chargers matching wattage constraints crashed the compatibility evaluator for wireless chargers. In addition, stripping clothing and furniture broke over 30 evaluation test cases in `backend/tests/evals/test_commerce_evals.py` that rely on those categories to test multi-category recommendations and cross-selling.

### Root Cause

In the working tree, an uncommitted data replacement modified `backend/app/seed/data/catalog.json`. In this modified file:
1. Three wireless charging products (`voltedge_wireless_pad`, `voltedge_wireless_stand`, and `voltedge_wireless_trio`) declared compatibility rules with constraints:
   ```json
   "constraints": {
     "minimum_wattage": 7,
     "fast_charge": true
   }
   ```
   However, their product `attributes` dictionary declared `"output_wattage": 15` instead of `"wattage"`. When `test_every_constraint_predicate_is_satisfied_by_its_own_product` checked `key.removeprefix("minimum_")`, it looked for `product.attributes["wattage"]`, raising `KeyError: 'wattage'`.
2. The catalog replacement purged all non-electronics categories, conflicting directly with ADR-021 and breaking tests in `test_catalog_seed.py` and `test_merchant_service.py`.

### Decision

Products with `minimum_wattage` compatibility constraints must define the matching `"wattage"` attribute in their `attributes` dictionary. Furthermore, any catalogue pruning must preserve the required multi-category taxonomy defined by ADR-021.

### Fix

1. Correct the attribute name in `voltedge_wireless_pad`, `voltedge_wireless_stand`, and `voltedge_wireless_trio` in `catalog.json` from `"output_wattage"` to `"wattage"`.
2. Maintain the committed 51-product / 216-SKU catalog from commit `1fba159` that satisfies all evaluation and storefront tests.

### Verification

Run `pytest tests/seed/test_catalog_seed.py`.
Directly reproduced:
- `test_every_constraint_predicate_is_satisfied_by_its_own_product` crashes with `KeyError: 'wattage'`.
- `test_the_catalog_is_the_expanded_multi_category_storefront` fails assertion.

### Result

FAIL / CONFIRMED BUG. Reproducible on the current working copy.

### Evidence

- Files: [`backend/app/seed/data/catalog.json`](file:///l:/AI_COMMERCE/backend/app/seed/data/catalog.json), [`backend/tests/seed/test_catalog_seed.py`](file:///l:/AI_COMMERCE/backend/tests/seed/test_catalog_seed.py)
- Reproduction command: `backend/.venv/Scripts/python.exe -m pytest tests/seed/test_catalog_seed.py -v`
