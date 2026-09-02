# ADR-018: Groq Is the Locked LLM Provider

**Status:** Accepted, **implemented (M4-R, 2026-09-02)** and **verified live**
**Date:** 2026-09-02
**Milestone:** M4 (reopens and replaces a decision made there) / binding on M5 onward
**Supersedes:** [ADR-016](ADR-016-single-model-provider.md), which is now **Superseded** in full
**Source references:** L§44 (implementation technology), L§48 DECISION 1 and 2, L§50 (LLM MVP
checklist), A§56 (Agent Runtime checklist), L§45 and A§45 (secret handling), L§46 (error handling
and cost control), F§37 STEP 6
**Related decisions:** ADR-001 (the architecture invariant), ADR-008 (money representation),
ADR-009 (agent tool boundaries), ADR-015 (the LLM test seam — **still binding, unchanged**)

## Context

The project owner has designated **the Groq API as the required and locked LLM provider**, and has
stated the decision is permanent unless they explicitly change it. They further instructed that the
project must not be migrated to, and must not be recommended for migration to, Anthropic, Claude,
OpenAI, Gemini or any other provider, and that older documentation naming Anthropic/Claude must not
be silently followed.

This reverses [ADR-016](ADR-016-single-model-provider.md), which held that Claude was the only
permissible provider and which deleted a provisional `GroqClient` from `app/llm/` in commit
`78f6f4d`.

**This ADR does not re-argue the choice.** ADR-016's reasoning is preserved in that file for the
historical record, and its conclusion is void. What follows records the decision and specifies what
implementing it correctly requires.

## The conflict with `architecture.md`, stated plainly

`architecture.md` is never edited (a standing project rule), and it names Claude Sonnet in four
places: L§44 (`AI MODEL: Claude Sonnet`), L§48 DECISION 1, and the completion checkboxes at L§50
(`[ ] Claude Sonnet connected`) and A§56 (`[ ] Runtime can call Claude Sonnet`).

**Those four items are now permanently unsatisfiable as written, by deliberate decision.** This is
the largest single deviation from the specification in the project. It is recorded here, indexed in
`docs/notes/deviations.md`, and reflected in `docs/PROJECT_STATE.md`. The checkboxes are re-read as
*"the configured provider is connected and the runtime can call it"* — the architectural role the
specification was describing — and are satisfied against Groq.

Nothing else in `architecture.md` changes meaning. The invariant it exists to protect —
**LLM proposes → application validates → user authorizes → Razorpay executes → system audits** —
is provider-independent. The model is untrusted input on either provider (ADR-001, ADR-009), which
is precisely why swapping the provider does not weaken any guarantee in the system.

## Decision

### 1. Groq is the provider. One provider, not a selectable set.

There is **no multi-provider abstraction, no runtime provider switch, and no key-prefix sniffing.**
ADR-016 was right about one thing that survives its reversal: a `build_client` that chose a backend
by inspecting the shape of an API key turned a misconfiguration into a silent second mode. A single
provider is configured, and a wrong key is an error rather than a fallback.

### 2. The exact backend client boundary

The boundary already exists and is provider-agnostic by construction. It does not change.

```
app/llm/client.py          ← the ONLY module permitted to import the Groq SDK
  └── LLMClient (Protocol) ← one method; what the rest of the application depends on
        def complete(*, system, messages, tools, tool_choice,
                     max_tokens, temperature) -> ModelResponse

app/llm/models.py          ← provider-agnostic transport types (deviation A22)
        Message · ModelResponse · ToolCall · TokenUsage · StopReason · Role
```

**Rules, unchanged from ADR-015 and still binding:**

- **Exactly one module may import the provider SDK: `app/llm/client.py`.** An AST-walking test
  asserts the importer list is exactly that one file. Nothing else — no service, no route, no agent
  module, no test outside `tests/llm/test_client.py` — may import it.
- **Every consumer depends on the `LLMClient` protocol**, never on the concrete class. This is what
  makes the entire LLM and agent suite runnable with no key and no network.
- **No provider-native type escapes `client.py`.** Nothing outside it may see a raw SDK response
  object. `_to_model_response` is the single conversion site.
- **The deterministic packages must never import `app.llm` or `app.agent`** — `app/services/`,
  `app/ranking/`, `app/policy/`, `app/repositories/`, `app/domain/` and `app/payments/` are the
  trusted side of the boundary (ADR-001). Standing tests enforce this and are unaffected by the
  provider change.

Because the boundary is already provider-agnostic, **the concrete client class is the only
application code that is provider-specific.** That is the whole of the code reconciliation surface.

### 3. The configured Groq model: `openai/gpt-oss-120b`

**Confirmed by the owner on 2026-09-02, after checking what the account actually serves.**

The value that had been in `.env` was `ANTHROPIC_MODEL=Groq`, which is not a model identifier at
all; it would have failed on the first request. An earlier draft of this ADR proposed
`llama-3.3-70b-versatile` — **that model is not available on this account**, and querying
`models.list()` rather than trusting the proposal is what caught it. Groq serves 14 models here, of
which five are chat-capable; `groq/compound-mini` rejects tool calling outright and is disqualified,
because the agent depends on structured tool calling for all eight schemas (ADR-009).

`openai/gpt-oss-120b` is an **open-weights model served by Groq**, on Groq's infrastructure, with the
Groq key. No request reaches OpenAI, and OpenAI's SDK is forbidden under `app/` by a standing guard.
Only the model's origin appears in its name — a point worth stating because the name invites exactly
the wrong inference.

Alternatives verified working, should the choice ever be revisited: `openai/gpt-oss-20b` (faster,
smaller), `qwen/qwen3.8-27b` and `qwen/qwen3.6-27b`. All four returned a correct tool call in a live
probe. `GROQ_MODEL` is configuration, so switching is an env edit, not a code change.

The model name is **validated at startup**, in the same spirit as `RANKING_PROFILE`: an empty value
or a placeholder such as the literal `Groq` is rejected at configuration time rather than producing
a provider error on the first buyer message.

### 4. Required environment variables

| Variable | Type | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | **secret** (`SecretStr`) | Read by `app/llm/client.py` and nowhere else. |
| `GROQ_MODEL` | string | The model identifier. Configured: `openai/gpt-oss-120b`. |
| `GROQ_TIMEOUT_SECONDS` | int, 1–600 | Per-request timeout. Default `60`. |
| `GROQ_MAX_RETRIES` | int, 0–5 | Bounded retry budget. Default `2`. |

These **replaced** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_TIMEOUT_SECONDS` and
`ANTHROPIC_MAX_RETRIES` in M4-R. Keeping a Groq key in a variable named `ANTHROPIC_API_KEY` was
precisely the misconfiguration ADR-016's key-sniffing guard was written to catch; the rename
preserved the key's value and changed only its name.

### 5. Secret handling

Unchanged in mechanism; only the name of the secret changes.

- `GROQ_API_KEY` is held as `SecretStr`, so an accidental `repr` or log line prints `**********`
  rather than the value (L§45, A§45).
- `Settings.secret_values()` returns every configured secret to the logging redaction filter, so a
  key reaching a log record through any unforeseen path is masked.
- `client.py`'s `_assert_no_secret_leaked` refuses to send a prompt containing **any** configured
  secret — not merely its own — so a Razorpay secret cannot leave via the model either.
- **`GROQ_API_KEY` must never reach frontend code.** It has no legitimate presence in a frontend
  source file, in a `VITE_`-prefixed variable, in any API response, or in any network payload the
  browser can inspect. The frontend calls this backend; the backend calls Groq. Per
  [ADR-017](ADR-017-frontend-framework-and-browser-access.md), the only credential that ever reaches
  the browser is the **public** Razorpay key ID.
- No key value appears in source, tests, fixtures, documentation, logs, or git history.

### 6. Retry and timeout behaviour

Carried forward from ADR-015 unchanged, because it is a property of this application's error policy
and not of the provider:

- **Retries apply to transient failures only** — a timeout, a rate limit, a 5xx. An authentication
  failure and an invalid request are **not** retried; they are configuration and code errors, and
  repeating them wastes the buyer's time.
- **Backoff is `0.5 × 2^n`**, bounded by `GROQ_MAX_RETRIES` (default 2).
- **The SDK's own retry loop is disabled** (`max_retries=0` on the SDK client). L§46 asks for one
  bounded policy; two nested retry loops multiply rather than bound.
- **`temperature` is `0.0` everywhere.** Model output feeds deterministic machinery; sampling
  variety buys nothing and makes failures harder to reproduce. Determinism itself lives in the
  ranker (RULE 8), which the model cannot influence.
- Provider exceptions are mapped onto this application's own taxonomy (`LLMTimeoutError`,
  `LLMRateLimitError`, `LLMAuthenticationError`, `LLMInvalidRequestError`, `LLMTransportError`) at a
  single site. **A provider's error message is never echoed to a client** — a standing test asserts
  this, because a provider message can contain request detail.

### 7. Test-double strategy

[ADR-015](ADR-015-llm-test-seam.md) remains binding **in full**. It is a decision about testing, not
about which provider is used, and nothing in it depends on the answer.

- **No test may call a live model, ever.** Not marked, not skipped-when-absent, not in CI, not
  locally.
- **The model is faked at the `LLMClient` protocol** (`tests/llm/conftest.py::FakeClient`, which
  replays a script and records payloads). This is how the LLM and agent suites run with no key.
- **The SDK is faked only inside `tests/llm/test_client.py`**, and those doubles must raise the
  **real** Groq SDK exception classes, because `_map_exception` dispatches on class identity. A
  hand-rolled stand-in exception would make the mapping test pass while the mapping was wrong.
- **No `test_`-named module may live outside `tests/`.** Two live-calling scratch scripts once sat
  at the backend root, uncollected because `testpaths = ["tests"]`. That guard stays.

### 8. Which modules may access Groq

**Exactly one: `app/llm/client.py`.** Enforced by AST-walking tests rather than convention. The
standing guard that currently asserts *"`anthropic` is the only model SDK"* must be **inverted, not
deleted** — it becomes *"`groq` is the only model SDK, and `anthropic`/`openai` appear nowhere under
`app/`"*. Deleting it instead of inverting it would remove the check that caught this class of drift
in the first place.

## What was implemented (M4-R)

Done on 2026-09-02, and **verified against the live Groq API** — the first successful live provider
call in this project's history.

| Change | Detail |
| --- | --- |
| Dependency | `anthropic>=0.40` → `groq>=1.7` in `pyproject.toml` |
| Client | `AnthropicClient` → `GroqClient`; `chat.completions.create`, not `messages.create` |
| Settings | `anthropic_*` → `groq_*`; `GROQ_MODEL` validated at startup, placeholders rejected |
| Environment | `ANTHROPIC_*` → `GROQ_*` in `.env` and `.env.example`; the existing key value preserved |
| System prompt | Now the **first message**, not a top-level field — OpenAI-compatible APIs ignore `system=` |
| Token usage | Read as `prompt_tokens`/`completion_tokens`, not Anthropic's names |
| Tool authoring | `ToolSchema.to_anthropic` → `to_tool_definition`; the shape stays provider-neutral and `client.py` owns translation |
| Guards | Both inverted, **not deleted** (see below) |

### The five defects, each with a named regression test

Every one fails against the client deleted in `78f6f4d`:

1. `test_defect_1_truncation_is_detected_on_groqs_own_finish_reason` — `length` → `MAX_TOKENS`, so
   `is_truncated` is real. Plus `test_defect_1b_…`, asserting the four Anthropic stop-reason names
   map to `UNKNOWN` and can never silently read as a complete answer.
2. `test_defect_2_tool_schemas_are_really_converted_not_passed_through` — a genuine
   `{name, description, input_schema}` → `{"type": "function", "function": {…}}` conversion.
3. `test_defect_3_tool_choice_is_converted_to_the_openai_vocabulary` — including `any` → `required`,
   and an unknown shape falling back to `auto` rather than being forwarded as a mid-turn 400.
4. `test_defect_4_decimal_precision_survives_tool_arguments` — arguments arrive as a JSON **string**
   and go through `loads_decimal`, so `1500.10` is a `Decimal`, never a `float` (ADR-008).
   Malformed JSON yields no arguments rather than a repair (A§19).
5. `test_defect_5_the_sdk_is_a_declared_dependency` — reads `pyproject.toml` and asserts `groq` is
   declared and `anthropic` is not.

### The guards were inverted, not deleted

- `test_anthropic_is_the_only_model_sdk_in_the_repository` → **`test_groq_is_the_only_model_sdk_in_the_repository`**.
  `anthropic` joins the forbidden list; `openai` stays on it, because the configured model is named
  `openai/gpt-oss-120b` but is served **by Groq** through the Groq SDK — importing OpenAI's client
  would mean a different provider.
- `test_build_client_does_not_choose_a_provider_from_the_shape_of_the_key` kept, with the polarity
  swapped: a non-Groq-shaped key in `GROQ_API_KEY` is a misconfiguration that must fail against
  Groq, not silently reach elsewhere. ADR-016's one surviving conclusion.
- `test_service_boundaries.py`'s `FORBIDDEN_LIBRARIES` gained `groq`, so no deterministic package
  can import it.

### Live verification (first ever performed)

- `models.list()` → the key works; 14 models available.
- A direct `complete()` with all 8 tool schemas → the model returned a correct
  `get_compatible_products` call with `category='phone_case'`, `max_price=1500`; `stop_reason`
  mapped to `TOOL_USE`; usage reported 1376/109 tokens (non-zero, proving the OpenAI usage names).
- A full `POST /api/chat` turn → `state=RECOMMENDING`, three grounded recommendations with real
  catalog prices (AeroCase Pro ₹999.00 ×2, ShieldCase Premium ₹1299.00 `LOW_STOCK`). **This is M5's
  exit condition, verified live for the first time.**
- A rate-limited turn exercised the failure path exactly as designed: three bounded attempts,
  `LLMRateLimitError`, and a generic buyer-facing message with **no provider text leaked** (F§25).

### Operational limit, recorded

The account's Groq tier allows **8,000 tokens per minute** on every available model. One agent turn
costs roughly 5,000 (a large system prompt plus eight tool schemas, then a follow-up carrying tool
results), so **sustained use is about one turn per minute** before `429`s begin. This is an account
tier matter, not a code defect, and the retry path handles it correctly. It will matter for M14's
frontend demo and for any M15 scenario that chains turns.

## Consequences

- **Exactly one authoritative provider decision now exists in the repository**: this one. ADR-016 is
  marked Superseded and points here.
- **`architecture.md`'s four Claude checkboxes are permanently unsatisfiable as literally written**,
  by decision, and are re-read as provider-neutral. Recorded in `docs/notes/deviations.md`.
- **ADR-015 is untouched and still governs testing.** No test calls a live model on any provider.
- **The provider swap costs no architectural guarantee.** The model is untrusted input either way;
  `create_order` is still not a registered tool; the Policy Engine still decides whether money moves;
  a verified webhook is still the only payment truth.
- **Live provider verification remains unperformed** and is now a Groq check rather than a Claude
  one. It cannot be satisfied until M4-R ships.

## Alternatives considered

**A multi-provider abstraction with a configured provider name.** Rejected. The owner locked one
provider; a selectable set would be unused generality, and it reintroduces the "silent second mode"
failure that ADR-016 correctly identified.

**Keeping the `ANTHROPIC_*` variable names and pointing them at Groq.** Rejected as a permanent
shape. It is the exact misconfiguration a standing guard was written to detect, and it would mislead
every future reader. It is, however, the *current* state, which is why M4-R includes the rename.

**Editing `architecture.md` to say Groq.** Refused — the file is never edited. The deviation is
recorded in `docs/decisions/` and `docs/notes/deviations.md`, which is the project's established
mechanism for exactly this.
