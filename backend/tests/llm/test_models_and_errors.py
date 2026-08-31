"""The transport types and the failure taxonomy (L§46).

Two small modules, and both exist for the same reason: so that a caller can
reason about what the model did without importing the Anthropic SDK, and about
what went wrong without catching `Exception` and guessing.
"""

from __future__ import annotations

import pytest

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

# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "transient"),
    [
        (LLMTransportError, True),
        (LLMTimeoutError, True),
        (LLMRateLimitError, True),
        (LLMAuthenticationError, False),
        (LLMInvalidRequestError, False),
        (LLMOutputError, False),
    ],
)
def test_the_retry_decision_is_a_property_of_the_type(
    error: type[LLMError], transient: bool
) -> None:
    """L§46: bounded retries, and only for what a second attempt could fix.

    Making it a class attribute rather than a caller's judgement is what stops
    the retry policy drifting away from the taxonomy.
    """
    assert error("boom").is_transient is transient


def test_every_failure_at_this_boundary_is_one_kind_of_error() -> None:
    """So a caller catches `LLMError` and never an `anthropic.APIError`."""
    for error in (
        LLMTransportError,
        LLMTimeoutError,
        LLMRateLimitError,
        LLMAuthenticationError,
        LLMInvalidRequestError,
        LLMOutputError,
    ):
        assert issubclass(error, LLMError)


def test_a_timeout_is_a_transport_failure() -> None:
    """It shares the retry decision, so it shares the branch."""
    assert issubclass(LLMTimeoutError, LLMTransportError)
    assert issubclass(LLMRateLimitError, LLMTransportError)


def test_malformed_output_is_never_retried_by_the_client() -> None:
    """The client cannot know whether a second sample would differ.

    Whether to re-prompt belongs to the layer that knows what it asked for —
    `IntentExtractor`, which does exactly one bounded repair.
    """
    assert LLMOutputError.is_transient is False


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------


def test_a_tool_call_is_a_request_and_carries_no_validation() -> None:
    """ADR-001: `arguments` is raw model output that has passed nothing yet."""
    call = ToolCall(id="tu_1", name="search_catalog", arguments={"anything": "at all"})

    assert call.arguments == {"anything": "at all"}
    with pytest.raises(AttributeError):
        call.name = "other"  # type: ignore[misc]


def test_a_response_reports_whether_tools_were_requested() -> None:
    empty = ModelResponse(text="hello")
    asking = ModelResponse(tool_calls=(ToolCall(id="1", name="get_product"),))

    assert not empty.requested_tools
    assert asking.requested_tools


def test_a_truncated_response_is_not_a_short_response() -> None:
    """Treating one as complete is how a half-formed tool call gets acted on."""
    assert ModelResponse(stop_reason=StopReason.MAX_TOKENS).is_truncated
    assert not ModelResponse(stop_reason=StopReason.END_TURN).is_truncated


def test_a_named_tool_call_can_be_found_and_a_missing_one_is_none() -> None:
    response = ModelResponse(
        tool_calls=(
            ToolCall(id="1", name="search_catalog"),
            ToolCall(id="2", name="check_inventory"),
        )
    )

    found = response.tool_call("check_inventory")
    assert found is not None
    assert found.id == "2"
    assert response.tool_call("propose_cart") is None


def test_tokens_are_summed_for_the_cost_control_the_specification_asks_for() -> None:
    """L§47."""
    assert TokenUsage(input_tokens=100, output_tokens=25).total_tokens == 125
    assert TokenUsage().total_tokens == 0


def test_a_conversation_turn_has_only_the_two_roles_a_buyer_conversation_has() -> None:
    """The system prompt is a separate parameter, never a message.

    That separation is part of the prompt-injection boundary (L§29): buyer text
    always arrives as a `user` message and can never be confused for an
    application instruction.
    """
    assert Message(role="user", content="hi").role == "user"
    assert Message(role="assistant", content="hello").role == "assistant"
    assert "system" not in Message.__annotations__.get("role", "")


def test_the_transport_types_are_immutable() -> None:
    """Model output does not get edited after it arrives."""
    response = ModelResponse(text="hello")

    with pytest.raises(AttributeError):
        response.text = "goodbye"  # type: ignore[misc]
