"""The frontend's copy of the API contract, checked against the real one.

The frontend cannot import Python, so `frontend/src/api/schemas.ts` mirrors
F§25's error vocabulary by hand. A hand-written copy of a closed set is exactly
the kind of thing that drifts: the backend adds a code, the frontend's Zod enum
rejects it, and the symptom is a `MALFORMED_RESPONSE` in the browser with no
hint of why.

The assertion lives here, in Python, because this is where the source of truth
is. It fails on either side of the drift — a code added to `ApiErrorCode` without
updating the frontend, or a frontend list edited away from the backend.

These tests skip rather than fail when the frontend is absent, so the backend
suite stays runnable on its own.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.agent.errors import API_ERROR_CODES
from app.config import REPO_ROOT

SCHEMAS_TS = REPO_ROOT / "frontend" / "src" / "api" / "schemas.ts"

pytestmark = pytest.mark.skipif(
    not SCHEMAS_TS.exists(),
    reason="the frontend is not present in this checkout",
)


def _frontend_sources() -> list[pathlib.Path]:
    root = REPO_ROOT / "frontend" / "src"
    return sorted(root.rglob("*.ts")) + sorted(root.rglob("*.tsx"))


def _declared_error_codes() -> list[str]:
    """The string literals inside the frontend's `API_ERROR_CODES` array."""
    source = SCHEMAS_TS.read_text(encoding="utf-8")
    match = re.search(
        r"export const API_ERROR_CODES = \[(.*?)\] as const;",
        source,
        re.DOTALL,
    )
    assert match is not None, "API_ERROR_CODES array not found in schemas.ts"
    return re.findall(r'"([A-Z_]+)"', match.group(1))


def test_the_frontend_error_codes_match_the_backend_exactly() -> None:
    """F§25's vocabulary is closed, and both sides must agree on it."""
    assert _declared_error_codes() == list(API_ERROR_CODES)


def test_the_frontend_lists_each_code_once() -> None:
    codes = _declared_error_codes()

    assert len(codes) == len(set(codes))


def _strip_comments(text: str) -> str:
    """Remove `//` and block comments.

    Naming a secret in a comment that explains it must never appear here is
    exactly the documentation we want; only executable code is searched.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                break
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def test_no_secret_value_is_hardcoded_in_frontend_source() -> None:
    """A key-shaped literal must never appear in code that ships to a browser."""
    frontend_src = REPO_ROOT / "frontend" / "src"
    key_shapes = ("gsk_", "rzp_live_", "sk-ant-", "whsec_")

    offenders: list[str] = []
    for path in _frontend_sources():
        code = _strip_comments(path.read_text(encoding="utf-8"))
        for shape in key_shapes:
            if shape in code:
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{shape}")
    assert offenders == [], offenders
    assert frontend_src.exists()


def test_no_secret_bearing_env_var_is_read_by_frontend_code() -> None:
    """ADR-017 and ADR-018: no secret may reach frontend code.

    Vite inlines `VITE_`-prefixed variables into the published bundle, so a
    `VITE_`-prefixed secret is a published secret. The only credential that may
    ever reach the browser is the *public* Razorpay key id, and it arrives in a
    response body at checkout time rather than from configuration.

    Comments are stripped first: `config.ts` names these variables deliberately,
    in prose explaining that they must never be read here, and that
    documentation is the point rather than a violation.
    """
    forbidden = (
        "GROQ_API_KEY",
        "ANTHROPIC_API_KEY",
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
        "DATABASE_URL",
    )

    offenders: list[str] = []
    for path in _frontend_sources():
        code = _strip_comments(path.read_text(encoding="utf-8"))
        for name in forbidden:
            if name in code:
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{name}")
    assert offenders == [], offenders


def test_the_only_vite_variable_is_the_api_base_url() -> None:
    """A new `VITE_` variable is a deliberate decision, not an incidental one.

    Anything added here ships to every browser that loads the app, so the list
    is asserted rather than left to review.
    """

    allowed = {"VITE_API_BASE_URL"}
    found: set[str] = set()
    for path in _frontend_sources():
        code = _strip_comments(path.read_text(encoding="utf-8"))
        found.update(re.findall(r"VITE_[A-Z0-9_]+", code))

    assert found <= allowed, sorted(found - allowed)
