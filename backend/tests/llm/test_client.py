"""The Groq client (L§44 as amended by ADR-018, L§45, L§46, LLM-01).

No test here reaches the network or needs a key. `GroqClient` accepts an
injected `client` object and an injected `sleep`, which is what lets the three
properties that matter — bounded retries, mapped errors, and a payload that
cannot contain a secret — be asserted as ordinary unit tests.

The doubles raise the **real** `groq` exception classes, because `_map_exception`
dispatches on class identity: a hand-rolled stand-in would make the mapping
tests pass while the mapping was wrong.

The last section is the reason this file was rewritten rather than renamed.
Groq's API is OpenAI-compatible, and the client ADR-016 deleted got four shape
differences wrong; ADR-018 carries them forward as acceptance criteria, and each
has a named regression test here.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from typing import Any

import groq
import httpx
import pytest

from app.config import BACKEND_DIR
from app.llm.client import (
    DEFAULT_MAX_TOKENS,
    GroqClient,
    LLMClient,
    _to_groq_tool,
    _to_groq_tool_choice,
    _to_model_response,
)
from app.llm.errors import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransportError,
)
from app.llm.models import Message, StopReason

API_KEY = "gsk_test_key_not_real"
MODEL = "openai/gpt-oss-120b"


# --------------------------------------------------------------------------
# Doubles for the SDK
# --------------------------------------------------------------------------


class _Block:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class _Completions:
    """Stands in for `groq.Groq().chat.completions`."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.payloads: list[dict[str, Any]] = []

    def create(self, **payload: Any) -> Any:
        self.payloads.append(payload)
        outcome = self.outcomes.pop(0) if self.outcomes else _reply("ok")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _SDK:
    def __init__(self, *outcomes: Any) -> None:
        self.chat = _Block(completions=_Completions(*outcomes))

    @property
    def payloads(self) -> list[dict[str, Any]]:
        return self.chat.completions.payloads


def _reply(text: str = "", *, finish_reason: str = "stop", tool_calls: Any = None, **extra: Any):
    """An OpenAI-shaped chat completion, which is what Groq returns."""
    return _Block(
        choices=[
            _Block(
                message=_Block(content=text, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ],
        model=MODEL,
        usage=_Block(prompt_tokens=10, completion_tokens=5),
        **extra,
    )


def _tool_call(name: str, arguments: Any, call_id: str = "call_1") -> Any:
    """A tool call in the OpenAI shape: `arguments` is a JSON **string**."""
    return _Block(id=call_id, function=_Block(name=name, arguments=arguments))


#: The exception class the SDK actually raises for each status. Constructing the
#: base `APIStatusError` instead would make every mapping test pass through the
#: same branch and prove nothing about the ones that matter.
_STATUS_CLASSES: dict[int, type[groq.APIStatusError]] = {
    400: groq.BadRequestError,
    401: groq.AuthenticationError,
    403: groq.PermissionDeniedError,
    404: groq.NotFoundError,
    429: groq.RateLimitError,
    500: groq.InternalServerError,
    502: groq.InternalServerError,
    503: groq.InternalServerError,
}


def _status_error(status: int) -> groq.APIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return _STATUS_CLASSES[status]("boom", response=response, body=None)


def _rate_limited(*, retry_after: str | None = None, message: str = "boom") -> groq.RateLimitError:
    """A real 429, optionally carrying the provider's own wait hint."""
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(429, request=request, headers=headers)
    return groq.RateLimitError(message, response=response, body=None)


def make_client(*outcomes: Any, **overrides: Any) -> tuple[GroqClient, _SDK]:
    sdk = _SDK(*outcomes)
    defaults: dict[str, Any] = {
        "api_key": API_KEY,
        "model": MODEL,
        "timeout_seconds": 30.0,
        "max_retries": 2,
        "sleep": lambda _seconds: None,
        "client": sdk,
    }
    return GroqClient(**{**defaults, **overrides}), sdk


HELLO = [Message(role="user", content="hello")]


# --------------------------------------------------------------------------
# The protocol
# --------------------------------------------------------------------------


def test_the_concrete_client_satisfies_the_protocol() -> None:
    """Everything else in the layer depends on `LLMClient`, not on this class."""
    client, _ = make_client()

    assert isinstance(client, LLMClient)


def test_only_one_module_in_the_repository_imports_the_sdk() -> None:
    """The reason M4 is offline-testable at all.

    An `import groq` anywhere else would be a second path to the network and a
    second place a key could be read.
    """
    importers = []
    for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(name.split(".")[0] == "groq" for name in names):
                importers.append(path.relative_to(BACKEND_DIR).as_posix())

    assert importers == ["app/llm/client.py"]


def test_a_missing_key_fails_at_construction_not_at_the_first_chat_turn() -> None:
    with pytest.raises(LLMAuthenticationError, match="GROQ_API_KEY"):
        GroqClient(api_key="", model=MODEL, timeout_seconds=30.0, max_retries=0)


# --------------------------------------------------------------------------
# The payload
# --------------------------------------------------------------------------


def test_the_system_prompt_leads_the_conversation_as_its_own_message() -> None:
    """L§29: buyer text arrives as a `user` message and never as an instruction.

    On an OpenAI-compatible API the system prompt is the first *message*, not a
    top-level `system` field. Sending `system=` would be silently ignored and
    the agent would run with no instructions at all — a failure with no error.
    """
    client, sdk = make_client(_reply("hi"))

    client.complete(system="You are an assistant.", messages=HELLO)

    payload = sdk.payloads[0]
    assert payload["messages"] == [
        {"role": "system", "content": "You are an assistant."},
        {"role": "user", "content": "hello"},
    ]
    assert "system" not in payload
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == DEFAULT_MAX_TOKENS
    assert payload["model"] == MODEL


def test_an_empty_system_prompt_adds_no_message() -> None:
    client, sdk = make_client(_reply("hi"))

    client.complete(system="", messages=HELLO)

    assert sdk.payloads[0]["messages"] == [{"role": "user", "content": "hello"}]


def test_tools_are_sent_only_when_there_are_tools() -> None:
    client, sdk = make_client(_reply(), _reply())

    client.complete(system="s", messages=HELLO)
    client.complete(system="s", messages=HELLO, tools=[{"name": "search_catalog"}])

    assert "tools" not in sdk.payloads[0]
    assert sdk.payloads[1]["tools"][0]["type"] == "function"


def test_an_empty_conversation_is_refused_before_the_network() -> None:
    client, sdk = make_client()

    with pytest.raises(LLMInvalidRequestError, match="at least one message"):
        client.complete(system="s", messages=[])

    assert sdk.payloads == []


# --------------------------------------------------------------------------
# L§45 — a secret never reaches the model
# --------------------------------------------------------------------------


def test_a_prompt_containing_a_configured_secret_is_never_sent() -> None:
    """L§45: credentials must never be included in LLM prompts.

    Refusal rather than redaction — a redacted prompt still means something
    upstream interpolated a key into a string bound for the network, and the
    next path out of the process might not redact.
    """
    client, sdk = make_client(secret_values=[API_KEY, "rzp_secret_value"])

    with pytest.raises(LLMInvalidRequestError, match="configured secret"):
        client.complete(
            system="s", messages=[Message(role="user", content="my key is rzp_secret_value")]
        )

    assert sdk.payloads == []


def test_the_refusal_does_not_quote_the_secret() -> None:
    """An exception message is a log line waiting to happen."""
    client, _ = make_client(secret_values=["rzp_secret_value"])

    with pytest.raises(LLMInvalidRequestError) as caught:
        client.complete(system="rzp_secret_value", messages=HELLO)

    assert "rzp_secret_value" not in str(caught.value)


def test_a_secret_in_the_system_prompt_is_caught_too() -> None:
    client, sdk = make_client(secret_values=[API_KEY])

    with pytest.raises(LLMInvalidRequestError):
        client.complete(system=f"the key is {API_KEY}", messages=HELLO)

    assert sdk.payloads == []


def test_an_ordinary_prompt_is_sent() -> None:
    client, sdk = make_client(_reply("hi"), secret_values=[API_KEY])

    client.complete(system="be helpful", messages=HELLO)

    assert len(sdk.payloads) == 1


# --------------------------------------------------------------------------
# L§46 — bounded retries
# --------------------------------------------------------------------------


def test_a_transient_failure_is_retried_up_to_the_configured_bound() -> None:
    client, sdk = make_client(
        _status_error(502), _status_error(502), _reply("recovered"), max_retries=2
    )

    response = client.complete(system="s", messages=HELLO)

    assert response.text == "recovered"
    assert len(sdk.payloads) == 3


def test_retries_stop_at_the_bound_rather_than_continuing() -> None:
    """ "The agent should not repeatedly retry indefinitely" — L§46."""
    client, sdk = make_client(*[_status_error(503) for _ in range(5)], max_retries=2)

    with pytest.raises(LLMTransportError):
        client.complete(system="s", messages=HELLO)

    assert len(sdk.payloads) == 3


def test_a_permanent_failure_is_not_retried_at_all() -> None:
    """A bad request will be just as bad the second time, and the buyer is waiting."""
    client, sdk = make_client(*[_status_error(400) for _ in range(3)], max_retries=2)

    with pytest.raises(LLMInvalidRequestError):
        client.complete(system="s", messages=HELLO)

    assert len(sdk.payloads) == 1


def test_the_backoff_is_exponential_and_actually_waited() -> None:
    slept: list[float] = []
    client, _ = make_client(
        _status_error(502),
        _status_error(502),
        _reply("ok"),
        max_retries=2,
        sleep=slept.append,
    )

    client.complete(system="s", messages=HELLO)

    assert slept == [0.5, 1.0]


def test_a_rate_limit_waits_the_interval_the_provider_named() -> None:
    """Groq's binding limit is a per-minute token bucket, not a per-call one.

    A two-leg turn can exceed 8,000 tokens in one minute, and then every 429
    lands inside the same window: 0.5s and 1.0s of exponential backoff retry
    into the identical refusal and the turn fails with quota it could have had
    by waiting. The provider states the wait; this honours it.
    """
    slept: list[float] = []
    client, sdk = make_client(
        _rate_limited(retry_after="9"),
        _reply("recovered"),
        max_retries=2,
        sleep=slept.append,
    )

    response = client.complete(system="s", messages=HELLO)

    assert response.text == "recovered"
    assert len(sdk.payloads) == 2
    # A shade over the hint, so the retry lands after the refill.
    assert slept == [9.25]


def test_a_rate_limit_hint_in_the_body_is_read_when_there_is_no_header() -> None:
    """Groq words it as "Please try again in 8.522s" when it sends no header."""
    slept: list[float] = []
    client, _ = make_client(
        _rate_limited(message="Rate limit reached. Please try again in 8.522s. Visit..."),
        _reply("ok"),
        max_retries=2,
        sleep=slept.append,
    )

    client.complete(system="s", messages=HELLO)

    assert slept == [pytest.approx(8.772)]


def test_a_wait_longer_than_the_cap_fails_now_rather_than_later() -> None:
    """L§46 either way: an hour-long hint is a failed turn, not an hour's wait.

    And not a capped wait followed by the same refusal, either. Groq answers in
    seconds while the per-minute bucket refills, and in *twenty minutes* once the
    daily token quota is gone. Sleeping the cap and asking again cannot help in
    the second case — it only makes the buyer wait 90 seconds for the failure
    they were going to get anyway.
    """
    slept: list[float] = []
    client, sdk = make_client(
        _rate_limited(retry_after="3600"),
        _reply("ok"),
        max_retries=2,
        sleep=slept.append,
    )

    with pytest.raises(LLMRateLimitError):
        client.complete(system="s", messages=HELLO)

    assert slept == []
    assert len(sdk.payloads) == 1


def test_a_rate_limit_with_no_hint_falls_back_to_the_exponential_backoff() -> None:
    slept: list[float] = []
    client, _ = make_client(
        _rate_limited(),
        _reply("ok"),
        max_retries=2,
        sleep=slept.append,
    )

    client.complete(system="s", messages=HELLO)

    assert slept == [0.5]


def test_zero_retries_means_one_attempt() -> None:
    client, sdk = make_client(_status_error(502), max_retries=0)

    with pytest.raises(LLMTransportError):
        client.complete(system="s", messages=HELLO)

    assert len(sdk.payloads) == 1


# --------------------------------------------------------------------------
# Provider errors become this application's errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "expected", "transient"),
    [
        (groq.APITimeoutError(httpx.Request("POST", "https://x")), LLMTimeoutError, True),
        (_status_error(429), LLMRateLimitError, True),
        (_status_error(401), LLMAuthenticationError, False),
        (_status_error(403), LLMAuthenticationError, False),
        (_status_error(400), LLMInvalidRequestError, False),
        (_status_error(500), LLMTransportError, True),
        (
            groq.APIConnectionError(request=httpx.Request("POST", "https://x")),
            LLMTransportError,
            True,
        ),
        (RuntimeError("something else entirely"), LLMTransportError, True),
    ],
)
def test_every_provider_failure_is_mapped(
    raised: Exception, expected: type[Exception], transient: bool
) -> None:
    """F§25: no provider error type and no provider error string reaches a caller."""
    client, _ = make_client(raised, max_retries=0)

    with pytest.raises(expected) as caught:
        client.complete(system="s", messages=HELLO)

    assert caught.value.is_transient is transient  # type: ignore[attr-defined]


def test_an_authentication_failure_does_not_echo_the_provider_message() -> None:
    """The provider's message can quote the offending key."""
    client, _ = make_client(_status_error(401), max_retries=0)

    with pytest.raises(LLMAuthenticationError) as caught:
        client.complete(system="s", messages=HELLO)

    assert str(caught.value) == "the model API rejected the configured credentials"


# --------------------------------------------------------------------------
# Flattening the SDK's response
# --------------------------------------------------------------------------


def test_text_and_tool_calls_are_read_from_the_first_choice() -> None:
    raw = _reply(
        "Let me look.",
        finish_reason="tool_calls",
        tool_calls=[_tool_call("search_catalog", '{"category": "case"}')],
    )

    response = _to_model_response(raw)

    assert response.text == "Let me look."
    assert response.stop_reason is StopReason.TOOL_USE
    assert response.requested_tools
    call = response.tool_call("search_catalog")
    assert call is not None
    assert call.arguments == {"category": "case"}
    assert response.usage.total_tokens == 15


def test_an_unrecognized_finish_reason_is_visible_rather_than_normal() -> None:
    """Coercing it to `END_TURN` would make a provider change read as a complete answer."""
    response = _to_model_response(_reply("hi", finish_reason="something_new"))

    assert response.stop_reason is StopReason.UNKNOWN


def test_a_response_with_no_choices_does_not_explode() -> None:
    response = _to_model_response(_Block(choices=None, model=MODEL))

    assert response.text == ""
    assert response.tool_calls == ()
    assert response.stop_reason is StopReason.UNKNOWN
    assert response.usage.total_tokens == 0


def test_a_null_content_becomes_empty_text() -> None:
    """A tool-only reply has `content: null`, which must not become the string "None"."""
    response = _to_model_response(
        _reply(finish_reason="tool_calls", tool_calls=[_tool_call("search_catalog", "{}")])
    )
    response_text = response.text

    assert response_text == ""


# --------------------------------------------------------------------------
# ADR-018 regression tests: the five defects of the deleted Groq client
#
# Each of these fails against the implementation that was removed in `78f6f4d`.
# --------------------------------------------------------------------------


def test_defect_1_truncation_is_detected_on_groqs_own_finish_reason() -> None:
    """**The defect that decided ADR-016, and the one that must never return.**

    Groq reports truncation as `length`. The deleted client carried Anthropic's
    table, where `max_tokens` means truncation and `length` is absent — so
    `length` mapped to `UNKNOWN`, `is_truncated` was permanently `False`, the
    first guard in `_reject_unusable` never fired, and **a truncated intent
    passed as a complete one**. That is the fabrication L§30 and A§41 forbid.
    """
    response = _to_model_response(_reply("half an ans", finish_reason="length"))

    assert response.stop_reason is StopReason.MAX_TOKENS
    assert response.is_truncated is True


def test_defect_1b_anthropic_stop_reasons_are_not_silently_accepted() -> None:
    """The names the deleted table used never occur on this API.

    If any of them ever maps to something other than `UNKNOWN`, the table has
    drifted back toward the wrong provider.
    """
    for anthropic_name in ("end_turn", "tool_use", "max_tokens", "stop_sequence"):
        response = _to_model_response(_reply("x", finish_reason=anthropic_name))
        assert response.stop_reason is StopReason.UNKNOWN, anthropic_name


def test_defect_1c_the_ordinary_finish_reasons_map_correctly() -> None:
    for finish_reason, expected in (
        ("stop", StopReason.END_TURN),
        ("tool_calls", StopReason.TOOL_USE),
        ("length", StopReason.MAX_TOKENS),
        ("content_filter", StopReason.REFUSAL),
        ("function_call", StopReason.TOOL_USE),
    ):
        assert _to_model_response(_reply("x", finish_reason=finish_reason)).stop_reason is expected


def test_defect_2_tool_schemas_are_really_converted_not_passed_through() -> None:
    """The deleted converter returned its argument unchanged, commented
    "similar enough". Tool calling could not have worked at all."""
    converted = _to_groq_tool(
        {
            "name": "search_catalog",
            "description": "Search the catalog.",
            "input_schema": {"type": "object", "properties": {"category": {"type": "string"}}},
        }
    )

    assert converted == {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": "Search the catalog.",
            "parameters": {"type": "object", "properties": {"category": {"type": "string"}}},
        },
    }
    # The Anthropic key must be gone, not merely accompanied.
    assert "input_schema" not in converted["function"]


def test_defect_2b_a_tool_with_no_schema_still_gets_a_parameters_object() -> None:
    """Some models refuse a function declared without a parameter schema."""
    converted = _to_groq_tool({"name": "get_cart"})

    assert converted["function"]["parameters"] == {"type": "object", "properties": {}}


def test_defect_2c_an_already_converted_tool_is_not_double_wrapped() -> None:
    already = {"type": "function", "function": {"name": "x", "parameters": {}}}

    assert _to_groq_tool(already) == already


def test_defect_3_tool_choice_is_converted_to_the_openai_vocabulary() -> None:
    """Forwarded unconverted by the deleted client — the same shape mismatch."""
    assert _to_groq_tool_choice({"type": "auto"}) == "auto"
    assert _to_groq_tool_choice({"type": "none"}) == "none"
    assert _to_groq_tool_choice({"type": "any"}) == "required"
    assert _to_groq_tool_choice({"type": "tool", "name": "search_catalog"}) == {
        "type": "function",
        "function": {"name": "search_catalog"},
    }


def test_defect_3b_an_unknown_tool_choice_falls_back_to_auto_not_to_the_wire() -> None:
    """Forwarding an unrecognised object would be a 400 in the middle of a turn."""
    assert _to_groq_tool_choice({"type": "who_knows"}) == "auto"


def test_defect_4_decimal_precision_survives_tool_arguments() -> None:
    """**ADR-008's hole, reopened by the deleted client and closed here.**

    Groq returns arguments as a JSON *string*. The deleted client called `dict()`
    on it, which cannot work; a plain `json.loads` would be worse, turning
    `1500.50` into a `float` before any validator could intervene — and a
    `Decimal` built from a lossy float is still lossy.
    """
    response = _to_model_response(
        _reply(
            finish_reason="tool_calls",
            tool_calls=[_tool_call("propose_cart", '{"budget": 1500.10, "quantity": 2}')],
        )
    )

    call = response.tool_call("propose_cart")
    assert call is not None
    assert call.arguments["budget"] == Decimal("1500.10")
    assert isinstance(call.arguments["budget"], Decimal)
    assert not isinstance(call.arguments["budget"], float)
    # Integers are exact in both representations and stay ints.
    assert call.arguments["quantity"] == 2


def test_defect_4b_malformed_tool_arguments_yield_nothing_rather_than_a_guess() -> None:
    """A§19 forbids executing raw model output; a "helpful" repair is how a
    malformed call becomes a real one. The validation pipeline rejects it."""
    response = _to_model_response(
        _reply(finish_reason="tool_calls", tool_calls=[_tool_call("search_catalog", "{not json")])
    )

    call = response.tool_call("search_catalog")
    assert call is not None
    assert call.arguments == {}


def test_defect_4c_an_empty_argument_string_is_not_an_error() -> None:
    """A no-argument tool call legitimately sends `""` or `"{}"`."""
    for raw in ("", "{}", "   "):
        response = _to_model_response(
            _reply(finish_reason="tool_calls", tool_calls=[_tool_call("get_cart", raw)])
        )
        call = response.tool_call("get_cart")
        assert call is not None
        assert call.arguments == {}


def test_defect_5_the_sdk_is_a_declared_dependency() -> None:
    """The deleted client's import path raised `ImportError`, because `groq` was
    never added to `pyproject.toml`."""
    import tomllib

    manifest = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    declared = manifest["project"]["dependencies"]

    assert any(dep.startswith("groq") for dep in declared), declared
    assert not any(dep.startswith("anthropic") for dep in declared), declared


def test_token_usage_is_read_under_its_openai_names() -> None:
    """Groq reports `prompt_tokens`/`completion_tokens`. Reading Anthropic's
    `input_tokens`/`output_tokens` yields a silent zero, which would make
    L§47's cost accounting quietly useless."""
    response = _to_model_response(_reply("hi"))

    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5


# --------------------------------------------------------------------------
# Construction from settings
# --------------------------------------------------------------------------


def test_the_client_is_built_from_settings_including_every_secret() -> None:
    """A leak of *any* configured secret is caught, not only a leak of the model key."""
    from app.config import Settings

    settings = Settings(groq_api_key=API_KEY, razorpay_key_secret="rzp_secret_value")
    client = GroqClient.from_settings(settings, client=_SDK(), sleep=lambda _s: None)

    with pytest.raises(LLMInvalidRequestError, match="configured secret"):
        client.complete(system="s", messages=[Message(role="user", content="rzp_secret_value")])


def test_build_client_does_not_choose_a_provider_from_the_shape_of_the_key() -> None:
    """ADR-018, carrying forward ADR-016's one surviving conclusion.

    `build_client` reads no prefix and has no provider branch. Groq is the
    locked provider; a key of any other shape in `GROQ_API_KEY` is a
    misconfiguration, and the right response is to fail against Groq with that
    key rather than quietly reach somewhere else. Dispatching on the prefix made
    the variable's name a claim about its contents, and made which model the
    application talks to a property of a string in `.env` rather than of the
    code.
    """
    from app.config import Settings
    from app.llm.client import build_client

    settings = Settings(groq_api_key="sk-ant-looks-like-another-provider")

    assert isinstance(build_client(settings), GroqClient)


def test_the_configured_model_reaches_the_wire() -> None:
    from app.config import Settings

    settings = Settings(groq_api_key=API_KEY, groq_model="qwen/qwen3.8-27b")
    sdk = _SDK(_reply("hi"))
    client = GroqClient.from_settings(settings, client=sdk, sleep=lambda _s: None)

    client.complete(system="s", messages=HELLO)

    assert sdk.payloads[0]["model"] == "qwen/qwen3.8-27b"
