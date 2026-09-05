# Bug — Sub-Second LLM Rate Limit Retries Exhausted Token Quota in Two Seconds

**Date:** September 5, 2026  
**Time:** 08:41:37 +0530

### Question

When Groq's API responds with HTTP 429 Too Many Requests due to per-minute token bucket exhaustion, does the agent client wait out the cooldown period indicated by the provider, or does it fail prematurely?

### What I Expected

When the LLM provider rate-limits a request and returns a `retry-after` header or cooldown hint (e.g. "try again in 13.5s"), the application's retry loop should honour the provider's cooldown window, sleeping until the quota resets, up to a reasonable timeout cap, before completing the turn.

### What Actually Happened

During live browser testing, every multi-turn agent conversation crashed with an error presented to the user:
*"I could not reach the assistant just then."*

Logs showed that Groq returned HTTP 429 with:
`Rate limit reached for model openai/gpt-oss-120b in organization ... Limit: 8000 TPM. Please try again in 12.8s.`
Instead of waiting 12.8 seconds, the application's retry loop immediately retried after 0.5s, then after 1.0s. All 3 retries were exhausted in under 2 seconds — well within the same rate-limited minute.

### Why Was This a Problem?

Groq's free tier has an 8,000 tokens-per-minute (TPM) limit. Because our agent executes two sequential LLM calls per turn (leg 1: tool call proposal; leg 2: final answer synthesis) totalling ~9,200 tokens, leg 1 succeeded, but leg 2 consistently hit the 8,000 TPM ceiling. Retrying immediately meant 100% of second-leg calls failed, rendering the AI assistant unusable in live testing.

### Root Cause

In `app/llm/client.py`, the `GroqClient.complete()` method caught rate-limit errors and applied a standard hard-coded exponential backoff:
```python
# Old retry logic:
backoff = 0.5 * (2 ** attempt)  # 0.5s, 1.0s, 2.0s
time.sleep(backoff)
```
The client ignored the HTTP `retry-after` response header, as well as the provider's structured JSON error message detailing the required cooldown duration.

### Decision

We decided that:
1. `LLMRateLimitError` must extract and carry the provider's `retry-after` value (from the header if present, or parsed from the error message string via regex).
2. The client retry loop must sleep for the exact duration requested by the provider, bounded by `MAX_RETRY_AFTER_SECONDS = 45`.
3. If the requested cooldown exceeds 45 seconds (e.g. a daily quota limit of 20 minutes), it must fail immediately rather than making the user wait at a spinning loader for a hopeless retry.

### Fix

In commit `d7d801a`:
1. Added regex parsing in `app/llm/client.py` for `r"try again in ([0-9.]+)s"` and inspection of the `retry-after` header.
2. Updated `_retry_sleep()` in `app/llm/client.py` to sleep for `retry_after_seconds` when provided.
3. Added unit tests with mocked backoff sleep to assert that a hint of 8.772s is honoured and that waits > 45s fail promptly.

### Verification

Tested with live Groq calls:
- Sent query "recommend cases for iPhone 16".
- Leg 1 executed (4,600 tokens).
- Leg 2 received HTTP 429 asking for 13.2s.
- Client paused for 13.2s, retried, and succeeded.
- Full turn completed in ~18 seconds without user-facing errors.

### Result

PASS. The client successfully navigates provider rate-limit windows.

### Evidence

- Git commit: `d7d801a fix(llm): wait out a rate limit for the interval the provider named`
- File: [`backend/app/llm/client.py`](file:///l:/AI_COMMERCE/backend/app/llm/client.py)
- Regression tests:
  - [`backend/tests/llm/test_client.py::test_a_rate_limit_hint_in_the_header_is_honoured`](file:///l:/AI_COMMERCE/backend/tests/llm/test_client.py#L365-L375)
  - [`backend/tests/llm/test_client.py::test_a_rate_limit_hint_in_the_body_is_read_when_there_is_no_header`](file:///l:/AI_COMMERCE/backend/tests/llm/test_client.py#L376-L388)
