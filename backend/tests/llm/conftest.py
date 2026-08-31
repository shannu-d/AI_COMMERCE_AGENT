"""Builders for the LLM-layer tests.

Not one test in this package needs an API key, a network or a database, and
that is M4's stated exit condition: *"natural language to validated structured
intent, offline-testable"*. It is achievable because everything except
`client.py` depends on the `LLMClient` protocol rather than on the Anthropic
SDK, so a fake that returns canned `ModelResponse` values drives every path.

`FakeClient` also **records what was sent**. Several of the properties this
layer must have are properties of the outgoing payload — that buyer text is
never in the system prompt, that a previous intent is carried as application
state, that the history window is trimmed — and they can only be asserted by
looking at what the client was asked to send.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.llm.models import Message, ModelResponse, StopReason, TokenUsage


class FakeClient:
    """An `LLMClient` that replays a script and remembers every call.

    Each queued item is either a `ModelResponse` to return or an exception to
    raise, so a test can script "malformed, then valid" without patching
    anything. Running past the end of the script is a test bug rather than a
    default response, and says so.
    """

    def __init__(self, *responses: ModelResponse | Exception) -> None:
        self.queued: list[ModelResponse | Exception] = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> ModelResponse:
        self.calls.append(
            {
                "system": system,
                "messages": list(messages),
                "tools": tools,
                "tool_choice": tool_choice,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if not self.queued:
            raise AssertionError(
                f"FakeClient was called {len(self.calls)} times but only "
                f"{len(self.calls) - 1} responses were queued"
            )
        item = self.queued.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    # -- convenience for assertions ----------------------------------------

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last(self) -> dict[str, Any]:
        assert self.calls, "the client was never called"
        return self.calls[-1]

    @property
    def last_system(self) -> str:
        return str(self.last["system"])

    @property
    def last_messages(self) -> list[Message]:
        return list(self.last["messages"])


def say(payload: Any, **kwargs: Any) -> ModelResponse:
    """A `ModelResponse` whose text is `payload`, serialized if it is not a string.

    `json.dumps` is used rather than a hand-written string so that a test
    describing an intent writes a dict and cannot accidentally assert against
    invalid JSON it meant to be valid.
    """
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return ModelResponse(text=text, **kwargs)


def extraction_payload(
    intent: dict[str, Any] | None = None,
    **envelope: Any,
) -> dict[str, Any]:
    """The envelope `IntentExtractor` expects, with an empty intent by default."""
    return {"intent": intent if intent is not None else {}, **envelope}


def user(text: str) -> Message:
    return Message(role="user", content=text)


def assistant(text: str) -> Message:
    return Message(role="assistant", content=text)


@pytest.fixture
def truncated() -> ModelResponse:
    """A response the model did not finish writing."""
    return ModelResponse(
        text='{"intent": {"product_requirements": [{"product_ty',
        stop_reason=StopReason.MAX_TOKENS,
        usage=TokenUsage(input_tokens=100, output_tokens=1024),
    )
