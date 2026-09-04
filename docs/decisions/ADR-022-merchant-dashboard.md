# ADR-022 — The Merchant Dashboard: single-tenant, no authentication, a separate write side

**Status:** Accepted · **Date:** 2026-09-04 · **Supersedes:** nothing · **Superseded by:** nothing

Relates to ADR-002 (merchant scoping is server-resolved configuration), ADR-006 (no `users`
table), ADR-009 (deterministic side of the boundary), ADR-017 (Vite + React), ADR-021 (the
expanded catalogue this dashboard manages).

---

## Context

The project owner asked for a real Merchant Dashboard — a portal to manage the commerce catalogue
(products, variants, categories, inventory) and monitor commerce activity (orders, aggregate
metrics) — *connected to the actual backend and database*, not a mock with hard-coded numbers.

The audit (Phase A) established:

- **There is no authentication of any kind.** ADR-006 has no `users` table: *"everything maps to
  `session_id`… introducing authentication later means adding `users`."* No merchant login, no API
  keys or tokens for merchants, no roles.
- The storefront and the agent resolve the merchant **server-side** from
  `settings.default_merchant_id`. A client cannot name a merchant anywhere.
- The catalogue services are **read-only by contract**: `CatalogService` — *"never writes, never
  invents"*; `InventoryService` — *"never writes, never estimates"*. There is **no write path** for
  creating or editing a product, a variant, a category, or an inventory level. The seed script is
  the only thing that writes catalogue rows.
- There is no "list orders" endpoint, no aggregate/analytics endpoint, and no HTTP audit read.
- The schema supports N merchants (`merchant_id` on every catalogue and commerce row, composite
  foreign keys), but the application serves one.

## Decision

### 1. Single-tenant, no authentication — and that is the isolation guarantee

**The dashboard operates on the one configured merchant, resolved server-side from
`settings.default_merchant_id`.** Every `/api/merchant/*` handler resolves it that way; the merchant
is **never** read from a path parameter, a header, or a request body, and the request schemas are
`extra="forbid"` so a `merchant_id` field is a 422. A client cannot name a merchant, so it cannot
name another one — merchant isolation is structural, not a check that could be forgotten. A row
whose `merchant_id` does not match the resolved one is reported as *not found*, never acted on
(tested with a real id for a second merchant's product / variant / inventory row).

**A production authentication system was explicitly not built** — the owner's instruction was to
document the limitation, not to invent auth. The `/merchant` route tree is reachable by anyone who
knows the URL. This is stated plainly on the dashboard's own Settings page and in
`docs/notes/deviations.md` (D10). A real merchant switcher, roles, or a login would each require a
`users` table first (a future ADR that would supersede ADR-006's MVP stance).

### 2. Writes are a new service, separate from the pure read services

`CatalogService` and `InventoryService` stay read-only. The write side is
**`app/services/merchant_service.py`**:

- `MerchantCatalogService` — `create_product` (with initial variants + inventory), `update_product`,
  `set_product_active` (archive / restore), `create_variant`, `update_variant`, `set_stock`,
  `create_category`, plus dashboard reads (`list_products` paginated + filtered, `get_product`
  including inactive rows, `stock_rows`).
- `MerchantAnalyticsService` — the overview aggregates, each derived directly from a source table.

This is the same read/write split the codebase already draws between `CatalogService` (read) and
`CartService` (write). Every field is validated in the service — canonical slug, uppercase-token
SKU, two-decimal-place money **string** (a JSON number is refused, ADR-008), category ownership,
`quantity ≥ reserved` — with the schema's CHECK constraints as the backstop. `merchant_service.py`
does **not** import `app.llm` or `app.agent` (the deterministic-side boundary; the new-variant
currency is read from the `merchants` row, not from a constant in `app.llm.schemas`). A standing
boundary test enforces this.

`OrderService` gained one read method, `list_for_merchant`, alongside its existing `get`. **No
handler mutates an order's state** — the dashboard observes the commerce state machine
(`create_order` + the verified webhook own it, ADR-011 / ADR-012), it does not drive it. There is
no advance / refund / cancel control.

### 3. The API reuses existing conventions

Twelve endpoints under `/api/merchant`, following the same route style as `catalog.py` /
`sessions.py`: `Depends(get_db)`, `Depends(get_settings)`, `settings.default_merchant_id`, error
bodies as `{"code", "message", "details"}` using F§25's closed vocabulary
(`VALIDATION_ERROR` / `PRODUCT_NOT_FOUND` / `VARIANT_NOT_FOUND`) so no new public error code was
minted. Reads that a browsing buyer could also make (`GET /categories`, product detail) reuse
`CatalogService` directly rather than duplicating it.

### 4. Metrics are real or absent — never fabricated

`/api/merchant/overview` returns product / variant / category counts, inventory units, low-stock and
out-of-stock counts, order counts and revenue — every one a direct aggregate over `products`,
`product_variants`, `inventory` and `orders`. **Revenue counts only `PAYMENT_CONFIRMED` orders**,
because that is the only money actually received; an order in `ORDER_CREATED` is not revenue. There
are no placeholder numbers and no metric that is displayed but not backed.

### 5. The dashboard frontend is its own shell

`/merchant/*` renders under **`MerchantShell`** (a sidebar + workspace, responsive drawer on
mobile), a sibling layout route to the storefront's `Shell` — not one shell with a mode flag,
because they are two products for two people. It has no concierge rail, no cart, no category bar.
It reuses the entire design system: the primitives, `Money`, `Toast`, the `--volt` (#94DD26)
accent used only for active nav / focus / a primary action / a status colour, the motion tokens,
and the global `prefers-reduced-motion` rule. The one new shared component is a responsive
`DashTable` (a real table on desktop, a stack of labelled cards on a phone). Charts are inline SVG
(a single stock-health bar), consistent with `SpecMark` — no chart library was added.

Pages: **Overview** · **Products** (paginated, filter by category / stock / active, search name &
SKU) · **Product editor** (create + edit; category-templated attribute fields; per-variant SKU /
price / stock; add-variant; archive / restore) · **Inventory** (lowest-available first, inline
quantity edit) · **Orders** (paginated list + read-only detail) · **Categories** (tree + create) ·
**Settings** (the merchant context and the MVP's stated limitations).

### What was rejected

| Rejected | Why |
| --- | --- |
| A real login / `users` table | The owner said not to invent auth. It would supersede ADR-006. Deferred, documented. |
| Client-supplied `merchant_id` (path or body) | It would turn a structural guarantee into a check. `extra="forbid"` refuses the field. |
| Writes added to `CatalogService` / `InventoryService` | Their contract is "never writes". A separate service keeps the pure read path pure. |
| Merchant catalogue actions written to `audit_events` | Widening the closed `AUDIT_EVENT_TYPES` CHECK is a migration to a load-bearing constraint, and `audit_events` is scoped to the *order* path ("how a transaction reached its outcome") with no `merchant_id`. Deferred as a known limitation rather than shipped hastily. |
| A second seeded merchant + a dashboard switcher | Pointless without a sign-in, and would need a multi-merchant `CatalogSeed`. Isolation is covered by backend test fixtures instead. |
| A chart library | The dashboard needs one bar. Inline SVG matches the house style. |

## Consequences

**Positive.** A merchant can create a product and it is immediately real: it appears in the
dashboard list, in the storefront `/api/products`, and — verified live — the Groq agent discovers
it through the normal tool path. Changing stock to zero removes the variant from what the agent can
recommend as available; changing a price is reflected everywhere on the next read. All of this goes
through validated APIs; nothing mutates the database from the browser.

**Negative, and accepted.** No authentication (documented). No merchant activity log (the commerce
audit trail still covers the order path only). Single tenant. Razorpay is unconfigured, so
`paid_orders` and `revenue` will read zero until it is.

**Unchanged.** Groq is the LLM (ADR-018), untouched. The chat / cart / approval / order / webhook
contracts and their invariants are untouched — the dashboard adds a parallel read/write surface,
it does not modify the buyer path. `create_order` is still not a tool.

## Verification

- Backend: **1344 passed** with a database. New: `tests/services/test_merchant_service.py` (15,
  including four merchant-isolation tests and an analytics-accuracy test) and
  `tests/api/test_merchant.py` (14, including create→storefront round-trip, price→storefront
  propagation, stock→availability propagation, `extra="forbid"`, and "a real id for another
  merchant's variant is a 404").
- Frontend: **57 passed** (was 50; +7 for the dashboard — real-aggregates render, list, empty
  state, create-form submits a string price with no `merchant_id`, inline stock `PATCH`, and the
  shell has no cart/concierge). typecheck, eslint, production build all clean.
- Live, in a browser against a seeded backend: the Overview tiles, the Products table (all three
  families in one list), the Inventory low-stock view, and end-to-end Scenarios 4–6 (merchant
  creates / restocks / reprices, storefront + agent honour it) and 7 (cross-merchant access
  rejected).
