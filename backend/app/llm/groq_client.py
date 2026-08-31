"""The Groq client (provider-agnostic backend for LLMClient).

Implements the LLMClient protocol using Groq's API instead of Anthropic's.
This module is imported only when Groq is the configured provider.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

try:
    from groq import Groq
    from groq import APITimeoutError as GroqTimeoutError
    from groq import RateLimitError as GroqRateLimitError
    from groq import AuthenticationError as GroqAuthenticationError
    from groq import BadRequestError as GroqBadRequestError
    from groq import NotFoundError as GroqNotFoundError
    from groq import APIStatusError as GroqAPIStatusError
    from groq import APIConnectionError as GroqAPIConnectionError
except ImportError:
    raise ImportError(
        "Groq SDK not installed. Install it with: pip install groq"
    )

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

__all__ = ["GroqClient"]

#: Groq's stop reasons, mapped onto ours. Anything absent becomes
#: `UNKNOWN` rather than `END_TURN`, so a provider change is visible instead of
#: silently reading as a complete answer.
_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
}

#: Default ceiling on a single completion (same as Anthropic client)
DEFAULT_MAX_TOKENS = 2048


class GroqClient:
    """`LLMClient` backed by the Groq API.

    Mirrors the structure and behavior of AnthropicClient but uses Groq's SDK.
    Implements the same `LLMClient` protocol so it can be swapped in.
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
                "ANTHROPIC_API_KEY (Groq) is not configured; set it in .env (never in code)"
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
        self._client = client or Groq(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **overrides: Any) -> GroqClient:
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

        # Convert messages to Groq format and add system message
        groq_messages: list[dict[str, Any]] = [
            {"role": m.role, "content": m.content} for m in messages
        ]

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": groq_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Groq uses "system" in the message list, not as a separate field
        if system:
            groq_messages.insert(0, {"role": "system", "content": system})

        if tools:
            payload["tools"] = [_convert_tool_to_groq(tool) for tool in tools]
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
                return self._client.chat.completions.create(**payload)
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


# --------------------------------------------------------------------------
# Translation
# --------------------------------------------------------------------------


def _map_exception(exc: Exception) -> LLMError:
    """Map a Groq SDK exception onto this application's taxonomy.

    Mirrors the mapping in the Anthropic client but for Groq exceptions.
    """
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, GroqTimeoutError):
        return LLMTimeoutError("the model did not respond within the configured timeout")
    if isinstance(exc, GroqRateLimitError):
        return LLMRateLimitError("the model API rate limit was reached")
    if isinstance(exc, (GroqAuthenticationError,)):
        # Deliberately does not echo the provider message, which can quote the
        # offending key.
        return LLMAuthenticationError("the model API rejected the configured credentials")
    if isinstance(exc, (GroqBadRequestError, GroqNotFoundError)):
        return LLMInvalidRequestError(f"the model API rejected the request: {exc}")
    if isinstance(exc, GroqAPIStatusError):
        return LLMTransportError(f"the model API returned {exc.status_code}")
    if isinstance(exc, GroqAPIConnectionError):
        return LLMTransportError("could not reach the model API")
    return LLMTransportError(f"unexpected failure calling the model API: {type(exc).__name__}")


def _convert_tool_to_groq(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert an Anthropic-style tool definition to Groq format.

    Groq uses a slightly different structure for tool definitions.
    """
    # For now, pass through with minimal conversion
    # Groq's format is similar enough to Anthropic's for basic tools
    return tool


def _to_model_response(raw: Any) -> ModelResponse:
    """Flatten a Groq SDK completion into a `ModelResponse`.

    Text blocks are concatenated and tool-use blocks collected. Anything else
    the provider may add is ignored rather than guessed at.
    """
    texts: list[str] = []
    calls: list[ToolCall] = []

    # Groq returns choices with a message object
    choice = getattr(raw, "choices", [None])[0] if getattr(raw, "choices", None) else None
    if choice is None:
        return ModelResponse(
            text="",
            tool_calls=(),
            stop_reason=StopReason.UNKNOWN,
            usage=TokenUsage(input_tokens=0, output_tokens=0),
            model=str(getattr(raw, "model", "")),
        )

    message = getattr(choice, "message", None)
    if message is None:
        return ModelResponse(
            text="",
            tool_calls=(),
            stop_reason=StopReason.UNKNOWN,
            usage=TokenUsage(input_tokens=0, output_tokens=0),
            model=str(getattr(raw, "model", "")),
        )

    # Groq uses tool_calls for function calling (not tool_use blocks)
    content = getattr(message, "content", None)
    if content:
        texts.append(str(content))

    tool_calls_list = getattr(message, "tool_calls", None)
    if tool_calls_list:
        for tool_call in tool_calls_list:
            calls.append(
                ToolCall(
                    id=str(getattr(tool_call, "id", "")),
                    name=str(getattr(tool_call.function, "name", "")),
                    arguments=dict(getattr(tool_call.function, "arguments", None) or {}),
                )
            )

    usage = getattr(raw, "usage", None)
    return ModelResponse(
        text="".join(texts),
        tool_calls=tuple(calls),
        stop_reason=_STOP_REASONS.get(
            str(getattr(choice, "finish_reason", "")), StopReason.UNKNOWN
        ),
        usage=TokenUsage(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        ),
        model=str(getattr(raw, "model", "")),
    )
