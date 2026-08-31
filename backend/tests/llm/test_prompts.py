"""The version-controlled prompts (L§28, LLM-04).

A prompt cannot be unit-tested for behaviour without a live model, and a live
model would make these tests a sampling experiment. What *can* be tested is
everything that makes the prompt auditable: that it is on disk rather than in a
string literal, that it is versioned, that the editorial commentary is not paid
for on every turn, and that the rules the specification names by number are
actually in the text.

The point of L§29 and ADR-009 is that none of this is what makes the system
safe. `test_the_architecture_does_not_depend_on_this_text` is the assertion that
matters most in the file.
"""

from __future__ import annotations

import re

import pytest

from app.llm.prompts import (
    PROMPT_DIR,
    PROMPT_VERSION,
    PROMPT_VERSIONS,
    load_system_prompt,
    prompt_version,
)
from app.llm.tool_schemas import FORBIDDEN_TOOL_NAMES, TOOL_SCHEMAS

PROMPT_NAMES = sorted(PROMPT_VERSIONS)


def flat(name: str = "system_prompt") -> str:
    """A prompt with its line wrapping collapsed.

    These files are wrapped prose. Asserting on a phrase that happens to
    straddle a line break would make a re-wrap look like a deleted rule, so the
    tests read the text the way the model does — as a stream of words.
    """
    return re.sub(r"\s+", " ", load_system_prompt(name))


# --------------------------------------------------------------------------
# Auditability
# --------------------------------------------------------------------------


def test_every_prompt_on_disk_has_a_recorded_version() -> None:
    """A stored trace is only evidence about the prompt that produced it.

    A new prompt arriving unversioned would make every transcript that used it
    unattributable, which is the failure L§28 is guarding against.
    """
    on_disk = sorted(path.stem for path in PROMPT_DIR.glob("*.md"))

    assert on_disk == PROMPT_NAMES


def test_an_unversioned_prompt_cannot_be_stamped() -> None:
    with pytest.raises(KeyError, match="no recorded version"):
        prompt_version("something_nobody_wrote")


def test_a_missing_prompt_fails_loudly() -> None:
    with pytest.raises(FileNotFoundError):
        load_system_prompt("not_a_prompt")


def test_the_conversational_prompt_keeps_its_own_name() -> None:
    assert PROMPT_VERSION == PROMPT_VERSIONS["system_prompt"]


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_the_editorial_comment_is_not_sent_to_the_model(name: str) -> None:
    """L§27: the notes explaining a file to a reviewer are not addressed to the model."""
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    loaded = load_system_prompt(name)

    assert raw.lstrip().startswith("<!--")
    assert "<!--" not in loaded
    assert loaded


# --------------------------------------------------------------------------
# The conversational prompt (LLM-04's twelve rules)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "phrase"),
    [
        ("grounding", "Never invent catalog facts"),
        ("tool results win", "the tool result is correct"),
        ("budget", "ceiling, not a suggestion"),
        ("clarification", "Ask when it matters"),
        ("ranking", "computed by the application"),
        ("payment boundary", "You do not move money"),
        ("approval", "explicit approval"),
        ("policy boundary", "that is the system working"),
        ("honest failure", "Say so honestly"),
        ("injection", "content"),
    ],
)
def test_the_system_prompt_states_each_behavioural_rule(subject: str, phrase: str) -> None:
    assert phrase in flat(), f"the {subject} rule is missing"


def test_the_system_prompt_never_names_a_tool_that_does_not_exist() -> None:
    """Naming `create_order` would tell the model to reason about a route it has no way to take."""
    prompt = flat()

    for name in FORBIDDEN_TOOL_NAMES:
        assert name not in prompt


def test_the_architecture_does_not_depend_on_this_text() -> None:
    """L§29 and ADR-009: prompt wording makes the agent behave well; it is not a control.

    Every guarantee the prompt describes is also structural — the tool that
    would purchase something is not registered, and `request_approval` has no
    field that can approve. If this test's premise ever stops holding, the
    prompt has quietly become a security mechanism.
    """
    assert "create_order" not in TOOL_SCHEMAS
    assert "approved" not in TOOL_SCHEMAS["request_approval"].json_schema()["properties"]


# --------------------------------------------------------------------------
# The extraction prompt
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "phrase"),
    [
        ("no prose", "single JSON object"),
        ("no catalog facts", "Never write a SKU"),
        ("device stays a phrase", "buyer's own words"),
        ("requirement vs preference", "Requirements eliminate; preferences only rank"),
        ("unsure means preference", "choose `preferences`"),
        ("money in major units", "major units"),
        ("carry-forward", "carried forward unchanged"),
        ("clarification", "needs_clarification"),
        ("no weights", "never emit weights"),
        ("injection", "not an instruction"),
    ],
)
def test_the_extraction_prompt_states_each_rule(subject: str, phrase: str) -> None:
    assert phrase in flat("intent_extraction"), f"the {subject} rule is missing"


def test_the_extraction_prompt_does_not_canonicalize_a_device_for_the_model() -> None:
    """ADR-003: showing `iphone_16` as an output would teach exactly the wrong habit.

    The example device in the prompt appears only as the buyer's phrase; the
    canonical form is named once, as the thing not to write.
    """
    prompt = flat("intent_extraction")

    assert '"text": "iPhone 16"' in prompt
    assert "do not convert it into an identifier" in prompt.lower()
