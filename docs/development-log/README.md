# Development Log

Reconstructed from repository evidence — commits and their timestamps, source, tests, migrations
and the documentation written alongside the work. What could not be established from that evidence
is marked as such rather than filled in. The method, the gaps and the confidence level of every
timestamp are in **[DEVELOPMENT-HISTORY-AUDIT.md](DEVELOPMENT-HISTORY-AUDIT.md)**; read that before
treating anything here as settled history.

Days are grouped by clusters of commit timestamps, not by calendar. Where a working period runs
past midnight it stays in one entry, and where two calendar days are separated by no commits at
all the gap is stated.

## Index

| Day | Date (IST) | Commit window | Main work | Important decision | Bug |
| --- | --- | --- | --- | --- | --- |
| [01](day-01.md) | 30 Aug 2026 (into 31 Aug) | 22:19 – 00:17 | Repo, ADR-001…014, M0 foundation, M1 catalog schema + seed, M2 read services | Database owns product facts; `architecture.md` is never edited | Ambiguous ORM foreign keys (BUG-011) |
| [02](day-02.md) | 31 Aug 2026 | 19:50 – 20:02 | M3 deterministic ranking, M4 LLM layer, a provisional Groq client | Ranking is deterministic and lives outside the model (ADR-004, ADR-005); no test may call a live model (ADR-015) | None established |
| [03](day-03.md) | 1 Sep 2026 | 00:21 – 06:24 | M5 agent runtime → M13 audit log; the whole money path in code | Payment authorization stays outside the LLM (ADR-011…014) | Price-drift approval rollback loop (BUG-002) |
| [04](day-04.md) | 3 Sep 2026 | 00:25 – 11:09 | M4-R Groq switch, CORS, the frontend (M14 F0–F9), CI, Assistant UI runtime | Groq is the locked provider (ADR-018, supersedes ADR-016); Vite, not Next.js (ADR-017) | No CORS middleware + pydantic comma-list crash (BUG-012) |
| [05](day-05.md) | 4 Sep 2026 | 10:55 – 20:16 | Storefront, catalogue expansion, merchant dashboard, auth, MCP; **the money path goes live** | Catalogue grows as data only (ADR-021); auth reopens ADR-006 deliberately (ADR-023); MCP is additive (ADR-024) | Undeclared `razorpay` dependency (BUG-001); non-hermetic suite made live provider calls (BUG-004) |
| [06](day-06.md) | 5 Sep 2026 | 08:41 – 13:54 | 270-case evaluation suite, F-3 fix, a full browser walkthrough, Top-K 9, electronics-only catalogue | The evaluation suite evaluates the agent, not the product (R-5); Top-K is configuration (D12); pruning is explicit (D13) | Five in one day: BUG-003, BUG-005, BUG-006, BUG-007, BUG-008 |

Test-count progression, from the per-milestone records in `docs/implementation-status.md` and the
runs recorded on Day 06:

| Point | Backend tests |
| --- | --- |
| M0 + M1 | 153 |
| M3 | 520 |
| M4 | 719 |
| M5 | 920 |
| M9 | 1115 |
| M13 | 1246 |
| M15 backend half | 1258 |
| After CORS (M14 F1) | 1273 |
| After M16 | 1344 |
| End of Day 06 | 1711 passed, 2 xfailed, 0 skipped |

## Development Story

It started at the bottom. The first working period put a specification, fourteen ADRs, a schema
and a seeded PostgreSQL catalog in place before any code existed that could generate product text
— so by the time an LLM entered the codebase there was already a table it had to defer to.

The second period built the two halves that the architecture exists to keep apart: a
deterministic ranking engine that is pure by construction, and an LLM layer whose only SDK
importer is a single file, guarded by a test that walks the AST. A provisional Groq client was
committed here because a Groq key was on hand and an Anthropic key was not.

The third period is the long one. It opened by removing that provisional client under ADR-016 —
and the review that removed it found the client was not merely untested but wrong in ways a fake-SDK
suite catches on its first assertion. Then nine milestones in sequence: agent runtime, commerce
schema, cart, approval, Policy Engine, orders, Razorpay, webhook, audit. The defect that mattered
was found by an integration test, not a unit test: `POST /api/cart/approve` rolled back its own
legitimate re-pricing when it rejected a stale version, so price-drift recovery looped forever and
the buyer could never reach a version they were able to approve. Every unit test passed throughout,
because each asserted one step.

The fourth period reversed the provider decision at the owner's instruction — ADR-018 supersedes
ADR-016 explicitly, because a repository that holds two live answers will eventually be read by
someone who finds the wrong one — and then discovered that the reason no frontend existed was not
the framework question everyone had been debating. There was no CORS middleware anywhere in the
backend. It was fixed before any frontend code existed to be blocked by it.

The fifth period made it a shop and then made the money real. A readiness audit performed the same
day disbelieved the documentation and found the actual P0: two documents blamed missing
credentials, but the credentials were valid and the `razorpay` package was simply never declared.
With that line added, an order, a Razorpay Checkout, a signature-verified webhook and an audit
trail ran end to end for the first time. The same day exposed that the test suite had been reading
the developer's `.env` and making live provider calls mid-run.

The sixth period built a 270-case evaluation suite, and then someone opened the application in a
browser. Four defects surfaced in one pass that 1,697 backend and 69 frontend tests had all passed
that morning: a permanently disabled *Add to cart*, every agent turn failing on a per-minute token
bucket, a completed turn discarded by the browser's schema, and a buyer's order landing in an
account that was not allowed to see it. Each lived in a seam between two pieces that were correct
on their own. The catalogue was then rebuilt electronics-only at the owner's request, which
immediately collided with a constraint nobody had had to think about before: Groq refuses any
single request over 8,000 tokens, and a bigger catalogue means a bigger tool payload.

Two findings are still open and recorded rather than closed: the assistant's prose is not validated
against its own tool results (F-1, held as strict `xfail`s), and R§13's combination search is
implemented but reachable from nothing (F-2).
