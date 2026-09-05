# Bug History

This directory documents real bugs, regressions, and engineering failures discovered and resolved across the development and integration lifecycle of the Merchant AI Commerce Agent.

Every report follows the human incident report standard: detailing the engineering question, what was expected, what actually happened, root cause, architectural decisions made, fix implementation, and reproducible regression test evidence.

| ID | Area | Bug | Severity | Status | Test |
|
> **Test citations in this table were re-verified against the repository on 5 September 2026.**
> Four of them named tests that do not exist and have been corrected; where a fix has no direct
> automated test, the row says so rather than naming one. Every remaining citation resolves to a
> real test — checked with `grep -rl` over `backend/tests` and `frontend/src/test`.

---|---|---|---|---|---|
| [BUG-001](undeclared-razorpay-dependency.md) | Payments | Undeclared `razorpay` package dependency blocked live checkout | CRITICAL | FIXED | No direct test — `razorpay>=1.4` is declared in `backend/pyproject.toml`; verified by a live test-mode checkout |
| [BUG-002](price-drift-approval-rollback-loop.md) | Policy Engine | `POST /api/cart/approve` rolled back legitimate re-pricing on stale cart version | CRITICAL | FIXED | `backend/tests/integration/test_scenarios.py::test_price_drift_recovers_through_a_fresh_approval` |
| [BUG-003](order-ownership-session-hijacking.md) | Security / Auth | Customer order ownership lost and session hijacked by merchant login | HIGH | FIXED | `backend/tests/api/test_account.py::test_an_order_placed_on_a_session_that_was_anonymous_still_reaches_the_account`, `backend/tests/api/test_auth.py::test_a_merchant_sign_in_does_not_claim_a_shopping_session` |
| [BUG-004](non-hermetic-test-suite-live-payments.md) | Testing / Payments | Non-hermetic test suite triggered live Razorpay API calls during pytest runs | HIGH | FIXED | `backend/tests/api/test_orders.py::test_the_razorpay_id_is_null_until_m11` |
| [BUG-005](add-to-cart-anonymous-session.md) | Frontend / Cart | Add-to-cart button permanently disabled on fresh browser visits | HIGH | FIXED | No direct test for the button state — the session-recovery path is covered by `frontend/src/test/agent-runtime.test.tsx` |
| [BUG-006](llm-rate-limit-retry-exhaustion.md) | AI Agent / LLM | Sub-second LLM rate limit retries exhausted token quota in two seconds | HIGH | FIXED | `backend/tests/llm/test_client.py::test_a_rate_limit_waits_the_interval_the_provider_named` (+3 sibling cases) |
| [BUG-007](chat-cart-serialization-mismatch.md) | API / Cart | Inconsistent cart serialization caused browser to discard turns with `MALFORMED_RESPONSE` | HIGH | FIXED | `backend/tests/api/test_frontend_contract.py::test_a_serialized_cart_carries_every_field_the_frontend_requires` |
| [BUG-008](search-catalog-tool-parameters-f3.md) | AI Agent / Tooling | Undescribed tool schema treated hard search requirements as soft preferences (F-3) | HIGH | FIXED | `backend/tests/evals/test_commerce_evals.py::test_case[spec_004]` |
| [BUG-009](stale-session-storage-deadlock.md) | Frontend / State | Stale session storage deadlocked assistant chat on rebuilt database | HIGH | FIXED | `frontend/src/test/agent-runtime.test.tsx::starts a fresh session when the backend no longer accepts the stored one` |
| [BUG-010](unsolicited-agent-cart-creation.md) | AI Agent / Prompt | Agent built and proposed an unsolicited cart on exploratory queries | MEDIUM | FIXED | No automated test — system prompt 1.4.0 rule 11; verified by a live turn recorded in `docs/DEMO-SCRIPT.md` |
| [BUG-011](ambiguous-orm-category-foreign-keys.md) | Database / Schema | Ambiguous foreign keys between products and categories caused mapper crash | MEDIUM | FIXED | `backend/tests/db/test_catalog_schema.py::test_every_orm_relationship_resolves` |
| [BUG-012](missing-cors-and-pydantic-config-crash.md) | API / Config | Missing CORS middleware and Pydantic comma-list parsing startup crash | HIGH | FIXED | `backend/tests/test_config.py` |
| [BUG-013](test-top-k-regression.md) | Recommendation | Test suite regression in `test_top_k_caps_the_result_at_three` after default top_k increased to 9 | MEDIUM | REGRESSION | `backend/tests/services/test_recommendation_service.py::test_top_k_caps_the_result_at_the_configured_number` |
| [BUG-014](catalog-seed-constraint-key-error.md) | Catalog Data | Incomplete catalog seed replacement caused constraint `KeyError: 'wattage'` and broken category contract | HIGH | CONFIRMED BUG | `backend/tests/seed/test_catalog_seed.py::test_every_constraint_predicate_is_satisfied_by_its_own_product` |
| [BUG-015](llm-prose-hallucination-f1.md) | AI Agent | Assistant natural-language prose hallucinates fabricated SKUs and prices (F-1) | HIGH | CONFIRMED BUG (OPEN) | `backend/tests/evals/test_commerce_evals.py::test_case[halluc_003]`, `test_case[inject_001]` |

---

## Potential Issues

These items represent credible architectural and operational risks identified during code inspection and audit, but were not classified as confirmed bugs because they either reflect intentional design deferrals or could not be reliably reproduced as runtime defects:

1. **F-2: Basket-Budget Combination Unreachable by Agent Tools**
   - **Area:** Recommendation / Agent Tooling
   - **Risk:** `RecommendationService.combine(total_budget=...)` implements a knapsack-style basket optimizer to maximize utility across multiple product requirements within an aggregate spending cap. However, `app/llm/tools/definitions.py` exposes no tool schema through which the LLM can express an aggregate multi-category basket budget in a single call. A buyer asking "find me a case and a charger under ₹2,000 total" must rely on the individual item budget parameters or the final spending limit validation at checkout.
   - **Classification:** Potential Issue — Not Reproduced (Design Gap / Deferred Feature).

2. **Stale Settings via `@lru_cache` in Long-Running Worker Processes**
   - **Area:** Configuration Management / Operations
   - **Risk:** `app.config.get_settings()` is memoized using `@lru_cache(maxsize=1)`. In production environments or local long-running Uvicorn processes, modifying environment variables or the `.env` file does not invalidate the cached settings instance. During the readiness audit, a stale webhook secret in a cached process led to initial webhook signature rejections until the process was restarted.
   - **Classification:** Potential Issue — Not Reproduced (Documented Operational Behavior: process restart required on configuration changes).

3. **Absence of End-to-End Headless Browser Automation (Playwright / Cypress)**
   - **Area:** Testing Infrastructure
   - **Risk:** The repository features 1,713 backend tests and 71 React unit tests, yet all four browser walkthrough bugs (BUG-005, BUG-006, BUG-007, BUG-009) went undetected until a human drove an empty browser session manually. Without automated end-to-end browser testing against a live backend, client-side session initialization regressions remain a latent risk.
   - **Classification:** Potential Issue — Not Reproduced (Infrastructure Recommendation R9).
