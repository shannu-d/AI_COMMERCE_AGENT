"""The A§19 validation pipeline, implemented once for every tool (ADR-009).

    tool call -> parse -> schema validation -> authorization
              -> business validation -> execute -> validated result

Written once rather than once per tool, because a pipeline each handler applied
for itself would be a pipeline some handler eventually skipped. A tool module
contains business logic and nothing else; whether the call was allowed to happen
at all is decided here, before the handler is reached.

**Every failure leaves as a structured result, not an exception.** A§42 fixes the
shape and F§25 the codes. The model is told *that* a call failed and *which*
kind of failure it was, in a sentence written for a buyer — never a traceback,
never a database message, never a Python type name. That is what lets the agent
say "I could not check that" instead of filling the gap from memory (L§30, A§41).

**The loop limit is enforced here** (A§36, ADR-009, closing E1). Eight calls per
buyer turn. The counter belongs to the executor rather than to the runtime loop
because it must bound calls however they arrive — including a model that asks for
several tools in one reply.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.context import AgentContext, TurnMemory
from app.agent.errors import ToolError, ToolErrorCode
from app.agent.registry import ToolRegistry
from app.llm.tool_schemas import FORBIDDEN_TOOL_NAMES, RiskTier

logger = logging.getLogger(__name__)

__all__ = ["ToolExecutor"]


def _problems(exc: ValidationError) -> str:
    """A validation failure the model can act on, without internal detail.

    Field name and message only. Pydantic's full error carries the input value
    and a documentation URL; echoing the input back to a model that just
    produced it is noise, and the URL is not something it can follow.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}"
        for error in exc.errors()
    )


class ToolExecutor:
    """Runs registered tools, and refuses everything else."""

    def __init__(
        self,
        registry: ToolRegistry,
        context: AgentContext,
        *,
        max_calls_per_turn: int,
    ) -> None:
        self._registry = registry
        self._context = context
        self._max_calls = max_calls_per_turn

    @property
    def max_calls_per_turn(self) -> int:
        return self._max_calls

    def remaining(self, memory: TurnMemory) -> int:
        """Calls left in this turn. The runtime uses it to warn before it stops."""
        return max(0, self._max_calls - memory.call_count)

    def execute(self, name: str, arguments: dict[str, Any], memory: TurnMemory) -> dict[str, Any]:
        """One tool call, through the whole pipeline.

        Always returns a result payload — `{"success": true, ...}` or the A§42
        error shape. It does not raise: a raised `ToolError` would have to be
        caught by the runtime loop and converted anyway, and one conversion site
        is one place for the rule to be wrong.

        The call is recorded in `memory` whether it succeeded or failed, because
        A§39's trace has to show the attempts as well as the answers, and because
        a failed call still consumed one of the eight.
        """
        try:
            payload = self._execute(name, arguments, memory)
            result: dict[str, Any] = {"success": True, "result": payload}
        except ToolError as error:
            logger.info(
                "tool call failed",
                extra={"tool": name, "code": error.code.value},
            )
            result = error.as_result()
        except Exception:  # the boundary that must not leak
            # An unexpected fault becomes INTERNAL_ERROR with a generic sentence.
            # The exception is logged for an operator; its text never reaches the
            # model, because a stack trace in the context window is an invitation
            # to reason about internals (F§25).
            logger.exception("tool raised an unexpected exception", extra={"tool": name})
            result = ToolError(
                ToolErrorCode.INTERNAL_ERROR,
                "that lookup failed for a technical reason",
            ).as_result()

        memory.record(name, arguments, result)
        return result

    # -- the pipeline --------------------------------------------------------

    def _execute(self, name: str, arguments: dict[str, Any], memory: TurnMemory) -> dict[str, Any]:
        # 1. The limit, before anything else. A call that cannot be afforded is
        #    not validated, authorized or run.
        if memory.call_count >= self._max_calls:
            raise ToolError(
                ToolErrorCode.TOOL_LIMIT_REACHED,
                (
                    f"this turn has already used its {self._max_calls} tool calls. "
                    "Answer with what you have, or ask the buyer to narrow the request."
                ),
            )

        # 2. Parse. A forbidden name is reported as forbidden rather than
        #    unknown, so an attempt at `create_order` is visible in a log
        #    instead of looking like a typo (ADR-009).
        if name in FORBIDDEN_TOOL_NAMES:
            raise ToolError(
                ToolErrorCode.FORBIDDEN_TOOL,
                f"{name!r} is not an available tool and cannot be called.",
            )

        tool = self._registry.get(name)
        if tool is None:
            raise ToolError(
                ToolErrorCode.UNKNOWN_TOOL,
                f"{name!r} is not an available tool.",
                details={"available": list(self._registry.names())},
            )

        if not isinstance(arguments, dict):
            raise ToolError(
                ToolErrorCode.INVALID_ARGUMENTS,
                f"tool arguments must be a JSON object, got {type(arguments).__name__}",
            )

        # 3. Schema validation. The argument model is `extra="forbid"`, so a
        #    hallucinated field — a price, a stock level — fails here rather than
        #    being silently dropped and acted on as if it had never been sent.
        try:
            parsed: BaseModel = tool.arguments.model_validate(arguments)
        except ValidationError as exc:
            raise ToolError(
                ToolErrorCode.INVALID_ARGUMENTS,
                f"the arguments were not valid: {_problems(exc)}",
            ) from exc

        # 4. Authorization by tier (A§22, A§23). No tool is trusted merely
        #    because the model asked for it. M5 registers only LOW-tier read
        #    tools; a MEDIUM one arriving here before its milestone has wired
        #    its business checks is refused rather than run.
        if tool.tier is not RiskTier.LOW:
            raise ToolError(
                ToolErrorCode.FORBIDDEN_TOOL,
                f"{name!r} is not available in this conversation.",
            )

        # 5. Business validation and execution. Everything from here is the
        #    handler's own job, and it runs against services that scope every
        #    query by merchant.
        return tool.handler(self._context, memory, parsed)
