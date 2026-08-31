# Deviations from `architecture.md`

`architecture.md` is the source of truth and is never edited. Every place the
implementation resolves an ambiguity in it, adds to it, or departs from its letter is recorded
here with the reason and the ADR that decided it.

This note is **non-authoritative** — it is an index. The ADRs carry the decisions.

Status key: **shipped** = implemented and tested in this session; **decided** = recorded in an ADR,
implemented in a later milestone.

---

## 1. Additions the specification does not contain

| # | Addition | Why | ADR | Status |
| --- | --- | --- | --- | --- |
| A1 | `compatibility_targets` table, in its own migration `0002` | Compatibility is matched by exact string, the model is forbidden from deciding compatibility, and the model is nevertheless what produces that string. Nothing in the specification maps "iPhone 16" onto `iphone_16`, and nothing distinguishes a resolution failure from a genuine no-match. Kept in a separate migration so `0001` remains exactly the specified seven tables. | ADR-003 | shipped |
| A2 | `app/canonical.py` — `normalize_token`, `is_canonical_token` | The deterministic normalization step ADR-003 requires. ADR-003 names `app/services/compatibility_service.py` as its home; it is at the application root instead because the M1 seed validator needs it and `app/services/` does not exist until M2. The M2 service imports it rather than reimplementing it. | ADR-003 | shipped |
| A3 | Composite foreign keys `products(merchant_id, category_id) → categories(merchant_id, id)` and `product_variants(merchant_id, product_id) → products(merchant_id, id)` | D§22's plain foreign keys allow a product to sit in another merchant's category. Merchant scoping is a hard constraint in the recommendation pipeline, so it is enforced by the database rather than by convention. The plain keys D§22 specifies are also present. | ADR-002 | shipped |
| A4 | `UNIQUE(merchants.name)` | Not in D§4. Gives the seed loader a natural key and prevents two CircuitCraft rows. | ADR-002 | shipped |
| A5 | CHECK constraints throughout — canonical-token slugs and identifiers, uppercase SKUs, non-negative money and quantities, `reserved_quantity <= quantity`, JSONB columns restricted to objects, enumerated `rule_type` and `relationship_type` | D§40 principle 9 asks for integrity in the database. Each of these makes a class of bad row unstorable rather than merely discouraged. | ADR-002, ADR-003 | shipped |
| A6 | `UNIQUE` constraints on `compatibility_rules(product_id, target_type, target_identifier, rule_type)` and `product_relationships(source, target, type)` | Prevent duplicate rules and duplicate relationships, which would double-count in ranking and cross-sell. | — | shipped |
| A7 | `ix_product_variants_product_id`, `ix_product_variants_is_active`, `ix_categories_parent_id`, `ix_compatibility_rules_product_id` | Beyond D§24. Loading a product's variants and a product's compatibility rules are the two most common catalog joins; D§24 says indexes should follow real query patterns. | — | shipped |
| A8 | Deterministic UUIDv5 identifiers for seeded rows (`app/identifiers.py`) | Makes seeding idempotent, lets tests name a seeded row, and gives `DEFAULT_MERCHANT_ID` a known value before the database exists. | ADR-002 | shipped |
| A9 | `GET /api/health` | Not in F§26. M0 needs a liveness signal, and it distinguishes "the app is up" from "the catalog is reachable". | ADR-010 | shipped |
| A10 | `session_messages` table | A§38 lists conversation history as session state without giving it a home. An unbounded JSONB column updated on every turn is the wrong shape. | ADR-006 | decided |
| A11 | `approvals`, `idempotency_keys`, `webhook_events`, `sessions` | Required by the Policy Engine, by idempotency and by webhook deduplication; never named as tables in the specification. | ADR-006 | decided |
| A12 | `orders.total_amount_minor`, `payments.amount_minor` | The exact integers exchanged with Razorpay, stored beside the decimals, so the money boundary is auditable after the fact rather than only inside the code path that wrote it. | ADR-008 | decided |
| A13 | `approvals.items_fingerprint` | A total is not a composition: two different carts can reach ₹1,798. `cart_version` catches this in the normal case; the fingerprint catches it unconditionally. | ADR-007 | decided |
| A14 | `app/domain/` package | Not in `docs/analysis/05-proposed-repo-structure.md`. Services must return typed results rather than ORM rows: an ORM instance carries a live session, carries every column, and is mutable. Frozen dataclasses in one place keep that boundary enforceable and testable. | ADR-001 | shipped |
| A15 | `LOW_STOCK_THRESHOLD` setting, default 5 | ADR-009 names `IN_STOCK` / `LOW_STOCK` / `OUT_OF_STOCK` without fixing where `LOW_STOCK` begins. Configuration rather than a literal, so the M2 tests do not depend on the production default. | ADR-009 | shipped |
| A16 | `StockStatus.NO_RECORD` | ADR-009 lists three statuses. The schema permits a variant with no inventory row — `inventory` holds the foreign key, not the reverse — and "we know there are none" is not the same fact as "we have no idea". Both are unpurchasable; only one is a data problem. Flattening them would hide it. | ADR-005, ADR-009 | shipped |

| A17 | `app/attributes.py` — `values_equal`, `predicate_satisfied`, `attributes_satisfy`, `count_satisfied` | Three callers must agree on what "this attribute satisfies that expectation" means: compatibility rule constraints (ADR-003), the ranking engine's required-specification constraint (ADR-005) and its preference scorer (ADR-004). A second implementation would eventually disagree with the first. Same reasoning, and same placement at the application root, as `app/canonical.py` (A2). M3 moved the predicates out of `CompatibilityService`, which kept `constraints_satisfied` as a thin wrapper; the semantics are unchanged and are now regression-tested without a database. | ADR-003, ADR-004, ADR-005 | shipped |
| A18 | `RANKING_PROFILE` and `RANKING_TOP_K` settings | RULE 14 requires the weights to be configuration. `RANKING_PROFILE` selects a named profile and is validated at startup against the registry, so a typo fails loudly instead of silently reordering every result. `RANKING_TOP_K` makes RULE 11's "preferably Top 3" adjustable without editing code. | ADR-004 | shipped |
| A19 | Weight numbers for the `price_sensitive` and `premium` profiles | ADR-004 names four profiles and fixes the numbers for two of them. R§12 describes the other two only as intents ("price importance HIGH", "premium features HIGH, price LOW"). Chosen here: `price_sensitive` = preference 0.20 / price 0.60 / relevance 0.20; `premium` = 0.70 / 0.10 / 0.20. Price is de-weighted under `premium`, never inverted — rewarding a higher price would assert that dear means good, which no catalog data supports. | ADR-004 | shipped |
| A20 | `VariantView.merchant_id`, `.is_active`, `.product_is_active`, `.product_description` | ADR-005 lists existence and merchant as hard constraints 1 and 2, and requires each constraint to be independently unit-testable. A view that omitted these facts could only *assume* them from the repository's SQL, which is exactly the kind of silent trust a merchant leak hides behind. `product_description` is carried because ADR-004's relevance `text_match` is defined over the product's name *and* description; substituting the slug would be a different formula. | ADR-004, ADR-005 | shipped |
| A21 | `RELAXABLE_CONSTRAINTS` = `{BUDGET, REQUIRED_SPECIFICATION}` | ADR-005 says compatibility is never relaxed to produce an alternative and leaves the rest implicit. Made explicit as a closed set, and narrower than "everything except compatibility": inventory is excluded because RULE 5 forbids presenting an out-of-stock product as purchasable and an alternative nobody can buy is not an alternative; category is excluded because a charger is not a cheaper case; merchant and existence are not business preferences at all. | ADR-005 | shipped |
| A22 | `app/llm/models.py` — `Message`, `ModelResponse`, `ToolCall`, `TokenUsage`, `StopReason` | Provider-agnostic transport types the specification never names. M4's exit condition is "offline-testable", which is only reachable if nothing outside `client.py` sees an `anthropic.types.Message`. They are also where model output stops being a network payload and becomes untrusted input. | ADR-015 | shipped |
| A23 | `app/llm/errors.py` — a six-way exception taxonomy with `is_transient` | L§46 names six failure modes and requires bounded retries, but gives them no types. Making the retry decision a class attribute rather than a caller's judgement is what stops the retry policy drifting away from the taxonomy. | ADR-015 | shipped |
| A24 | `app/llm/prompts/intent_extraction.md`, and `PROMPT_VERSIONS` as a per-file map | L§28 requires the system prompt to be version-controlled and names only one. Extraction is a different job — structured output, no prose — and a change to the agent's conversational manner must not silently alter the shape of an extracted intent. A single shared version number would make every stored trace look stale whenever either prompt moved. | ADR-015 | shipped |
| A25 | `IntentExtractor.max_history`, default 20 turns | L§27 says not to send unnecessary application data and gives no bound. Older turns cost tokens and latency while contributing less than the structured intent already carries. | — | shipped |
| A26 | One bounded repair attempt on malformed extraction output | L§46 requires bounded retries at the *transport* layer and says nothing about unusable-but-successful replies. The client cannot know whether a second sample would differ, so the decision belongs to the layer that knows what it asked for. The repair tells the model what failed validation; it never edits the output. | ADR-015 | shipped |
| A27 | `tests/llm/conftest.py::FakeClient` and the SDK doubles in `tests/llm/test_client.py` | The model-side test seam F1 asked for. Placed beside their tests rather than in `backend/tests/fixtures/`, which is reserved for recorded Razorpay payloads from M9. | ADR-015 | shipped |

## 2. Ambiguities resolved

| # | What the specification leaves open | Resolution | ADR |
| --- | --- | --- | --- |
| R1 | Two ranking weight sets (R§4 vs R§19) | `preference 0.50 / price 0.30 / relevance 0.20`, compatibility as a hard filter. R§4's four-weight set survives as a named `explainability_demo` profile. | ADR-004 |
| R2 | No RelevanceScore formula (R§9) | `0.40 category + 0.30 attribute + 0.20 text + 0.10 tag`, each normalized to `[0,1]`. | ADR-004 |
| R3 | `PriceScore` undefined without a budget | Normalize against the most expensive candidate in the set; `1.0` when the set is degenerate. | ADR-004 |
| R4 | `PreferenceScore` divides by zero | `0.0` when no preferences were stated. | ADR-004 |
| R5 | Top-K scope on multi-product requests | Top 3 **per requested product type**. | ADR-004 |
| R6 | Who writes the recommendation `reason` | The ranking engine, deterministically. The model may paraphrase; the structured field is authoritative. | ADR-004, ADR-010 |
| R7 | `compatibility_rules.constraints` semantics | Predicates evaluated against the **product's own** attributes. | ADR-003 |
| R8 | `rule_type` enum | `compatible` only; `incompatible` and `requires` are reserved but not storable. | ADR-003 |
| R9 | `request_approval` is model-callable, but approval is a human act | The tool may only move state to `WAITING_FOR_APPROVAL` and write a `PENDING` row. Only `POST /api/cart/approve` records `APPROVED`. | ADR-007, ADR-009 |
| R10 | `create_order` is listed as a tool and simultaneously declared off-limits | Not registered as a model-callable tool at all. Order creation is a user-initiated API path behind the Policy Engine. | ADR-009, ADR-011 |
| R11 | Two `/api/chat` response shapes (A§48 vs F§8) | One union contract carrying `session_id`, `message`, `state`, `recommendations[]`, `cart`, `trace[]`, `error`. | ADR-010 |
| R12 | Money units are never reconciled | `Decimal` and `NUMERIC(12,2)` inside; integer minor units only at the Razorpay boundary, converted in one module. | ADR-008 |
| R13 | Approval TTL unspecified | 15 minutes, plus unconditional supersession on any cart change. | ADR-007 |
| R14 | Idempotency key minting, scope and TTL unspecified | Backend-minted at approval, scoped to `(session, cart, cart_version, approved_total, currency)`, 24 hours. | ADR-013 |
| R15 | Spending-limit scope unspecified | Per transaction, from application configuration, one global value. | ADR-011 |
| R16 | Webhook event subscriptions unlisted | `payment.captured`, `payment.failed`, `order.paid`; everything else stored and ignored. | ADR-012 |
| R17 | Tool-call loop limit "an implementation decision" | 8 per user turn. | ADR-009 |
| R18 | Two overlapping state machines (A§25 vs P§30) | Three separate enums — conversation state, approval status, order state — each owned by one table, none derived from another. | ADR-006, ADR-007 |
| R19 | Tool naming: `search_products` vs `search_catalog` | `search_catalog` is canonical. | ADR-009 |
| R20 | Stock disclosure granularity | Coarse `stock_status` in buyer-facing payloads; exact quantities stay internal. | ADR-009, ADR-010 |
| R21 | Build-order conflict (D§36/D§39 vs F§37) | The commerce schema is its own milestone, M6, landing after the read-only agent and before the cart service. | ADR-006 |
| R22 | ADR-004's `attribute_match` says "the attributes the buyer explicitly requested" without saying which intent field that is | The union of `required_attributes` and `preferences`, requirements winning on a shared key. Requirements alone would make the term constant among survivors — they were all filtered on it — so the 0.30 sub-weight could reorder nothing. The resulting overlap with `PreferenceScore` is the specification's own: R§9 lists "requested attributes match" as a relevance signal separate from the preference score. | ADR-004 |
| R23 | ADR-004's `tag_match` is `|query ∩ tags|`, which a multi-word tag can never satisfy | A tag matches when *every* one of its tokens appears in the query, which for a single-token tag is exactly the stated set intersection. Without it `fast_charging` could never match "fast charging" and the term would be dead for most of the catalog. | ADR-004 |
| R24 | ADR-004 states the `PriceScore` degenerate branch unconditionally, next to a budgeted branch that also divides | The degenerate branch governs the **unbudgeted** denominator only. Both reasons ADR-004 gives for it — avoiding division by zero, and avoiding ranking a lone candidate at 0.0 — are properties of the candidate-set denominator. A stated budget is externally fixed and meaningful, so R§8's formula applies unchanged, and a product priced exactly at the budget scores 0.0 as the specification intends. | ADR-004 |
| R25 | ADR-004 names three reason labels without saying which candidate earns which | Rank 1 is `BEST_OVERALL` (it won the weighted total). Otherwise the candidate whose largest *contribution* came from the price term is `BEST_PRICE`, and everything else is `CLOSEST_MATCH`, since preference, relevance and compatibility are all statements about fit. Derived from the same arithmetic that produced the ordering, so it is checkable. | ADR-004 |
| R26 | Where alternatives are scored from, when the budget that excluded them is relaxed | With no budget at all, so the candidate-set denominator applies. Keeping the buyer's budget would drive every over-budget candidate below zero, where the clamp flattens them into a meaningless tie and the alternatives lose their order. | ADR-004, ADR-005 |
| R27 | L§26 requires the LLM to "update the intent" across turns without defining what updating means | A top-level field the model **omits** is carried forward from the previous intent; a field it sets to `null` or `[]` is cleared. Both are needed: L§26's own example ("Around 1500") states only a budget and must inherit the device, while a buyer who withdraws a budget must be able to. The distinction is knowable because the extractor parses the model's JSON itself and can see which keys were present. The merge is shallow — reconciling two turns' `product_requirements` item by item would mean deciding whether "make it two" refers to the case or the charger, which is a judgement only the model can make. | ADR-015 |
| R28 | L§5 gives a "conceptual" intent structure and defers the real schema to implementation | `IntentExtraction` wrapping a `BuyerIntent`, with `required_attributes` and `preferences` as separate fields (ADR-005), a device as a phrase rather than an identifier (ADR-003), money as `Decimal` (ADR-008), and `extra="forbid"` throughout so a hallucinated SKU or price fails validation instead of being silently dropped. | ADR-003, ADR-005, ADR-008 |
| R29 | Whether intent extraction should use a tool call or free text | Text JSON, parsed with `parse_float=Decimal`. Tool arguments arrive from the SDK already JSON-decoded, so a budget of `1500.10` would be a `float` before this application ever saw it, and a `Decimal` built from a lossy binary float is still lossy. This is the only interception point that exists. | ADR-008, ADR-015 |
| R30 | E2 — LLM retry and timeout values, "explicitly deferred" | Settled as configuration, adopting the analysis document's proposed default unchanged: 60s timeout, 2 retries, `0.5 × 2ⁿ` backoff, transient failures only. The SDK's own retry loop is disabled, because two nested bounded loops multiply rather than bound. | ADR-015 |

## 3. Departures from the letter of the specification

| # | Departure | Reason | ADR |
| --- | --- | --- | --- |
| D1 | A price **decrease** invalidates an approval, exactly as an increase does. P§32 illustrates only an increase. | The buyer approved a specific total; charging a different one, cheaper or not, charges an amount that was never authorized. P§11's rule is stated as inequality. | ADR-014 |
| D2 | `products.category_id` is `NOT NULL`. D§6 does not say. | Category is a hard constraint in the recommendation pipeline; a product with no category could never satisfy it. | ADR-002 |
| D3 | Product colour lives in variant attributes, not product attributes. D§34's example puts `color` on the product. | D§27 says variant attributes are what differentiate sellable versions, and AeroCase Pro has three colours. The example illustrates a single-variant case. | ADR-002 |
| D4 | `compatibility_rules.target_type` is restricted by CHECK to `phone_model`, `laptop_model`, `device`, `device_port`. D§13 describes it as free-form `VARCHAR` with examples. | Same reasoning ADR-003 applies to `rule_type`: a value the compatibility filter cannot interpret is worse than a value that cannot be stored. All four of the specification's own examples are permitted. | ADR-003 |
| D5 | `compatibility_targets.target_type` and `compatibility_rules.target_type` mean different things and are deliberately not the same vocabulary. | The specification uses `phone_model` for cases and `device` for chargers, which are different axes — what the identifier *is* versus how a product *relates* to it. Conflating them would make the specification's own examples inconsistent. | ADR-003 |
| D6 | `ix_products_merchant_id` is created even though `uq_products_merchant_id_slug` already covers the prefix. | D§24 names it explicitly. The redundancy is accepted in favour of following the specified index list. | — |

## 4. Deferred, with the reason

| # | Deferred | Reason | Where |
| --- | --- | --- | --- |
| F1 | `reserved_quantity` lifecycle — nothing reserves, releases or expires | The MVP relies on the Policy Engine's live re-check plus a row lock in one transaction. Reservations would close a narrow race that the lock already covers. | ADR-005, ADR-011 |
| F2 | Variant-level compatibility | The authored catalog does not need it. Would be a nullable `variant_id` on `compatibility_rules` plus an override rule. | ADR-003 |
| F3 | Product images | Neither `products` nor `product_variants` has an image column, and `ProductCard` renders one (F§10). Not added speculatively; a column plus a migration when M14 needs it. | — |
| F4 | Dynamic intent-driven ranking weights | R§12 defers it. Named weight profiles ship instead; the model may select a profile, never emit numbers. | ADR-004 |
| F5 | Refunds and cancellation | `CANCELLED` exists as a state with no transition implemented. | ADR-006 |
| F6 | Multi-currency and conversion | INR only. A mismatch is an error, not something to convert. | ADR-008 |
| F7 | The frontend | F§37 STEP 11 sequences the frontend after the APIs it consumes exist. Nothing is scaffolded at M0. | — |
| F8 | GIN indexes on `products.tags` / `products.attributes` | D§24 says to add them when real query patterns justify them. M2/M3 will show whether they do. | — |

## 5. Still open

Superseded by [`open-questions-status.md`](open-questions-status.md), which carries the verified
status of all 45 analysis questions plus the three project-level items. In summary:

| # | Question | Status |
| --- | --- | --- |
| U1 | Is `L:\RazorPayackend` part of this project? | **RESOLVED: no.** `L:\AI_COMMERCE` is the sole project root. That directory is a separate, unrelated project and must not be inspected, copied, imported, merged, referenced or depended on. Verified: no source file, test, migration or configuration file in this repository references it. |
| U2 | The external project brief (MUST-WORK / SHOULD-WORK tiers, pre-submission gate) | **Open external-input gap, blocks nothing.** Searched for and genuinely absent. The six brief-derived requirements the supplied documents actually state are preserved verbatim in [`external-brief-gap.md`](external-brief-gap.md). No requirement has been invented. |
| U3 | PostgreSQL provisioning on this machine | **Resolved in practice.** A throwaway PostgreSQL 16.4 runs from the session scratchpad; `docker-compose.yml` remains the supported path. |

Of the 45 analysis questions, seven remain open. None blocks M5. **F1**, the LLM test-double
strategy, is closed by ADR-015, and **E2** is closed as configuration by the same ADR. The next
decision owed is **E3**, the `/api/chat` response shape, which ADR-010 has already decided and M5
must implement.
