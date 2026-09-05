# Bug — Price-Drift Approval Rollback Infinite Loop

**Date:** September 1, 2026  
**Time:** 06:24:26 +0530

### Question

When the price of an item changes after a user has approved their cart, does `POST /api/cart/approve` allow the buyer to recover by refreshing and confirming the current version, or does it leave them trapped?

### What I Expected

When price drift occurs between approval and order placement, the user must be prompted to re-approve the updated price. I expected `POST /api/cart/approve` to re-price the cart against the authoritative catalog, update the cart's version, reject the stale version with HTTP 409 `CART_VERSION_STALE`, and persist the new version so that the user's next request can confirm the newly committed version.

### What Actually Happened

Price-drift recovery entered an infinite failure loop. Every time the buyer attempted to approve, the route recalculated the cart items at their new catalog prices, incremented `cart_version` (e.g. version 1 -> version 2), raised an `ApprovalError` because the incoming approval was based on version 1, and then rolled back the entire database transaction. 

Because the transaction was rolled back, the cart reverted to version 1 with the old price. On the buyer's next attempt to approve, the server saw the cart was still stale, bumped version 1 to 2 again, failed, and rolled back again. The user could never reach an approvable state.

### Why Was This a Problem?

This broke one of the most critical promises of the system: graceful recovery from price drift. If an item changed price while sitting in the cart, the buyer was permanently blocked from completing checkout unless they manually emptied their cart and started over from scratch.

### Root Cause

In `app/api/routes/cart.py`, the `approve_cart` endpoint wrapped the service call in a generic try/except block:

```python
try:
    approval = ApprovalService(db).approve(...)
except (ApprovalError, InvalidOperation) as error:
    db.rollback()
    raise _handle_approval(error) from error
```

The author treated all approval failures identically as failures requiring a rollback. But `ApprovalService.approve` performs two distinct operations:
1. It refreshes cart prices from the catalog and updates `cart_version` if prices moved.
2. It validates the user's submitted version against the current version.

Rolling back the transaction threw away the legitimate price refresh and version increment. Thus, the 409 response reported a `current_version` of 2, but the database actually remained at version 1!

### Decision

We decided that when `approve_cart` fails due to an `ApprovalError` (such as a version mismatch or price change), the database transaction must be **committed, not rolled back**. The catalog really did move, the cart items really do have new prices, and any prior approval really is invalidated. Committing ensures the database state matches the `current_version` returned in the HTTP 409 response.

### Fix

In commit `38232ea`, `app/api/routes/cart.py` was modified to separate `InvalidOperation` (malformed input, which rolls back) from `ApprovalError`:

```python
except InvalidOperation as error:
    db.rollback()
    raise _handle_approval(error) from error
except ApprovalError as error:
    # Committed, not rolled back:
    # The refresh is legitimate work: the catalog really moved,
    # and the cart really is at a new version.
    db.commit()
    raise _handle_approval(error) from error
```

### Verification

An end-to-end integration test was written in `backend/tests/integration/test_scenarios.py`:
1. Add item at ₹999.00 (version 1).
2. Approve version 1.
3. Update catalog price to ₹1,499.00 in database.
4. Place order with version 1 -> Blocked with HTTP 422 `POLICY_FAILED` (`PRICE_CHANGED`).
5. Call `POST /api/cart/approve` with stale version 1 -> Returns HTTP 409 `CART_VERSION_STALE` with `current_version: 2`.
6. Inspect `GET /api/cart` -> Persisted `cart_version` is 2, total is ₹1,499.00, `price_changes` is clean.
7. Call `POST /api/cart/approve` with version 2 -> HTTP 200 `APPROVED`.
8. Place order -> HTTP 201 `ORDER_CREATED` at ₹1,499.00.

### Result

PASS. The recovery path completes in exactly two deterministic turns.

### Evidence

- Git commit: `38232ea fix: let price-drift recovery reach a confirmable cart, and record the stopping point`
- File: [`backend/app/api/routes/cart.py`](file:///l:/AI_COMMERCE/backend/app/api/routes/cart.py)
- Regression test: [`backend/tests/integration/test_scenarios.py::test_price_drift_recovers_through_a_fresh_approval`](file:///l:/AI_COMMERCE/backend/tests/integration/test_scenarios.py#L169-L213)
