"""The Claude client (L§44–L§46, LLM-01).

No test here reaches the network or needs a key. `AnthropicClient` accepts an
injected `client` object and an injected `sleep`, which is what lets the three
properties that matter — bounded retries, mapped errors, and a payload that
cannot contain a secret — be asserted as ordinary unit tests.
"""

from __future__ import annotations

import ast
from typing import Any

import anthropic
import httpx
import pytest

from app.config import BACKEND_DIR
from app.llm.client import DEFAULT_MAX_TOKENS, AnthropicClient, LLMClient, _to_model_response
from app.llm.errors import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransportError,
)
from app.llm.models import Message, StopReason

API_KEY = "sk-ant-test-key-not-real"


# --------------------------------------------------------------------------
# Doubles for the SDK
# --------------------------------------------------------------------------


class _Block:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class _Messages:
    """Stands in for `anthropic.Anthropic().messages`."""

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
        self.messages = _Messages(*outcomes)


def _reply(text: str = "", *, stop_reason: str = "end_turn", **extra: Any) -> Any:
    return _Block(
        content=[_Block(type="text", text=text)],
        stop_reason=stop_reason,
        model="claude-sonnet-5",
        usage=_Block(input_tokens=10, output_tokens=5),
        **extra,
    )


#: The exception class the SDK actually raises for each status. Constructing the
#: base `APIStatusError` instead would make every mapping test pass through the
#: same branch and prove nothing about the ones that matter.
_STATUS_CLASSES: dict[int, type[anthropic.APIStatusError]] = {
    400: anthropic.BadRequestError,
    401: anthropic.AuthenticationError,
    403: anthropic.PermissionDeniedError,
    404: anthropic.NotFoundError,
    429: anthropic.RateLimitError,
    500: anthropic.InternalServerError,
    502: anthropic.InternalServerError,
    503: anthropic.InternalServerError,
}


def _status_error(status: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request)
    return _STATUS_CLASSES[status]("boom", response=response, body=None)


def make_client(*outcomes: Any, **overrides: Any) -> tuple[AnthropicClient, _SDK]:
    sdk = _SDK(*outcomes)
    defaults: dict[str, Any] = {
        "api_key": API_KEY,
        "model": "claude-sonnet-5",
        "timeout_seconds": 30.0,
        "max_retries": 2,
        "sleep": lambda _seconds: None,
        "client": sdk,
    }
    return AnthropicClient(**{**defaults, **overrides}), sdk


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

    An `import anthropic` anywhere else would be a second path to the network
    and a second place a key could be read.
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
            if any(name.split(".")[0] == "anthropic" for name in names):
                importers.append(path.relative_to(BACKEND_DIR).as_posix())

    assert importers == ["app/llm/client.py"]


def test_a_missing_key_fails_at_construction_not_at_the_first_chat_turn() -> None:
    with pytest.raises(LLMAuthenticationError, match="ANTHROPIC_API_KEY"):
        AnthropicClient(api_key="", model="claude-sonnet-5", timeout_seconds=30.0, max_retries=0)


# --------------------------------------------------------------------------
# The payload
# --------------------------------------------------------------------------


def test_the_payload_carries_the_system_prompt_separately_from_the_conversation() -> None:
    """L§29: buyer text arrives as a `user` message and never as an instruction."""
    client, sdk = make_client(_reply("hi"))

    client.complete(system="You are an assistant.", messages=HELLO)

    payload = sdk.messages.payloads[0]
    assert payload["system"] == "You are an assistant."
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == DEFAULT_MAX_TOKENS


def test_tools_are_sent_only_when_there_are_tools() -> None:
    client, sdk = make_client(_reply(), _reply())

    client.complete(system="s", messages=HELLO)
    client.complete(system="s", messages=HELLO, tools=[{"name": "search_catalog"}])

    assert "tools" not in sdk.messages.payloads[0]
    assert sdk.messages.payloads[1]["tools"] == [{"name": "search_catalog"}]


def test_an_empty_conversation_is_refused_before_the_network() -> None:
    client, sdk = make_client()

    with pytest.raises(LLMInvalidRequestError, match="at least one message"):
        client.complete(system="s", messages=[])

    assert sdk.messages.payloads == []


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

    assert sdk.messages.payloads == []


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

    assert sdk.messages.payloads == []


def test_an_ordinary_prompt_is_sent() -> None:
    client, sdk = make_client(_reply("hi"), secret_values=[API_KEY])

    client.complete(system="be helpful", messages=HELLO)

    assert len(sdk.messages.payloads) == 1


# --------------------------------------------------------------------------
# L§46 — bounded retries
# --------------------------------------------------------------------------


def test_a_transient_failure_is_retried_up_to_the_configured_bound() -> None:
    client, sdk = make_client(
        _status_error(502), _status_error(502), _reply("recovered"), max_retries=2
    )

    response = client.complete(system="s", messages=HELLO)

    assert response.text == "recovered"
    assert len(sdk.messages.payloads) == 3


def test_retries_stop_at_the_bound_rather_than_continuing() -> None:
    """ "The agent should not repeatedly retry indefinitely" — L§46."""
    client, sdk = make_client(*[_status_error(503) for _ in range(5)], max_retries=2)

    with pytest.raises(LLMTransportError):
        client.complete(system="s", messages=HELLO)

    assert len(sdk.messages.payloads) == 3


def test_a_permanent_failure_is_not_retried_at_all() -> None:
    """A bad request will be just as bad the second time, and the buyer is waiting."""
    client, sdk = make_client(*[_status_error(400) for _ in range(3)], max_retries=2)

    with pytest.raises(LLMInvalidRequestError):
        client.complete(system="s", messages=HELLO)

    assert len(sdk.messages.payloads) == 1


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


def test_zero_retries_means_one_attempt() -> None:
    client, sdk = make_client(_status_error(502), max_retries=0)

    with pytest.raises(LLMTransportError):
        client.complete(system="s", messages=HELLO)

    assert len(sdk.messages.payloads) == 1


# --------------------------------------------------------------------------
# Provider errors become this application's errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "expected", "transient"),
    [
        (anthropic.APITimeoutError(httpx.Request("POST", "https://x")), LLMTimeoutError, True),
        (_status_error(429), LLMRateLimitError, True),
        (_status_error(401), LLMAuthenticationError, False),
        (_status_error(403), LLMAuthenticationError, False),
        (_status_error(400), LLMInvalidRequestError, False),
        (_status_error(404), LLMInvalidRequestError, False),
        (_status_error(500), LLMTransportError, True),
        (
            anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")),
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


def test_text_blocks_are_concatenated_and_tool_blocks_collected() -> None:
    raw = _Block(
        content=[
            _Block(type="text", text="Let me look. "),
            _Block(type="tool_use", id="tu_1", name="search_catalog", input={"category": "case"}),
            _Block(type="text", text="One moment."),
            _Block(type="something_new", surprise=True),
        ],
        stop_reason="tool_use",
        model="claude-sonnet-5",
        usage=_Block(input_tokens=100, output_tokens=20),
    )

    response = _to_model_response(raw)

    assert response.text == "Let me look. One moment."
    assert response.stop_reason is StopReason.TOOL_USE
    assert response.requested_tools
    call = response.tool_call("search_catalog")
    assert call is not None
    assert call.arguments == {"category": "case"}
    assert response.usage.total_tokens == 120


def test_an_unrecognized_stop_reason_is_visible_rather_than_normal() -> None:
    """Coercing it to `END_TURN` would make a provider change read as a complete answer."""
    response = _to_model_response(_reply("hi", stop_reason="something_new"))

    assert response.stop_reason is StopReason.UNKNOWN


def test_a_truncated_response_says_so() -> None:
    response = _to_model_response(_reply("half an ans", stop_reason="max_tokens"))

    assert response.is_truncated


def test_a_response_with_no_content_does_not_explode() -> None:
    response = _to_model_response(_Block(content=None, stop_reason="end_turn"))

    assert response.text == ""
    assert response.tool_calls == ()
    assert response.usage.total_tokens == 0


# --------------------------------------------------------------------------
# Construction from settings
# --------------------------------------------------------------------------


def test_the_client_is_built_from_settings_including_every_secret(monkeypatch: Any) -> None:
    """A leak of *any* configured secret is caught, not only a leak of the model key."""
    from app.config import Settings

    settings = Settings(anthropic_api_key=API_KEY, razorpay_key_secret="rzp_secret_value")
    client = AnthropicClient.from_settings(settings, client=_SDK(), sleep=lambda _s: None)

    with pytest.raises(LLMInvalidRequestError, match="configured secret"):
        client.complete(system="s", messages=[Message(role="user", content="rzp_secret_value")])
