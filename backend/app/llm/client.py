"""The Groq client (L§44 as amended by ADR-018, L§45, L§46).

The only module in the repository that imports the Groq SDK. Everything else
depends on the `LLMClient` protocol, which is what makes the rest of the LLM
layer testable with a three-line fake and no API key.

Groq's API is **OpenAI-compatible**, not Anthropic-compatible, and that is the
single most important fact about this file. Three shapes differ, and every one
of them was a real defect in the Groq client that ADR-016 deleted (`78f6f4d`);
ADR-018 carries them forward as acceptance criteria:

- **`finish_reason`, not `stop_reason`**, with values `stop` / `length` /
  `tool_calls` / `content_filter`. The Anthropic names never occur. Mapping
  `length` wrongly is not a cosmetic bug: it leaves `ModelResponse.is_truncated`
  permanently `False`, so a **truncated intent passes as a complete one** — the
  fabrication L§30 and A§41 forbid.
- **Tools are `{"type": "function", "function": {...}}`**, not
  `{name, description, input_schema}`. A pass-through converter means tool
  calling silently never works.
- **Tool arguments arrive as a JSON *string***, not a decoded object. Parsing it
  with a plain `json.loads` reopens the money-precision hole ADR-008 closes, so
  it goes through `loads_decimal` (`parse_float=Decimal`).

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
mapped onto `app.llm.errors`, so no caller ever catches `groq.APIError` and no
provider error string is ever on a path to the buyer (F§25).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

import groq

from app.config import Settings, get_settings
from app.llm.errors import (
    LLMAuthenticationError,
    LLMError,
    LLMInvalidRequestError,
    LLMOutputError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransportError,
)
from app.llm.models import Message, ModelResponse, StopReason, TokenUsage, ToolCall
from app.llm.schemas import loads_decimal

logger = logging.getLogger(__name__)

__all__ = ["GroqClient", "LLMClient", "build_client"]

#: Groq's OpenAI-compatible finish reasons, mapped onto ours.
#:
#: These are **not** Anthropic's names. `end_turn`, `tool_use`, `max_tokens` and
#: `stop_sequence` never occur on this API, and a table containing them would
#: map every real response to `UNKNOWN`. Anything absent becomes `UNKNOWN`
#: rather than `END_TURN`, so a provider change is visible instead of silently
#: reading as a complete answer.
_STOP_REASONS: dict[str, StopReason] = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    #: The one that matters most: truncation. See the module docstring.
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.REFUSAL,
    #: Deprecated OpenAI spelling, still emitted by some models.
    "function_call": StopReason.TOOL_USE,
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


class GroqClient:
    """`LLMClient` backed by the Groq API (ADR-018).

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
                "GROQ_API_KEY is not configured; set it in .env (never in code)"
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
        self._client = client or groq.Groq(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **overrides: Any) -> GroqClient:
        settings = settings or get_settings()
        key = settings.groq_api_key
        return cls(
            api_key=key.get_secret_value() if key else "",
            model=settings.groq_model,
            timeout_seconds=float(settings.groq_timeout_seconds),
            max_retries=settings.groq_max_retries,
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

        # OpenAI-compatible APIs carry the system prompt as the first message
        # rather than as a top-level field. Sending `system=` would be silently
        # ignored, and the agent would run with no instructions at all.
        wire_messages: list[dict[str, Any]] = []
        if system:
            wire_messages.append({"role": "system", "content": system})
        wire_messages.extend({"role": m.role, "content": m.content} for m in messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": wire_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [_to_groq_tool(tool) for tool in tools]
        if tool_choice:
            payload["tool_choice"] = _to_groq_tool_choice(tool_choice)

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


def build_client(settings: Settings | None = None) -> LLMClient:
    """The client the application uses, constructed from configuration."""
    return GroqClient.from_settings(settings or get_settings())


# --------------------------------------------------------------------------
# Translation
# --------------------------------------------------------------------------


def _to_groq_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert this application's tool schema to the OpenAI/Groq wire shape.

    `app/llm/tool_schemas.py` authors tools in the Anthropic shape
    (`{name, description, input_schema}`), which is what `architecture.md`
    describes. Groq expects `{"type": "function", "function": {name,
    description, parameters}}`.

    This is a **real** conversion. The deleted client's version returned its
    argument unchanged with a comment saying the shapes were "similar enough";
    they are not, and tool calling could not have worked at all. A tool already
    in the Groq shape is passed through, so a caller that supplies one directly
    is not double-wrapped.
    """
    if tool.get("type") == "function" and "function" in tool:
        return dict(tool)

    function: dict[str, Any] = {"name": tool["name"]}
    if tool.get("description"):
        function["description"] = tool["description"]
    # `input_schema` is the Anthropic name; `parameters` is the OpenAI one. An
    # empty object rather than an omission: a function with no parameters still
    # needs a schema, or some models refuse the tool.
    function["parameters"] = tool.get("input_schema") or {"type": "object", "properties": {}}
    return {"type": "function", "function": function}


def _to_groq_tool_choice(tool_choice: dict[str, Any]) -> Any:
    """Convert Anthropic's `tool_choice` to the OpenAI/Groq form.

    Anthropic: `{"type": "auto"}`, `{"type": "any"}`, `{"type": "tool", "name": x}`.
    OpenAI/Groq: the strings `"auto"` / `"none"` / `"required"`, or
    `{"type": "function", "function": {"name": x}}`.

    The deleted client forwarded this unconverted, the same mismatch as the tool
    schemas.
    """
    kind = tool_choice.get("type")
    if kind == "auto":
        return "auto"
    if kind == "none":
        return "none"
    if kind == "any":
        # "Call some tool" — OpenAI spells this `required`.
        return "required"
    if kind == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    if kind == "function" and "function" in tool_choice:
        return dict(tool_choice)
    # An unrecognised shape is not guessed at. `auto` is the API default and the
    # only safe fallback: forwarding an unknown object would be a 400 mid-turn.
    return "auto"


def _map_exception(exc: Exception) -> LLMError:
    """Map an SDK exception onto this application's taxonomy.

    Checked most specific first. `groq.APIStatusError` covers the 4xx and 5xx
    families, and the split between them is the split between "the request was
    wrong" and "the service was", which is exactly the retry decision.
    """
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, groq.APITimeoutError):
        return LLMTimeoutError("the model did not respond within the configured timeout")
    if isinstance(exc, groq.RateLimitError):
        return LLMRateLimitError("the model API rate limit was reached")
    if isinstance(exc, groq.AuthenticationError | groq.PermissionDeniedError):
        return LLMAuthenticationError("the model API rejected the configured credentials")
    if isinstance(exc, groq.BadRequestError | groq.UnprocessableEntityError):
        return LLMInvalidRequestError(f"the model API rejected the request: {exc}")
    if isinstance(exc, groq.APIStatusError):
        return LLMTransportError(f"the model API returned {exc.status_code}")
    if isinstance(exc, groq.APIConnectionError):
        return LLMTransportError("could not reach the model API")
    return LLMTransportError(f"unexpected failure calling the model API: {type(exc).__name__}")


def _tool_call_arguments(raw_arguments: Any) -> dict[str, Any]:
    """Decode one tool call's arguments, without losing decimal precision.

    Groq returns arguments as a **JSON string**, not a decoded object. The
    deleted client called `dict()` on that string, which cannot work; parsing it
    with a plain `json.loads` would be worse, because `1500.50` would become a
    `float` before any validator could intervene and a `Decimal` built from a
    lossy float is still lossy (ADR-008). `loads_decimal` uses
    `parse_float=Decimal`.

    Malformed JSON is not repaired. It yields no arguments, and the validation
    pipeline rejects the call — A§19 forbids executing raw model output, and a
    "helpful" coercion is how a malformed call becomes a real one.
    """
    if isinstance(raw_arguments, dict):
        # Already decoded (a test double, or a future SDK change). Trusted only
        # for its shape; every value is still validated downstream.
        return dict(raw_arguments)
    if not isinstance(raw_arguments, str) or not raw_arguments.strip():
        return {}
    try:
        parsed = loads_decimal(raw_arguments)
    except (LLMOutputError, ValueError):
        logger.warning("model returned unparseable tool arguments")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _to_model_response(raw: Any) -> ModelResponse:
    """Flatten an OpenAI-shaped chat completion into a `ModelResponse`.

    Reads `choices[0]`, not Anthropic's top-level `content` list. A response
    with no choices is not an error here: it becomes an empty answer with an
    `UNKNOWN` stop reason, which the extractor rejects as unusable rather than
    treating as a complete reply.
    """
    choices = getattr(raw, "choices", None) or ()
    if not choices:
        return ModelResponse(
            text="",
            tool_calls=(),
            stop_reason=StopReason.UNKNOWN,
            usage=_usage(raw),
            model=str(getattr(raw, "model", "")),
        )

    choice = choices[0]
    message = getattr(choice, "message", None)
    text = getattr(message, "content", None) or ""

    calls: list[ToolCall] = []
    for call in getattr(message, "tool_calls", None) or ():
        function = getattr(call, "function", None)
        calls.append(
            ToolCall(
                id=str(getattr(call, "id", "")),
                name=str(getattr(function, "name", "")),
                arguments=_tool_call_arguments(getattr(function, "arguments", None)),
            )
        )

    return ModelResponse(
        text=str(text),
        tool_calls=tuple(calls),
        stop_reason=_STOP_REASONS.get(
            str(getattr(choice, "finish_reason", "")), StopReason.UNKNOWN
        ),
        usage=_usage(raw),
        model=str(getattr(raw, "model", "")),
    )


def _usage(raw: Any) -> TokenUsage:
    """Token counts, under their OpenAI names.

    Groq reports `prompt_tokens` / `completion_tokens`, not Anthropic's
    `input_tokens` / `output_tokens`. Reading the wrong names yields a silent
    zero, which would make L§47's cost accounting quietly useless.
    """
    usage = getattr(raw, "usage", None)
    return TokenUsage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )
