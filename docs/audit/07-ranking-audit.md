# 07 — Ranking / Recommendation Audit

## Purity — verified structurally

`app/ranking/` must be pure: no session, no query, no clock, no randomness, no model. An AST scan of
every module for imports of `sqlalchemy`, `datetime`, `random`, `time`, `httpx`, `requests`,
`app.llm` and `app.agent` found:

```
impurity violations: 0
=> app/ranking is pure: no DB, clock, randomness, or model
```

This is what makes the R§10 exit test an ordinary unit test, and why 880 of the backend tests need no
database at all. `RecommendationService` is the only M3-adjacent code that opens a query.

## The exit criterion reproduces exactly

ADR-004's exit condition is the specification's own worked example, and it is exact:

```python
assert aerocase.final_score == Decimal("0.796800")   # spec says 0.7968
assert shieldcase.final_score == Decimal("0.786800") # spec says 0.7868
```

Scores are `Decimal` quantized to six places, because a `float` total is not reproducible across
platforms and RULE 8 requires determinism.

## Required scenarios — all ten covered

The audit checked each scenario against named tests in the 136-test ranking suite.

| # | Scenario | Covered by | Status |
| --- | --- | --- | --- |
| 1 | Compatible product | `test_compatibility_is_binary`, `test_compatibility_is_resolved_before_ranking_never_inside_it` | ✅ |
| 2 | Incompatible product | `test_a_cheaper_incompatible_product_is_never_a_candidate`, `test_an_incompatible_product_is_never_offered_as_an_alternative` | ✅ |
| 3 | Out-of-stock product | `test_an_out_of_stock_variant_is_removed`, `test_a_variant_with_no_inventory_row_is_removed_not_assumed_available`, `test_insufficient_stock_for_the_requested_quantity_is_removed` | ✅ |
| 4 | Above budget | `test_a_product_over_budget_is_removed_not_ranked_low`, `test_an_over_budget_product_becomes_a_labelled_alternative` | ✅ |
| 5 | Below budget | `test_cheaper_is_always_better`, `test_a_product_exactly_at_the_budget_survives` | ✅ |
| 6 | Equal scores | `test_a_score_tie_breaks_on_the_lower_price`, `test_a_price_tie_breaks_on_the_sku`, `test_a_tie_on_score_breaks_on_the_lower_total` | ✅ |
| 7 | Missing preference | `test_a_preference_never_eliminates`, `test_a_product_with_no_tags_scores_zero_rather_than_dividing_by_zero` | ✅ |
| 8 | Missing budget | `test_degenerate_candidate_sets_have_no_denominator`, `test_a_stated_budget_is_the_denominator` | ✅ |
| 9 | Zero / boundary budget | `test_a_product_priced_exactly_at_the_budget_scores_zero` | ✅ |
| 10 | Multiple merchants | `test_another_merchants_variant_is_removed`, `test_merchant_scoping_excludes_rather_than_reorders` | ✅ |

Additionally covered: inactive products and variants, missing attributes, multiword tag matching,
negative weights rejected at construction, profiles that do not sum to one rejected, unknown profile
names failing loudly rather than falling back, and every failure recorded rather than only the first.

## Hard constraints eliminate; they never score

`apply_hard_constraints` **takes no profile argument at all**. That signature is the structural form
of ADR-005's promise: there is no weight configuration in which a cheap incompatible product can
outrank a compatible one. Merchant, activity, category, budget, compatibility, required
specification and inventory are filters applied *before* ranking.

Every candidate is evaluated against every constraint rather than stopped at the first failure,
because deciding whether a rejection is an honest *alternative* requires knowing it failed only a
relaxable one.

**Only `BUDGET` and `REQUIRED_SPECIFICATION` are relaxable.** Compatibility never is (a case for a
different phone is a wrong answer, not a lesser one); inventory never is (RULE 5 — an alternative
nobody can buy is not an alternative); category never is. Alternatives are re-scored with the budget
removed, or the clamp would flatten them all to zero and lose their order.

## Zero-division and degenerate cases

`price_denominator` returns `None` for degenerate sets — empty, a single candidate, all one price, or
a maximum of zero — and `price_score` answers `1.0` for that branch. This governs the *unbudgeted*
denominator only; a stated budget always uses R§8's formula, so a product priced exactly at the
budget scores `0.0` on purpose.

A product with no tags scores zero rather than dividing by zero. A missing attribute always fails
rather than being treated as absent-therefore-acceptable, and `app/attributes.py` is the single
implementation of "attribute satisfies expectation" shared by compatibility rules, the
required-specification constraint and the preference scorer.

**A deliberate trap worth knowing:** no stated preferences scores `0.0`, not `1.0` (ADR-004, A4).
Ordering is unaffected — a constant cannot reorder anything — but no candidate can then exceed the
remaining weights, so anyone writing a threshold against `FinalScore` must know this.

## Determinism and tie-breaking

Sorting is `(-final_score, price, sku)` — three keys, because scores tie often on a small catalogue
and prices tie across colours of one product. Both tie-break levels have dedicated tests.

## Weights

All weights live only in `app/ranking/weights.py` (RULE 14). No scorer, aggregator or service
contains a number; they multiply by what a `WeightProfile` says. Profiles are validated to sum to
exactly `1`, and `RANKING_PROFILE` is validated at startup so a typo fails loudly instead of silently
reordering every result.

**The model may pick a profile by name; it may never emit a weight.** Verified: no tool schema
accepts a weight or a score.

## The model never determines ranking — verified

| Check | Result |
| --- | --- |
| Does any tool accept a price, score or weight? | **No** — zero such parameters in `tool_schemas.py` |
| Does `app/ranking/` import the model layer? | **No** — AST verified |
| Is the `reason` text model-authored? | **No** — the engine emits `BEST_OVERALL`, `BEST_PRICE`, `CLOSEST_MATCH` |
| Runtime confirmation | Live turn returned reasons "Best overall", "Best price", "Closest match to your requirements" — engine strings, not prose |

## Runtime verification

A live turn ("a case for iPhone 16 under 1500") produced, deterministically:

| Rank | Product | Price | Stock | Reason |
| --- | --- | --- | --- | --- |
| 1 | AeroCase Pro (Black) | ₹999.00 | IN_STOCK | Best overall |
| 2 | AeroCase Pro (Blue) | ₹999.00 | IN_STOCK | Best price |
| 3 | ShieldCase Premium (Black) | ₹1,299.00 | LOW_STOCK | Closest match to your requirements |

The ranks-1-and-2 price tie broke on SKU, exactly as the tie-break rule specifies. Backend log:
`recommendation computed alternatives=0 candidates=3 label='phone_case' outcome='EXACT_MATCH'`.

## Verdict

**FULL.** 136 tests, all ten required scenarios covered, purity structurally enforced, the
specification's worked example reproduced to six decimal places, and live output consistent with the
deterministic rules. No defects found.
