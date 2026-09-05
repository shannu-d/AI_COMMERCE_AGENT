"""What one evaluation case produced, in a shape every grader can read.

The three runners — the agent runtime, the MCP surface, the commerce/money path
— observe very different things, and folding them into one record is what lets a
check like `prices_are_authoritative` be written once. Anything genuinely
specific to one runner goes in `extras` and is read only by the checks that know
about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Observation"]


@dataclass
class Observation:
    """One case's actual result. Facts only — no verdict."""

    case_id: str
    mode: str
    #: The assistant's prose. Scripted in offline mode, real in live mode.
    message: str = ""
    #: ADR-010's structured half: what the ranking engine produced.
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    cart: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    #: Every tool call attempted this run, as `{"tool", "arguments", "result"}`.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    #: Tool names the runtime offered the model.
    offered_tools: tuple[str, ...] = ()
    #: Runner-specific observations: policy decisions, order rows, MCP payloads,
    #: provider calls, counts taken before and after.
    extras: dict[str, Any] = field(default_factory=dict)
    #: An exception the runner could not attribute to the system under test.
    crashed: str | None = None
    #: How many conversational turns the runner drove. A multi-turn case that
    #: narrows a request ("...only black ones", "...under 1200") must be graded
    #: on the turn that carries the narrowed constraint, or the first turn's
    #: deliberately wider results would fail a check that is not about them.
    turn_count: int = 1

    def scoped_to_last_turn(self) -> Observation:
        """The same observation with only the final turn's tool calls.

        A shallow copy rather than a mutation: several checks on one case may
        want different scopes, and a check that narrowed the shared record would
        change what the next one sees.
        """
        last = self.turn_count - 1
        clone = Observation(
            case_id=self.case_id,
            mode=self.mode,
            message=self.message,
            recommendations=self.recommendations,
            cart=self.cart,
            error=self.error,
            tool_calls=[c for c in self.tool_calls if c.get("turn", last) == last],
            offered_tools=self.offered_tools,
            extras=self.extras,
            crashed=self.crashed,
            turn_count=self.turn_count,
        )
        return clone

    # -- convenience the checks share ---------------------------------------

    def results_of(self, tool: str | None = None) -> list[dict[str, Any]]:
        """Every ranked row any search tool returned, flattened.

        `results` only — never `alternatives`. R§14 makes that distinction and
        the graders must not blur it: an alternative offered as a match is the
        failure, so a check that read both would be unable to see it.
        """
        rows: list[dict[str, Any]] = []
        for call in self.tool_calls:
            if tool is not None and call["tool"] != tool:
                continue
            payload = call.get("result", {})
            if not payload.get("success"):
                continue
            body = payload.get("result", {})
            rows.extend(body.get("results", []) or [])
        return rows

    def alternatives(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for call in self.tool_calls:
            payload = call.get("result", {})
            if payload.get("success"):
                rows.extend(payload.get("result", {}).get("alternatives", []) or [])
        return rows

    def outcomes(self) -> list[str]:
        out: list[str] = []
        for call in self.tool_calls:
            payload = call.get("result", {})
            if payload.get("success"):
                outcome = payload.get("result", {}).get("outcome")
                if outcome:
                    out.append(str(outcome))
        return out

    def error_codes(self) -> list[str]:
        """Every tool error code raised this run, in order."""
        codes: list[str] = []
        for call in self.tool_calls:
            payload = call.get("result", {})
            if not payload.get("success"):
                code = payload.get("error", {}).get("code")
                if code:
                    codes.append(str(code))
        return codes

    def called(self, tool: str) -> list[dict[str, Any]]:
        return [call for call in self.tool_calls if call["tool"] == tool]

    def all_payload_rows(self) -> list[dict[str, Any]]:
        """Every product-shaped dict that left the system, whatever it was called.

        Used by the checks that must hold for *anything* shown to a buyer —
        that money is a string, that no exact stock count escaped — where the
        distinction between a match and an alternative does not matter.
        """
        rows = list(self.recommendations)
        rows.extend(self.results_of())
        rows.extend(self.alternatives())
        for call in self.tool_calls:
            payload = call.get("result", {})
            if not payload.get("success"):
                continue
            body = payload.get("result", {})
            rows.extend(body.get("variants", []) or [])
            rows.extend(body.get("candidates", []) or [])
            rows.extend(body.get("items", []) or [])
        if self.cart:
            rows.extend(self.cart.get("items", []) or [])
        rows.extend(self.extras.get("payload_rows", []))
        return [row for row in rows if isinstance(row, dict)]
