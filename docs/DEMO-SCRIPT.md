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

## 5. Close (15s)

> "Bounded, gated, explainable, audited — for a human's assistant and for an
> autonomous AI buyer. Built on Razorpay test mode, with the failure paths shown
> working, not hidden."
