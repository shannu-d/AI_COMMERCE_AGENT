# Bug — Non-Hermetic Test Suite Triggered Live Razorpay API Calls During Test Runs

**Date:** September 4, 2026  
**Time:** 18:17:06 +0530

### Question

Does the automated test suite run completely hermetically in offline mode without reaching out to external third-party payment APIs when live credentials exist in `.env`?

### What I Expected

The test suite must be fully isolated from live third-party services. Running `pytest` should never trigger external network requests to Razorpay or mutate the merchant's live test account unless explicitly running dedicated live verification tests.

### What Actually Happened

As soon as real test-mode Razorpay credentials (`RAZORPAY_KEY_ID=rzp_test_...` and `RAZORPAY_KEY_SECRET=...`) were placed in the local `.env` file for integration testing, two standard unit/API tests began failing:
- `test_the_razorpay_id_is_null_until_m11`
- `test_an_approved_cart_creates_an_order`

Investigation showed that running `pytest` was actually invoking `POST /api/orders`, which saw the real credentials in configuration and initiated live HTTP requests to `api.razorpay.com` mid-suite! The tests failed because they expected `order.razorpay_order_id` to remain `None` (the M10 order creation state), but received a live `order_...` ID from Razorpay.

### Why Was This a Problem?

This violated testing hermeticity. If internet access was unavailable or slow, tests hung or failed. Furthermore, it polluted the live Razorpay test dashboard with throwaway test orders from every pytest invocation, and caused auth/account tests to slow down dramatically.

### Root Cause

Pydantic's `Settings` model in `app/config.py` hard-coded `.env` loading via `model_config`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR.parent / ".env",
        extra="forbid"
    )
```

Although `tests/conftest.py` set `os.environ["ENVIRONMENT"] = "test"`, Pydantic Settings still parsed the developer's `.env` file whenever `get_settings()` was instantiated. Thus, the application booted during tests with the live Razorpay keys instead of null or mock values.

### Decision

We decided to enforce hermetic isolation at the payment boundary directly in `tests/conftest.py`, ensuring `Settings` ignores `.env` during all standard test runs. Tests that specifically test live webhook verification or provider interactions must supply their own test secrets explicitly.

### Fix

In commit `2dda5ff`, `backend/tests/conftest.py` was updated to blank `env_file`:

```python
from app.config import Settings

# Blanking env_file here keeps the suite hermetic at the payment boundary:
Settings.model_config["env_file"] = None
```

In addition, mock LLM and payment clients were injected into the auth and account test fixtures to mirror the isolation in the chat tests.

### Verification

We verified the fix by running the full test suite with live credentials present in `.env`.
All order tests in `tests/api/test_orders.py` passed with `order.razorpay_order_id is None`, confirming zero external calls to Razorpay occurred during the run.

### Result

PASS. The test suite is completely hermetic at the payment and LLM boundaries.

### Evidence

- Git commit: `2dda5ff feat(payments): declare the razorpay dependency; keep the suite hermetic at the payment boundary`
- File: [`backend/tests/conftest.py`](file:///l:/AI_COMMERCE/backend/tests/conftest.py#L47-L50)
- Regression test: [`backend/tests/api/test_orders.py::test_the_razorpay_id_is_null_until_m11`](file:///l:/AI_COMMERCE/backend/tests/api/test_orders.py#L48-L56)
