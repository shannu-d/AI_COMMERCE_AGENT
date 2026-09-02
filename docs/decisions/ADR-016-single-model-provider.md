# ADR-016: Claude Is the Only Model Provider

**Status:** ⛔ **SUPERSEDED by [ADR-018](ADR-018-groq-as-the-locked-llm-provider.md)** (2026-09-02)

> **This decision is void.** The project owner has locked **Groq** as the LLM provider. The
> reasoning below is retained for the historical record and for its defect analysis, which
> ADR-018 carries forward as acceptance criteria. Do not act on this file's conclusion, and do
> not treat its argument as a reason to migrate back to Claude.

**Original status:** Accepted
**Date:** 2026-09-01
**Milestone:** M4 (corrects a provisional addition) / binding on M5 onward
**Source references:** L§44 (implementation technology), L§48 DECISION 1 and DECISION 2 (LLM
architecture decisions), L§50 (the LLM MVP completion checklist), A§56 (the Agent Runtime MVP
checklist), F§37 STEP 6 (verification)
**Related decisions:** ADR-001 (the architecture invariant), ADR-015 (the LLM test seam)

## Context

A `GroqClient` was added to `app/llm/` after M4 and committed as provisional (`3b483ed`), together
with a `build_client` that selected a provider by sniffing the configured API key's prefix: `gsk_`
chose Groq, anything else fell through to Anthropic. The development machine's `.env` holds a Groq
key under the name `ANTHROPIC_API_KEY`.

The motivation was practical rather than architectural: a Groq key was available and an Anthropic
key was not. That is a real constraint and it deserves a real answer, but it is a constraint on
*running* the system, not on building it, and the two must not be confused.

The question this ADR settles is whether a second provider is something the architecture permits at
all.

## Problem

`architecture.md` names one model. Does "Anthropic API / supported Claude API interface" admit a
provider that serves a different model family, and if not, what happens to the provisional Groq
client?

## Decision

**Claude is the only model this application talks to. `app/llm/client.py` holds the only client, and
it speaks to the Anthropic API.** The provisional Groq client and its key-prefix dispatch are
removed.

Three independent grounds, any one of which would be sufficient.

### 1. The specification names the model, and names it as an acceptance criterion

L§44 is not a preference expressed once. It states `AI MODEL: Claude Sonnet` and `INTEGRATION:
Anthropic API / supported Claude API interface`, and then says outright that "the project explicitly
defines Claude Sonnet with structured tool calling as the AI layer". L§48 repeats it as DECISION 1,
"use Claude Sonnet as the reasoning model". It then appears twice more as a box that must be ticked
before the work is considered complete — L§50's `[ ] Claude Sonnet connected` and A§56's `[ ] Runtime
can call Claude Sonnet` — and once more in F§37's verification order as "verify Claude tool calling".

"A supported Claude API interface" is a widening of the *interface*, not of the *model*. It admits
Amazon Bedrock and Google Vertex AI, which serve Claude over a different API surface and for which
the Anthropic SDK ships `AnthropicBedrock` and `AnthropicVertex`. Groq serves Llama, Mixtral, Gemma,
Qwen and gpt-oss. It does not serve Claude. Selecting it is not choosing another interface to the
specified model; it is choosing another model, which is the one thing L§44 forecloses.

This is therefore not a gap in the specification. `docs/decisions/` exists for what
`architecture.md` leaves open, states two ways, or requires without defining. On the provider it is
none of those three: it is explicit, repeated, and testable.

### 2. The provisional client did not work, in the exact way that proves the point

The code was not merely untested. Reviewing it against the `LLMClient` contract found five defects,
and the first is a silent safety regression:

1. **`_STOP_REASONS` is the Anthropic table with one key renamed.** Groq's API is OpenAI-compatible,
   so its `finish_reason` is `stop`, `length`, `tool_calls` or `content_filter`. The keys
   `end_turn`, `max_tokens` and `stop_sequence` never occur. Two consequences follow. No Groq
   completion could ever report `END_TURN` — every successful call would arrive as `UNKNOWN`. And
   `length`, which is truncation, would also arrive as `UNKNOWN`, so `ModelResponse.is_truncated`
   would be permanently `False`, the first guard in `IntentExtractor._reject_unusable` would never
   fire, and **a truncated intent would be accepted as a complete one**. `models.py` states the rule
   this breaks — "a truncated response is not a short response; treating one as complete is how a
   half-formed intent or a partial tool call gets acted on" — and L§30 and A§41 forbid precisely
   this: a failure must never become a fabrication.
2. **`_convert_tool_to_groq` is a documented no-op**, commented "pass through with minimal
   conversion — Groq's format is similar enough". It is not similar enough. An Anthropic tool is
   `{name, description, input_schema}`; an OpenAI-style tool is `{"type": "function", "function":
   {name, description, parameters}}`. Structured tool calling, which L§48 DECISION 2 requires, could
   not have worked.
3. **`tool_choice` is forwarded unconverted**, with the same shape mismatch.
4. **`ToolCall.arguments` is built as `dict(function.arguments)`**, but in the OpenAI shape
   `arguments` is a JSON *string*. That raises; and had it been parsed it would have gone through a
   plain `json.loads` with no `parse_float=Decimal`, reopening the money precision hole that ADR-008
   and deviation R29 exist to close.
5. **`groq` was never a declared dependency** and was not installed, so `build_client` against the
   configured key raised `ImportError` and the path was unreachable in any case.

Defect 1 is the decisive one, and it is decisive in a specific way: it is exactly the class of error
ADR-015 says only a fake-SDK suite catches, because it dispatches on values a live smoke test would
mask. Writing that suite — the honest way to keep the client — would have turned red on its first
assertion. A provider integration that fails its own acceptance test before it is finished is not a
feature awaiting polish.

### 3. Nothing in the repository needs a second provider

ADR-015 already establishes that no automated test may call a live model at any milestone, and that
M4's exit condition is offline-testable. 577 tests pass with no key, no network and no database. A
model key is needed only for manual live verification, which is recorded in
`docs/implementation-status.md` rather than in `pytest`. Removing Groq therefore costs the project
no capability that any current code, test or milestone depends on.

## What this does not resolve, and how it is handled

The development machine has a Groq key and no Anthropic key, so the manual live verification of M4 —
and L§50's `[ ] Claude Sonnet connected` — cannot be performed here today. That is recorded as an
open gap in `docs/implementation-status.md` rather than closed by substituting a different model. A
checklist item that says "Claude Sonnet connected" is not satisfied by connecting something else,
and a green suite obtained that way would be answering a question nobody asked.

Development, testing and every milestone through M5 proceed unaffected, because none of them needs a
key.

## Alternatives considered

**Keep Groq as an officially supported second provider, with an ADR and a full fake-SDK test suite.**
Rejected on ground 1. No amount of test coverage makes a non-Claude model satisfy `[ ] Claude Sonnet
connected`, and the ADR would have to argue against the specification's plainest sentence rather than
interpret its silence.

**Keep Groq as an unsupported local development convenience, clearly marked non-conforming.**
Rejected on ground 2 and on ADR-015 obligation 3. A second SDK is a second path to the network and a
second place a key is read, and the guard asserting one importer would have to be weakened to permit
it. "Unsupported" is also not a property code has; it is a property a comment claims, and the defects
above are what that claim would have been protecting.

**Repair the Groq client rather than remove it, deferring the provider question.** Rejected because
the repair is the expensive half — a correct stop-reason table, a real tool-schema translation, a
`Decimal`-safe argument parse, and roughly thirty fake-SDK tests mirroring `test_client.py` — and it
would all be spent on a path the specification does not permit. The work is recoverable from git
history if the decision is ever revisited.

**Generalise the seam now, so a provider can be added later without another ADR.** Rejected as
speculative. `LLMClient` already has exactly one method and `IntentExtractor` already depends on the
protocol rather than the client, so the seam a future provider would need exists and is tested.
Nothing further is required until a provider is actually justified.

## Consequences

`app/llm/client.py` is again the only module in the repository that imports a model SDK, and
`tests/llm/test_client.py`'s AST guard is again the complete statement of that fact rather than a
statement with one silent exception. `build_client` returns `AnthropicClient.from_settings(...)`
unconditionally; there is no provider branch and no key sniffing, so which model the application
talks to is a property of the code rather than of the shape of a string in `.env`.

`ANTHROPIC_API_KEY` means what its name says again. The prefix-dispatch made the variable's name a
lie about its contents, which is a poor property for the one setting L§45 singles out as never to be
logged, echoed or interpolated into a prompt.

Removing the client drops two cases from `tests/llm/test_boundaries.py`, whose import guards
parametrize over the files in `app/llm`. The three guards this ADR adds — one that no non-Claude
model SDK is imported anywhere under `app/`, one that no `test_`-named module lives outside the
suite, and one that `build_client` still returns an `AnthropicClient` when handed a `gsk_`-shaped
key — bring the suite to **722 tests, 577 of them needing no database**.

If a second provider is ever genuinely warranted — most plausibly Bedrock or Vertex, both of which
serve Claude and would satisfy L§44 as written — it supersedes this ADR, and the obligations in
ADR-015 apply to it unchanged.

## Implementation implications

| # | Obligation | Where |
| --- | --- | --- |
| 1 | Exactly one model SDK is imported, from exactly one module | `app/llm/client.py`, asserted by `tests/llm/test_client.py` |
| 2 | `build_client` selects no provider and reads no key prefix | `app/llm/client.py` |
| 3 | No live-network script exists in the repository, test-named or otherwise | the whole tree |
| 4 | The unperformed live verification is recorded, not quietly dropped | `docs/implementation-status.md` |

## Status

**Accepted**, 2026-09-01.
