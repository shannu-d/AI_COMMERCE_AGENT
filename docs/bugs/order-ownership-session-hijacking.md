# Bug — Order Ownership Loss and Session Hijacking by Merchant Login

**Date:** September 5, 2026  
**Time:** 08:41:55 +0530

### Question

When an anonymous buyer builds a cart, places an order, and signs into their customer account, does their order appear under their account history, and does a merchant signing in from the same browser corrupt session ownership?

### What I Expected

1. An order placed by a customer on an anonymous session should become linked to that customer's user account once they register or log in, appearing under `GET /api/account/orders`.
2. A merchant administrator signing in at `/merchant` should never claim or hijack a shopper's consumer session.

### What Actually Happened

During browser walkthrough testing, an order placed by a buyer never appeared under **Account -> Orders**. Even worse:
When a merchant administrator logged into the admin dashboard on the same machine, the merchant's login stole the anonymous session! Because `/api/account/orders` explicitly returns HTTP 403 Forbidden for merchant accounts, the order became an orphan owned by a merchant user who was forbidden from ever querying it. The actual buyer saw zero orders.

### Why Was This a Problem?

This was a serious security and state integrity failure. Customer orders were lost from the buyer's portal, and merchant administrators could inadvertently seize consumer shopping sessions, creating an access-control deadlock where no user could view the order.

### Root Cause

The flaw had two interlocking root causes:
1. **Derived Ownership Without Re-linking:** Order ownership was never written as a column on `orders`. Instead, it was dynamically derived via `orders.session_id -> sessions.user_id`. If an order was placed while the session was anonymous (`sessions.user_id IS NULL`), that order remained permanently unlinked unless the session itself was claimed before or during order creation.
2. **Indiscriminate Session Claiming:** `POST /api/auth/login` claimed any submitted session ID regardless of the authenticated user's role:
   ```python
   # Old buggy code:
   if session_id:
       SessionService(db).claim_session(merchant_id, session_id, user.id)
   ```
   Even if `user.role == "merchant"`, the consumer session was claimed for the merchant ID.

### Decision

We established two structural rules:
1. `POST /api/auth/login` must only claim an anonymous session if the user's role is strictly `customer`. A merchant sign-in must leave consumer shopping sessions completely untouched.
2. `POST /api/orders` (and `OrderService.create_order`) must automatically claim an anonymous session for the authenticated customer if the caller presents a customer bearer token at order creation time.

### Fix

In commit `4ae0390`:
1. Updated `app/api/routes/auth.py` in `login()`:
   ```python
   if payload.session_id and user.role == "customer":
       SessionService(db).claim_session(merchant_id, payload.session_id, user.id)
   ```
2. Updated `app/api/routes/orders.py` in `create_order()`:
   ```python
   if current_user and current_user.role == "customer":
       SessionService(db).claim_session(merchant_id, request.session_id, current_user.id)
   ```

### Verification

Two new regression tests were added and verified against PostgreSQL:
1. `tests/api/test_auth.py::test_merchant_login_does_not_claim_session`: Asserts that when a merchant logs in with a session ID, `sessions.user_id` remains `NULL`.
2. `tests/api/test_account.py::test_an_order_placed_on_an_anonymous_session_appears_after_sign_in`: Asserts that an order created anonymously is visible in `GET /api/account/orders` once the customer signs in.

### Result

PASS. Both tests pass, and browser verification confirmed that an order placed while signed in as `demo@easybuy.test` appears under **Account -> Orders**.

### Evidence

- Git commit: `4ae0390 fix(auth): a buyer's order reaches the buyer's account`
- Files: [`backend/app/api/routes/auth.py`](file:///l:/AI_COMMERCE/backend/app/api/routes/auth.py), [`backend/app/api/routes/orders.py`](file:///l:/AI_COMMERCE/backend/app/api/routes/orders.py)
- Regression tests:
  - [`backend/tests/api/test_auth.py::test_merchant_login_does_not_claim_session`](file:///l:/AI_COMMERCE/backend/tests/api/test_auth.py#L182-L195)
  - [`backend/tests/api/test_account.py::test_an_order_placed_on_an_anonymous_session_appears_after_sign_in`](file:///l:/AI_COMMERCE/backend/tests/api/test_account.py#L95-L125)
