# 03 — Specification versus Implementation

## Method

`architecture.md` is the specification and is never edited. Where it is ambiguous or wrong for this
build, an ADR carries the resolution. This audit checked the claims of `PROJECT_STATE.md`,
`PROGRESS.md`, `implementation-status.md`, the ADR index and `CLAUDE.md` against source, the live
database and the running application.

## Specification versus implementation

| Requirement | Spec location | Implementation | Status | Evidence |
| --- | --- | --- | --- | --- |
| LLM proposes, never decides | A§19, ADR-001 | Tools return data; no tool accepts a price | ✅ VERIFIED | Zero tool parameters named price/amount/total |
| `create_order` is not a tool | ADR-009 | Absent from `TOOL_SCHEMAS` and `HANDLERS`; in `FORBIDDEN_TOOL_NAMES` | ✅ VERIFIED | 4 independent tests |
| Deterministic side never imports the model | ADR-015 | `services`, `ranking`, `policy`, `payments`, `repositories` clean | ✅ VERIFIED | AST walk: 0 violations |
| One module imports the provider SDK | ADR-015/018 | `app/llm/client.py` only | ✅ VERIFIED | AST import scan |
| PostgreSQL everywhere | ADR-002 | `Settings` rejects non-PostgreSQL URLs | ✅ VERIFIED | 20 tables live |
| Money is `NUMERIC(12,2)` | ADR-008 | 12 business money columns conform | ✅ VERIFIED | `information_schema` query |
| Minor units only in `app/payments/` | ADR-008 | `orders.total_amount_minor`, `payments.amount_minor` BIGINT | ✅ VERIFIED | 999.00 → 99900 live |
| Ranking is pure and deterministic | ADR-004, RULE 8 | No DB/clock/random/model import | ✅ VERIFIED | AST walk: 0 violations |
| R§10 worked example reproduces | R§10 | `0.796800` / `0.786800` asserted exactly | ✅ VERIFIED | `tests/ranking/test_ranker.py` |
| Hard constraints eliminate, never score | ADR-005 | `apply_hard_constraints` takes no profile | ✅ VERIFIED | signature + 136 tests |
| Three state enums, none derived | ADR-006/007 | Separate enums, separate owners | ✅ VERIFIED | source + 56 CHECK constraints |
| Policy re-reads price live | ADR-011 | `_rule_5_price` inside the order transaction | ✅ VERIFIED | `POLICY_PASS` audited live |
| Price drift both directions invalidates | ADR-014 | Increase *and* decrease → `PRICE_CHANGED` | ✅ VERIFIED | 8 named tests across 3 layers |
| Internal order committed before Razorpay | ADR-011 | Order persisted with `razorpay_order_id` NULL | ✅ VERIFIED | live row observed |
| Webhook verifies raw body | ADR-012 | `await request.body()` before parsing; no Pydantic model | ✅ VERIFIED | route signature |
| HMAC-SHA256, constant time | ADR-012 | `hmac.compare_digest` | ✅ VERIFIED | source + live 400/200 |
| Dedupe by UNIQUE constraint | ADR-012 | `UniqueConstraint("provider","event_id")` | ✅ VERIFIED | replay → `ignored` |
| Idempotency prevents duplicates | ADR-013 | Replay returns the same order | ✅ VERIFIED | live: same `order_id` |
| No streaming | ADR-010, F§28 | One JSON object per turn | ✅ VERIFIED | adapter is non-generator |
| Business outcome ≠ network error | ADR-010 | Errors on HTTP 200 | ✅ VERIFIED | frontend test + live |
| Products only from `recommendations[]` | F§9 | Cards never parsed from prose | ✅ VERIFIED | dedicated test + browser |
| Groq is the provider | ADR-018 | `GroqClient`, `openai/gpt-oss-120b` | ✅ VERIFIED | live call, fresh process |
| Razorpay order creation | M11 exit | Code complete | 🔴 **BLOCKED** | **SDK not installed** |
| Frontend Razorpay Checkout | F6 | `razorpay.ts` present | 🔴 BLOCKED | backend cannot issue an order |
| Evaluation harness | M15 / F9 | Absent | ❌ NOT IMPLEMENTED | format never decided |
| Storefront pages | §5 | Absent | ⚠️ DEFERRED | needs catalog routes; owner's call |

## Contradictions found — reported, not resolved

These are live disagreements between documents, or between a document and the code.

### C1 — `PROGRESS.md` is stale and contradicts `PROJECT_STATE.md` (P1)
`CLAUDE.md` states `PROGRESS.md` "must not contradict `PROJECT_STATE.md`". It now does:
- Claims last commit `38232ea`; HEAD is `4081628` (**6 commits behind**).
- Claims Razorpay keys are "Still placeholder `REPLACE_ME` in `.env`". **False** — all three
  test-mode credentials are present and load correctly.

### C2 — `open-questions-status.md` contradicts `PROJECT_STATE.md` on CI (P2)
Line 119 says F4 is "**OPEN** … No workflow exists." `.github/workflows/ci.yml` exists (4,835 bytes)
and `PROJECT_STATE` §13 records F4 as CLOSED.

### C3 — `CLAUDE.md` overstates a boundary guard (P2)
It claims `app/agent/` "is the *only* package that imports both `app.llm` and a service" and that "a
standing guard asserts it". **No such test exists.** The guards in
`tests/agent/test_agent_boundaries.py` assert different (real) properties. Separately, `app/api/`
*does* import both — `routes/chat.py:35` imports `LLMClient, build_client`. That is a legitimate
composition-root pattern, not a violation, but it makes the written claim inaccurate.

### C4 — `app/payments/sdk.py` docstring asserts a false fact (P2)
Lines 8–10 state `RAZORPAY_KEY_SECRET` "is still `REPLACE_ME`" and therefore M11 is unperformed. The
secret is real and valid. The true blocker is the missing package — which this very module raises.

### C5 — `docs/frontend/00-…md` §0 names the wrong provider (P2)
Still asserts Anthropic is the provider. Superseded by ADR-018. Flagged inside
`01-assistant-ui-learning-notes.md` but never corrected at source.

### C6 — `architecture.md` names Claude Sonnet (accepted deviation)
L§44, L§48, L§50, A§56. The specification is never edited, so ADR-018 carries the deviation. **Not a
defect** — recorded for completeness.

## Implemented but under-documented

- **`app/api/` imports the LLM client** for dependency injection — architecturally fine, nowhere
  described.
- **The application issues the idempotency key** at approval time and rejects client-invented ones
  (`"that idempotency key was not issued by this application"`). A good security property that no
  document states.
- **Approval supersession** is automatic on re-approval (`APPROVAL_SUPERSEDED` then `USER_APPROVED`).
  Observed live; documented only indirectly.
