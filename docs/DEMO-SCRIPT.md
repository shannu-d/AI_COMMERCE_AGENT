# Demo video script (~4 minutes)

Record with all four services up (see `RUNBOOK.md`). Keep a terminal visible for
the audit-trail and MCP moments.

---

## 0. Frame (10s)

> "EASY BUY — a merchant made transactable by AI, on Razorpay. One rule runs
> through every layer: the LLM proposes, the application validates, the user
> authorises, Razorpay executes, a verified webhook confirms, the system audits."

---

## 1. Conversational checkout — the happy path (75s)

1. `http://127.0.0.1:5173`. In the chat: **"I need a rugged case for an iPhone 16 under ₹1500."**
2. Point out: the short reply is prose; the **product cards are on the Smart Agent surface**, chosen and ordered by a **deterministic ranking engine** — each card shows the engine's reason ("Best overall", "Best price"). *The model never set a price or picked the winner.*
3. Add the top result to cart. Point at the total: **"this number is the backend's — nothing in the frontend adds up line items."**
4. Approve — the dialog submits the exact `cart_version` and total on screen.
5. **Pay now** → real **Razorpay Checkout** opens. Pay with **Netbanking → Success** (or UPI `success@razorpay`).
6. Order page: **"Verifying your payment"** → wait → **"Payment confirmed."**
   > "That flip happened because Razorpay sent a signature-verified webhook — not because the browser said so."

---

## 2. The audit trail (30s)

In the terminal, show the order's audit rows (or the merchant Orders page):

```
ORDER_CREATED (SYSTEM) → RAZORPAY_ORDER_CREATED (SYSTEM)
→ PAYMENT_WEBHOOK_RECEIVED (RAZORPAY) → PAYMENT_CONFIRMED (RAZORPAY)
```

> "Every money action, attributed. This reconstructs the whole transaction."

---

## 3. One failure, handled gracefully — price drift (45s)

1. Start a new cart, add an item, **approve** it.
2. Switch to the **merchant dashboard** (`/merchant`, signed in) → change that product's price.
3. Back to the buyer → **Pay now**.
4. The Policy Engine re-reads live price inside the order transaction → the order is **refused** with `PRICE_CHANGED`, the Razorpay order is **never created**, and the buyer is sent back to re-approve with a fresh idempotency key.
   > "No order is ever created at an amount nobody approved — in either direction, cheaper or dearer."

*(Optional second failure: an international test card → Razorpay declines → a real `payment.failed` webhook → order `PAYMENT_FAILED`, cart intact.)*

---

## 4. Sellable to an AI buyer — the MCP server (60s)

Open an MCP client (Claude Desktop, MCP Inspector, or a script) pointed at
`python -m app.mcp`.

1. `search_catalog("rugged case", category="phone_case", max_price="1500.00")`
   → ranked results, same engine, with reasons and scores.
2. `create_quote(items=[{"sku": "CASE-IP16-BLK", "quantity": 1}])`
   → `{"quote_reference": "...", "total": "999.00"}`.
   > "The total is the merchant's. The buyer's agent can only confirm it."
3. `authorize_and_pay(quote_reference, authorized_amount="1.00")`
   → `{"status": "rejected", "code": "TOTAL_CHANGED", "current_total": "999.00"}`.
   > "The authorisation names the amount — an AP2-style mandate. Wrong amount, no charge."
4. `authorize_and_pay(quote_reference, authorized_amount="999.00")`
   → a real Razorpay order + `pay_url`.
5. `get_order_status(order_id)` → `paid: false` until the webhook.
   > "Same invariant, same Policy Engine, same webhook truth — over a standard protocol, no browser."

---

## A. Prompt bank — what to type, and what you will get

Every line below was **run against the live agent and the live catalogue** on
2026-09-05. The counts are what the ranking engine returns, so they are stable
unless the merchant edits stock or prices. Nothing here needs the model to
cooperate for the *numbers* to be right — the model chooses the tool arguments,
the engine chooses the products.

`RANKING_TOP_K=9`, so a category with more matches shows up to nine cards.

> **Refreshed 2026-09-05 for the electronics-only catalogue** (200 products / 360 SKUs).
> Every row below was run live against it on the day.

### The reliable openers

| Type this | You get | Good for showing |
| --- | --- | --- |
| **Show me a 5G phone under 30000** | **9 cards** — CoreWave Go 5G ₹12,999 up to Nova X5 Pro ₹27,999 | A boolean attribute *and* a budget as hard filters. The 4G Nova Lite is excluded even though it is cheaper |
| **I need a phone with 256GB storage** | **8 cards**, every one a 256GB variant | A variant-level attribute eliminating rather than ranking |
| **I need a laptop with 16GB RAM and 512GB SSD** | **5 cards** — CoreWave Office 14 ₹46,999 to ByteCore Studio 14 ₹89,999 | Two required attributes at once |
| **I need a 20000mAh power bank** | **4 cards** — PowerCell 20000 PD and Solar 20000 | A numeric attribute as a stated requirement |
| **Show me a 144Hz gaming monitor** | **2 cards** — Nexa View 27 (165Hz) and 25 Pro (240Hz) | A minimum, not an equality: faster panels still qualify |
| **I need a 65W charger** | **2 cards** — VoltEdge 65W GaN, black and white | The wattage filter on the original accessory range |
| **I need a case for my iPhone 16** | **5 cards** — AeroCase Pro Black ₹999 (Best overall), Blue ₹999, ShieldCase Premium ₹1,299, LeatherLine Folio Black / Brown ₹1,799 | The core loop. The Clear AeroCase is **out of stock and correctly absent**, and the iPhone **15** case never appears |
| **a fast charger for my iPhone 16 under 1500** | **2 cards** — VoltEdge 20W ₹1,099, VoltEdge 30W ₹1,499 | A budget as a hard ceiling *and* device compatibility, together. The ₹2,799 MacBook charger is compatible but over budget, so it is excluded |
| **earbuds with noise cancelling** | **2 cards** — SonicBuds Pro ANC Black and Ivory, ₹4,499 | The F-3 fix. The catalogue holds five earbuds; only these two have `anc: true`. The other three are **not** offered and **not** described as noise-cancelling |
| **Show me headphones** | up to **9 cards** — SoundSeal Lite ₹2,499 to SoundSeal Max ANC ₹24,999 | Top-K at 9, and the price ladder inside one category |
| **a case for my Pixel 9** | **0 cards**, and an honest "I couldn't find one" | The no-match path. Pixel 9 is a **resolvable** device with zero compatible products — the agent does not substitute, and names no product |

### If you want more variety

Verified as catalogue facts (in stock, compatible), so they will produce cards:

| Prompt | Expected |
| --- | --- |
| Find a Wi-Fi 6 router | routers, cheapest first — see the caveat below |
| Show me a mechanical keyboard | KeyCraft Mech TKL, Compact 60, Nexa Strike 75 |
| Find an SSD for my laptop | ByteCore Portable and Rugged SSD, 500GB–4TB |
| Show me smartwatches under 7000 | Pulse Band Lite ₹1,999, Pulse Fit 2 ₹2,999, Pulse Active GPS ₹6,999 |
| I need a USB-C hub for my laptop | HyperLink Hub 7, Hub Mini, Dock Dual |
| a screen protector for my iPhone 16 | 3 cards, ₹299–₹649 |
| a charger for my MacBook Air M3 | 3 cards, ₹2,799–₹3,999 |
| a sleeve for my MacBook Air M3 | 2 cards, ₹1,199 |
| a USB-C cable | 3 cards, ₹499–₹999 |
| a power bank with USB-C | 4 cards, ₹1,299–₹3,299 |
| show me speakers / keyboards / storage | up to 9 cards each |

### The two-turn narrowing (good on camera)

1. **I need a charger** → the agent asks which device, because the answer changes
   what you pay. It does **not** guess.
2. **for my iPhone 16, under ₹1200** → one card, VoltEdge 20W ₹1,099.

### One caveat worth knowing

**"Wi-Fi 6 router" returns every router, cheapest first, not only the Wi-Fi 6 ones.** The tool
payload advertises six attribute names per category — Groq refuses any single request over 8,000
tokens and the full list does not fit — and `wifi_standard` falls outside the six for routers, so
the agent states it as free text, which ranks rather than eliminates (R§9). Under-filtering is the
intended failure direction (prompt rule 9), and nothing false is claimed, but you will see Wi-Fi 5
routers in the list. Prefer the openers above on camera.

### What to avoid on camera

- **Anything you have not tried on the day.** The model picks the tool arguments;
  the catalogue decides the rest. A phrasing you have not run is the one that
  asks a clarifying question in the middle of your take.
- **Rapid-fire turns.** See the pacing note below.
- **"Add both to my cart" in the same breath as a search.** Ask for products,
  *then* add — the agent is instructed not to build a cart you did not ask for
  (system prompt 1.4.0, rule 11).

## B. Pacing, and the rate limit that will bite you

The Groq account is on the free `on_demand` tier: **8,000 tokens per minute** and
**200,000 tokens per day, per model**. One agent turn is two model calls totalling
roughly **9,000 tokens** — more than the per-minute allowance, so:

- **Every turn pauses ~13 seconds mid-way** while the client waits out the
  per-minute bucket. That is the application obeying the provider's own
  `retry-after`, not a hang. Expect 15–25 seconds per answer and plan the edit.
- **You get about 22 turns per day, per model.** Rehearsing burns the same budget
  as recording.
- When the daily budget is gone, a turn **fails fast** with "I could not reach the
  assistant just then" rather than hanging.

Two levers when you run out:

1. **Switch model.** The daily quota is *per model*, and `GROQ_MODEL` is
   configuration. `openai/gpt-oss-20b` and `openai/gpt-oss-120b` each have their
   own 200,000. Change `.env`, restart the backend. Both were verified against the
   prompt bank above.
2. **Rehearse without the agent.** The storefront, cart, approval, Razorpay
   Checkout, order page and the whole merchant dashboard cost **no model tokens
   at all**. Only `/api/chat` does. Block out the take on those, and spend the
   agent turns on the recording.

---

## 5. Close (15s)

> "Bounded, gated, explainable, audited — for a human's assistant and for an
> autonomous AI buyer. Built on Razorpay test mode, with the failure paths shown
> working, not hidden."
