# Ambiguities & Missing Architectural Decisions

Every item below is something `architecture.md` either leaves explicitly open, states
inconsistently, or requires but never defines. Each carries a proposed default so the
build can proceed without stalling — **the proposals are recommendations, not decisions.**

**Severity**

- **BLOCKING** — cannot write correct code for the affected milestone without an answer.
- **MAJOR** — a wrong guess causes rework or a correctness bug.
- **MINOR** — a sensible default is safe; record it and move on.

---

## A. Ranking & recommendation

### A1. Two competing weight sets — BLOCKING (M3)
R§4 specifies Compatibility 40 / Preference 30 / Price 20 / Relevance 10. R§19 then
offers Preference 0.50 / Price 0.30 / Relevance 0.20 *after* compatibility is used as a
hard filter, and states the hard-filter approach is preferred.
**Proposed default:** ship `{preference: 0.50, price: 0.30, relevance: 0.20}` as the
config default with compatibility as a pure hard filter; keep the 4-weight variant as an
alternate config profile for explainability demos.

### A2. RelevanceScore has no formula — BLOCKING (M3)
R§9 lists signals (category match, name match, description match, tags, requested
attributes, spec match) but never defines how they combine. The document simultaneously
demands the ranking be deterministic and explainable, so this cannot be delegated to the
model.
**Proposed default:** a fixed-weight signal sum, each signal normalized to 0..1 —
category exact match 0.40, tag overlap ratio 0.25, name/description token overlap 0.20,
requested-attribute match ratio 0.15. Weights live in the same config as A1.

### A3. PriceScore is undefined without a budget — BLOCKING (M3)
`1 - (price / max_budget)` divides by an absent value when the buyer states no budget,
and yields exactly 0.0 when price equals budget.
**Proposed default:** when no budget is given, normalize against the max price of the
candidate set: `1 - (price / max_candidate_price)`. When a budget exists, keep the
documented formula.

### A4. PreferenceScore divides by zero — MAJOR (M3)
`matched / total` with zero stated preferences.
**Proposed default:** return a neutral 1.0 when `total_preferences == 0`, so the term
contributes uniformly and does not distort relative ordering.

### A5. Multi-product budget combination — MAJOR (M3)
R§13 says the system "evaluates valid combinations against the overall budget" without
an algorithm. With a small catalog this is tractable.
**Proposed default:** for the MVP, take the top candidate per requested product type; if
the combined total exceeds the budget, fall back to maximizing summed FinalScore subject
to the budget over the Top-5 of each type (exhaustive, small N).

### A6. Top-K scope on multi-product requests — MINOR
Is "Top 3" per product type or across the whole request?
**Proposed default:** Top 3 *per requested product type*.

### A7. Who writes the recommendation `reason` string — MAJOR (M5/M14)
The frontend contract (F§9) expects a `reason` per recommendation ("Best overall"). If
the model writes it, it becomes an ungrounded claim; if the ranker writes it, it is
deterministic and explainable.
**Proposed default:** the ranking engine emits structured explanation data (winning
feature, score deltas) and a short deterministic label; the model may paraphrase in
prose but the structured field is authoritative.

### A8. Dynamic intent-driven weighting — MINOR
R§12 describes adjusting soft weights from expressed intent ("cheapest", "premium") but
defers it.
**Proposed default:** out of scope for MVP; ship named weight profiles the intent
extractor can select from, rather than model-generated numeric weights.

## B. Catalog & compatibility

### B1. Device-identifier canonicalization is missing — BLOCKING (M2)
`compatibility_rules.target_identifier` is a free-form VARCHAR (`iphone_16`). The buyer
says "iPhone 16", "iphone16", "the new iPhone". The document forbids the model from
guessing compatibility, yet the model is the thing producing that string. No
normalization component, alias table, or lookup tool exists.
**Proposed default:** add a `compatibility_targets` reference table (canonical
identifier + display name + alias array) plus a `resolve_target` step in the
Compatibility Service. Unresolvable targets trigger clarification, never a guess.

### B2. Category slug taxonomy is not shared with the model — BLOCKING (M4/M5)
The model emits `category: "phone_case"`; the database stores `categories.slug`. Nothing
guarantees they match.
**Proposed default:** enumerate valid category slugs in the `search_catalog` tool schema
so the model can only select from real values; unknown values are rejected by validation.

### B3. `compatibility_rules.constraints` semantics — MAJOR (M2)
`{"minimum_wattage": 20, "fast_charge": true}` — is this a requirement on the product's
own attributes, or a description of what the target device needs?
**Proposed default:** treat `constraints` as predicates evaluated against the *product's*
attributes, so a rule reads "compatible with X provided this product satisfies Y".

### B4. `rule_type` enum — MINOR
Only `compatible` is shown.
**Proposed default:** `compatible` only for MVP; reserve `incompatible` and `requires`
as future values, validated against an enum.

### B5. Compatibility attaches to product, price/stock attach to variant — MAJOR
A variant that differs by connector or length would need variant-level compatibility.
The schema does not allow it.
**Proposed default:** accept product-level compatibility for the MVP catalog and record
the limitation; add `variant_id` (nullable) to `compatibility_rules` only if the seed
catalog actually needs it.

### B6. Product images are missing from the schema — MAJOR (M14)
`ProductCard` renders a product image; neither `products` nor `product_variants` has an
image column.
**Proposed default:** add `image_url TEXT` to both tables in M1, or accept a
placeholder-only UI and note it.

### B7. `search_catalog` product/variant granularity — MAJOR (M5)
The tool returns both `product_id` and `variant_id` in one row. Multi-variant products
have no defined representation.
**Proposed default:** search returns one row per *variant* (the sellable unit), carrying
its parent product's identity — consistent with SKU, price, and inventory all living on
the variant.

### B8. Merchant scoping at runtime — MAJOR (M5)
The schema is multi-merchant; nothing in the chat API or Agent Runtime says how a
session resolves its merchant.
**Proposed default:** a single configured `DEFAULT_MERCHANT_ID` for the MVP, resolved in
the API layer and injected into every service call — never taken from model output.

### B9. Currency handling — MINOR
Merchant, variant, and budget each carry a currency; no conversion is specified.
**Proposed default:** single-currency INR for the MVP; reject or clarify on any mismatch
rather than converting.

## C. Commerce schema & state

### C1. Phase-2 tables have no column definitions — BLOCKING (M6)
`carts`, `cart_items`, `orders`, `order_items`, `payments`, `audit_events`, plus the
implied `approvals`, `idempotency_keys`, `webhook_events`, `sessions` are all required
by the money path but specified only as names and a two-line sketch (P§29).
**Proposed default:** design them in an ADR before M6, following the Phase-1 conventions
(UUID PKs, TIMESTAMPTZ, FK integrity, merchant scoping, NUMERIC(12,2) money).

### C2. No user/identity model — MAJOR (M6/M8)
`user_id` appears in the policy input and approvals bind to "user/session", but no user
table exists anywhere in the document.
**Proposed default:** session-only identity for the MVP — approvals bind to
`session_id`; add a `users` table only if authentication is introduced.

### C3. Session & approval persistence explicitly deferred — BLOCKING (M8)
A§38 leaves the persistence strategy open.
**Proposed default:** persist to PostgreSQL. In-memory state would make the price-drift
and duplicate-request scenarios untestable across processes, and the audit requirement
effectively forces durable state anyway.

### C4. Money representation mismatch — BLOCKING (M11)
Postgres stores `NUMERIC(12,2)`; Razorpay transacts in integer minor units (paise). The
conversion boundary is never mentioned.
**Proposed default:** keep `NUMERIC(12,2)` as the domain type, convert to integer paise
exactly once at the Razorpay client boundary, and assert round-trip equality in tests.

### C5. `reserved_quantity` lifecycle is undefined — MAJOR (M7/M9)
The column exists, `available = quantity - reserved`, and "can initially be 0". Nobody
reserves, releases, or expires reservations.
**Proposed default:** leave reservations at 0 for the MVP; rely on the Policy Engine's
live inventory re-check plus a row-level lock during order creation. Record that this
leaves a narrow race window that reservations would close.

### C6. Concurrency between policy check and order creation — MAJOR (M9/M10)
Nothing specifies locking or transaction isolation between "inventory verified" and
"order created".
**Proposed default:** perform the policy re-check and order insert in one transaction
with `SELECT ... FOR UPDATE` on the affected inventory rows.

### C7. Two overlapping state machines — MAJOR (M5/M10)
The agent conversation states (A§25) and the order lifecycle states (P§30) overlap
(`APPROVED`, `POLICY_VALIDATED`, `PAYMENT_CONFIRMED`) and both are marked "finalize
during implementation".
**Proposed default:** keep them as two separate enums — conversation state on the
session, order state on the order — with an explicit documented mapping, so neither
becomes the other's source of truth.

## D. Policy & payments

### D1. Approval TTL — MAJOR (M8)
"Expired/stale approval handling" is required but no expiry is given.
**Proposed default:** approvals expire after 15 minutes, and unconditionally on any cart
version change.

### D2. Price *decrease* handling — MAJOR (M9)
The rule compares approved total to current total for inequality. A price drop also
trips it.
**Proposed default:** any difference in either direction fails the policy and requires
reconfirmation — the buyer approved a specific total, and re-confirming a cheaper price
is trivial. Record the decision explicitly; silently charging less is still charging an
unapproved amount.

### D3. Spending-limit scope and storage — MAJOR (M9)
"Maximum transaction ₹10,000" — per transaction, per session, per day? Stored in env,
config, or per-merchant?
**Proposed default:** per-transaction only, from application config, single global value
for MVP. Merchant-configurable policy is explicitly deferred by P§13.

### D4. Idempotency key generation, scope, and TTL — BLOCKING (M10)
The document requires fresh keys after price drift but never says who mints them, what
they cover, or how long they live.
**Proposed default:** the backend mints the key when an approval is recorded, scoped to
`(session_id, cart_id, cart_version, approved_total)`, stored with the approval, and
retained 24 hours.

### D5. `request_approval` semantics — BLOCKING (M8)
It is listed as an LLM-callable tool, but approval is by definition a human act. If the
tool records approval, the model can approve on the buyer's behalf.
**Proposed default:** `request_approval` may only transition state to
`WAITING_FOR_APPROVAL` and surface the cart. Only a user-originated
`POST /api/cart/approve` records `APPROVED`. This must be enforced in code, not prompt.

### D6. Is `create_order` exposed to the model at all — BLOCKING (M10)
It appears in the tool list given to Claude, yet A§15 says it "must NOT be freely
available to the LLM."
**Proposed default:** do not register `create_order` as a model-callable tool. Order
creation is a user-initiated API path behind the Policy Engine. If it is registered for
demonstration purposes, its handler must hard-fail without a valid user approval record.

### D7. Which Razorpay webhook events to subscribe — MAJOR (M12)
No event names are listed.
**Proposed default:** `payment.captured`, `payment.failed`, `order.paid`; ignore all
others after logging.

### D8. Payment-failure recovery path — MAJOR (M12)
`PAYMENT_FAILED` exists as a state; no recovery flow is described.
**Proposed default:** a failed payment leaves the cart intact, invalidates the approval
and idempotency key, and requires fresh approval — the same path as price drift.

### D9. Price change while Razorpay Checkout is open — MINOR
Not addressed. The Razorpay order amount is already fixed at creation, so this is
contained by design.
**Proposed default:** accept the Razorpay order amount as final once created; document
this as the boundary of the price-drift guarantee.

### D10. Refunds and cancellation — MINOR
`CANCELLED` appears in the order state machine with no flow.
**Proposed default:** out of scope for MVP; the state exists but no transition is
implemented.

## E. Agent, LLM, and API

### E1. Tool-call loop limit value — MAJOR (M5)
Explicitly "an implementation decision".
**Proposed default:** 8 tool calls per user turn, then a controlled error asking the
buyer to refine.

### E2. LLM retry/timeout values — MINOR (M4)
Explicitly deferred.
**Proposed default:** 60s request timeout, 2 retries with exponential backoff on
transient errors only, no retry on validation failures.

### E3. Two conflicting `/api/chat` response shapes — BLOCKING (M5/M14)
A§48 returns `{session_id, message, state, trace}`; F§8–9 returns
`{session_id, message, recommendations[]}`.
**Proposed default:** one union contract —
`{session_id, message, state, recommendations[], cart, trace[], error}` — with
`recommendations` structured (never parsed out of prose) and `trace` omitted unless
enabled.

### E4. Tool naming inconsistency — MINOR
F§6 uses `search_products(...)`; every other section uses `search_catalog(...)`.
**Proposed default:** `search_catalog` is canonical.

### E5. Stock disclosure granularity — MINOR (M5/M14)
Tools return `available_quantity: 17`; the frontend example returns
`stock_status: "IN_STOCK"`.
**Proposed default:** expose a coarse `stock_status` to the buyer-facing payload and
keep exact quantities internal to tools and policy.

### E6. Agent trace persistence — MINOR (M13)
Never stated whether the trace is stored or per-turn only.
**Proposed default:** returned per-turn in the API response and not persisted; the audit
log is the durable record.

### E7. `audit_events` schema — MAJOR (M13)
Twelve event names are listed (P§RZP-07) with no columns, and the audit log is a
MUST-WORK component.
**Proposed default:** `id, session_id, order_id (nullable), event_type, payload JSONB,
created_at`, append-only, no updates or deletes.

## F. Absent from the document entirely

These are not ambiguities — the document simply never addresses them.

| # | Gap | Impact | Proposed default |
| --- | --- | --- | --- |
| F1 | **LLM test-double strategy** | Blocks deterministic CI for every agent test | Record/replay fixtures for Claude responses; live calls only in a separately-marked suite |
| F2 | Test framework and DB fixture strategy | Blocks M0 | pytest + transactional fixtures against a disposable Postgres |
| F3 | Local dev orchestration | Blocks M0 | docker-compose with Postgres; app run locally |
| F4 | CI pipeline | Slows everything | Lint + type-check + unit + integration on push |
| F5 | Deployment / hosting | Demo delivery | Local-only for MVP; state it |
| F6 | Frontend framework decision (React vs Next.js) | Blocks M14 | The proposed tree (`src/`, `pages/`, `package.json`) matches a plain React SPA; pick Vite + React unless SSR is wanted |
| F7 | Streaming responses | — | Explicitly discouraged by F§28; no streaming |
| F8 | Non-functional targets (latency, throughput) | — | None for MVP; note that agent turns will take seconds |
| F9 | Evaluation harness format | Blocks QA-8 | Query → expected-intent/expected-tool fixtures run as a pytest suite |
| F10 | Accessibility / i18n | — | Out of scope; INR and English only |
| F11 | The external requirement tiers | Real unknown | The document repeatedly cites "MUST-WORK", "SHOULD-WORK", and a "pre-submission gate" from a project brief that is **not part of this file** — obtain it |
| F12 | The CircuitCraft catalog data | Blocks M1 seed | 30–36 SKUs are referenced but no product data is provided — needs authoring or supplying |

---

## Decisions needed before coding starts

If only a handful are answered first, make it these — each one blocks a milestone
outright:

1. **A2** RelevanceScore formula (M3)
2. **B1** Device-identifier canonicalization (M2)
3. **C1** Phase-2 commerce schema (M6)
4. **C3** Session/approval persistence (M8)
5. **C4** Money representation at the Razorpay boundary (M11)
6. **D5 / D6** Can the model approve or create orders (M8/M10)
7. **E3** Canonical `/api/chat` contract (M5/M14)
8. **F11 / F12** The external requirement tiers and the seed catalog (M1)
