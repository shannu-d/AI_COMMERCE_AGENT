# Bug — Undeclared razorpay Dependency Blocked Live Checkout

**Date:** September 4, 2026  
**Time:** 18:17:06 +0530

### Question

When we wire up valid Razorpay test keys and click "Pay" in the browser or trigger `POST /api/orders/{id}/checkout`, does the server successfully create a provider order and open Razorpay Checkout?

### What I Expected

I expected `POST /api/orders/{id}/checkout` to initialise the Razorpay client using our `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` from `.env`, call Razorpay's `/v1/orders` endpoint with the integer minor unit amount (e.g. ₹999.00 -> `99900`), and return `razorpay_order_id` along with Checkout options to the frontend.

### What Actually Happened

Checkout failed immediately with HTTP 503 `PAYMENT_PENDING`:

```json
{
  "code": "PAYMENT_PENDING",
  "message": "the razorpay package is not installed; install it to reach the provider"
}
```

The server completely refused to contact Razorpay.

### Why Was This a Problem?

This was a total blocker for the entire live payment workflow. The frontend was ready, the database order had been created in `ORDER_CREATED` status, the user had explicitly approved the cart total, and real test credentials were in place. Yet no payment could be initiated or captured because the Python SDK wasn't available at runtime.

### Root Cause

The module `app/payments/sdk.py` was written to import `razorpay` inside a guarded try/except block:

```python
try:
    import razorpay
except ImportError:
    razorpay = None
```

When building milestone M11, the developer wrote the client code and unit-tested it against protocol doubles (`FakeRazorpayApi`), but forgot to add `razorpay` to the project dependencies in `backend/pyproject.toml`. To make matters worse, early documentation in `app/payments/sdk.py` and `PROGRESS.md` asserted that the failure was due to missing credentials (`RAZORPAY_KEY_SECRET is still REPLACE_ME`), which distracted everyone from the fact that real test keys were already configured in `.env` and the package simply wasn't installed.

### Decision

We decided to add `razorpay>=1.4` directly to the core application dependencies in `pyproject.toml` rather than keeping it optional or pretending mock doubles were sufficient for Buildathon submission.

### Fix

In commit `2dda5ff`, `backend/pyproject.toml` was updated to declare `razorpay>=1.4.1` in `[project.dependencies]`, and the environment was updated with `pip install -e .`.

### Verification

We verified the fix by starting the backend on port 8004, creating a test cart, approving it, and calling `POST /api/orders/{id}/checkout`. The application returned a live `order_TestModeXYZ` from Razorpay. Furthermore, a real Razorpay test-mode payment was completed end-to-end in the browser, triggering a signed webhook that updated the order to `PAYMENT_CONFIRMED`.

### Result

PASS. Razorpay order creation and Checkout opened properly without runtime import failures.

### Evidence

- Git commit: `2dda5ff feat(payments): declare the razorpay dependency; keep the suite hermetic at the payment boundary`
- File: [`backend/pyproject.toml`](file:///l:/AI_COMMERCE/backend/pyproject.toml)
- Pre-fix response: `503 {"code": "PAYMENT_PENDING", "message": "the razorpay package is not installed; install it to reach the provider"}`
- Post-fix live order verification recorded in [`docs/PROJECT_STATE.md`](file:///l:/AI_COMMERCE/docs/PROJECT_STATE.md) and [`docs/notes/bugs-found-during-development.md`](file:///l:/AI_COMMERCE/docs/notes/bugs-found-during-development.md) §A4.
