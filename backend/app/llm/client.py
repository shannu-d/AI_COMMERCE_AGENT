"""The Claude client (L§44, L§45, L§46).

The only module in the repository that imports the Anthropic SDK. Everything
else depends on the `LLMClient` protocol, which is what makes the rest of the
LLM layer testable with a three-line fake and no API key.

Three things this file is responsible for, in order of how badly they go wrong:

**Secrets never reach the model.** L§45's last bullet: credentials must "never
be included in LLM prompts". `_assert_no_secret_leaked` checks the outgoing
payload against every configured secret and refuses to send rather than
redacting, because a redacted prompt still means something upstream put a key
into a string that was on its way out of the process.

**Retries are bounded.** L§46: "The agent should not repeatedly retry
indefinitely." Only `LLMError.is_transient` failures are retried, at most
`max_retries` times, with the sleep injected so tests do not sleep.

**Provider errors do not escape as provider types.** Every SDK exception is
mapped onto `app.llm.errors`, so no caller ever catches `anthropic.APIError`
and no provider error string is ever on a path to the buyer (F§25).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

import anthropic

from app.config import Settings, get_settings
from app.llm.errors import (
    LLMAuthenticationError,
    LLMError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransportError,
)
from app.llm.models import Message, ModelResponse, StopReason, TokenUsage, ToolCall

logger = logging.getLogger(__name__)

__all__ = ["AnthropicClient", "LLMClient", "build_client"]

#: Anthropic's stop reasons, mapped onto ours. Anything absent becomes
#: `UNKNOWN` rather than `END_TURN`, so a provider change is visible instead of
#: silently reading as a complete answer.
_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "refusal": StopReason.REFUSAL,
}

#: Default ceiling on a single completion. Generous for a chat turn and an
#: intent object, small enough that a runaway generation fails fast.
DEFAULT_MAX_TOKENS = 2048


@runtime_checkable
class LLMClient(Protocol):
    """What the rest of the application needs from a model.

    Deliberately one method. A wider interface would be a wider surface for the
    probabilistic side of the boundary to reach through.
    """

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
    ) -> ModelResponse: ...


class AnthropicClient:
    """`LLMClient` backed by the Anthropic API.

    `temperature` defaults to `0.0` everywhere in this application. The model's
    output is an input to deterministic machinery — an intent object, a tool
    call — and sampling variety buys nothing there while making a failure
    harder to reproduce. It does not make the model deterministic, and nothing
    in the system relies on it doing so; determinism lives in the ranker
    (RULE 8), which the model cannot influence.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        secret_values: Sequence[str] = (),
        sleep: Callable[[float], None] = time.sleep,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise LLMAuthenticationError(
                "ANTHROPIC_API_KEY is not configured; set it in .env (never in code)"
            )
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        # Every configured secret, so a leak of *any* of them is caught here and
        # not only a leak of this one.
        self._secrets = tuple(value for value in secret_values if value)
        # The SDK's own retries are disabled: L§46 asks for one bounded policy,
        # and two nested retry loops multiply rather than bound.
        self._client = client or anthropic.Anthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **overrides: Any) -> AnthropicClient:
        settings = settings or get_settings()
        key = settings.anthropic_api_key
        return cls(
            api_key=key.get_secret_value() if key else "",
            model=settings.anthropic_model,
            timeout_seconds=float(settings.anthropic_timeout_seconds),
            max_retries=settings.anthropic_max_retries,
            secret_values=settings.secret_values(),
            **overrides,
        )

    # -- the one method --------------------------------------------------

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
    ) -> ModelResponse:
        if not messages:
            raise LLMInvalidRequestError("at least one message is required")

        self._assert_no_secret_leaked(system, messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = list(tools)
        if tool_choice:
            payload["tool_choice"] = tool_choice

        raw = self._send_with_retries(payload)
        return _to_model_response(raw)

    # -- bounded retry (L§46) ---------------------------------------------

    def _send_with_retries(self, payload: dict[str, Any]) -> Any:
        """At most `max_retries` extra attempts, transient failures only."""
        attempt = 0
        while True:
            try:
                return self._client.messages.create(**payload)
            except Exception as exc:  # mapped immediately; never re-raised raw
                error = _map_exception(exc)
                if not error.is_transient or attempt >= self._max_retries:
                    logger.warning(
                        "llm call failed",
                        extra={
                            "error": type(error).__name__,
                            "attempt": attempt + 1,
                            "transient": error.is_transient,
                        },
                    )
                    raise error from exc
                attempt += 1
                # Exponential, from a small base: a chat turn has a buyer
                # waiting on it, so the ceiling matters more than the curve.
                self._sleep(0.5 * (2 ** (attempt - 1)))

    # -- L§45 ---------------------------------------------------------------

    def _assert_no_secret_leaked(self, system: str, messages: Sequence[Message]) -> None:
        """Refuse to send a payload containing a configured secret.

        Refusal rather than redaction. A redacted prompt would still mean a key
        had been interpolated into a string that reached this boundary, and the
        next path out of the process might not redact. The exception names
        neither the secret nor its value.
        """
        if not self._secrets:
            return
        haystack = system + "\n".join(m.content for m in messages)
        if any(secret in haystack for secret in self._secrets):
            raise LLMInvalidRequestError(
                "refusing to send a prompt containing a configured secret (L§45)"
            )


def build_client(settings: Settings | None = None) -> LLMClient:
    """The client the application uses, constructed from configuration."""
    return AnthropicClient.from_settings(settings or get_settings())


# --------------------------------------------------------------------------
# Translation
# --------------------------------------------------------------------------


def _map_exception(exc: Exception) -> LLMError:
    """Map an SDK exception onto this application's taxonomy.

    Checked most specific first. `anthropic.APIStatusError` covers the 4xx and
    5xx families, and the split between them is the split between "the request
    was wrong" and "the service was", which is exactly the retry decision.
    """
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, anthropic.APITimeoutError):
        return LLMTimeoutError("the model did not respond within the configured timeout")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMRateLimitError("the model API rate limit was reached")
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        # Deliberately does not echo the provider message, which can quote the
        # offending key.
        return LLMAuthenticationError("the model API rejected the configured credentials")
    if isinstance(exc, anthropic.BadRequestError | anthropic.NotFoundError):
        return LLMInvalidRequestError(f"the model API rejected the request: {exc}")
    if isinstance(exc, anthropic.APIStatusError):
        return LLMTransportError(f"the model API returned {exc.status_code}")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMTransportError("could not reach the model API")
    return LLMTransportError(f"unexpected failure calling the model API: {type(exc).__name__}")


def _to_model_response(raw: Any) -> ModelResponse:
    """Flatten an SDK message into a `ModelResponse`.

    Text blocks are concatenated and tool-use blocks collected. Anything else
    the provider may add is ignored rather than guessed at.
    """
    texts: list[str] = []
    calls: list[ToolCall] = []
    for block in getattr(raw, "content", None) or ():
        kind = getattr(block, "type", None)
        if kind == "text":
            texts.append(getattr(block, "text", ""))
        elif kind == "tool_use":
            calls.append(
                ToolCall(
                    id=str(getattr(block, "id", "")),
                    name=str(getattr(block, "name", "")),
                    arguments=dict(getattr(block, "input", None) or {}),
                )
            )

    usage = getattr(raw, "usage", None)
    return ModelResponse(
        text="".join(texts),
        tool_calls=tuple(calls),
        stop_reason=_STOP_REASONS.get(str(getattr(raw, "stop_reason", "")), StopReason.UNKNOWN),
        usage=TokenUsage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        ),
        model=str(getattr(raw, "model", "")),
    )
