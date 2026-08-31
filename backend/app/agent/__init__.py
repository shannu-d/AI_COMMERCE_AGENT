"""The agent runtime (M5) — where a model's request becomes a validated action.

This is the layer ADR-001 puts between the two halves of the system. `app/llm`
says what the model may ask for; `app/services`, `app/ranking` and the catalog
decide what is true. Neither imports the other, and this package is the only
place they meet.

    POST /api/chat -> runtime loop -> executor (A§19) -> tool -> service -> PostgreSQL
                                          |
                                    ranking engine
                                  (deterministic, no model)

Three properties hold regardless of what the model produces, and each is
structural rather than a matter of prompt wording:

**The buyer's recommendations come from the ranker.** The response's
`recommendations[]` is assembled from what `RecommendationService` returned, held
in `TurnMemory`. Model prose travels in `message` and nothing is parsed out of it
(ADR-010, F§9).

**No tool call can move money.** M5 registers only LOW-tier read tools;
`create_order` is not a tool at any milestone (ADR-009, closing D6); the executor
refuses a name it does not hold and reports a forbidden one as forbidden.

**A failure is reported, never filled in.** Tool errors return a code and a
sentence in F§25's vocabulary; the agent has no catalog data except what a tool
returned this turn, so there is nothing to fabricate from (L§30, A§41).
"""

from app.agent.context import AgentContext, TurnMemory
from app.agent.errors import (
    API_ERROR_CODES,
    ApiErrorCode,
    ToolError,
    ToolErrorCode,
    TurnError,
    to_api_code,
)
from app.agent.executor import ToolExecutor
from app.agent.registry import HANDLERS, RegisteredTool, ToolRegistry, build_registry
from app.agent.runtime import AgentRuntime, TurnResult
from app.agent.state import next_state

__all__ = [
    "API_ERROR_CODES",
    "HANDLERS",
    "AgentContext",
    "AgentRuntime",
    "ApiErrorCode",
    "RegisteredTool",
    "ToolError",
    "ToolErrorCode",
    "ToolExecutor",
    "ToolRegistry",
    "TurnError",
    "TurnMemory",
    "TurnResult",
    "build_registry",
    "next_state",
    "to_api_code",
]
