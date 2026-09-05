# Frontend Architecture & UX Specification

**Status:** Analysis only. Nothing in this document has been implemented. No frontend code, backend
code, or existing documentation was changed to produce it.
**Author's note on method:** Every backend fact below was read from the current code
(`backend/app/...`) or from `architecture.md` and `docs/decisions/*.md` at the time of writing, not
recalled from memory. Where a capability does not exist, it is labeled a gap rather than assumed.

---

## 0. Two corrections before anything else

Two premises in the request don't match the repository as it stands. Both change what's designable
today, so they're stated up front rather than absorbed silently.

**Groq is not the LLM provider.** It was tried, found to have real defects (a stop-reason mapping bug
that would have let a truncated model reply pass as complete, a tool-schema converter that was a
no-op, an argument-parsing path that would have reopened a `Decimal` precision hole), and removed —
recorded in `docs/decisions/ADR-016-single-model-provider.md`. The specification (`architecture.md`
L§44, L§48) names Claude Sonnet specifically and treats it as an acceptance criterion, not a
preference. **Anthropic's API is the only provider**, called from exactly one backend module
(`app/llm/client.py`); this is invisible to the frontend either way; a chat request never carries a
provider name.

**`architecture.md`'s own frontend section argues against the storefront this brief asks for.**
Its §3 says outright: *"For the MVP, keep the frontend small... Do NOT build a large e-commerce UI
for the MVP. The important demonstration is: conversational commerce - recommendations - cart -
policy validation - payment - auditability."* The recommended component tree in that section is nine
components under one `ChatPage`. This document was asked to specify a full storefront — home,
browse, category listings, search results, product detail pages, order history, a merchant
dashboard — which is a materially larger and, in three places, backend-dependent scope. That's not
disqualifying; it's a real decision the brief itself makes, and it's flagged as such throughout this
document (every page and feature below is tagged with what it depends on) and summarized in
**§20**. I did not narrow the scope back to the spec's minimal sketch on my own judgment, and I did
not silently expand the backend to match the brief either — both are laid out for you to choose
between.

---

## 1. Executive Summary

CircuitCraft's backend (M0–M13, plus M15's backend-only scenarios) is complete: catalog, ranking,
LLM intent extraction, agent runtime, cart, approval, Policy Engine, orders, idempotency, Razorpay
order creation, verified webhooks, and an append-only audit log. Every commerce fact — price, stock,
compatibility, approval, payment — is decided by deterministic backend code and never by the
frontend or the model. 1258 tests pass against a real PostgreSQL; 880 need no database at all.

**What's missing for a frontend to exist at all, regardless of scope:**

1. **CORS is not configured anywhere.** A browser on a different origin than the API (which is every
   realistic frontend setup — Vite dev server on `:5173`, API on `:8000`) cannot call it today. This
   is a two-line backend change (`CORSMiddleware`) but it is not optional and not yet done.
2. **There is no HTTP endpoint for browsing the catalog outside of chat.** The service layer
   (`CatalogService.get_products`, `.search`, `.list_categories`, `.get_product`) fully supports it;
   nothing routes an HTTP request to it. The only way to see a product today is to type a sentence to
   the agent. This is the central fact that shapes the framework recommendation below and the page
   architecture in §5.
3. **There is no buyer or merchant identity of any kind.** `ADR-006` closes this deliberately: no
   `users` table, session-only. A "session" is an anonymous, unauthenticated row created the moment
   someone sends their first chat message, with no login, no password, and no way to find it again
   from a different browser. "Order history" and "account area" as the brief describes them, and the
   entire merchant dashboard, need an identity and authorization model that doesn't exist yet.

None of this blocks *designing* the frontend, which is what follows. It does mean the specification
below is honest about two tracks: what can be built today against the real API (a genuinely capable
conversational-commerce experience — chat, recommendations, cart, approval, Razorpay checkout, order
status, all backend-authoritative), and what requires backend work first (direct catalog browsing,
any persistent identity, the merchant dashboard). **§19** sequences both; **§20** is the complete gap
list.

**Recommended stack:** React 18 + TypeScript + **Vite** (not Next.js — reasoning in §2) + Tailwind CSS
+ shadcn/ui, TanStack Query for server state, no global commerce store, Zod for response validation,
Framer Motion for the handful of animations that earn their place, Vitest + React Testing Library +
Playwright + MSW for testing.

---

## 2. Recommended Frontend Architecture

### 2.1 Stack, chosen by inspection rather than default

| Layer | Choice | Why (evidence, not preference) |
| --- | --- | --- |
| Framework | **React 18 + TypeScript** | `architecture.md` L§44 names "React / Next.js"; nothing in the codebase implies a different framework family. TypeScript is the only reasonable choice given the backend's own discipline around typed contracts (Pydantic models, `extra="forbid"` everywhere) — an untyped frontend would be the one place the "never invent a shape" rule had no enforcement. |
| Build tool | **Vite**, not Next.js | This is open question **F6**, explicitly "now due" per `docs/notes/open-questions-status.md`. Next.js earns its place chiefly when a frontend needs a secure server layer — but inspecting `RazorpayClient.checkout_config()` (`app/payments/razorpay_client.py`) confirms the **only** thing the frontend ever needs to open Checkout is the **public** key ID, an amount, a currency, and a provider order ID — all handed over by the backend at request time. The frontend never holds a secret Next.js would need to protect. There is also no SEO requirement anywhere in the spec (it's a conversational demo, not a content site) and no server-rendering need. Given that, and given §3's "keep it small" instruction, Vite's simpler dev loop and build model is the better fit and adds no unjustified layer between the browser and FastAPI. *(I recommended Next.js in an earlier, less-inspected pass — `PROGRESS.md` — before checking what `checkout_config` actually returns. This supersedes that.)* |
| Routing | **React Router v6** | Needed the moment there's more than one page (order status, order detail, and — if the storefront direction is taken — product/category pages). Vite has no bundled router; this is the standard pairing. |
| Styling | **Tailwind CSS** | Matches the "modern fintech/e-commerce, not generic chatbot" design goal in §12 with utility classes rather than a heavy component library's opinions; pairs directly with shadcn/ui. |
| Component primitives | **shadcn/ui** (Radix UI + Tailwind, copied into the repo rather than installed as a dependency) | Radix's accessibility primitives (focus trapping, ARIA roles, keyboard handling) are exactly what §13's accessibility requirements need and are tedious to get right by hand for a chat panel, dialogs, and toasts. Copied-in rather than a black-box npm package means the AI panel's specific interaction needs (streaming-looking message append, structured cards inside a chat bubble) can be modified directly. |
| Server-state / data fetching | **TanStack Query** | Nine backend endpoints, every one of which already returns everything the UI needs to render (no client-side joining across endpoints). Query gives cache invalidation, retry, and loading/error states for free, matching backend semantics (e.g., re-fetching `GET /api/cart` after `POST /api/cart/items` succeeds) without hand-rolled state machines. |
| Global commerce store | **None — deliberately** | §7 develops this fully. Every piece of commerce truth (cart, approval, order) already lives in one backend response; a Redux/Zustand store holding a second copy is the exact "frontend must not invent or duplicate state" failure `architecture.md` §5 and §29 warn about twice. A tiny Context or two for pure UI state (is the AI panel open) is enough. |
| Client-side validation | **Zod**, validating responses at the API boundary | The backend validates every request with Pydantic and `extra="forbid"`; nothing validates on the way back into the frontend today. A Zod schema per response type turns a silent contract drift (a renamed field, a widened enum) into a caught error at the fetch boundary instead of a runtime `undefined` deep in a component. |
| Animation | **Framer Motion** | Well-established, tree-shakes reasonably, and has first-class `prefers-reduced-motion` support, which §10 requires throughout. |
| Payment | **Razorpay Checkout.js** (loaded via `<script>`, per Razorpay's own integration model) | Not an npm package — Razorpay's web SDK is a script tag that exposes `window.Razorpay`. This is standard for their integration and is what "backend hands over a public config, frontend opens Checkout" (§9) actually looks like in code. |
| Testing | **Vitest + React Testing Library + Playwright + MSW** | Vitest shares Vite's config and transform pipeline (no second bundler to maintain); MSW intercepts the same nine endpoints at the network layer so component tests exercise real fetch code against realistic fixtures instead of mocked hooks. Playwright for the handful of true end-to-end flows. Detailed in §17. |

### 2.2 What React owns, what the backend owns, what the agent owns, what Razorpay owns

This is `architecture.md`'s Frontend §1 and §35 ("the most important design rule"), stated as a table
because the brief asks for it explicitly:

| Responsibility | Owner | Evidence |
| --- | --- | --- |
| What products exist, their price, stock, compatibility | **Backend** (`CatalogService`, `InventoryService`, `CompatibilityService`) | Never computed or cached authoritatively client-side (§5 of `architecture.md`'s frontend part) |
| Which products best match a request, and why | **Ranking engine** (`app/ranking/`), invoked only through the agent | Deterministic; the model never computes a score (ADR-004) |
| Interpreting free text into a structured request | **The LLM** (Claude, via the agent runtime) | Bounded to tool calls the agent runtime validates before executing (ADR-009) |
| Whether a purchase may proceed | **Policy Engine** (`app/policy/`) | Ten rules, pure, no model or frontend input (ADR-011) |
| Whether payment succeeded | **A verified Razorpay webhook, exclusively** | `orders.status` only advances past `RAZORPAY_ORDER_CREATED` via `app/services/webhook_service.py`; nothing else can move it (ADR-012) |
| Collecting card/UPI details and authenticating the payment | **Razorpay Checkout** (hosted, off the page) | The frontend never sees a card number or UPI PIN |
| Displaying all of the above, collecting input, and requesting explicit confirmation | **React** | — |

**What must never be handled by the frontend**, stated as absolutes because §14 asks for this list
explicitly:

- Any secret: `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`, the database URL.
  None of these have any legitimate reason to exist in frontend code, an env var prefixed `VITE_`, or
  a network request the browser can inspect.
- Computing an authoritative price, subtotal, or total. Every money value the frontend ever displays
  is a string it received from the backend (`"999.00"`), never a sum it performed.
- Deciding compatibility, stock sufficiency, or whether a discount/spending limit applies.
- Verifying a Razorpay webhook signature, or treating Razorpay's client-side success callback as
  proof of payment (`architecture.md` P§28 is explicit: the callback "MUST NOT mark an order paid").
- Minting or reusing an idempotency key by itself — the backend mints it at approval time
  (`ApprovalService.approve`, ADR-013) and the frontend only ever relays the value it was given.
- Constructing a `cart_version` or an approved total from its own arithmetic.

---

## 3. Complete User Flow

### 3.1 The primary flow, mapped to real endpoints and states

Every step below names the actual request and the actual `ConversationState` / HTTP status involved
— nothing here is invented.

```
Landing
  │
  ▼
[Gap: no unauthenticated browse — see §20.C] ──or──▶ Open AI assistant
  │                                                     │
  ▼                                                     ▼
Browse / search (blocked today, §5)          Natural-language request
                                                         │
                                                         ▼
                                              POST /api/chat  { message }
                                              (session_id omitted → backend mints one)
                                                         │
                                                         ▼
                                    Agent runtime: intent → tool calls
                                    (search_catalog / get_compatible_products)
                                                         │
                              hard constraints (merchant, category, budget,
                              compatibility, required spec, inventory) eliminate
                                                         │
                                          deterministic ranking (app/ranking/)
                                                         │
                                                         ▼
                                    ChatResponse { state: RECOMMENDING,
                                       message, recommendations: [...] }
                                                         │
                                                         ▼
                                          Product recommendation cards render
                                       (from `recommendations[]`, never from `message`)
                                                         │
                                                         ▼
                                          User: "add the second one"
                                                         │
                                                         ▼
                     POST /api/cart/items { session_id, variant_id, quantity }
                        — OR the agent's own propose_cart tool inside chat —
                                                         │
                                                         ▼
                                    CartResponse { cart_id, cart_version,
                                            subtotal, total, items[] }
                                                         │
                                                         ▼
                                              Cart review (backend totals only)
                                                         │
                                                         ▼
                            POST /api/cart/approve { session_id, cart_version }
                                                         │
                                            (re-prices first; stale version → 409)
                                                         ▼
                          ApprovalResponse { status: APPROVED, idempotency_key,
                                              approved_total, cart }
                                                         │
                                                         ▼
        POST /api/orders { session_id, cart_id, cart_version, idempotency_key }
                                                         │
                                    Policy Engine evaluates all 10 rules
                                                         │
                              ┌──────────────────────────┴───────────────────────┐
                             FAIL (422, reason_codes[])                        PASS (201)
                              │                                                    │
                              ▼                                                    ▼
                    Recovery UI per code (§15)                     Internal order committed,
                                                                  Razorpay order attached inline
                                                                              │
                                                                              ▼
                                          POST /api/orders/{id}/checkout (if not already attached)
                                          → { key, razorpay_order_id, amount, currency, name }
                                                                              │
                                                                              ▼
                                               window.Razorpay(...).open()
                                                                              │
                                                                  Customer authenticates (Razorpay-hosted)
                                                                              │
                                              ┌───────────────────────────────┴──────────────┐
                                          success handler fires                      user cancels/closes
                                     (NOT payment truth — just closes the modal)      (no state change)
                                                                              │
                                                     GET /api/orders/{order_id}  (poll)
                                                                              │
                                            Razorpay → POST /api/webhooks/razorpay (server-to-server,
                                                    frontend never sees this request)
                                                                              │
                                              orders.status → PAYMENT_CONFIRMED (or PAYMENT_FAILED)
                                                                              │
                                                                              ▼
                                                        Frontend's poll picks up the change
                                                                              │
                                                                              ▼
                                                              Order confirmation screen
```

### 3.2 Alternative and failure flows

| Scenario | What actually happens (verified against the code) |
| --- | --- |
| **User searches without AI** | **Not currently possible.** There is no non-chat catalog endpoint. Gap — see §20.C. |
| **User asks AI to find products** | The primary flow above. |
| **User changes requirements mid-conversation** | Handled entirely server-side: `merge_intent` carries forward omitted fields and clears fields the model set to `null` across turns (`app/llm/extractor.py`). The frontend does nothing special — it's still just `POST /api/chat` with the next message and the same `session_id`. |
| **No products match** | `Recommendation.outcome` distinguishes `NO_MATCH` from `NO_MATCH_WITH_ALTERNATIVES` (ADR-005/R§14) — a real backend concept: an alternative that failed only a *relaxable* constraint (budget, required spec) is never presented as a match. The frontend must render these as two different things: "nothing fits" vs. "here's the closest option, and here's what it doesn't satisfy." |
| **Product becomes unavailable between recommendation and cart** | `POST /api/cart/items` returns `409 OUT_OF_STOCK` (via `_handle` in `app/api/routes/cart.py`). |
| **Price changes before approval** | `POST /api/cart/approve` re-prices the cart *before* checking the submitted `cart_version` (deliberately — a code comment in the route explains why: so the buyer reaches a version they can actually confirm). A stale version comes back as `409 CART_VERSION_STALE`, with `details.current_version`. |
| **Price changes after approval, before order** | `POST /api/orders` → `422 POLICY_FAILED`, `details.reason_codes` includes `PRICE_CHANGED`, `details.validated_total` carries the real number. **This is the flagship scenario** — proven end-to-end in `tests/integration/test_scenarios.py::test_the_price_drift_scenario`. |
| **Compatibility failure** | Never reaches the frontend as an error — it's a hard constraint in the ranking pipeline (ADR-005), so an incompatible product is simply absent from `recommendations[]`. |
| **Budget failure** | Same mechanism as "no products match" above — a relaxable constraint, surfaces as an alternative, not an error. |
| **User rejects a recommendation** | Just another chat message ("show me something cheaper"). No dedicated endpoint. |
| **User removes a cart item** | `DELETE /api/cart/items/{item_id}?session_id=...` — version increments (§7 of `architecture.md`'s cart section). |
| **User cancels payment (closes Razorpay modal)** | Razorpay fires its own dismiss callback; nothing on the backend changes. The order sits in `RAZORPAY_ORDER_CREATED`. The frontend should offer "resume payment," which re-opens Checkout against the same order (via `/checkout` again — idempotent, same Razorpay order). |
| **Payment fails** | Webhook delivers `payment.failed`; `orders.status → PAYMENT_FAILED` unless the order is already `PAYMENT_CONFIRMED` (a later, successful attempt), in which case the failure is logged and ignored (`WebhookService._apply`). The frontend polling `GET /api/orders/{id}` will see `PAYMENT_FAILED`. |
| **Payment succeeds but webhook is delayed** | The order stays in `RAZORPAY_ORDER_CREATED` from the frontend's point of view until the webhook lands. This is a real, expected state, not an error — §15 designs its own "verifying payment" UI for it, distinct from failure. |
| **User refreshes during payment** | Nothing is lost: `session_id`, `cart_id`, and `order_id` can all be carried in the URL or `localStorage` (never anything sensitive), and `GET /api/orders/{order_id}` re-establishes state from the backend. |
| **User returns later to view an order** | Works only if they still have the `order_id` (URL, browser history, or local storage) — **there is no way to list "my orders" without one**, because there's no identity to list them by. Gap — see §20.C. |

---

## 4. AI Chatbot UX

### 4.1 Comparing the four options

| Option | Fit for this project |
| --- | --- |
| **A. Floating button + expandable side panel** | Matches `architecture.md`'s own sketch (a `ChatPage`-centric app) while leaving room for a storefront shell around it if that direction is taken. Lets a user browse (once browsing exists) *and* converse without a full-page context switch. |
| **B. Dedicated AI page** | This is closest to what the specification actually describes today (`ChatPage` is the only page it names). Simplest to build against the current API exactly as it exists — no browsing is needed if the whole app *is* the chat. Weakest fit for the brief's "real storefront" framing. |
| **C. AI-first homepage** | Interesting for a demo (it puts the flagship capability first) but awkward once/if product-listing pages exist — a returning user who just wants to look at chargers shouldn't have to talk their way there. |
| **D. Hybrid** | Effectively "B now, A once browsing exists" — not a fourth thing, a sequencing of A and B. |

**Recommendation: build B first, arrive at A.** Concretely:

- **Phase 1 (matches what the backend supports today, §19 F0–F7):** the whole app *is* the chat
  experience — a single page, full width on desktop, full-screen on mobile. This is exactly
  `architecture.md`'s own recommended shape and requires no new backend work. It is not a "floating
  button" because there is nothing else on the page yet to float over.
- **Phase 2 (if the storefront direction is taken, and only once §20.C's catalog-browsing gap is
  closed):** the chat becomes a floating button + side panel *alongside* real storefront pages, which
  is option A. The chat UI itself doesn't need to be rebuilt for this transition — a `ChatWindow`
  component built to Phase 1's spec drops into a `<Sheet>` (shadcn's slide-over panel) unchanged.

This isn't hedging — it's the one sequencing that lets the flagship scenario (price-drift, the
architecture's own stated demo) ship without waiting on a browsing feature that doesn't exist yet,
while not foreclosing the fuller storefront if that's the direction chosen.

### 4.2 Element definitions

| Element | Definition |
| --- | --- |
| **Floating button** | Fixed-position, bottom-right on desktop/tablet; opens the panel (Phase 2 only — see above). Badge shows unread agent messages if the panel is closed mid-conversation. |
| **Chat panel** | Phase 1: the page itself. Phase 2: a `<Sheet>` — ~420px wide on desktop (`md:` breakpoint and up), full viewport on mobile. |
| **Header** | Merchant name/logo, a "clear conversation" affordance (starts a fresh `session_id` — there is no "delete session" endpoint, so this is purely "stop sending the old one"), and (Phase 2) a close button. |
| **Conversation area** | Vertically scrolling list of turns, oldest to newest, auto-scrolls to the newest message on arrival unless the user has scrolled up (in which case show a "new message" pill instead of yanking their scroll position). |
| **User message** | Right-aligned bubble, plain text — a buyer's message is never rendered as anything but text; the backend never returns structured data *about* what the buyer said. |
| **AI message** | Left-aligned. `message` (prose) always renders as text. If `recommendations[]` is non-empty, product cards render **below** the prose, as their own block — never inline-parsed out of the text (`architecture.md` Frontend §5 forbids exactly this). |
| **Typing/loading state** | See §4.4 — no real streaming exists (ADR-010 / F7 closed), so this is a bounded, honest "thinking" indicator, not a fake stream. |
| **Streaming response** | **Deliberately not implemented.** `ADR-010` and `architecture.md` F§28 both reject it for this project. If revisited later, note it would require reopening a closed decision, not just a frontend change. |
| **Product recommendation cards** | Specified in full in §4.5 below. |
| **Product comparison** | The backend does not compute a side-by-side comparison; it ranks. A comparison UI is a **client-side arrangement** of two or more `Recommendation` objects the backend already returned in one `recommendations[]` array — never a new data shape invented by the frontend, and never comparing a card against a product the backend didn't return this turn. |
| **Compatibility indicators** | A `Recommendation` doesn't carry a raw compatibility boolean — compatibility is a hard constraint already applied *before* ranking (ADR-005), so every recommendation shown is already compatible by construction. Where the buyer named a device, the assistant's `message` states it in prose; there is no separate structured "compatible: true" field to render as a badge. (If one is wanted, it's a small backend addition — noted in §20.C.) |
| **Ranking explanation** | `reason` (a sentence: "Best overall", "Best price", "Closest match to your requirements" — from `RecommendationLabel`/`LABEL_TEXT`, `app/domain/ranking.py`) and, only when `AGENT_TRACE_ENABLED`, `score.components` (a dict of named sub-scores). `score` is present for inspectability but is not meant to be everyday buyer-facing UI — treat it as a "why this?" disclosure, not primary card content. |
| **Add-to-cart action** | Calls `POST /api/cart/items` directly with the card's `variant_id` — does not require going back through chat. |
| **View-product action** | See §5 — degrades to "ask the agent for details" until a product-detail endpoint exists (§20.C). |
| **Follow-up suggestions** | Not backend-generated. If wanted, these are **frontend-authored** static prompts ("show me something cheaper", "what about a case instead?") — must be visually distinct from anything backend-sourced, since they are frontend UI copy, not agent output. |
| **Cart actions** | Quantity stepper, remove — call `PATCH`/`DELETE /api/cart/items/{id}` directly; never require re-entering chat. |
| **Approval UI** | Specified fully in §4.6. |
| **Error states** | Per `ChatError.code` / HTTP status — full table in §15. |
| **Empty states** | New session, no messages yet: a short prompt ("Tell me what you're looking for") plus 2–3 example queries grounded in the real catalog (e.g. "a case for my iPhone 16", "a charger under ₹1,500" — using real category slugs `phone_case`, `charger` from the seed data, not invented ones). |
| **No-match state** | `Recommendation` list empty and `message` explains why — render the prose plus a "try different criteria" affordance; do not render an empty product-card grid. |
| **Tool execution/loading states** | The frontend has no visibility into individual tool calls during a turn (the trace, if enabled, only returns *after* the turn completes) — so this cannot be "Searching catalog… Checking compatibility…" shown live. It must be a single bounded "Thinking…" state for the whole turn (§4.4). Presenting fake granular steps would be inventing information the frontend does not have. |

### 4.3 Comparison, upsell, approval, and payment-state UI

**Comparison UI** — client-side only, built from ≥2 items already present in one turn's
`recommendations[]`:

```
┌─────────────────────┬─────────────────────┐
│   AeroCase Pro       │   ShieldCase Premium │
│   ₹999.00            │   ₹1,299.00          │
│   Best overall        │   Closest match      │
│   TPU · Black         │   Polycarbonate      │
│   In stock             │   In stock           │
│   [Add to Cart]       │   [Add to Cart]      │
└─────────────────────┴─────────────────────┘
```
Every field above is a `Recommendation` field already returned this turn (§4.5's table) — the
"differences" a comparison highlights are computed by the frontend by diffing fields it already has
(price, `attributes`, `stock_status`), never fetched separately or invented.

**Upsell UI** — the backend's `get_upsell_candidates` tool (bound to `product_relationships` rows,
R§15) is the only legitimate source. It is a tool the *agent* calls during a turn, not a separate
frontend-triggered endpoint — so an upsell card appears exactly when the agent's `message` for that
turn discusses it, rendered the same way a `Recommendation` card is. There's no independent "show me
upsells for this product" button today (that would need a new tool binding — noted in §20.C if
wanted as a direct feature).

**Approval UI** — every field comes from `CartResponse`/`ApprovalResponse`, nothing computed:

```
┌───────────────────────────────────────────┐
│  Review your order                         │
│                                             │
│  AeroCase Pro — Black         ₹999.00      │
│  Qty: 1                                    │
│                                             │
│  ───────────────────────────────           │
│  Subtotal                     ₹999.00      │
│  Total                        ₹999.00      │
│                                             │
│  [ Confirm & Pay ]     [ Back to cart ]    │
└───────────────────────────────────────────┘
```
`[ Confirm & Pay ]` calls `POST /api/cart/approve` — never Razorpay directly (§9, §14).

**Payment state UI** — one screen, states driven by polling `GET /api/orders/{order_id}` plus local
UI-only states before the order exists:

| State | Trigger | Copy |
| --- | --- | --- |
| Preparing payment | Between `POST /api/orders` success and `checkout_config` being available | "Preparing your payment…" |
| Razorpay Checkout open | `window.Razorpay(...).open()` called | (Razorpay's own hosted UI — no app UI visible underneath on mobile) |
| Payment processing / verifying | Checkout closed with a client-side "success" signal, webhook not yet reflected | "Verifying your payment…" — **never** "Payment successful" at this point (P§28) |
| Payment confirmed | `orders.status === "PAYMENT_CONFIRMED"` from a poll | "Payment verified. Order confirmed." |
| Payment failed | `orders.status === "PAYMENT_FAILED"` | "Payment failed." + retry (new Checkout attempt against the same order) |
| Payment pending (webhook delayed) | Checkout closed successfully, order still `RAZORPAY_ORDER_CREATED` after a reasonable poll window (~30s) | "Your payment is being confirmed. This can take a minute — we'll update this page automatically." Keep polling; do not treat this as failure. |

### 4.4 "Thinking" state, precisely

Because there is no token streaming and no live per-tool-call visibility, the honest design is a
single indicator that:
- Appears immediately on send.
- Shows rotating, generic phrases ("Thinking…", "Looking through the catalog…") on a fixed timer —
  **cosmetic only**, not tied to real backend progress, and must be visually distinguishable (e.g., a
  slightly different animation weight) from anything claiming to reflect real state.
- Has no fixed max duration in the UI, but the backend's tool-call budget (8 per turn, `ADR-009`) and
  typical multi-second LLM latency (open question F8: no non-functional targets are set; turns take
  seconds) mean a soft warning ("This is taking longer than usual…") after ~15s is reasonable
  defensive UX, not a spec requirement.

### 4.5 Product recommendation card — the exact data contract

Every field below is a real key on the `Recommendation` model (`app/api/schemas/chat.py`) — nothing
here is a proposed backend addition:

| Card element | Source field | Type / example |
| --- | --- | --- |
| Name | `name` | `"AeroCase Pro"` |
| Variant | `variant_name` | `"Black"` |
| Price | `price` | `"999.00"` — fixed-scale string, render verbatim with the currency symbol, never parse to a number and reformat |
| Currency | `currency` | `"INR"` |
| Category | `category` | `"phone_case"` |
| Availability | `stock_status` | `"IN_STOCK" \| "LOW_STOCK" \| "OUT_OF_STOCK"` — **coarse only; no quantity is ever returned** (ADR-009, closing E5) |
| Attributes | `attributes` | `{"material": "TPU", "color": "black"}` — render as a small key:value list, not assumed keys |
| Brand | `brand` | nullable |
| Rank | `rank` | `1, 2, 3…` — use for ordering and a "#1 pick" badge on rank 1 only |
| Reason | `reason` | `"Best overall"` — render verbatim; this is backend-authoritative text |
| Reason code | `reason_code` | `"BEST_OVERALL" \| "BEST_PRICE" \| "CLOSEST_MATCH"` — use to pick an icon/badge style, not to write new copy |
| Score (optional) | `score.final`, `score.components` | Only present when trace is enabled; treat as an expandable "why?" disclosure |
| Identifiers | `product_id`, `variant_id`, `sku` | Used for the Add-to-Cart request and `key`s in the list render; never displayed as primary UI unless the buyer is troubleshooting |

No card field is ever computed, guessed, or defaulted by the frontend. A missing/null field renders
as an omitted UI element (e.g., no brand pill), never a fabricated placeholder.

---

## 5. Frontend Pages

Every page below is tagged:
**✅ buildable now** (existing endpoints only) · **🟡 needs a small addition** · **🔴 blocked** (needs
a backend subsystem that doesn't exist).

### Public / Buyer

| Page | Status | Purpose | Main data | Backend | Notes |
| --- | --- | --- | --- | --- | --- |
| **Home** | 🟡 | Entry point | If chat-first (Phase 1): none needed, just the chat UI. If storefront: featured categories/products | None exist for "featured" — would reuse a new listing endpoint (§20.C) | Phase 1: this page *is* the chat page. |
| **Product listing / Category listing / Search results** | 🔴 | Browse without chat | Product grid, filters | **No endpoint exists.** `CatalogService.get_products/search/list_categories` are backend-internal only. | The single largest gap. See §20.C for the exact routes this would need. |
| **Product details** | 🔴 (as a standalone page) / 🟡 (as an agent-driven card) | See one product's full detail incl. all variants | `ProductDetail` (product + variants) | `get_product` exists as an **agent tool only** — no `GET /api/products/{id}` | A "view details" click today can only mean "ask the agent about this product," not navigate to a URL. |
| **AI assistant** | ✅ | The core experience | `ChatResponse` | `POST /api/chat` | Fully specified above. |
| **Cart** | ✅ | Review/edit cart | `CartResponse` | `GET/POST/PATCH/DELETE /api/cart*` | Requires an existing `session_id` — see gap on session creation below. |
| **Checkout / review (approval)** | ✅ | Explicit confirm | `CartResponse`, `ApprovalResponse` | `POST /api/cart/approve` | — |
| **Payment status** | ✅ | Mid-payment states | `OrderResponse`, checkout config | `POST/GET /api/orders*` | Polling-based (§8, §9). |
| **Order success** | ✅ | Confirmation | `OrderResponse` | `GET /api/orders/{id}` | — |
| **Order history** | 🔴 | List past orders | N/A | **No identity to list by, and no "list orders for X" endpoint** | Needs the identity model in §20.D before this can mean anything. |
| **Order details** | ✅ (if you have the `order_id`) | One order's state | `OrderResponse` | `GET /api/orders/{order_id}` | Reachable only via a saved/shared link or same-session history until 🔴 above is resolved. |
| **User/account area** | 🔴 | Profile, saved info | N/A | No `users` table exists at all (ADR-006) | Not a frontend task — a backend/architecture decision. |

### Merchant

| Page | Status | Notes |
| --- | --- | --- |
| **Merchant login/auth** | 🔴 | No merchant authentication exists. `Settings.default_merchant_id` is a fixed config value read server-side; there is no login flow, session, or role model for a merchant user. |
| **Dashboard, catalog management, inventory, orders, order details, agent metrics, audit trail** | 🔴 (all) | Every one of these needs merchant-scoped **write** APIs (product CRUD, inventory adjustment) or merchant-scoped **read** APIs (an order list, the audit log) that do not exist. `AuditRepository`/`AuditService` exist and are fully capable of producing a reconstruction (`reconstruct_order`, `reconstruct_session`) — but nothing routes an HTTP request to them. This entire section is a distinct, sizeable backend project before any merchant-facing frontend page can be built. |

For each ✅/🟡 page, the same shape applies (per the brief's per-page requirements) — spelled out
once here rather than repeated eleven times, since the pattern is identical:

- **Loading state:** skeleton matching the eventual layout (skeleton cards for recommendations,
  skeleton rows for cart lines), never a bare spinner replacing the whole page.
- **Empty state:** per §4.2's table (no messages yet, empty cart, no orders).
- **Error state:** per §15's full table, keyed off `ChatError.code` / HTTP status / `ReasonCode`.
- **Mobile behavior:** full-width, single column, bottom-anchored primary actions (Add to Cart,
  Confirm & Pay) — detailed in §11.
- **Important interactions:** documented per-section above (§4 for chat/cards, this section's data
  columns for what triggers a fetch).

---

## 6. Component Architecture

Kept flat and close to the real data shapes rather than fragmented into one-prop wrapper components —
a `ProductCard` that just forwards nine props to nine sub-components would be exactly the
over-fragmentation the brief asks to avoid.

```
src/
  components/
    ui/                      # shadcn/ui primitives (button, dialog, sheet, badge, skeleton, toast…)
    layout/
      AppShell.tsx            # header + main slot; the one place that knows Phase 1 vs Phase 2 layout
      Header.tsx
    chat/
      ChatWindow.tsx          # owns the conversation list + input; the composition root for chat
      MessageList.tsx
      MessageBubble.tsx       # renders one turn: text, then (if present) a RecommendationGrid
      MessageInput.tsx
      ThinkingIndicator.tsx   # §4.4's bounded, honest "thinking" state
      EmptyConversation.tsx
    recommendations/
      RecommendationGrid.tsx
      RecommendationCard.tsx  # §4.5's exact field mapping, one component, not nine
      ComparisonView.tsx      # client-side arrangement of ≥2 already-fetched Recommendations
      ScoreDisclosure.tsx     # optional "why this?" expandable, only rendered if `score` is present
    cart/
      CartPanel.tsx
      CartItemRow.tsx
      CartSummary.tsx
      PriceChangeBanner.tsx   # renders `price_changes[]` from CartResponse — never invents drift
    approval/
      ApprovalReview.tsx      # §4.3's approval screen
      PolicyFailureCard.tsx   # one component, driven by `reason_codes[]` — see §15's table
    payment/
      CheckoutLauncher.tsx    # wraps window.Razorpay(...).open(); the ONLY place Razorpay's script is touched
      PaymentStatus.tsx       # the state table in §4.3, driven by polling
    orders/
      OrderStatusBadge.tsx
      OrderSummary.tsx
    (catalog/ — does not exist until §20.C's endpoints do; see §19 Phase 2)
    (merchant/ — does not exist until §20's merchant subsystem does; not part of this spec's buildable scope)
  pages/
    ChatPage.tsx               # Phase 1's entire app
    OrderStatusPage.tsx
    OrderDetailPage.tsx
    (CatalogPage.tsx, ProductPage.tsx — Phase 2 only)
  hooks/
    useSession.ts              # reads/writes the session_id the backend minted; see §7
    useChat.ts                 # wraps the chat mutation + local turn-append logic
    useCart.ts
    useApproval.ts
    useOrder.ts                 # includes the polling logic for payment status
  api/
    client.ts                  # one typed fetch wrapper; the only module that knows the base URL
    chat.ts / cart.ts / orders.ts   # one file per backend router, mirroring app/api/routes/*.py 1:1
    schemas.ts                 # Zod schemas mirroring app/api/schemas/*.py 1:1
  state/
    sessionContext.tsx          # the one piece of cross-page state that truly needs sharing
    uiContext.tsx               # panel open/closed, active toast, etc. (Phase 2)
  types/
    chat.ts / cart.ts / order.ts  # TS types generated from or mirroring the Zod schemas
  lib/
    money.ts                    # formats a fixed-scale string for display — never does arithmetic on it
    errors.ts                   # maps ApiErrorCode / ReasonCode to the copy table in §15
```

The `api/*.ts` files mirroring `app/api/routes/*.py` one-to-one is deliberate: when the backend adds
`GET /api/products`, there's exactly one new frontend file to write, and its name is already implied
by the pattern.

---

## 7. State Management

| State | Category | Where it lives | Why |
| --- | --- | --- | --- |
| Conversation messages (this turn's list) | Chat/conversation | TanStack Query cache, keyed by `session_id` | Each `POST /api/chat` response is appended to a local array driven by the mutation's `onSuccess`; no separate "chat store" duplicates it. |
| `session_id` | Cross-cutting | A small Context + `localStorage` mirror | Needs to survive a refresh (§3.2) and be readable by cart/order calls outside the chat component tree. This is the one piece of state that is neither purely local nor server-fetched — it's a client-generated *reference* to server state. |
| Recommendations for the current turn | Product state | Embedded in the chat message it arrived with (not hoisted elsewhere) | A recommendation is a fact about one turn, not a standing catalog the app maintains. |
| Cart contents/totals | Cart state | **TanStack Query, server state exclusively** | `CartResponse` is refetched after every mutation; there is no local cart reducer computing totals — that's precisely the duplication `architecture.md` §27 forbids ("frontend state: what should I display? backend state: what is actually true?"). |
| Authentication | — | **N/A — none exists** | Not a frontend decision to make; see §20.D. |
| Checkout/approval in-flight status | Checkout state | Local component state (`useState`/`useMutation`'s own `isPending`) | Transient, page-local, disposable on navigation. |
| Payment status | Payment state | TanStack Query with `refetchInterval` (polling) | Needs to reflect backend truth over time, not a one-shot fetch — see §8/§9's polling design. |
| Order details (post-purchase) | Order state | TanStack Query, keyed by `order_id` | Same reasoning as cart. |
| UI-only state (panel open, active tab, toasts) | UI state | Local component state or a tiny UI Context (Phase 2 only) | Never touches commerce data. |

**No Redux, no Zustand, no MobX.** The commerce data is small (nine endpoints, no client-side
joining), always server-authoritative, and TanStack Query already solves caching/invalidation. Adding
a global store would create exactly the second source of truth the backend's entire architecture is
built to prevent on its own side — there's no reason to reintroduce it on the frontend.

---

## 8. API Integration

Every row below is a real, currently-implemented endpoint (`backend/app/api/routes/*.py`) — nothing
in this table is invented. A separate "not yet built" table follows for what the storefront direction
needs.

### 8.1 Implemented today

| Frontend feature | Method & path | Request body/query | Response | UI consumer |
| --- | --- | --- | --- | --- |
| Send a chat message | `POST /api/chat` | `{ session_id?: uuid, message: string }` | `ChatResponse` (`session_id`, `state`, `message`, `recommendations[]`, `cart`, `trace`, `error`) | `ChatWindow`, `MessageBubble`, `RecommendationGrid` |
| Read the cart | `GET /api/cart?session_id=...` | query param | `CartResponse` | `CartPanel` |
| Add an item | `POST /api/cart/items` | `{ session_id, variant_id, quantity }` | `CartResponse` | `RecommendationCard`'s Add-to-Cart button, `CartPanel` |
| Change quantity / remove | `PATCH /api/cart/items/{item_id}` (body `{session_id, quantity}`) — `quantity: 0` removes | `CartResponse` | `CartItemRow` |
| Remove an item explicitly | `DELETE /api/cart/items/{item_id}?session_id=...` | `CartResponse` | `CartItemRow` |
| Approve the cart | `POST /api/cart/approve` | `{ session_id, cart_version, expected_total? }` | `ApprovalResponse` (incl. `idempotency_key`) | `ApprovalReview` |
| Create the order | `POST /api/orders` | `{ session_id, cart_id, cart_version, idempotency_key }` | `OrderResponse` | `CheckoutLauncher` |
| Get checkout config | `POST /api/orders/{order_id}/checkout` | — | `{ key, razorpay_order_id, amount, currency, name, receipt }` (plain dict; no `response_model` declared on this route today — a minor backend polish item, not a blocker) | `CheckoutLauncher` |
| Read order status | `GET /api/orders/{order_id}` | — | `OrderResponse` | `PaymentStatus`, `OrderSummary`, `OrderStatusPage` |
| Liveness/health | `GET /api/health` | — | `HealthResponse` | Optional: a dev-only "API reachable" indicator |

### 8.2 Not built — required for the storefront direction (§20.C has the full reasoning)

| Frontend feature | Proposed method & path | Backend capability it would wrap |
| --- | --- | --- |
| Product listing | `GET /api/products?category=&max_price=&search=` | `CatalogService.get_products` / `.search` (exists, unexposed) |
| Category listing | `GET /api/categories` | `CatalogService.list_categories` (exists, unexposed) |
| Product detail | `GET /api/products/{id}` | `CatalogService.get_product` (exists, unexposed) |
| Create a session without a message | `POST /api/session` | Trivial — the exact code chat's route already runs when `session_id` is omitted, just without requiring a message |
| List orders | `GET /api/orders?session_id=...` (or by identity, once one exists) | No service method exists yet; needs a new `OrderService` query |
| Merchant: catalog/inventory/orders/audit | An entirely separate authenticated router | Needs the identity/authorization model from §20.D first |

### 8.3 Error/business-outcome consumers (not new endpoints — the shapes above already carry these)

| Concern | Where it appears | Consumer |
| --- | --- | --- |
| Business failure during a chat turn | `ChatResponse.error` (`{code, message, details}`) — turn still `200` | `MessageBubble` renders an inline error block, not a toast |
| Cart/approval/order failures | HTTP status + `detail.code`/`detail.details.reason_codes` | `PolicyFailureCard`, `PriceChangeBanner` — full mapping in §15 |
| Payment truth | `OrderResponse.status` polled over time | `PaymentStatus` |

---

## 9. Razorpay Frontend Flow

```
Frontend                    Backend                        Razorpay
   │                            │                               │
   │  POST /api/orders          │                               │
   ├───────────────────────────▶│  Policy Engine evaluates      │
   │                            │  (all 10 rules; live prices,  │
   │                            │   locked inventory)            │
   │                            │                               │
   │                            │  PASS → internal order         │
   │                            │  committed FIRST (ADR-011)     │
   │                            │                               │
   │                            │  POST order  ─────────────────▶│
   │                            │◀──────────── razorpay_order_id │
   │  ◀── OrderResponse ────────┤  (order now RAZORPAY_ORDER_    │
   │      { razorpay_order_id }│   CREATED)                     │
   │                            │                               │
   │  POST /orders/{id}/checkout│  (only if not already attached)│
   ├───────────────────────────▶│                               │
   │  ◀── { key (PUBLIC),       │                               │
   │        razorpay_order_id,  │                               │
   │        amount, currency,   │                               │
   │        name }              │                               │
   │                            │                               │
   │  window.Razorpay({...}).open()                              │
   ├──────────────────────────────────────────────────────────▶│
   │                            │        Customer authenticates  │
   │                            │        (card/UPI/etc, entirely │
   │                            │         inside Razorpay's UI)  │
   │  ◀── client callback (NOT payment truth) ───────────────────┤
   │                            │                               │
   │                            │◀──── webhook: payment.captured─┤
   │                            │  signature verified (HMAC,     │
   │                            │  constant-time compare)        │
   │                            │  orders.status → PAYMENT_       │
   │                            │  CONFIRMED                     │
   │                            │                               │
   │  GET /api/orders/{id}  (poll)                                │
   ├───────────────────────────▶│                               │
   │  ◀── { status: PAYMENT_CONFIRMED } ────┤                    │
   │                            │                               │
   ▼ render "Payment verified"  │                               │
```

**What React explicitly does not do**, restated as a checklist against real code:

- ❌ Access `RAZORPAY_KEY_SECRET` — it's read only inside `app/config.py`/`app/payments/sdk.py`,
  server-side, `SecretStr`-typed so it can't even be logged accidentally.
- ❌ Access PostgreSQL — the frontend has no database driver, connection string, or ORM at all.
- ❌ Verify the webhook signature — that's `verify_signature()` in `app/services/webhook_service.py`,
  HMAC-SHA256 over the **raw request body**, and the frontend never receives a webhook (Razorpay calls
  the backend directly, server-to-server).
- ❌ Decide whether payment succeeded — only `orders.status`, set exclusively by the webhook handler,
  answers that.
- ❌ Store card numbers, UPI IDs, or PINs — Razorpay Checkout collects these inside its own
  iframe/hosted page; they never touch the parent page's JS context.
- ❌ Bypass authentication — Checkout enforces whatever authentication the payment method requires
  (3DS, UPI PIN, etc.) on Razorpay's side; there's no code path around it.

**UI behavior per state**, cross-referenced to §4.3's table: *Preparing* (spinner, no Checkout UI
yet) → *Checkout open* (Razorpay's own modal; the app's own UI should stay visible but inert
underneath) → *Verifying* (spinner, explicit "not final" language) → *Confirmed* / *Failed* /
*Pending* (three distinct terminal-or-waiting states, never collapsed into one generic "done").

---

## 10. Animations and Micro-interactions

| Animation | Purpose | Where | Duration | Essential? |
| --- | --- | --- | --- | --- |
| Page/panel transition | Orient the user across a route or panel change | Route changes; Phase 2's chat sheet open/close | 150–200ms | Essential (jarring without it) |
| Product card hover | Affordance that the card is interactive | `RecommendationCard` | 100ms | Optional |
| Chat panel open/close | Spatial continuity for the floating-button pattern | Phase 2 only | 200ms | Essential once Phase 2 exists |
| Message appearance | New message doesn't just pop in | `MessageBubble` mount | 150ms fade+slight rise | Optional, cheap to justify |
| "Streaming" text | **Not implemented** | — | — | N/A — would misrepresent a non-streaming backend as streaming; see §4.2 |
| Thinking indicator | Signal ongoing work honestly | `ThinkingIndicator` | Looping, ~1.2s cycle | Essential (§4.4) |
| Recommendation grid loading | Reduce perceived latency | `RecommendationGrid` | Skeleton, matches final card layout | Essential |
| Add-to-cart feedback | Confirm the click registered | `RecommendationCard`, `CartItemRow` | ~300ms (icon or button state change) | Essential (without it, a slow network makes it feel broken) |
| Cart update | Draw attention to a changed total | `CartSummary` | Brief highlight/pulse on total, ~400ms | Optional |
| Compatibility success/failure | — | **N/A** — no such indicator exists (§4.2) | — | — |
| Checkout transition | Clear handoff into payment | Approval → Checkout | 200ms | Optional |
| Payment processing | Fill the "Razorpay closed, webhook pending" gap | `PaymentStatus` | Looping spinner + progress-feeling copy | Essential — this state can last real seconds |
| Success animation | Reward completion | Order confirmed | One-shot, ~500ms (checkmark) | Optional but high-value here specifically — it's the flagship moment |

**Reduced motion:** every animation above must have a `prefers-reduced-motion: reduce` fallback that
is an instant state change, no exceptions — Framer Motion's `useReducedMotion` hook makes this a
one-line guard per animated component rather than a scattered set of media queries.

**Not recommended:** parallax, gradient animations, glassmorphism, or any animation whose purpose is
decorative rather than one of the rows above — consistent with §12's "fintech, not chatbot toy"
design goal and the brief's own "avoid gimmicky" instruction.

---

## 11. Responsive Design

| Breakpoint | Layout |
| --- | --- |
| **Desktop (≥1024px)** | Phase 1: centered chat column, max-width ~720px, generous margins. Phase 2: storefront grid + floating button + side panel (`<Sheet side="right">`, ~420px). |
| **Tablet (768–1023px)** | Phase 1: same as desktop, narrower margins. Phase 2: panel becomes a larger overlay (~60% width) rather than a fixed sidebar. |
| **Mobile (<768px)** | Phase 1: full-viewport chat, input pinned to the bottom above the safe-area inset. Phase 2: floating button opens a **full-screen** panel (not a sheet) — matching the brief's explicit direction and standard mobile chat-UI convention (WhatsApp, Intercom). Product cards stack single-column; cart and checkout are single-column with the primary action (Add to Cart / Confirm & Pay) as a sticky bottom bar rather than inline, so it survives scrolling a long recommendation list or cart. |

Navigation at breakpoints: Phase 1 has no navigation (one page). Phase 2's storefront nav collapses
to a hamburger/bottom-tab pattern below 768px, standard for the category count here (≤10 real
category slugs from the seed data — small enough for a simple horizontal scroll or dropdown, not a
mega-menu).

---

## 12. Design System

Goal restated from the brief: **fintech/e-commerce, not generic AI chatbot.** Concretely, that means
resisting the two things most chat-UI templates default to — heavy rounded bubbles with drop shadows
everywhere, and a purple/blue gradient "AI" identity — in favor of the same visual language a
checkout flow needs to feel trustworthy.

| Aspect | Recommendation |
| --- | --- |
| Typography | One sans-serif family (e.g., Inter) throughout, including the chat — no separate "friendly chatbot" font. Numerals (prices) use tabular figures so a cart's totals align. |
| Spacing | Tailwind's default 4px scale, unmodified — no reason to invent a custom scale for an app this size. |
| Border radius | Small and consistent (`rounded-md`, ~6–8px) on cards, buttons, and inputs alike — including chat bubbles, which should look like the rest of the app, not like a separate "chat widget" skin. |
| Shadows | Minimal — a single subtle elevation level for cards/panels, none for buttons. Fintech UIs read as trustworthy partly *because* they're visually quiet. |
| Cards | One `Card` primitive (shadcn's) reused for recommendation cards, cart lines, and order summaries — visual consistency across "this is a product" and "this is my order" reinforces that they're the same kind of fact. |
| Buttons | Primary (Confirm & Pay, Add to Cart), secondary (Back, Cancel), destructive (Remove item) — three variants, no more. |
| Inputs | Standard shadcn input/textarea for the chat composer; no custom "chat bubble" input styling. |
| Badges | `stock_status` (green/amber/red-toned, but never pure red for `OUT_OF_STOCK` — muted, since it's informational, not an error the buyer caused), `reason_code` (a small icon+label, not a colored pill competing with stock status). |
| Colors | A single accent color (not "AI purple") reused for both primary CTAs and the assistant's visual identity — the point is that this doesn't read as two different products bolted together. Semantic colors (success/warning/destructive) reserved strictly for state, never decoration. |
| Icons | One icon set (e.g., Lucide, which ships with shadcn) throughout. |
| Status indicators | Consistent small dot/badge pattern reused for `stock_status`, `order.status`, and `state` (conversation state) — one visual language for "where are we" across the whole app. |
| AI visual identity | A small, static avatar/mark for assistant messages — no animated "AI glow," no gradient. The assistant is a feature of the storefront, not a separate brand. |

---

## 13. Accessibility

**Scope note:** the project's own `docs/notes/open-questions-status.md` records accessibility/i18n
(F10) as *"OPEN, out of scope"* for the MVP — English/INR only, nothing further decided. The
requirements below are still specified in full because the brief asked for them and because most cost
little when shadcn/Radix primitives are used as intended; they should not be read as contradicting
that scope note, but as "cheap to do right from the start" rather than "blocking the MVP."

| Requirement | Approach |
| --- | --- |
| Keyboard navigation | Every interactive element (cards, cart controls, chat input, Confirm & Pay) reachable and operable via Tab/Enter/Space; Radix primitives (dialog, sheet) trap focus correctly by default. |
| Screen readers | `aria-live="polite"` region for new assistant messages (announces arrival without interrupting); recommendation cards use semantic headings for product names, not styled `div`s. |
| Focus states | Visible focus ring on every interactive element — Tailwind's `focus-visible:` variants, never suppressed. |
| Color contrast | WCAG AA minimum (4.5:1 for body text) — checked against the chosen palette before shipping, especially for `stock_status`/badge text on colored backgrounds. |
| Form labels | The chat input has a visually-hidden `<label>`; cart quantity steppers are labeled per row ("Quantity for AeroCase Pro"), not generically. |
| Button semantics | `<button>` for actions, `<a>` only for navigation — no `<div onClick>` anywhere, which also keeps keyboard support free rather than hand-rolled. |
| Error messages | Associated with their field via `aria-describedby`; policy/payment failures announced via the same live region as chat messages. |
| Reduced motion | Per §10 — every animation has a no-motion fallback. |
| Chat accessibility | Message list is a `role="log"` region; each turn is a discrete, focusable item so a screen-reader user can review history without re-hearing the whole conversation. |

---

## 14. Security Boundaries

Restated as an explicit "must never contain" list, per the brief's request:

| Must never appear in frontend code, bundle, or network-visible request | Where it actually lives |
| --- | --- |
| `RAZORPAY_KEY_SECRET` | `app/config.py` (`SecretStr`), read only inside `app/payments/sdk.py` |
| `RAZORPAY_WEBHOOK_SECRET` | Same — used only in `app/services/webhook_service.py`'s HMAC check |
| `ANTHROPIC_API_KEY` | `app/llm/client.py`, the sole importer of the Anthropic SDK (an AST-walking test enforces this) |
| Database credentials | Never leave `app/db/session.py`'s engine construction |
| Webhook verification logic | `verify_signature()`, backend-only, over the raw body — a browser structurally cannot reproduce this even if it tried, since it never receives the webhook |
| Internal Policy Engine logic | `app/policy/engine.py` — pure, no network access, and specifically never imported by anything on the model/frontend-facing side (a standing backend test enforces this) |
| Authoritative payment state | `orders.status`, mutated only by the webhook handler |
| Sensitive user data | None currently collected — there's no identity/PII field anywhere in the schema; if one is added later (§20.D), it inherits this same rule |

**The correct architecture, restated:** every one of the above is a *backend-only* fact or secret.
The frontend's job is to ask the backend, receive an already-decided answer, and display it — never to
compute, store, or independently verify any of the above. This is not a frontend discipline to
maintain by convention; in most cases (secrets, webhook verification) the backend's own code makes it
structurally impossible for the frontend to do otherwise, which is the stronger guarantee.

---

## 15. Error / Edge Case UX

| Situation | Detection | UI behavior |
| --- | --- | --- |
| Backend unavailable | Fetch fails / network error | Full-page or inline "Can't reach the server right now" with a retry button; never a blank screen |
| AI unavailable / LLM timeout | `ChatResponse.error.code === "SERVER_ERROR"` (turn still `200`, per ADR-010) | Inline error bubble in the chat, "I couldn't process that. Please try again." — never a generic network-error UI, since the HTTP call itself succeeded |
| Invalid AI response | Zod validation fails on `ChatResponse` | Treated as `SERVER_ERROR` — logged for debugging, never shown to the buyer as raw validation output |
| No products found | `Recommendation.outcome === "NO_MATCH"` | Prose + "try different criteria," no empty grid |
| Compatibility failure | N/A — never surfaces as an error (§4.2) | — |
| Inventory changed (mid-cart) | `409 OUT_OF_STOCK` from `POST/PATCH /api/cart/items` | "This item is no longer available in that quantity" + link back to recommendations |
| Price changed (pre-approval) | `409 CART_VERSION_STALE` from `POST /api/cart/approve`, `details.current_version` | "Your cart changed — here's the current total" + re-fetch cart, re-show approval screen |
| Cart conflict | Same as above | Same |
| Policy rejection | `422 POLICY_FAILED` from `POST /api/orders`, `details.reason_codes[]` | One `PolicyFailureCard` per code present: `PRICE_CHANGED` → "price changed, review again"; `OUT_OF_STOCK` → "an item is no longer available"; `INVALID_CART`/`APPROVAL_REQUIRED` → "please approve your cart again"; `SPENDING_LIMIT_EXCEEDED` → "this order is above what we can process in one transaction"; `INVALID_PRODUCT`/`ORDER_ALREADY_EXISTS` → generic recovery ("go back to your cart") |
| Payment cancelled | Razorpay's own dismiss callback | "Payment not completed" + "Resume payment" (re-opens Checkout on the same order) |
| Payment failed | `OrderResponse.status === "PAYMENT_FAILED"` | "Payment failed" + retry |
| Payment pending / webhook delayed | `OrderResponse.status === "RAZORPAY_ORDER_CREATED"` past a grace period | "Verifying your payment…" — continue polling, do not show failure |
| Session expired / not found | `404` with `code: "VALIDATION_ERROR"`, message containing `SESSION_NOT_FOUND` | Clear the stored `session_id`, start a fresh conversation, brief "let's start over" notice |
| Network failure mid-payment | Checkout modal's own error handling (Razorpay-side) + order stays queryable by `order_id` | On return, `GET /api/orders/{id}` re-establishes true state regardless of what the client-side flow believed |

Every message is written in plain language derived from the machine-readable code — never a raw
exception or database message, matching `architecture.md` §25's explicit example ("Bad: `IntegrityError:
duplicate key...` / Good: `We couldn't complete the order. Please try again.`"), which the backend
already guarantees on its side (F§25) by never emitting the former.

---

## 16. Performance

Kept proportionate to an MVP with ~32 SKUs and no deployment target yet (F5 is explicitly out of
scope) — nothing below is premature for the scale involved, and nothing further is recommended
because it would be.

- **Code splitting:** route-based only (`OrderStatusPage`, `OrderDetailPage` lazy-loaded) — Phase 1's
  single chat page has nothing to split.
- **Lazy loading:** product images below the fold (Phase 2's grids); the Razorpay Checkout script
  loaded on-demand at the point Checkout is actually about to open, not on initial page load.
- **Image optimization:** standard `srcset`/responsive images once real product imagery exists — the
  current seed catalog has no image assets, so this is speculative until that exists.
- **API caching:** TanStack Query's default cache does this for free (cart, order polling) —
  explicit `staleTime` tuning only if a real perf problem shows up, not preemptively.
- **Debouncing:** the chat composer needs none (explicit send); a Phase 2 search box would debounce
  input (~300ms) before firing a request.
- **Streaming:** not applicable — closed decision (§4.2).
- **Skeleton loaders:** per §10/§5 — used for recommendation grids and cart loads.
- **Pagination/infinite scroll:** only relevant to Phase 2's product listing; with 32 SKUs total, a
  single page with client-side filtering is likely sufficient and simpler than server pagination —
  revisit only if the catalog grows.
- **Avoiding unnecessary re-renders:** normal React hygiene (stable query keys, memoized card lists) —
  nothing exotic needed at this scale.

---

## 17. Testing Strategy

| Layer | Tool | Scope | Needs external services? |
| --- | --- | --- | --- |
| Unit | Vitest | `lib/money.ts`, `lib/errors.ts`, Zod schemas, pure hooks logic | No |
| Component | Vitest + React Testing Library + MSW | `RecommendationCard` renders every field in §4.5's table correctly incl. nulls; `PolicyFailureCard` renders the right copy per `reason_code`; `CartItemRow` interactions call the right endpoint with the right payload | No — MSW mocks the nine real endpoints with realistic fixtures generated from the actual Pydantic schemas |
| Integration | Vitest + RTL + MSW | Full page flows against mocked API: send message → see recommendations → add to cart → approve → see policy failure card for a scripted `PRICE_CHANGED` | No |
| E2E | Playwright | Real flows against a real running backend (dev DB, no real Razorpay key needed for most — `RazorpayClient` behind a fake in test config the same way the backend's own tests do) | **Yes, for the full price-drift/success scenarios** — needs the backend running with a database, exactly as `tests/integration/test_scenarios.py` already does server-side |
| Manual / sandbox-only | — | Actually opening Razorpay Test Checkout and completing a test payment | **Yes — a real Razorpay test-mode key**, per the credential gap already recorded in `PROGRESS.md` and `docs/implementation-status.md` |

**Scenarios to cover**, matching the brief's list, with the layer each belongs to:

- Product browsing → **blocked** until §20.C exists; not testable before then.
- AI interaction, recommendation rendering, compatibility display (i.e., its *absence* as a separate
  indicator, per §4.2) → component + integration.
- Add to cart, cart updates → component + integration.
- Approval → integration (mock a `409 CART_VERSION_STALE` and assert the recovery UI).
- Checkout / Razorpay integration boundary → **the boundary itself** (does `CheckoutLauncher` call
  `window.Razorpay` with exactly the config the backend returned, and nothing more?) is unit/component
  testable without any real Razorpay call; the actual payment is E2E/manual only.
- Payment status, order confirmation → integration (poll simulation via MSW) + E2E for the real thing.
- Error handling → component tests, one per row of §15's table.

---

## 18. Frontend File/Folder Structure

(Full component-level breakdown already given in §6; this is the top level.)

```
frontend/
├── src/
│   ├── api/            # one file per backend router + Zod schemas
│   ├── components/      # ui/, layout/, chat/, recommendations/, cart/, approval/, payment/, orders/
│   ├── hooks/
│   ├── lib/
│   ├── pages/
│   ├── state/
│   ├── types/
│   ├── App.tsx
│   └── main.tsx
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/             # Playwright specs
├── public/
├── index.html
├── vite.config.ts
├── vitest.config.ts
├── playwright.config.ts
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

`api/` and `components/` are the two directories that grow when the backend grows (§8.2's new
endpoints, §5's blocked pages) — everything else is stable regardless of which phase is being built.

---

## 19. Frontend Implementation Phases

Derived from the existing `FE-00`–`FE-07` / `INT-01`–`INT-10` plan in
`docs/analysis/04-task-breakdown.md` (already established, not invented here), extended only where
this brief's larger scope requires it — and every extension is marked as such.

| Phase | Goal | Depends on | APIs used | Tests | Acceptance |
| --- | --- | --- | --- | --- | --- |
| **F0** — Foundation & framework decision | Scaffold, decide Vite vs Next.js (**F6**, this doc recommends Vite in §2.1) | None | — | Build/lint/format run | App boots, hits `GET /api/health` |
| **F1** — CORS + design system | Backend CORS middleware (new, small); Tailwind/shadcn setup, design tokens from §12 | F0 | `GET /api/health` | Visual/component tests for primitives | A page from a different origin can call the API |
| **F2** — Chat core | `ChatWindow`, message list/input, session handling | F1 | `POST /api/chat` | Component + integration | User can converse; matches `architecture.md`'s own MVP exactly |
| **F3** — Recommendations | `RecommendationCard`/`Grid`, comparison view | F2 | (same, `recommendations[]`) | Component (§4.5's field table) | Cards render every real field correctly, including nulls |
| **F4** — Cart | `CartPanel`, item rows, summary | F3 | `GET/POST/PATCH/DELETE /api/cart*` | Component + integration | Never computes a total client-side |
| **F5** — Approval & policy failures | `ApprovalReview`, `PolicyFailureCard` | F4 | `POST /api/cart/approve` | Integration (scripted failures) | Every `reason_code` has distinct, correct UI |
| **F6** — Razorpay checkout | `CheckoutLauncher`, `PaymentStatus`, polling | F5 | `POST /api/orders`, `POST /orders/{id}/checkout`, `GET /orders/{id}` | Boundary unit tests + manual sandbox test | Matches this doc's §9 flow exactly; **manual test needs a real Razorpay test key (gap)** |
| **F7** — Order status/detail pages | `OrderStatusPage`, `OrderDetailPage` | F6 | `GET /api/orders/{id}` | Component + integration | Reachable via saved link; §3.2's delayed-webhook state handled |
| **F8** — Responsive & accessibility pass | Apply §11/§13 across F2–F7 | F7 | — | axe/manual audit, keyboard walkthroughs | WCAG AA contrast, full keyboard operability |
| **F9** — E2E & polish | Playwright for the flagship scenarios, animation pass (§10) | F8 | All of the above | E2E against a real backend+DB | Price-drift and success scenarios pass end-to-end from the UI |
| — *(Phase 1 complete here; matches architecture.md's stated MVP)* | | | | | |
| **F10** — Catalog browsing *(new backend work required, §20.C)* | `GET /api/products`, `/categories`, `/products/{id}`; `CatalogPage`, `ProductPage` | Backend: new routes | New endpoints | Component + integration | User can browse without ever opening chat |
| **F11** — Storefront shell & AI panel migration | `AppShell`, floating button, `<Sheet>`-based chat (Phase 2 of §4.1) | F10 | Same as F2–F9, relocated | Regression on F2–F9's tests | Chat still works identically, now alongside browsing |
| **F12** — Identity & order history *(new backend subsystem, §20.D)* | Whatever identity model is decided | Backend: auth design | New endpoints | New test suite | "My orders" is meaningful |
| **F13** — Merchant dashboard *(new backend subsystem, §20.D)* | Separate authenticated app/section | Backend: merchant auth + APIs | New endpoints | New test suite | Out of this document's detailed design — needs its own spec once the backend exists |

F0–F9 need **zero new backend work** beyond the CORS fix in F1. F10 onward each name their backend
dependency explicitly, per the brief's "do not invent backend functionality" instruction.

---

## 20. Gaps and Questions

### A. Already supported by the existing architecture
- Full conversational commerce loop: intent → ranked recommendations → cart → approval → policy →
  order → Razorpay → verified webhook → status.
- Every money value backend-computed and returned as a fixed-scale string.
- Structured, non-prose recommendation data (`recommendations[]`) separate from chat text.
- Machine-readable error/reason codes throughout (`ApiErrorCode`, `ReasonCode`).
- Idempotent order creation (safe to retry `POST /api/orders`).
- A verified-webhook-only payment truth model.

### B. Buildable immediately, no backend changes (beyond CORS)
- The entire chat-first Phase 1 experience: F2–F9 in §19.
- Comparison UI, upsell rendering, all approval/payment/error UI.

### C. Backend APIs that are missing
1. **CORS middleware** — blocks *everything*, not just the storefront. Trivial to add, but must be
   added before any frontend, of any scope, can call this API from a browser.
2. **Direct catalog browsing** (`GET /api/products`, `/api/categories`, `/api/products/{id}`) — blocks
   Home/Browse/Category/Search/Product-detail pages and the "search without AI" flow.
3. **Session creation without a message** (`POST /api/session`) — minor; lets a browsing user get a
   `session_id` before they've said anything to the agent, needed if Phase 2's storefront lets someone
   add to cart before ever opening chat.
4. **List orders for a session/identity** — blocks any "order history."
5. **A compatibility indicator on `Recommendation`**, if a visible "compatible with your device" badge
   is wanted beyond prose — currently compatibility is enforced but not exposed as a boolean field.
6. **A direct upsell-request endpoint/tool binding**, if upsells should be triggerable outside of the
   agent's own discretion during a turn.
7. **A `response_model` on `POST /orders/{id}/checkout`** — currently returns a plain `dict`; cosmetic,
   doesn't block anything, but means its shape isn't in the OpenAPI doc today.
8. **The entire merchant-facing API surface** — auth, catalog CRUD, inventory adjustment, an order
   list, an audit-log read endpoint. `AuditService.reconstruct_order`/`reconstruct_session` already
   exist and are fully capable; nothing routes to them.

### D. Architecture decisions that must be made before implementation
1. **F6 — Vite or Next.js.** This document recommends Vite (§2.1) and gives the reasoning; it's still
   your decision to confirm.
2. **Any buyer identity model at all**, if order history or a returning-user experience is wanted.
   `ADR-006` closed this as "no users table" for the MVP — reopening it is a real architectural
   decision, not a frontend one, and it should be made deliberately rather than backed into by
   frontend requirements.
3. **Merchant authentication and authorization model**, if the merchant dashboard is in scope at all
   for this phase of the project.
4. **Whether Phase 2 (storefront) is in scope now, or the MVP ships as Phase 1** — this is the single
   biggest scope decision, and it's yours (§0, §19).

### E. Potential contradictions between this brief and `architecture.md`
- The brief asks for a full storefront; `architecture.md`'s own frontend section explicitly says not
  to build one for the MVP. Addressed throughout via the Phase 1/Phase 2 split — not resolved
  unilaterally.
- The brief's UX section implies live, granular tool-execution status ("Searching catalog…
  Comparing options…"); the backend has no mechanism to stream that (no streaming at all, ADR-010),
  so this is designed as a single bounded state instead (§4.2, §4.4), not the granular version.

### F. Security concerns
- No CORS today means, once fixed, its configuration (allowed origins) needs to be deliberately
  scoped — not `allow_origins=["*"]` — even in an MVP, since the API mints and trusts `session_id`
  values with no other authentication.
- `session_id` is currently the *only* thing standing between "this is my cart" and "this is anyone's
  cart" — it's an unguessable UUID, but there's no rate-limiting or session-fixation protection
  visible in the backend today. Not necessarily wrong for an MVP demo, but worth being aware of before
  any real deployment (which F5 already puts out of scope).

### G. UX concerns
- Polling for payment status (§9) is simple and correct but not instant — a buyer staring at
  "Verifying your payment…" for 10–30 seconds needs that state to feel calm and expected, not broken
  (addressed in §4.3's copy, but worth testing with real latency, not just mocks).
- The "thinking" indicator's rotating phrases (§4.4) are cosmetic; if overused or too specific
  ("Checking compatibility…" when no such tool ran this turn), they'd misrepresent what happened —
  keep them generic.

### H. Should NOT be implemented in this MVP
- Token-by-token streaming (closed decision, ADR-010/F7).
- Any client-side price/total computation, ever, for any UI convenience — always refetch.
- A merchant dashboard before its backend subsystem exists (§20.C.8, §20.D.3).
- Internationalization/localization beyond English/INR (F10, explicitly out of scope).
- Real payment-provider integration testing in CI — sandbox/manual only (§17).

---

## 21. Recommended Next Step

Two decisions unblock everything else, and neither requires writing frontend code to make:

1. **Confirm the framework** (§2.1's Vite recommendation, or override it) and **add CORS middleware**
   to the backend — a few lines, and the one thing that blocks every subsequent step regardless of
   which scope is chosen.
2. **Decide the scope**: ship Phase 1 (the conversational-commerce MVP exactly as `architecture.md`
   itself specifies, buildable today with zero further backend work beyond #1) and treat Phase 2 (the
   full storefront this brief also describes) as a deliberately sequenced follow-on once §20.C's
   catalog-browsing endpoints exist — or commit to building both together now, accepting that the
   backend work in §20.C and §20.D needs to happen first or in parallel.

Once you've reviewed this and told me which way to go on both, the next concrete unit of work is
**F0**: scaffold the frontend project and wire the CORS fix — nothing else, so the very first thing
built is verified working end-to-end against the real API before anything else is layered on top.

**No frontend or backend code has been written or modified to produce this document.**
