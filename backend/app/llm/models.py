"""Provider-agnostic transport types.

A thin layer between the Anthropic SDK and everything else in the application,
for one reason that is worth the file: **the whole LLM layer has to be testable
without an API key and without a network**. M4's exit condition is "natural
language to validated structured intent, *offline-testable*", and that is only
achievable if the extractor depends on types a test can construct.

So `IntentExtractor` never sees an `anthropic.types.Message`. It sees a
`ModelResponse`, which a fake client can produce in three lines. `client.py` is
the only module in the repository that imports the SDK, and one test asserts
that.

These are also the boundary at which model output stops being a network payload
and becomes **untrusted input** (ADR-001). A `ToolCall.arguments` dict is a
claim about what the model wants, not an instruction; nothing here validates it,
and nothing here may be executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

__all__ = [
    "Message",
    "ModelResponse",
    "Role",
    "StopReason",
    "TokenUsage",
    "ToolCall",
]

Role = Literal["user", "assistant"]


class StopReason(StrEnum):
    """Why the model stopped generating.

    `TOOL_USE` and `MAX_TOKENS` are the two the runtime must branch on: the
    first continues the tool loop, the second means the answer is truncated and
    must not be treated as complete (L§46, "malformed model output").
    """

    END_TURN = "END_TURN"
    TOOL_USE = "TOOL_USE"
    MAX_TOKENS = "MAX_TOKENS"
    STOP_SEQUENCE = "STOP_SEQUENCE"
    REFUSAL = "REFUSAL"
    #: The provider returned a reason this application does not model. Kept
    #: rather than coerced, so an unknown value is visible instead of silently
    #: reading as a normal end of turn.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool the model asked for. A *request*, never an authorization.

    `arguments` is raw model output: an arbitrary JSON object that has passed no
    validation whatsoever. A§19 requires it through parse → schema validation →
    authorization → business validation before anything executes, and ADR-009
    adds that any identifier inside it is a lookup key rather than a fact.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Tokens billed for one call, for the cost control L§47 asks for."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of conversation as the model sees it.

    Only `user` and `assistant` roles: the system prompt is a separate parameter
    on the client, not a message, because it is application-authored and must
    never be confusable with something a buyer typed. That separation is part of
    the prompt-injection boundary (L§29) — buyer text always arrives as a `user`
    message, never as an instruction.
    """

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """What one call to the model produced."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: StopReason = StopReason.END_TURN
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""

    @property
    def requested_tools(self) -> bool:
        return bool(self.tool_calls)

    @property
    def is_truncated(self) -> bool:
        """Whether the answer was cut off mid-generation.

        A truncated response is not a short response. Treating one as complete
        is how a half-formed intent or a partial tool call gets acted on.
        """
        return self.stop_reason is StopReason.MAX_TOKENS

    def tool_call(self, name: str) -> ToolCall | None:
        """The first call to `name`, or `None`."""
        return next((call for call in self.tool_calls if call.name == name), None)
