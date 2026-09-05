"""A model whose behaviour the case file gets to choose.

ADR-015 forbids any test from calling a live model, and the evaluation suite has
a second reason to want the model scripted: **the model's behaviour is the
independent variable.** A live model rarely tries to call `create_order`, rarely
invents a SKU, rarely asks for a product it was never shown. Those are exactly
the behaviours the application's guarantees exist for, and a suite that waited
for a real model to attempt them would mostly be measuring the model's luck.

So a case declares a `model_plan` — the sequence of tool calls and the final
prose a model produces this turn — and this client replays it. A well-behaved
plan checks that a correct request is served correctly. A misbehaving plan
checks the only thing that actually matters: that a model determined to break
the invariant cannot.

What the runtime does with the plan is not scripted. Validation, authorization,
the call bound, the ranking engine, the cart and the policy engine all run for
real, against a real database.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

from app.llm.models import Message, ModelResponse, StopReason, TokenUsage, ToolCall

__all__ = ["ScriptedModel", "plan_to_responses"]


def plan_to_responses(plan: Sequence[dict[str, Any]]) -> list[ModelResponse]:
    """A case's `model_plan` as the responses a model would have produced.

    Each step is one model turn:

    * ``{"tools": [{"name": ..., "arguments": {...}}, ...]}`` — a turn that asks
      for one or more tools. Several in one step is deliberate: A§36's bound has
      to hold however the calls arrive, including several in a single reply.
    * ``{"say": "..."}`` — the final prose that ends the turn.
    * ``{"truncated": "..."}`` — a reply cut off mid-generation (L§46).
    * ``{"refusal": "..."}`` — the provider refused to answer.
    """
    counter = itertools.count(1)
    responses: list[ModelResponse] = []
    for step in plan:
        if "tools" in step:
            calls = tuple(
                ToolCall(
                    id=f"call_{next(counter)}",
                    name=call["name"],
                    arguments=dict(call.get("arguments", {})),
                )
                for call in step["tools"]
            )
            responses.append(
                ModelResponse(
                    text=step.get("text", ""),
                    tool_calls=calls,
                    stop_reason=StopReason.TOOL_USE,
                    usage=TokenUsage(input_tokens=100, output_tokens=20),
                )
            )
        elif "truncated" in step:
            responses.append(
                ModelResponse(text=step["truncated"], stop_reason=StopReason.MAX_TOKENS)
            )
        elif "refusal" in step:
            responses.append(ModelResponse(text=step["refusal"], stop_reason=StopReason.REFUSAL))
        else:
            responses.append(
                ModelResponse(
                    text=step.get("say", ""),
                    stop_reason=StopReason.END_TURN,
                    usage=TokenUsage(input_tokens=100, output_tokens=40),
                )
            )
    return responses


class ScriptedModel:
    """An `LLMClient` that replays a plan and records what it was sent.

    Running past the end of the plan is not an error here — unlike the LLM
    layer's own `FakeClient`, which treats it as a test bug. An evaluation case
    that deliberately overruns the tool budget cannot know in advance how many
    times the runtime will come back, so the fall-through is a plain final
    answer and the *grader* decides whether that was acceptable.
    """

    def __init__(self, plan: Sequence[dict[str, Any]], *, fallback: str = "") -> None:
        self.queued: list[ModelResponse] = plan_to_responses(plan)
        self.calls: list[dict[str, Any]] = []
        self._fallback = fallback or "Here is what I found."

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
                "tools": list(tools or []),
                "tool_choice": tool_choice,
            }
        )
        if not self.queued:
            return ModelResponse(text=self._fallback, stop_reason=StopReason.END_TURN)
        return self.queued.pop(0)

    # -- what the payload can be asked about ---------------------------------

    @property
    def offered_tool_names(self) -> tuple[str, ...]:
        """Every tool name the runtime actually offered the model.

        The suite asserts on this because "`create_order` is absent" is a claim
        about the payload, not about the registry: a tool the model is told
        about is a capability it will plan around.
        """
        names: set[str] = set()
        for call in self.calls:
            for tool in call["tools"]:
                function = tool.get("function", tool)
                name = function.get("name")
                if name:
                    names.add(str(name))
        return tuple(sorted(names))

    @property
    def system_prompts(self) -> tuple[str, ...]:
        return tuple(str(call["system"]) for call in self.calls)
