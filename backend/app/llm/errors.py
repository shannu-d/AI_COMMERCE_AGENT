"""What can go wrong at the model boundary, as types (L§46).

L§46 names six failure modes the runtime must handle deliberately — timeout,
API failure, rate limit, malformed model output, invalid tool call, tool
timeout — and requires *bounded* retries, a controlled timeout and a clear
failure response. Naming them as separate exceptions is what lets the caller
retry the transient ones and refuse the rest, rather than catching `Exception`
and guessing.

The division that matters is `is_transient`. A rate limit and a 502 are worth
retrying; a malformed intent, a bad API key and an invalid request are not, and
retrying them burns the buyer's latency budget to arrive at the same answer.

None of these ever reaches the buyer as-is. A§42 and F§25 require a structured
error with a code the frontend can act on, and never a Python traceback or a
provider error string. Mapping these onto that model is the agent runtime's job
(M5); this layer's job is to be precise about what happened.
"""

from __future__ import annotations

__all__ = [
    "LLMAuthenticationError",
    "LLMError",
    "LLMInvalidRequestError",
    "LLMOutputError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMTransportError",
]


class LLMError(Exception):
    """Base class for every failure at the model boundary.

    `is_transient` decides whether the client's bounded retry loop will try
    again. It is a property of the class, not of a caller's judgement, so the
    retry policy cannot drift from the taxonomy.
    """

    is_transient: bool = False


class LLMTransportError(LLMError):
    """The API could not be reached, or answered with a server error.

    Transient: a 502 from any HTTP service is worth one more attempt.
    """

    is_transient = True


class LLMTimeoutError(LLMTransportError):
    """The request exceeded `ANTHROPIC_TIMEOUT_SECONDS`.

    Transient, but bounded — L§46 is explicit that the agent "should not
    repeatedly retry indefinitely", and a buyer waiting on a chat turn notices
    every retry.
    """


class LLMRateLimitError(LLMTransportError):
    """The API rate limit was hit. Transient by definition.

    `retry_after` is the provider's own hint, in seconds, when it gave one.
    It matters because Groq's binding limit is a **per-minute token bucket**:
    an exponential backoff measured in fractions of a second cannot outlast a
    window that refills on the minute, so a turn whose two legs together exceed
    the bucket fails every attempt within a couple of seconds. Waiting the
    interval the provider named is the only retry that can succeed. `None`
    means it named none, and the caller falls back to its own backoff.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMAuthenticationError(LLMError):
    """The API key is missing, malformed or rejected.

    Never retried: the key will not become valid between two attempts. The key
    itself never appears in this exception's message — L§45 forbids a secret
    reaching a log line, and an exception message is a log line waiting to
    happen.
    """


class LLMInvalidRequestError(LLMError):
    """The request itself was malformed — a bad model name, an oversized prompt.

    Never retried: this is a bug in the caller, and repeating it repeats the bug.
    """


class LLMOutputError(LLMError):
    """The model answered, but not with something usable.

    Malformed JSON, a payload that fails schema validation, a missing tool call
    where one was required. Never retried *by the client*, because the client
    cannot know whether a second sample would differ; whether to re-prompt is a
    decision for the layer that knows what it asked for.

    This is the failure that must never become a fabrication. L§30 and A§41: the
    agent says it could not do the thing. It does not fill the gap from memory.
    """
