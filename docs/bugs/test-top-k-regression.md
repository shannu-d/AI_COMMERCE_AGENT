# Bug — Test Suite Regression When Default Top-K Recommendations Increased to 9

**Date:** September 5, 2026  
**Time:** 11:36:54 +0530

### Question

When the configured number of recommendations per product type (`RANKING_TOP_K`) was raised from 3 to 9 to support a richer storefront UI, did all existing recommendation unit tests continue to pass?

### What I Expected

I expected the test suite to pass cleanly or adapt to the configured `ranking_top_k` setting, asserting that the recommendation engine respects its configured limit rather than a hard-coded integer.

### What Actually Happened

During our audit test run with `TEST_DATABASE_URL` against PostgreSQL, `tests/services/test_recommendation_service.py::test_top_k_caps_the_result_at_three` failed:

```
tests/services/test_recommendation_service.py:140: in test_top_k_caps_the_result_at_three
    assert len(result.candidates) <= 3
E   AssertionError: assert 8 <= 3
E    +  where 8 = len((RankedCandidate(rank=1, ...), ...))
```

The recommendation service returned 8 matching candidates (all compatible in-stock phone cases under the ₹1,500 budget), but the test expected at most 3!

### Why Was This a Problem?

This was a classic regression where production configuration was updated, evals were updated, but a service unit test was left with a stale hard-coded assertion. Anyone running the full test suite against PostgreSQL encountered a failure in what is supposed to be clean baseline code.

### Root Cause

In commit `9413bb5` (`feat(ranking): return up to 9 recommendations per product type, not 3`), the developer changed the default `ranking_top_k` in configuration from 3 to 9 to allow the UI to display more candidate cards.
The developer updated `backend/tests/evals/graders.py` to resolve `"configured_top_k"` from `Settings.ranking_top_k`:
```python
if high == "configured_top_k":
    from app.config import get_settings
    high = get_settings().ranking_top_k
```
However, the developer overlooked `tests/services/test_recommendation_service.py:140`:
```python
def test_top_k_caps_the_result_at_three(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    result = recommendations.recommend(merchant_id, case_under_1500(iphone_16))
    assert len(result.candidates) <= 3  # HARD-CODED 3!
```
Because the catalog contained 8 compatible variants under ₹1,500, the engine obeyed its configured limit of 9 and returned all 8, breaking the test's assumption of `<= 3`.

### Decision

We must update `test_top_k_caps_the_result_at_three` to test what the function actually guarantees: that the candidates count is bounded by `settings.ranking_top_k` (or pass an explicit `top_k=3` parameter to verify the parameter override).

### Fix

Update `backend/tests/services/test_recommendation_service.py` so that `test_top_k_caps_the_result_at_three` asserts against `get_settings().ranking_top_k`, or explicitly tests `top_k` parameter slicing.

### Verification

Ran pytest on `tests/services/test_recommendation_service.py`:
Observed failure: `assert 8 <= 3`.
Directly reproduced in the test runner.

### Result

FAIL / REGRESSION. Confirmed reproducible failure in current repository state.

### Evidence

- Git commit: `9413bb5 feat(ranking): return up to 9 recommendations per product type, not 3`
- File: [`backend/tests/services/test_recommendation_service.py`](file:///l:/AI_COMMERCE/backend/tests/services/test_recommendation_service.py#L134-L141)
- Reproduction command: `backend/.venv/Scripts/python.exe -m pytest tests/services/test_recommendation_service.py::test_top_k_caps_the_result_at_three`
