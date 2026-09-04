# 06 — LLM / Groq Audit

> **The provider is GROQ.** This is a hard project requirement (ADR-018), permanent unless the
> project owner changes it. Nothing in this audit proposes, implies or prepares a migration to
> Anthropic, OpenAI or any other provider.

## Verified provider

| Question | Answer | Evidence |
| --- | --- | --- |
| Which provider does the code call? | **Groq** | `app/llm/client.py` is the only module importing `groq`; AST import scan across all 103 backend modules |
| Which model? | `openai/gpt-oss-120b` | `Settings.groq_model`, read live from a fresh process |
| Is that an OpenAI call? | **No** | An open-weights model *served by Groq*; the request goes to `api.groq.com` |
| Any Anthropic in the executable path? | **None** | AST walk: **0** executable references in `backend/app/` |
| Any Anthropic in the frontend? | **None** | 0 occurrences in `frontend/src/` |
| Is the SDK installed? | Yes, `groq` | plus `anthropic`, an undeclared orphan (P3) |

### The Anthropic question, answered rigorously

A plain text search finds 14 occurrences of "anthropic" in `backend/app/`. An AST walk that
distinguishes docstrings and comments from executable code finds **zero**:

```
EXECUTABLE 'anthropic' references in backend/app/: 0
  => CONFIRMED: every occurrence is a docstring or a # comment.
```

Every one is prose explaining that Groq's API is OpenAI-compatible and that "the Anthropic names
never occur" — comments that exist precisely to stop a future reader reintroducing the wrong shape.
There is **no `anthropic_*` field on `Settings`**; only `groq_api_key`, `groq_model`,
`groq_timeout_seconds` and `groq_max_retries` exist. The four `ANTHROPIC_*` entries formerly in
`.env` were therefore provably dead configuration, discarded by `extra="ignore"`.

## Live test — NOT blocked, and it passed

A valid key is present, so this audit performed a real request rather than reasoning from source.

**Test 1 — direct client, fresh process:**
```
LIVE Groq call  : SUCCESS
stop reason     : MAX_TOKENS
tokens in/out   : 85 / 16
```
(The empty completion is `gpt-oss-120b` spending a 16-token budget on internal reasoning. Auth and
transport are what this proves.)

**Test 2 — restart safety, through the full application.** A second backend was started on port 8002
from the current `.env` in a brand-new process:
```
state: RECOMMENDING | recs: 3 | error: None
```

**This answers the "does restarting still use Groq" question affirmatively and by experiment.**

## Configuration finding, now resolved

At the start of this audit `GROQ_API_KEY` did **not exist on disk**. The key lived only in the memory
of the long-running process on port 8001, injected at launch in an earlier session. `Settings.groq_api_key`
resolved to `None`, and the four `ANTHROPIC_*` variables held the Groq values under the wrong names —
including `ANTHROPIC_MODEL=Groq`, the literal string.

That configuration was corrected during this session at the owner's explicit instruction, and the
correction is what Tests 1 and 2 above verify. Before it, a restart would have silently broken every
agent turn.

**The `GROQ_MODEL` validator earned its place here.** A blind rename would have produced
`GROQ_MODEL=Groq`, which `config.py` rejects at startup:

> `GROQ_MODEL='Groq' is a placeholder, not a model identifier.`

Failing loudly at configuration time is exactly what that validator was written for, and it caught a
real defect rather than a hypothetical one.

## Remaining configuration weakness (P1)

`groq_api_key: SecretStr | None = None`, and `GroqClient.from_settings` passes `api_key=""` when it
is absent. A missing key therefore produces a per-turn authentication failure at call time rather
than a loud failure at startup — inconsistent with how `GROQ_MODEL`, `DATABASE_URL` and
`RANKING_PROFILE` are treated. The recommendation in
[18-recommendations](18-recommendations.md) is to validate its presence at startup outside test runs.

## Client implementation

Groq's API is OpenAI-compatible, and every difference from the Anthropic shape was a real defect once
and now carries a named regression test in `tests/llm/test_client.py`:

| Concern | Groq form |
| --- | --- |
| Stop reason | `finish_reason`, not `stop_reason` |
| Tools | `{"type": "function", ...}` |
| Tool arguments | a JSON **string** |
| Usage | `prompt_tokens` / `completion_tokens` |
| System prompt | the **first message**, not a top-level field |

Retries cover transient failures only (timeout, rate limit, 5xx) with `0.5 × 2ⁿ` backoff; the SDK's
own retry loop is disabled so the policy is bounded once rather than twice. Errors map by class
identity through `_map_exception`.

## Test discipline

**No test calls a live model** — not marked, not skipped-when-absent. The model is faked at the
`LLMClient` protocol (`tests/llm/conftest.py::FakeClient`, which replays a script and records
payloads); the SDK is faked only inside `tests/llm/test_client.py`, and those doubles raise the SDK's
*real* exception classes because `_map_exception` dispatches on class identity. All **147 LLM tests**
run with no key and no network.

## Rate limiting — an observed operational constraint

The account's free tier allows roughly 8,000 tokens per minute, and one agent turn costs three model
calls. During an earlier browser test this produced a real `429` mid-turn:

```
11:00:29  recommendation computed  candidates=3  outcome='EXACT_MATCH'
11:00:30  Groq 429 Too Many Requests  (x3)
11:00:32  turn failed on a model transport error
          POST /api/chat 200 OK
```

The backend answered **HTTP 200 with a business outcome** and the frontend rendered a calm recovery
message rather than a crash — the ADR-010 boundary holding under a genuine failure. Practical
throughput is roughly one turn per two minutes.

## Verdict

**Groq integration: COMPLETE and EXTERNALLY VERIFIED.** Provider correct and locked, single import
site, restart-safe from disk, live calls succeed, no Anthropic code in any executable path.
