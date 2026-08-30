# ADR-004: Deterministic Recommendation Scoring

**Status:** Accepted (2026-08-30)
**Milestone:** M3 (not implemented in this session)
**Source references:** `architecture.md` R§4, R§5, R§6, R§7, R§8, R§9, R§10, R§11, R§12, R§17 (RULE 8, 10, 11, 14, 15), R§19, D§31
**Related open questions:** A1, A2 (BLOCKING), A3 (BLOCKING), A4, A5, A6, A7, A8

## Context

The ranking system is the largest single part of `architecture.md` and the part with the most
unfinished arithmetic. It is unambiguous about the properties the ranker must have — deterministic
(RULE 8), explainable (RULE 10), reproducible (R§11), configuration-driven (RULE 14), evaluable
(RULE 15) — and it explicitly forbids the model from computing the score (R§11).

It is ambiguous about the arithmetic itself:

- **Two weight sets** for the same calculation. R§4 gives Compatibility 0.40 / Preference 0.30 /
  Price 0.20 / Relevance 0.10. R§19 gives Preference 0.50 / Price 0.30 / Relevance 0.20 *after*
  compatibility has been applied as a hard filter, and states that the hard-filter approach is
  preferred. R§6 adds that compatible products entering the ranking stage all have
  `CompatibilityScore = 1.0`, making the 0.40 weight "primarily a conceptual representation".
- **RelevanceScore has no formula at all.** R§9 lists six signals — category, name, description,
  tags, requested attributes, technical specification — and never says how they combine.
- **PriceScore divides by a value that may not exist.** `1 - (price / max_budget)` is undefined when
  the buyer states no budget, and yields exactly `0.0` when price equals budget.
- **PreferenceScore divides by zero.** `matched / total` when the buyer states no preferences.

## Problem

Fix every formula, every weight and every degenerate case, so that the same request against the same
catalog produces the same ordering, and so the ordering can be explained to a buyer without
consulting the model.

## Decision

### Weights

Compatibility is a **hard filter**, not a scoring dimension (R§19's stated preference; see ADR-005).
The overall weights are:

```
FinalScore(p) = 0.50 × PreferenceScore(p)
              + 0.30 × PriceScore(p)
              + 0.20 × RelevanceScore(p)
```

The R§4 four-weight variant is retained as a **named alternate configuration profile**
(`explainability_demo`) so the specification's other presentation stays runnable. It is not the
default, and it is never the profile used for a real recommendation. Weights live in configuration
(`app/ranking/weights.py`), never inline in scoring code (RULE 14).

### RelevanceScore

Not defined by the specification, and therefore defined here:

```
RelevanceScore(p) = 0.40 × category_match
                  + 0.30 × attribute_match
                  + 0.20 × text_match
                  + 0.10 × tag_match
```

Every component is normalized to `[0, 1]`:

| Component | Definition |
| --- | --- |
| `category_match` | `1.0` if the product's category slug equals the requested category slug; `0.0` otherwise. Category is normally already a hard filter, so this is usually `1.0` — it stays in the formula for the case where relevance is computed over a relaxed or alternative-suggestion candidate set. |
| `attribute_match` | Of the attributes the buyer explicitly requested, the fraction the product's `attributes` (product-level merged with variant-level, variant winning on conflict) actually satisfy. `0.0` when the buyer requested none. |
| `text_match` | Token-overlap ratio between the buyer's normalized query tokens and the union of the product's normalized name and description tokens: `|query ∩ text| / |query|`. `0.0` when there is no free-text query. |
| `tag_match` | `|query tokens ∩ tags| / |tags|` when the product has tags; `0.0` when it has none. |

This differs from the proposal recorded in `docs/analysis/03-open-questions.md` A2 (which suggested
category 0.40 / tag 0.25 / name-and-description 0.20 / attributes 0.15). The specification contains
no formula, so it contradicts neither; the divergence is deliberate, and it favours structured
attribute matching over tag overlap, because attributes are curated catalog data while tags are
free-form.

### PreferenceScore

```
PreferenceScore = 0.0                                    if total_preferences == 0
                = matched_preferences / total_preferences otherwise
```

A preference is "matched" when the product's merged attributes contain the requested key with an
equal value, compared case-insensitively for strings and exactly for numbers and booleans.

The zero-preference case returns **0.0**, not the neutral `1.0` proposed in the analysis (A4). The
consequence is stated plainly because it is real: when the buyer expresses no preferences the
preference term contributes nothing for *every* candidate, so ordering is decided entirely by the
remaining 0.30 price and 0.20 relevance weights, and no candidate can score above 0.50. Ordering is
unaffected — the term is a constant across candidates — but the absolute scores are lower, and any
future threshold expressed against `FinalScore` must account for that. `0.0` is chosen over `1.0`
because "the buyer stated no preferences" is not evidence that every product matches them.

### PriceScore

```
PriceScore(p) = 1 - (price / max_budget)              when a budget was stated
              = 1 - (price / max_candidate_price)     when no budget was stated
              = 1.0                                    when the candidate set has one member,
                                                       or every candidate has the same price
```

The budgeted branch is the specification's own formula (R§8), applied only after the budget hard
filter has run, so the value is always in `[0, 1]`. The unbudgeted branch normalizes against the
most expensive candidate in the set, which keeps the score comparable within a request while
remaining deterministic — the same request against the same catalog yields the same denominator.
The degenerate branch avoids dividing by zero and avoids ranking a single candidate at `0.0`
(closes A3).

### CompatibilityScore

Binary, and normally not used: incompatible products are removed before ranking (R§6, R§32; see
ADR-005). It is computed and emitted only under the `explainability_demo` profile.

### Top-K

Top 3, **per requested product type** (closes A6). A request for "a case and a charger" yields three
cases and three chargers, not three items overall.

### Multi-product budget combination

For the MVP (closes A5): take the highest-scoring candidate for each requested product type. If the
combined total exceeds the stated overall budget, search exhaustively over the top 5 candidates of
each type for the combination that maximizes summed `FinalScore` subject to the budget. With two or
three product types and five candidates each this is at most a few hundred combinations. If no
combination fits, return no combination and say so — never silently drop a requested product type.

### Who writes the recommendation reason

The **ranking engine** does (closes A7). It emits structured explanation data for every ranked
candidate: the component scores, the weights applied, the winning component, and the margin over the
next candidate. From that it derives a short deterministic label — `"Best overall"`,
`"Best price"`, `"Closest match to your requirements"`. The model may paraphrase the label in prose,
but the structured field is authoritative and is what the frontend renders. A model-authored reason
would be an ungrounded claim about a computation the model did not perform.

### Dynamic weighting

Out of scope for the MVP (closes A8). R§12 describes adjusting weights from expressed intent
("cheapest", "premium") and defers it. The implementation ships **named weight profiles** that the
intent extractor may select by name (`default`, `price_sensitive`, `premium`, `explainability_demo`).
The model may choose a profile; it MUST NOT emit numeric weights.

## Alternatives considered

**Let the model rank, or let it re-order the ranker's output.** Rejected by R§11 and R§16 and by
ADR-001. It would also make A§54 ("Claude should not arbitrarily change Product C → rank 1")
unenforceable.

**Use the R§4 four-weight set as the default.** Rejected: R§19 states the hard-filter approach is
preferred, and R§6 concedes the 0.40 compatibility weight is conceptual. Keeping it as a selectable
profile preserves the specification's alternative presentation without letting an incompatible
product score at all.

**Learn the weights from evaluation data.** Rejected by R§18, which forbids ML ranking, training and
collaborative filtering for the MVP. RULE 15 asks that weights be *evaluable and adjustable*, which
configuration satisfies.

**Return `PreferenceScore = 1.0` with no stated preferences** (the analysis proposal). Rejected in
favour of `0.0` as decided above. Ordering is identical under both; `0.0` avoids asserting a match
that was never established.

**Score relevance with embeddings or a text index.** Rejected for the MVP: non-deterministic across
model versions, unexplainable to a buyer, and unnecessary for 30-odd SKUs.

## Consequences

**Enables.** A ranker that is unit-testable without a database and without a model; scores that can
be recomputed by hand; a reason string that is defensible because it is derived from the same
arithmetic that produced the ordering.

**Forecloses.** Nuanced relevance. Token overlap will not recognise that "slim" and "low-profile"
mean the same thing. For a 30-SKU catalog that is acceptable; at 30,000 SKUs it would not be.

**Costs.** Four scorers, a weight configuration module, an explanation module and a combination
search, all with tests. The `0.0` zero-preference rule compresses absolute scores, which must be
remembered by anyone who later writes a threshold against `FinalScore`.

## Implementation implications

- `app/ranking/weights.py` — profiles as data, validated to sum to 1.0.
- `app/ranking/scorers.py` — four pure functions, no I/O, no model, no database.
- `app/ranking/ranker.py` — hard filter (ADR-005) → score → weighted sum → sort → Top-K per type.
- `app/ranking/explain.py` — structured explanation and the deterministic label.
- `app/ranking/combinations.py` — the multi-product budget search.
- Ties are broken deterministically: higher `FinalScore`, then lower price, then SKU ascending. An
  unstable sort would violate RULE 8.
- **M3 exit test:** the R§10 worked example reproduces under the `explainability_demo` profile —
  AeroCase Pro ≈ 0.797, ShieldCase Premium ≈ 0.787 — proving the aggregator matches the
  specification's own arithmetic.
- Scoring is computed in `Decimal` or in floats rounded to a fixed precision before comparison, so
  ordering does not depend on floating-point noise.

## Status

**Accepted, not implemented.** M3. Recorded now because M1's seed catalog must contain the
attributes, tags and prices these formulas consume.
