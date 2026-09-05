"""Version-controlled prompt text (L§28).

The prompts live as Markdown files beside this module rather than as Python
string literals, because L§28 requires the exact system prompt to be
version-controlled and a `.md` diff is reviewable in a way a re-indented triple-
quoted string is not.

There are two, and they do different jobs. `system_prompt` governs how the
agent converses with a buyer; `intent_extraction` governs a single call that
produces a structured intent and no prose. Keeping them apart means a change to
the agent's manner cannot quietly alter the shape of an extracted intent.

A version is raised whenever a file changes in a way that could alter
behaviour. A recorded model transcript is only evidence about the prompt that
produced it, so the version is what lets a stored trace be matched to its
instructions later.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

__all__ = [
    "PROMPT_DIR",
    "PROMPT_VERSION",
    "PROMPT_VERSIONS",
    "load_system_prompt",
    "prompt_version",
]

PROMPT_DIR = Path(__file__).resolve().parent

#: One version per prompt file. Raise the entry whose file changed — a single
#: shared number would make every trace look stale whenever either prompt moved.
#: A test asserts that every `.md` file here has an entry, so a new prompt
#: cannot arrive unversioned.
PROMPT_VERSIONS: Mapping[str, str] = MappingProxyType(
    {
        # 1.4.0 — rule 11: do not build a cart the buyer did not ask for. A
        # live turn answered "earbuds with noise cancelling" by putting two
        # pairs in the cart and asking for approval of ₹8,998 — safe (no order
        # can follow without an approval the model cannot write) but wrong:
        # showing a product and adding it are different acts, and only the
        # buyer moves between them. Rules renumbered to 1–19.
        # 1.3.0 — rule 9: a stated requirement belongs in the search tool's
        # `attributes`, which eliminates, not in `search_query`, which only
        # ranks. Added after a live turn answered "find noise-cancelling
        # earbuds" with three products that have no ANC, having put the
        # requirement in the free-text field. Rule 5 gained the other half:
        # never describe a product as having a property the tool did not
        # report. The rules were renumbered to close a gap at 12 left by 1.1.0;
        # the numbers cited in these notes are the current ones.
        # 1.2.0 — hardened the no-match case: rule 18 forbids naming any
        # product or price when the tools returned none, after a live turn
        # fabricated two earbud names and prices for a request nothing in the
        # catalogue satisfied. Rule 6 gained the same point in one line.
        # 1.1.0 — added the "Writing your reply" section (brief prose, no tables
        # or attribute dumps; recommended products render as cards in a separate
        # panel). See ADR-020.
        "system_prompt": "1.4.0",
        "intent_extraction": "1.0.0",
    }
)

#: The conversational prompt's version, kept as a name of its own because it is
#: the one that appears in a chat trace.
PROMPT_VERSION = PROMPT_VERSIONS["system_prompt"]


def prompt_version(name: str = "system_prompt") -> str:
    """The recorded version of one prompt.

    Unknown names raise rather than returning a placeholder: a trace stamped
    with a version nobody assigned is worse than no trace at all.
    """
    try:
        return PROMPT_VERSIONS[name]
    except KeyError:
        raise KeyError(f"no recorded version for prompt {name!r}") from None


@lru_cache(maxsize=4)
def load_system_prompt(name: str = "system_prompt") -> str:
    """Read a prompt from disk, cached for the life of the process.

    Cached because the file cannot change under a running process in any
    supported deployment, and re-reading it on every chat turn would be a disk
    hit per buyer message.

    The leading HTML comment in each file is editorial — it explains the file to
    a reviewer and is not addressed to the model — so it is stripped rather than
    sent. Paying for it on every turn would be the "unnecessary context" L§27
    warns about.
    """
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt named {name!r} in {PROMPT_DIR}")
    return _without_editorial_comment(path.read_text(encoding="utf-8")).strip()


def _without_editorial_comment(text: str) -> str:
    """Drop a leading `<!-- ... -->` block, if there is one."""
    stripped = text.lstrip()
    if not stripped.startswith("<!--"):
        return text
    end = stripped.find("-->")
    return stripped if end == -1 else stripped[end + len("-->") :]
