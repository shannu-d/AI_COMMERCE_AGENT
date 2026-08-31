"""The tool registry: which tools exist, and what each one runs (ADR-009).

The registry is the *binding* layer, and it is deliberately thin. `app/llm`
already owns what the model is told a tool looks like — name, description, risk
tier, argument schema — and re-declaring any of that here would create two
descriptions of one tool that could disagree. What this module adds is the one
thing `app/llm` must never hold: the function that actually runs.

That split is why `tests/llm/test_boundaries.py` can assert no module under
`app/llm` is named after a tool. The model's action space is reviewable without
reading a single line of what happens when it acts.

**`create_order` is absent** (ADR-009, closing D6). Not registered with a
failing handler — absent. A registered tool with a hard-failing handler is still
a tool the model can reason about and try to route around; the safest tool is one
that does not exist. `FORBIDDEN_TOOL_NAMES` and a standing test keep it out, and
a call to it reports *forbidden* rather than *unknown*, so the attempt is visible
in a log rather than looking like a typo.

**A tool is exposed only once it can run.** `build_registry` refuses a name it
has no handler for, so the model is never offered a capability it would plan
around and then find missing. M5 registered the five read tools; M7 adds
`propose_cart` and M8 `request_approval`. `get_order_status` has a schema in
`app/llm` and no handler here until M11. M8 adds `request_approval`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.agent.context import AgentContext, TurnMemory
from app.agent.tools.approval import request_approval
from app.agent.tools.cart import propose_cart
from app.agent.tools.catalog import get_product, search_catalog
from app.agent.tools.compatibility import get_compatible_products
from app.agent.tools.inventory import check_inventory, get_upsell_candidates
from app.llm.tool_schemas import (
    EXPOSED_TOOL_NAMES,
    FORBIDDEN_TOOL_NAMES,
    TOOL_SCHEMAS,
    RiskTier,
    ToolDefinition,
)

__all__ = ["AVAILABLE_TOOL_NAMES", "HANDLERS", "RegisteredTool", "ToolRegistry", "build_registry"]

#: The callable a registered tool runs. Every handler has this shape, which is
#: what lets the executor implement A§19 once rather than once per tool.
ToolHandler = Callable[[AgentContext, TurnMemory, Any], dict[str, Any]]

#: Name to handler. The keys are the *only* tools this milestone can execute.
#: A name here that `TOOL_SCHEMAS` does not define, or a schema whose milestone
#: has arrived without a handler, is caught by `build_registry`.
HANDLERS: Mapping[str, ToolHandler] = {
    "search_catalog": search_catalog,
    "get_product": get_product,
    "get_compatible_products": get_compatible_products,
    "check_inventory": check_inventory,
    "get_upsell_candidates": get_upsell_candidates,
    # M7. MEDIUM tier: writes cart state, computes nothing, authorizes nothing.
    "propose_cart": propose_cart,
    # M8. MEDIUM tier, and the one whose name most suggests otherwise: it asks
    # for approval and cannot grant it. The service method it calls has no
    # parameter through which APPROVED could arrive (ADR-007).
    "request_approval": request_approval,
}


#: What `build_registry` exposes by default: everything with a handler, in the
#: order `TOOL_SCHEMAS` declares. Derived rather than listed, so adding a handler
#: is the single edit that makes a tool available - and `build_registry` still
#: checks the pairing, because a derived list can be derived from a mistake.
AVAILABLE_TOOL_NAMES: tuple[str, ...] = tuple(
    name for name in EXPOSED_TOOL_NAMES if name in HANDLERS
)


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """One executable tool: what the model is told, and what runs."""

    definition: ToolDefinition
    handler: ToolHandler

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def tier(self) -> RiskTier:
        return self.definition.tier

    @property
    def arguments(self) -> type[BaseModel]:
        return self.definition.arguments


class ToolRegistry:
    """The tools one runtime may execute.

    Immutable after construction. A registry that could be added to at runtime
    would be a registry whose contents at the moment of a call are not the ones
    that were reviewed.
    """

    def __init__(self, tools: Mapping[str, RegisteredTool]) -> None:
        self._tools = dict(tools)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        """Sorted, so the payload sent to the model is byte-stable between runs."""
        return tuple(sorted(self._tools))

    def definitions(self) -> list[ToolDefinition]:
        return [self._tools[name].definition for name in self.names()]

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self.names())


def build_registry(names: tuple[str, ...] = AVAILABLE_TOOL_NAMES) -> ToolRegistry:
    """The registry for this milestone.

    Three things are checked at construction rather than at call time, because a
    registry that is wrong should fail when the application starts and not when a
    buyer is waiting:

    * every requested name has a schema in `app/llm`;
    * every requested name has a handler here;
    * no forbidden name is present, whatever was requested.
    """
    forbidden = sorted(set(names) & FORBIDDEN_TOOL_NAMES)
    if forbidden:
        raise ValueError(
            f"{forbidden} is not a tool and must never be registered (ADR-009, D6). "
            "Order creation is a user-initiated API path behind the Policy Engine."
        )

    missing_schema = sorted(name for name in names if name not in TOOL_SCHEMAS)
    if missing_schema:
        raise KeyError(f"no tool schema for {missing_schema}")

    missing_handler = sorted(name for name in names if name not in HANDLERS)
    if missing_handler:
        raise KeyError(f"no handler for {missing_handler}; a tool is exposed only once it can run")

    return ToolRegistry(
        {
            name: RegisteredTool(definition=TOOL_SCHEMAS[name], handler=HANDLERS[name])
            for name in names
        }
    )
