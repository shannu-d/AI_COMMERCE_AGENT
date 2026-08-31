# ADR-015: The LLM Test Seam

**Status:** Accepted, **implemented (M4)**
**Date:** 2026-08-31
**Milestone:** M4 (implemented) / M5 (extended to the agent runtime)
**Source references:** L§44–L§47 (the Claude client, error handling, cost control), L§51 (testing
requirements), A§57 (integration tests), F§37 STEP 11 (build order)
**Related open questions:** F1 (LLM test-double strategy), E2 (retry and timeout values)

## Context

`architecture.md` requires the agent to be tested. L§51 lists intent extraction, tool-call
handling, grounding and the failure scenarios among the things that must work, and A§57 asks for
integration tests over nine named cases. It says nothing about **how** any of that is exercised
without calling a model.

That silence is the whole problem, because every property the specification cares about at this
boundary is a property of *behaviour under specific model output*:

- L§46 requires bounded retries and a controlled timeout — assertions about what happens after a
  429, a 502 and a timeout, in a specific order.
- L§30 and A§41 require that a failure never becomes a fabrication — an assertion about what
  happens when the model returns something unusable.
- ADR-008 requires that a budget of `1500.10` survives as a `Decimal` — an assertion about an exact
  byte sequence in the model's reply.
- A§19 requires that invalid tool arguments are rejected before execution — an assertion about a
  call the model should never have made.

A live model produces none of these on demand. Asking one to emit malformed JSON, or to truncate
mid-object, or to fail with a rate limit, is not a test; it is a request that may or may not be
granted this run. `docs/notes/open-questions-status.md` records F1 as *"the one genuinely blocking
open question ahead"*, needing an ADR before M4, for exactly this reason.

Two further facts constrain the answer. This repository has no `ANTHROPIC_API_KEY` in CI or on the
development machine, and M4's stated exit condition in
[`02-dependency-map.md`](../analysis/02-dependency-map.md) is *"natural language → validated
structured intent, **offline-testable**"*. The exit condition is not "tested"; it is "testable
without the network".

## Problem

Where is the seam between this application and the model, and what stands in for the model on the
other side of it, such that every behaviour the specification requires can be asserted
deterministically and without an API key?

## Decision

**No automated test in this repository may call a live model, at any milestone.** Not marked, not
skipped-when-absent, not opt-in. A test whose result depends on a sampled generation is a sampling
experiment, and a green run of one proves nothing about the next.

The seam is a **protocol with exactly one method**.

```python
class LLMClient(Protocol):
    def complete(self, *, system, messages, tools, tool_choice, max_tokens, temperature) -> ModelResponse: ...
```

Four rules follow from it, and all four are enforced by tests rather than by convention.

1. **`app/llm/client.py` is the only module in the repository that may import the Anthropic SDK.**
   `tests/llm/test_client.py::test_only_one_module_in_the_repository_imports_the_sdk` walks the AST
   of every module under `app/` and asserts the importer list is exactly that one file. A second
   importer would be a second path to the network and a second place a key could be read.

2. **Every other consumer depends on `LLMClient`, never on `AnthropicClient`.** `IntentExtractor`
   takes the protocol, and so must the agent runtime in M5. This is what makes the fake possible;
   it is also what makes a provider change a one-file change.

3. **The model is faked at the protocol, not at the SDK.** `tests/llm/conftest.py::FakeClient`
   replays a queued script of `ModelResponse` values and exceptions, and records every outgoing
   payload. Scripting "malformed, then valid" is two arguments to a constructor, which is what
   makes the extractor's bounded-repair path an ordinary unit test.

4. **The SDK is faked only in the one file that must talk to it.** `tests/llm/test_client.py`
   injects a stand-in for `anthropic.Anthropic()` through the client's `client=` parameter and a
   stand-in for `time.sleep` through `sleep=`. Those doubles raise the SDK's **real** exception
   classes — `anthropic.RateLimitError`, `anthropic.AuthenticationError` and the rest — because
   `_map_exception` dispatches on class identity, and a double that raised the base
   `APIStatusError` for every status would send every mapping test through one branch and prove
   nothing about the others.

Two things are **not** part of the seam, deliberately.

**Recorded transcripts are not used.** No VCR, no cassettes, no fixture files of captured API
responses. See *Alternatives*.

**Prompt quality is not asserted.** `tests/llm/test_prompts.py` checks that each prompt is on disk,
versioned, stripped of its editorial comment, and that the rules the specification names by number
are present in the text. It does not check that the model obeys them, because that is not knowable
offline — and, per L§29 and ADR-009, is not what makes the system safe. The prompt tests assert
auditability; the tool registry and the schema assert safety.

**Where the doubles live.** `FakeClient` and its helpers live in `tests/llm/conftest.py`, beside
the tests that use them, matching `tests/ranking/conftest.py`. `backend/tests/fixtures/` is
reserved for **Razorpay** payloads from M9 onward, which are recorded provider data rather than
in-process fakes. This narrows the "agreed home for test doubles" noted against F1 in
[`open-questions-status.md`](../notes/open-questions-status.md): a pytest fixture belongs in a
`conftest.py`; a captured webhook body belongs in a file.

**E2, the retry and timeout values**, are settled as configuration rather than as a further
decision: `ANTHROPIC_TIMEOUT_SECONDS` defaults to 60, `ANTHROPIC_MAX_RETRIES` to 2, backoff is
`0.5 × 2ⁿ` seconds, and only `LLMError.is_transient` failures are retried. The analysis document's
proposed default is adopted unchanged. The SDK's own retry loop is disabled (`max_retries=0`)
because L§46 asks for one bounded policy, and two nested retry loops multiply rather than bound.

## Alternatives considered

**Recorded transcripts (VCR-style cassettes).** Rejected for three reasons, in increasing order of
seriousness. A cassette is only as current as the day it was recorded, and a stale one tests a
provider that no longer exists. Recording requires a key, so the failure modes that matter most —
a 429, a truncation, a refusal — are the ones hardest to record and easiest to hand-edit into
fiction. And a hand-edited cassette is a `ModelResponse` written in JSON, with a large machinery in
front of it; `FakeClient` is the same thing without the machinery or the pretence of provenance.

**A live model, marked and skipped when no key is present.** Rejected because it makes the suite's
meaning depend on the environment — the same failure ADR-002 refuses for the database. It is worse
here than there: a skipped `requires_db` test is a test that did not run, whereas a passed
live-model test may have passed by luck, and nothing distinguishes the two afterwards.

**Monkeypatching `anthropic.Anthropic` globally.** Rejected because it leaves the production import
path in place and tests it by subversion. Every consumer would still be typed against the concrete
client, so nothing would stop a later module importing the SDK directly, and the "one importer"
guard could not exist.

**A wider protocol — `extract_intent()`, `chat()`, `choose_tool()`.** Rejected because the
interface is the surface through which the probabilistic side reaches the trusted side, and each
method is another thing a future caller can ask the model to decide. One method that sends messages
and returns a response cannot, by shape, be asked to decide anything.

**Testing the extractor against the real prompt with a real model, as a smoke test.** Rejected for
CI, and worth doing by hand before a release. It belongs in the M4 verification record
(`docs/implementation-status.md`), not in `pytest`.

## Consequences

**What this enables.** All 198 LLM-layer tests run in under a second with no key, no network and no
database, so M4's exit condition is checkable on any machine. The failure paths L§46 names are
covered exactly, in order, including the ones a live model would produce only by accident. Swapping
providers is a change to one module and its test file.

**What it costs, and this is the real cost.** *Nothing here tests that Claude actually does what
the prompts ask.* A prompt could instruct the model to emit a field the schema forbids and every
test in this package would still pass — the extraction would simply fail at runtime, loudly, which
is the designed behaviour but not a good discovery. Offline tests prove the application handles
model output correctly; they cannot prove the model produces good output. That gap is closed by
manual verification against the real API, recorded per milestone, and by the fact that no
correctness property of the system depends on the model behaving well (ADR-001, ADR-009).

**What it forecloses.** Any future test that wants to assert on real model behaviour has to be run
and recorded by hand, outside `pytest`. That friction is intentional.

## Implementation implications

Obligations this ADR is audited against:

| # | Obligation | Where |
| --- | --- | --- |
| 1 | `LLMClient` is a `runtime_checkable` `Protocol` with one method | `app/llm/client.py` |
| 2 | `AnthropicClient` accepts injected `client=` and `sleep=` | `app/llm/client.py` |
| 3 | Exactly one module imports `anthropic`, asserted by AST walk | `tests/llm/test_client.py` |
| 4 | Every SDK exception maps to `app.llm.errors`; no provider type or string escapes | `app/llm/client.py::_map_exception`, `tests/llm/test_client.py` |
| 5 | `IntentExtractor` and every later consumer take `LLMClient` | `app/llm/extractor.py`; M5's runtime |
| 6 | `FakeClient` replays a script and records payloads | `tests/llm/conftest.py` |
| 7 | No test calls a live model, at any milestone | the whole suite |
| 8 | Deterministic packages do not import `app.llm`; `app.llm` imports no service, repository or database module | `tests/services/test_service_boundaries.py`, `tests/llm/test_boundaries.py` |

M5 inherits all eight. The agent runtime must take an `LLMClient`, and its tool executor must be
constructible with fakes for both the model and the services.

## Status

**Accepted**, 2026-08-31. Implemented in M4.
