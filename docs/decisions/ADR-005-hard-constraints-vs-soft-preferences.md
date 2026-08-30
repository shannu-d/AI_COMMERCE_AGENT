# ADR-005: Hard Constraints versus Soft Preferences

**Status:** Accepted (2026-08-30)
**Milestone:** M3 (not implemented in this session); the schema that supports it lands in M1
**Source references:** `architecture.md` R§2 (steps 4–7), R§3, R§6, R§14, R§17 (RULE 3, 4, 5, 9, 15), R§19, D§15, D§29, D§30, D§32, D§33
**Related open questions:** A1, B4

## Context

The specification separates two questions and repeats the separation in both the ranking part and
the database part:

> HARD CONSTRAINTS answer: "Can this product be recommended at all?"
> SOFT PREFERENCES answer: "Among valid products, which one is better?"

D§15 gives the reason in the form of the failure it prevents:

> incompatible product − very cheap price − good rating = high recommendation score
> That would be unsafe and logically incorrect.

The pipeline is fixed (R§2, D§29): category → budget → compatibility → required specification →
inventory, all as filters, and only then scoring. R§17 RULE 3 and RULE 4 say the same thing as
rules.

## Problem

Which conditions are eliminating, in what order are they applied, what happens when the surviving
set is empty, and what stops a future change from quietly demoting a hard constraint into a heavily
weighted soft one?

## Decision

### The hard constraints

Applied as filters, before any score is computed. A candidate failing any of them is **removed**,
not penalized.

| # | Constraint | Rule |
| --- | --- | --- |
| 1 | **Existence and activity** | The product and variant exist, `products.is_active` and `product_variants.is_active` are both true. |
| 2 | **Merchant** | The variant belongs to the session's resolved merchant (ADR-002). Never taken from model output. |
| 3 | **Category** | When the buyer's intent names a product type, the product's category slug must match. |
| 4 | **Budget ceiling** | When a maximum budget is stated, `price <= max_budget`. Per-item for a single-product request; the combination search enforces the overall budget for multi-product requests (ADR-004). |
| 5 | **Compatibility** | When the intent carries a compatibility requirement, a matching `compatibility_rules` row must exist for the **resolved** canonical target (ADR-003), and any `constraints` predicates on that row must be satisfied by the product's attributes. |
| 6 | **Required specification** | Attributes the buyer stated as requirements rather than preferences — "must be fast charging", "must be USB-C" — are eliminating. |
| 7 | **Inventory** | `quantity - reserved_quantity >= requested_quantity`. |

Order matters only for cost, not for correctness: the filters commute, and they are applied
cheapest-and-most-eliminating first — merchant and activity in the SQL query, then category, budget,
compatibility, required specification, and inventory.

### Required specification versus preference

The distinction is drawn by the **intent schema**, not by heuristics over the buyer's phrasing. The
schema has two separate fields: `required_attributes` (eliminating) and `preferences` (scored). The
model populates both from the conversation; if it is unsure which a statement belongs in, the safe
placement is `preferences`, because over-filtering silently hides real products while
under-filtering merely reorders them. The specification supports this asymmetry: L§6 says optional
information "should not necessarily block the search".

### The soft preferences

Everything in R§3's soft list — colour, material, brand, feature match, relevance, price
attractiveness — is scored, never eliminating. Scoring is defined in ADR-004.

### Compatibility is never a score

`CompatibilityScore` is computed only under the `explainability_demo` weight profile, over an
already-compatible candidate set where it is uniformly `1.0`. Under every operational profile,
incompatible products **do not reach the scorer at all**. There is no configuration in which a cheap
incompatible product can outrank a compatible one.

### Inventory is never a score

Out-of-stock products are removed, never ranked low (RULE 5, D§33). Stock is re-checked at cart
time and again by the Policy Engine immediately before order creation (RULE 12, ADR-014) — the
filter at recommendation time is a courtesy to the buyer, not a guarantee.

### Reserved quantity

`available = quantity - reserved_quantity` (D§11). For the MVP, nothing writes `reserved_quantity`;
it stays at `0` (closes C5, partially). No reservation, release or expiry mechanism is implemented.
The residual risk is a narrow window between the Policy Engine's inventory re-check and order
creation, which is closed instead by performing both inside one transaction with
`SELECT ... FOR UPDATE` on the affected inventory rows (ADR-011, closes C6). Reservations would
close it more thoroughly and are recorded as deferred, not as forgotten.

### The empty result set

When no candidate survives, the system MUST NOT fabricate a product, relax compatibility, invent
availability, or silently widen the budget (R§14). It may offer **real catalog alternatives**, and
those must be labelled as alternatives rather than as matches. The response distinguishes three
outcomes explicitly, because they call for different next actions:

| Outcome | Meaning | Next action |
| --- | --- | --- |
| `EXACT_MATCH` | Candidates satisfied every hard constraint | Recommend |
| `NO_MATCH_WITH_ALTERNATIVES` | Nothing satisfied all constraints; real products satisfied a named subset | Offer, explicitly labelled, naming which constraint was not met |
| `NO_MATCH` | Nothing relevant exists | Say so; optionally ask whether a constraint can move |

Which constraint was relaxed to obtain an alternative is recorded in the structured response, so the
agent can say "no leather case under ₹500, but there is a leather case at ₹1,799" rather than
presenting it as a match. **Compatibility is the one constraint that is never relaxed to produce an
alternative** — a case for a different phone is not an alternative, it is a wrong answer.

## Alternatives considered

**Score everything, with very large weights on compatibility and stock.** Rejected explicitly by
D§15 and R§17 RULE 4. Large weights are still finite: enough soft advantage always outranks them,
and the resulting bug is silent.

**Treat budget as soft, so slightly-over-budget products can still be shown.** Rejected: R§8 and
D§30 make maximum budget a hard constraint. The `NO_MATCH_WITH_ALTERNATIVES` outcome covers the
legitimate case, and covers it honestly by labelling the product as over budget rather than by
quietly ranking it.

**Let the model decide which stated attributes are requirements.** Partly unavoidable — the model
populates the intent — but the *consequence* of that classification is fixed in code, and the schema
makes the classification explicit and inspectable rather than implicit in prose.

**Filter out-of-stock products only at checkout, showing them as recommendations.** Rejected by
RULE 5 and R§6: "Compatible + Out of Stock ≠ Purchasable".

## Consequences

**Enables.** The safety property the specification cares most about in the recommendation layer: an
incompatible or unavailable product cannot be recommended, whatever its other merits. It also makes
the filter stage independently testable — given a catalog and an intent, the surviving set is a pure
function.

**Forecloses.** Serendipitous recommendations. A buyer who asks for an iPhone 16 case will never be
shown an iPhone 15 case, even if it were the better product. That is the intended behaviour.

**Costs.** More empty result sets than a purely score-based system would produce, which makes the
no-match path a first-class feature rather than an afterthought — hence the three explicit outcomes.

## Implementation implications

- `app/ranking/filters.py` — one function per constraint, each independently unit-testable, plus a
  composed `apply_hard_constraints(candidates, intent) -> FilterResult` returning both the survivors
  and, for each rejected candidate, the constraint that rejected it. That rejection record is what
  makes the ranker explainable and the alternatives honest.
- The intent schema carries `required_attributes` and `preferences` as separate fields.
- `RecommendationResult` carries `outcome: EXACT_MATCH | NO_MATCH_WITH_ALTERNATIVES | NO_MATCH` and,
  for alternatives, `relaxed_constraints: list[str]`.
- **M1 obligation:** the seed catalog must make each filter individually testable — it contains an
  out-of-stock variant, an iPhone 15 case that must be excluded from iPhone 16 searches, products
  above and below the ₹1,500 budget line, and `pixel_9` as a resolvable device with no compatible
  products.
- **M3 tests:** one per constraint proving elimination rather than demotion, plus a regression test
  asserting that a cheap incompatible product never appears in ranked output under any weight
  profile.

## Status

**Accepted, not implemented.** M3. The catalog data that makes each constraint testable lands in M1.
