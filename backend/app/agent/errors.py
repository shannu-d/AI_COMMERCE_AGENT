"""Structured tool and turn failures (A§42, F§25, ADR-009, ADR-010).

Two rules govern this module, and both are about what a failure must *not*
become.

**A failure never reaches the model as a traceback.** A§42 requires a structured,
machine-readable result; F§25 fixes the vocabulary. A Python exception string in
the model's context is an invitation to reason about internals, and a database
error string leaks schema. Every failure here is a code plus a sentence written
for a buyer.

**A failure never becomes a fabrication.** L§30 and A§41: when a tool fails the
agent says so. The structural guarantee behind that is not this module — it is
that the agent has no catalog data except what a tool returned this turn
(ADR-009) — but the codes are what let it say *which* thing failed.

`ToolErrorCode` and `ApiErrorCode` are separate on purpose. The first is the
agent's internal vocabulary, rich enough for the runtime to decide whether to
retry, re-plan or give up. The second is F§25's closed list, which is what a
client may ever see. `to_api_code` is the only mapping between them, so widening
the internal set can never silently widen the public contract.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

__all__ = [
    "API_ERROR_CODES",
    "ApiErrorCode",
    "ToolError",
    "ToolErrorCode",
    "TurnError",
    "to_api_code",
]


class ApiErrorCode(StrEnum):
    """F§25's eleven codes. The complete set a client may receive (ADR-010)."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    VARIANT_NOT_FOUND = "VARIANT_NOT_FOUND"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PRICE_CHANGED = "PRICE_CHANGED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    POLICY_FAILED = "POLICY_FAILED"
    ORDER_CREATION_FAILED = "ORDER_CREATION_FAILED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    SERVER_ERROR = "SERVER_ERROR"


#: The closed list, for tests that assert the contract has not grown.
API_ERROR_CODES: tuple[str, ...] = tuple(code.value for code in ApiErrorCode)


class ToolErrorCode(StrEnum):
    """Why a tool call failed, in the runtime's own vocabulary."""

    # -- the call was malformed --------------------------------------------
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    #: A name the registry does not hold. Distinct from FORBIDDEN_TOOL so that a
    #: typo and an attempt at `create_order` are never confused in a log.
    FORBIDDEN_TOOL = "FORBIDDEN_TOOL"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"

    # -- the identifier did not resolve ------------------------------------
    #: ADR-009: a model-supplied identifier is a lookup key, never a fact. A
    #: miss is an error rather than a warning (A§30).
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    VARIANT_NOT_FOUND = "VARIANT_NOT_FOUND"
    CATEGORY_NOT_FOUND = "CATEGORY_NOT_FOUND"
    #: ADR-003: unresolvable or ambiguous means ask the buyer. Never guess,
    #: never substring-match, never drop the constraint to obtain results.
    DEVICE_NOT_RESOLVED = "DEVICE_NOT_RESOLVED"
    DEVICE_AMBIGUOUS = "DEVICE_AMBIGUOUS"

    # -- the request was well-formed and the answer is no ------------------
    OUT_OF_STOCK = "OUT_OF_STOCK"
    NO_MATCH = "NO_MATCH"

    # -- the runtime stopped it --------------------------------------------
    TOOL_LIMIT_REACHED = "TOOL_LIMIT_REACHED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


#: How the internal vocabulary narrows onto F§25's. Anything unmapped becomes
#: `SERVER_ERROR`, which is the safe direction: a code the client does not know
#: how to render is worse than a generic one.
_API_CODES: dict[ToolErrorCode, ApiErrorCode] = {
    ToolErrorCode.UNKNOWN_TOOL: ApiErrorCode.SERVER_ERROR,
    ToolErrorCode.FORBIDDEN_TOOL: ApiErrorCode.SERVER_ERROR,
    ToolErrorCode.INVALID_ARGUMENTS: ApiErrorCode.VALIDATION_ERROR,
    ToolErrorCode.PRODUCT_NOT_FOUND: ApiErrorCode.PRODUCT_NOT_FOUND,
    ToolErrorCode.VARIANT_NOT_FOUND: ApiErrorCode.VARIANT_NOT_FOUND,
    ToolErrorCode.CATEGORY_NOT_FOUND: ApiErrorCode.VALIDATION_ERROR,
    ToolErrorCode.DEVICE_NOT_RESOLVED: ApiErrorCode.VALIDATION_ERROR,
    ToolErrorCode.DEVICE_AMBIGUOUS: ApiErrorCode.VALIDATION_ERROR,
    ToolErrorCode.OUT_OF_STOCK: ApiErrorCode.OUT_OF_STOCK,
    ToolErrorCode.NO_MATCH: ApiErrorCode.VALIDATION_ERROR,
    ToolErrorCode.TOOL_LIMIT_REACHED: ApiErrorCode.SERVER_ERROR,
    ToolErrorCode.INTERNAL_ERROR: ApiErrorCode.SERVER_ERROR,
}


def to_api_code(code: ToolErrorCode) -> ApiErrorCode:
    """The F§25 code a client sees for an internal failure."""
    return _API_CODES.get(code, ApiErrorCode.SERVER_ERROR)


class ToolError(Exception):
    """A tool call that failed. Caught by the executor, never raised at a model.

    `details` carries machine-readable context — the identifier that missed, the
    candidates an ambiguous device matched. It must contain nothing a buyer may
    not see and nothing a model may treat as fact: an identifier that failed to
    resolve is not evidence of anything that does exist.
    """

    def __init__(
        self,
        code: ToolErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code.value}: {message}")

    def as_result(self) -> dict[str, Any]:
        """The A§42 shape the model receives in place of a result."""
        payload: dict[str, Any] = {
            "success": False,
            "error": {"code": self.code.value, "message": self.message},
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


class TurnError(Exception):
    """A turn that cannot produce an answer, in F§25's vocabulary.

    Distinct from `ToolError`: a failed tool is something the agent can tell the
    model about and route around, whereas this ends the turn. It is what the
    `error` field of the ADR-010 response carries.
    """

    def __init__(
        self,
        code: ApiErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code.value}: {message}")

    @classmethod
    def from_tool_error(cls, error: ToolError) -> TurnError:
        return cls(to_api_code(error.code), error.message, details=error.details)
