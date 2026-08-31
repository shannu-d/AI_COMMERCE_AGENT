"""Natural language in, validated structured intent out (L§5–L§7, LLM-03).

This is M4's exit condition, and the whole module is arranged so that it can be
verified without an API key and without a network: `IntentExtractor` depends on
the `LLMClient` protocol, so a fake returning a canned `ModelResponse` drives
every path through it.

Three decisions here are worth the reading time.

**Extraction asks for text JSON, not a tool call.** A tool call arrives from the
SDK already JSON-decoded, and a budget of `1500.50` would be a `float` before
this application ever saw it — irreparably, since a `Decimal` built from a lossy
binary float is still lossy (ADR-008). Text output can be parsed by
`app.llm.schemas.loads_decimal` with `parse_float=Decimal`, so money reaches
Pydantic exactly as the model wrote it. `Budget` rejects a `float` outright,
which turns any future shortcut around this into a test failure rather than a
rounding error on a buyer's ceiling.

**Malformed output gets one bounded repair, and never a repair by hand.** L§46
requires bounded retries; A§19 and `LLMOutputError` require that invalid output
is never quietly fixed up. So the extractor tells the model what was wrong and
asks once more, and if that fails it raises. It does not guess at a missing
field, coerce a wrong type, or accept a differently-shaped payload.

**Carry-forward is by omission; removal is by `null`.** L§26's example — "I need
a case for my iPhone 16", then "Around 1500" — requires the second turn to
inherit the first. Distinguishing a field the model *left out* from one it set
to `null` is what lets a buyer both add a budget and withdraw one, and it is
knowable because this module parses the JSON itself and can see which keys were
present. A model that simply re-states everything is also correct; the merge is
a floor, not a protocol.

What this module never does: name a product, quote a price, decide that a device
is `iphone_16`, or compute a score. It produces the buyer's requirements. Every
catalog fact comes later, from PostgreSQL (RULE 1, RULE 2, RULE 6, RULE 7), and
the device phrase it records is resolved by `CompatibilityService` (ADR-003).
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence

from pydantic import ValidationError

from app.llm.client import LLMClient
from app.llm.errors import LLMInvalidRequestError, LLMOutputError
from app.llm.models import Message, ModelResponse, StopReason
from app.llm.prompts import load_system_prompt, prompt_version
from app.llm.schemas import BuyerIntent, IntentExtraction, loads_decimal

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MAX_HISTORY",
    "EXTRACTION_MAX_TOKENS",
    "IntentExtractor",
    "merge_intent",
]

#: An intent object is small. A generous ceiling that still fails fast if the
#: model starts writing prose instead.
EXTRACTION_MAX_TOKENS = 1024

#: L§27: "Do not send unnecessary application data to the LLM." Older turns cost
#: tokens and latency while contributing less than the structured intent already
#: carries, so only a recent window is sent.
DEFAULT_MAX_HISTORY = 20

#: The application's own words to the model during a repair attempt. It goes in
#: a `user` message because the API has no other channel for it — it is not
#: buyer text, and it is the only non-buyer content this module puts there.
_REPAIR_TEMPLATE = (
    "That reply could not be used: {problem}\n"
    "Reply with only the JSON object described in your instructions, and nothing else."
)


def merge_intent(
    previous: BuyerIntent | None,
    update: BuyerIntent,
    stated: Collection[str],
) -> BuyerIntent:
    """Carry a previous turn's intent forward into this turn's (L§26, LLM-07).

    `stated` is the set of top-level keys the model actually wrote inside its
    `intent` object. A key that is present wins, *including* when its value is
    `null` or an empty list — that is how a buyer withdraws a budget or drops a
    device. A key that is absent inherits.

    The merge is deliberately shallow. Reconciling one turn's
    `product_requirements` against another's, item by item, would mean deciding
    whether "make it two" refers to the case or to the charger — a judgement
    that belongs to the model, which can see the conversation, and not to a
    merge function, which cannot. The prompt therefore asks for that list in
    full whenever it changes at all.
    """
    if previous is None:
        return update
    fields = {
        name: (getattr(update, name) if name in stated else getattr(previous, name))
        for name in BuyerIntent.model_fields
    }
    return BuyerIntent(**fields)


class IntentExtractor:
    """One model call that turns a conversation into a `BuyerIntent`.

    Stateless. The conversation and the previous intent are supplied per call,
    because the session that owns them belongs to the agent runtime (M5) and
    this layer must stay usable — and testable — without one.
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        prompt_name: str = "intent_extraction",
        max_tokens: int = EXTRACTION_MAX_TOKENS,
        max_history: int = DEFAULT_MAX_HISTORY,
        max_repair_attempts: int = 1,
    ) -> None:
        if max_history < 1:
            raise ValueError("max_history must be at least 1")
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts must not be negative")
        self._client = client
        self._prompt_name = prompt_name
        self._max_tokens = max_tokens
        self._max_history = max_history
        self._max_repair_attempts = max_repair_attempts

    @property
    def prompt_version(self) -> str:
        """The version of the prompt this extractor runs.

        Exposed so a stored trace can record which instructions produced it
        (L§28); a transcript without it is evidence about nothing in particular.
        """
        return prompt_version(self._prompt_name)

    def extract(
        self,
        messages: Sequence[Message],
        *,
        previous_intent: BuyerIntent | None = None,
    ) -> IntentExtraction:
        """Extract intent from a conversation whose last turn is the buyer's.

        Raises `LLMInvalidRequestError` for a conversation that cannot be
        extracted from, and `LLMOutputError` when the model's answer is unusable
        after the permitted repair attempts. It never returns a partially-valid
        intent, and never invents one to avoid raising.
        """
        conversation = self._prepare(messages)
        system = self._system_prompt(previous_intent)

        attempt = 0
        while True:
            response = self._client.complete(
                system=system,
                messages=conversation,
                max_tokens=self._max_tokens,
                temperature=0.0,
            )
            self._reject_unusable_response(response)
            try:
                extraction, stated = _parse(response.text)
            except LLMOutputError as error:
                if attempt >= self._max_repair_attempts:
                    logger.warning(
                        "intent extraction failed",
                        extra={"attempts": attempt + 1, "reason": str(error)},
                    )
                    raise
                attempt += 1
                conversation = [
                    *conversation,
                    Message(role="assistant", content=response.text),
                    Message(role="user", content=_REPAIR_TEMPLATE.format(problem=error)),
                ]
                continue

            merged = merge_intent(previous_intent, extraction.intent, stated)
            return extraction.model_copy(update={"intent": merged})

    # -- input --------------------------------------------------------------

    def _prepare(self, messages: Sequence[Message]) -> list[Message]:
        """Validate the conversation and trim it to the recent window.

        Extraction answers "what did the buyer just ask for", so a conversation
        that does not end with the buyer is a caller bug rather than a model
        failure — worth raising on, because the alternative is re-extracting the
        agent's own last message as though the buyer had said it.
        """
        if not messages:
            raise LLMInvalidRequestError("intent extraction needs at least one message")
        if messages[-1].role != "user":
            raise LLMInvalidRequestError(
                "intent extraction expects the buyer's message last; "
                f"got a {messages[-1].role!r} turn"
            )

        window = list(messages[-self._max_history :])
        # Trimming can strand an assistant turn at the front, answering a
        # question nobody can now see. The conversation opens with the buyer.
        while window[0].role != "user":
            window.pop(0)
        return window

    def _system_prompt(self, previous_intent: BuyerIntent | None) -> str:
        """The extraction prompt, plus the previous intent when there is one.

        The intent is appended to the *system* text rather than injected as a
        conversational turn: it is application-authored state, and L§29's
        boundary depends on buyer text being the only thing in the `user`
        channel. It is serialized without its defaults so that "not stated" and
        "stated as nothing" stay distinguishable to the model too.
        """
        prompt = load_system_prompt(self._prompt_name)
        if previous_intent is None:
            return prompt
        serialized = previous_intent.model_dump_json(exclude_defaults=True)
        return (
            f"{prompt}\n\n"
            "## Previous intent\n\n"
            "This is what the buyer had established before the latest message. "
            "Update it as instructed above.\n\n"
            f"```json\n{serialized}\n```"
        )

    # -- output -------------------------------------------------------------

    @staticmethod
    def _reject_unusable_response(response: ModelResponse) -> None:
        """Refuse a response that cannot contain a complete intent.

        None of these is repairable by asking again with the same input: a
        truncated answer means `max_tokens` is too small for this conversation,
        a refusal means the model declined, and a tool call on a call that
        offered no tools means the payload is not what this module thinks it is.
        Retrying any of them would spend the buyer's latency to arrive at the
        same place, which is what L§46's bounded-retry requirement is about.
        """
        if response.is_truncated:
            raise LLMOutputError(
                "the model's answer was truncated; a partial intent is not a small intent"
            )
        if response.stop_reason is StopReason.REFUSAL:
            raise LLMOutputError("the model declined to answer")
        if response.requested_tools:
            raise LLMOutputError("the model requested a tool during intent extraction")


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _parse(text: str) -> tuple[IntentExtraction, frozenset[str]]:
    """A validated extraction, plus the intent keys the model actually stated."""
    payload = loads_decimal(_json_object(text))
    if not isinstance(payload, dict):
        raise LLMOutputError(f"expected a JSON object, got {type(payload).__name__}")

    intent = payload.get("intent")
    # Reported rather than assumed: a bare intent object is a plausible mistake,
    # and accepting it would be the "helpful" repair A§19 forbids.
    if not isinstance(intent, dict):
        raise LLMOutputError("the JSON object has no 'intent' object")

    try:
        extraction = IntentExtraction.model_validate(payload)
    except ValidationError as exc:
        raise LLMOutputError(f"the intent failed validation: {_problems(exc)}") from exc
    return extraction, frozenset(intent)


def _json_object(text: str) -> str:
    """The JSON object inside a model reply.

    The prompt asks for bare JSON, but a fenced block or a sentence of preamble
    is the commonest way a model complies imperfectly, and failing a turn over a
    code fence would spend a repair attempt on nothing. This finds the outermost
    braces and no more: it does not repair the JSON between them, and a reply
    with no object at all is an error rather than an empty intent.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise LLMOutputError("the model's reply contains no JSON object")
    return text[start : end + 1]


def _problems(exc: ValidationError) -> str:
    """Pydantic's errors as one line the model can act on."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}"
        for error in exc.errors()
    )
