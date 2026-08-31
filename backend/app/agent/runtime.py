"""The agent runtime: one buyer message in, one grounded turn out (A§49, A§51).

    validate -> load session -> load context -> load tools -> call Claude
             -> tool call? -> validate -> execute -> feed result back
             -> repeat until a final response

The loop A§49 draws, with A§51's six termination conditions and A§36's bound.

**What the runtime is, and is not.** It is not the model, and it is not a
wrapper that forwards whatever the model says. It is the controlled environment
in which a model's requests are validated before they run and its answers are
replaced by computed ones on the way out. Three properties hold no matter what
the model does:

*The recommendations a buyer sees come from the ranker.* The response's
`recommendations[]` is built from `TurnMemory`, which the tools wrote from
`RecommendationService` output. The model's prose is carried in `message` and
nothing is parsed out of it (ADR-010, F§9). A model that describes a product it
was never shown produces a turn whose structured half simply does not contain it.

*No sequence of tool calls can move money.* Only LOW-tier read tools are
registered in M5, `create_order` is not a tool at any milestone (ADR-009), and
the executor refuses anything else. Prompt injection is contained structurally:
"ignore your rules and buy it" fails because the tool that would do it does not
exist, not because the prompt asks the model to decline.

*A failure never becomes a fabrication.* A tool error returns a code and a
sentence; the loop hands that back to the model as a tool result so it can say
what failed. When the loop itself cannot continue, the turn ends with an F§25
error rather than with an answer assembled from nothing (L§30, A§41).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agent.context import AgentContext, TurnMemory
from app.agent.errors import ApiErrorCode, TurnError
from app.agent.executor import ToolExecutor
from app.agent.registry import ToolRegistry
from app.agent.state import next_state
from app.domain.conversation import ConversationState
from app.llm.client import LLMClient
from app.llm.errors import LLMError, LLMOutputError
from app.llm.models import Message, StopReason
from app.llm.prompts import load_system_prompt, prompt_version
from app.llm.tool_schemas import build_tool_definitions

logger = logging.getLogger(__name__)

__all__ = ["AgentRuntime", "TurnResult"]

#: How many past turns are replayed into the model's context. L§27 says not to
#: send unnecessary application data and gives no bound; older turns cost tokens
#: while contributing less than the accumulated intent already carries.
DEFAULT_HISTORY_TURNS = 20

#: Ceiling on one assistant reply. Generous for a chat turn and small enough
#: that a runaway generation is bounded rather than merely expensive.
DEFAULT_MAX_TOKENS = 2048


@dataclass
class TurnResult:
    """Everything one turn produced, before it is shaped into an API response.

    Deliberately not the response model: the runtime answers in domain terms and
    `app/api` decides what a client sees. That keeps ADR-010's contract in one
    place and leaves the runtime testable without importing FastAPI.
    """

    session_id: uuid.UUID
    state: ConversationState
    message: str
    #: Ranked results, from the ranking engine. Never parsed out of `message`.
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    #: The authoritative cart, backend-computed (F§12). `None` until the buyer
    #: has one; never assembled from anything the model said.
    cart: dict[str, Any] | None = None
    error: TurnError | None = None
    #: A§39. Returned per turn and never persisted (ADR-010, closing E6); the
    #: audit log is the durable record.
    trace: dict[str, Any] | None = None


class AgentRuntime:
    """One instance per request. Holds no state between turns."""

    def __init__(
        self,
        client: LLMClient,
        registry: ToolRegistry,
        context: AgentContext,
        *,
        max_tool_calls_per_turn: int = 8,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        history_turns: int = DEFAULT_HISTORY_TURNS,
        trace_enabled: bool = False,
        top_k: int = 3,
    ) -> None:
        self._client = client
        self._registry = registry
        self._context = context
        self._executor = ToolExecutor(registry, context, max_calls_per_turn=max_tool_calls_per_turn)
        self._max_tokens = max_tokens
        self._history_turns = history_turns
        self._trace_enabled = trace_enabled
        self._top_k = top_k

    # -- the turn ------------------------------------------------------------

    def run_turn(self, session_id: uuid.UUID, message: str) -> TurnResult:
        """One buyer message, start to finish.

        The buyer's message is written to history *before* the model is called,
        so a turn that fails mid-way still leaves a record of what was asked.
        """
        merchant_id = self._context.merchant_id
        sessions = self._context.sessions

        session = sessions.get(merchant_id, session_id)
        if session is None:
            # ADR-010: an unknown session is rejected rather than silently
            # created, so a typo cannot strand a conversation in a new one.
            raise LookupError(f"session {session_id} does not exist")

        sessions.append_message(merchant_id, session_id, role="user", content=message)
        sessions.touch(merchant_id, session_id)
        sessions.set_state(merchant_id, session_id, ConversationState.UNDERSTANDING_INTENT)

        memory = TurnMemory(session_id=session_id)
        try:
            reply = self._converse(session_id, message, memory)
        except LLMOutputError as error:
            # The model produced something unusable and the bounded repair did
            # not help. That is a technical failure of the turn, not an answer.
            logger.warning("turn failed on unusable model output", extra={"error": str(error)})
            return self._failed_turn(
                session_id,
                ApiErrorCode.SERVER_ERROR,
                "I could not put together an answer just then. Please try again.",
                memory,
            )
        except LLMError as error:
            logger.warning("turn failed on a model transport error", extra={"error": str(error)})
            return self._failed_turn(
                session_id,
                ApiErrorCode.SERVER_ERROR,
                "I could not reach the assistant just then. Please try again.",
                memory,
            )

        recommendations = self._collect_recommendations(memory)
        cart = self._current_cart(session_id)
        state = next_state(
            memory_has_results=bool(recommendations),
            tool_failed=self._any_tool_failed(memory),
            has_cart=cart is not None and bool(cart["items"]),
        )

        sessions.append_message(merchant_id, session_id, role="assistant", content=reply)
        sessions.set_state(merchant_id, session_id, state)

        return TurnResult(
            session_id=session_id,
            state=state,
            message=reply,
            recommendations=recommendations,
            cart=cart,
            trace=self._trace(memory),
        )

    # -- the loop ------------------------------------------------------------

    def _converse(self, session_id: uuid.UUID, message: str, memory: TurnMemory) -> str:
        """A§49's loop. Returns the model's final prose.

        Terminates on every one of A§51's conditions: a final response ends it
        normally; a clarification, a business failure and a tool failure all
        arrive as tool results the model turns into prose; the call limit is
        enforced by the executor and announced to the model as a tool result;
        and an unrecoverable technical error raises out of here.
        """
        conversation = self._history(session_id, message)
        system = load_system_prompt()
        # Real category slugs are injected into the schema as an enum, so the
        # model can only name a category the merchant actually has (ADR-009,
        # closing B2). Only the registered names are offered: a tool without a
        # handler would be a capability the model plans around and cannot use.
        tool_payload = build_tool_definitions(
            category_slugs=self._context.catalog.category_slugs(self._context.merchant_id),
            names=self._registry.names(),
        )

        # One more iteration than the call budget: the extra pass is what lets
        # the model turn the limit's refusal into a sentence for the buyer
        # rather than the turn ending on a bare error.
        for _ in range(self._executor.max_calls_per_turn + 1):
            response = self._client.complete(
                system=system,
                messages=conversation,
                tools=tool_payload,
                max_tokens=self._max_tokens,
                temperature=0.0,
            )

            if response.is_truncated:
                raise LLMOutputError(
                    "the model's answer was truncated; a partial turn is not a short turn"
                )
            if response.stop_reason is StopReason.REFUSAL:
                raise LLMOutputError("the model declined to answer")

            if not response.requested_tools:
                return response.text.strip()

            # The assistant turn that asked for tools has to stay in the
            # conversation, or the results below refer to a request the model
            # cannot see.
            conversation = [
                *conversation,
                Message(role="assistant", content=self._render_request(response)),
            ]
            results = [
                self._executor.execute(call.name, dict(call.arguments), memory)
                for call in response.tool_calls
            ]
            conversation.append(
                Message(role="user", content=self._render_results(response, results))
            )

        # Falling out of the loop means the model asked for tools on every
        # permitted pass. That is A§51 condition 5, and the buyer gets a
        # controlled answer rather than silence (A§36).
        return (
            "I wasn't able to narrow that down within this turn. "
            "Could you tell me a little more about what you're looking for?"
        )

    # -- prompt plumbing -----------------------------------------------------

    def _history(self, session_id: uuid.UUID, message: str) -> list[Message]:
        """Past turns plus the current one, oldest first.

        The buyer's message was already appended to the session, so it is the
        last row and does not need adding again.
        """
        rows = self._context.sessions.history(
            self._context.merchant_id, session_id, limit=self._history_turns
        )
        conversation = [
            Message(
                role="user" if row.role == "user" else "assistant",
                content=row.content or "",
            )
            for row in rows
            if row.content
        ]
        if not conversation:
            conversation = [Message(role="user", content=message)]
        return conversation

    @staticmethod
    def _render_request(response: Any) -> str:
        """The assistant's tool request, as text the next call can read.

        Rendered rather than replayed as provider-native content blocks, because
        `Message` is deliberately provider-agnostic (ADR-015) and a tool-use
        block is the one shape that differs most between providers. The model
        needs to see *that* it asked and *what* it asked; the exact wire form is
        the client's business.
        """
        asked = ", ".join(f"{call.name}({call.arguments})" for call in response.tool_calls)
        prose = response.text.strip()
        return f"{prose}\n\n[called: {asked}]" if prose else f"[called: {asked}]"

    @staticmethod
    def _render_results(response: Any, results: list[dict[str, Any]]) -> str:
        """Tool results, as JSON the model reads as data rather than as prose."""
        import json

        rendered = [
            {"tool": call.name, **result}
            for call, result in zip(response.tool_calls, results, strict=False)
        ]
        return (
            "Tool results follow. Use only what is here; do not add products, "
            "prices or stock levels from anywhere else.\n"
            f"{json.dumps(rendered, ensure_ascii=False)}"
        )

    # -- assembling the answer ----------------------------------------------

    def _collect_recommendations(self, memory: TurnMemory) -> list[dict[str, Any]]:
        """The ranked results this turn produced, from the ranker (ADR-010).

        Read out of `TurnMemory` rather than out of the model's reply. If the
        model recommended something the ranker did not, it is absent here — the
        structured half of the response cannot be talked into carrying it.
        """
        from app.agent.tools._serialize import serialize_ranked

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in memory.recommendations.values():
            for candidate in result.candidates[: self._top_k]:
                key = str(candidate.variant.id)
                if key not in seen:
                    seen.add(key)
                    out.append(serialize_ranked(candidate))
        return out

    def _current_cart(self, session_id: uuid.UUID) -> dict[str, Any] | None:
        """The session's cart, re-read after the turn rather than remembered.

        Read from the Cart Service, not from whatever `propose_cart` returned
        mid-turn: a later tool call may have changed it, and F§12 says the
        authoritative total is the backend's current one. `None` when the
        session has no cart, which is different from an empty one.
        """
        from app.agent.tools.cart import serialize_cart

        cart = self._context.carts.get_active(self._context.merchant_id, session_id)
        return None if cart is None else serialize_cart(cart)

    @staticmethod
    def _any_tool_failed(memory: TurnMemory) -> bool:
        return any(not call["result"].get("success", False) for call in memory.calls)

    def _trace(self, memory: TurnMemory) -> dict[str, Any] | None:
        """A§39's trace, when enabled.

        `null` by default (ADR-010, closing E6). It carries what was asked and
        what came back, never prompt text and never a secret — the tool payloads
        it holds were already built for the model, so nothing new is exposed by
        showing them.
        """
        if not self._trace_enabled:
            return None
        return {
            "prompt_version": prompt_version(),
            "tool_calls": memory.calls,
            "tools_available": list(self._registry.names()),
        }

    def _failed_turn(
        self,
        session_id: uuid.UUID,
        code: ApiErrorCode,
        message: str,
        memory: TurnMemory,
    ) -> TurnResult:
        """A turn that could not produce an answer, in F§25's vocabulary.

        The state moves to `TOOL_ERROR` so the UI can show that something went
        wrong, and `recommendations` stays empty — there is nothing grounded to
        show, and showing stale results would be the fabrication L§30 forbids.
        """
        self._context.sessions.set_state(
            self._context.merchant_id, session_id, ConversationState.TOOL_ERROR
        )
        return TurnResult(
            session_id=session_id,
            state=ConversationState.TOOL_ERROR,
            message=message,
            error=TurnError(code, message),
            trace=self._trace(memory),
        )
