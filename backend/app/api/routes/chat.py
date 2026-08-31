"""`POST /api/chat` — the agent's only entry point (ADR-010, A§48, F§8).

The route is thin on purpose. It mints or loads a session, builds the runtime
from request-scoped services, runs one turn, and shapes the result into ADR-010's
contract. Every decision worth making happens below it, in code that can be
tested without an HTTP client.

**Status codes follow ADR-010 exactly.** `200` for any turn the agent completed,
including one that ends in a business failure — a refusal is a successful
conversational turn with an `error` body, and returning `4xx` would put an
outcome the frontend must render as a recovery flow into the client's
network-error path. `4xx` is reserved for a malformed request or an unknown
session; `5xx` for a genuine server fault.

**The session is committed even when the turn fails.** The buyer's message and
whatever state the turn reached are written either way, because a conversation
that loses its last message on an error is a conversation the buyer has to
restart.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.agent.context import AgentContext
from app.agent.errors import ApiErrorCode
from app.agent.registry import build_registry
from app.agent.runtime import AgentRuntime, TurnResult
from app.api.schemas.chat import ChatError, ChatRequest, ChatResponse, Recommendation
from app.config import Settings, get_settings
from app.db.session import get_db
from app.llm.client import LLMClient, build_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def get_llm_client() -> LLMClient:
    """The model client, as a dependency so a test can replace it.

    ADR-015: every consumer depends on the `LLMClient` protocol rather than on
    `AnthropicClient`. Overriding this in a test is what makes the endpoint
    testable with no key and no network — the same seam the LLM layer uses, one
    level up.
    """
    return build_client()


def build_runtime(
    context: AgentContext,
    settings: Settings,
    client: LLMClient,
) -> AgentRuntime:
    """One runtime for one request, over one already-built context.

    The context is passed in rather than constructed here so that the route
    holds exactly one of them. Two `AgentContext` objects over the same database
    session would work, and would also mean two `SessionService` instances whose
    identity a reader has to reason about; one is simply correct.
    """
    return AgentRuntime(
        client,
        build_registry(),
        context,
        max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
        trace_enabled=settings.agent_trace_enabled,
        top_k=settings.ranking_top_k,
    )


def _to_response(result: TurnResult) -> ChatResponse:
    """The runtime's answer, in ADR-010's shape.

    `recommendations` is validated on the way out. The runtime built it from
    ranking-engine output, and validating it here means a field that stopped
    matching the contract fails in a test rather than reaching a browser.
    """
    return ChatResponse(
        session_id=result.session_id,
        state=result.state,
        message=result.message,
        recommendations=[Recommendation.model_validate(item) for item in result.recommendations],
        cart=None,  # M7
        trace=result.trace,
        error=(
            None
            if result.error is None
            else ChatError(
                code=result.error.code,
                message=result.error.message,
                details=result.error.details,
            )
        ),
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Send one buyer message to the agent",
    responses={
        404: {"description": "The supplied session_id does not exist."},
        422: {"description": "The request body is malformed."},
    },
)
def chat(
    request: ChatRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: LLMClient = Depends(get_llm_client),
) -> ChatResponse:
    """One turn of conversation."""
    # The merchant is resolved from configuration, server-side. It is never read
    # from the request body and never taken from model output (ADR-002) - a
    # merchant id a client could set would be a merchant id a client could change.
    merchant_id = settings.default_merchant_id
    context = AgentContext.from_session(db, merchant_id)
    runtime = build_runtime(context, settings, client)

    if request.session_id is None:
        session_id = context.sessions.create(merchant_id).id
    else:
        # ADR-010: an unknown session is rejected rather than silently created,
        # so a typo cannot strand a conversation in a new one the buyer will
        # never see again.
        if context.sessions.get(merchant_id, request.session_id) is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": ApiErrorCode.VALIDATION_ERROR.value,
                    "message": "SESSION_NOT_FOUND: no such session for this merchant",
                },
            )
        session_id = request.session_id

    try:
        result = runtime.run_turn(session_id, request.message)
    except Exception:
        # The turn's own failures are already TurnResults; reaching here means
        # something outside the loop faulted. The session's writes are rolled
        # back and the client gets a 5xx, never an exception message (F§25).
        db.rollback()
        logger.exception("chat turn faulted", extra={"session_id": str(session_id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ApiErrorCode.SERVER_ERROR.value,
                "message": "the request could not be completed",
            },
        ) from None

    db.commit()
    return _to_response(result)
