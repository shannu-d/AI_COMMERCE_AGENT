# Development History — Reconstruction Audit

**Written:** 5 September 2026
**Reconstructed from:** the repository at commit `b52a481`, plus the working tree at the time of
writing.

This file exists so the daily logs can be read with the right amount of trust. It records what the
reconstruction is based on, what could not be established, and which timestamps are facts rather
than inferences.

---

## Evidence Used

**Primary — machine-generated, not authored:**

- `git log` with author and commit timestamps (`%ad`, `%an`) for all 77 commits
- `git log --stat` — the file-level change set of every commit, which is what establishes *what
  was built when* independently of any prose
- Migration filenames and their ordering: `0001_catalog_schema` … `0006_merchant_activity`
- Source and test files at their current state
- Filesystem modification times, used only for untracked files

**Secondary — contemporaneous documentation written alongside the work:**

- `docs/implementation-status.md` — a per-milestone record including test counts and defects
- `docs/notes/bugs-found-during-development.md` — sections A, A2, B, C
- `docs/notes/deviations.md` — D1 … D13
- `docs/PROJECT_STATE.md` — dated status blocks
- `docs/decisions/ADR-001` … `ADR-024`
- `docs/audit/` — the readiness audit, 19 documents
- `docs/EVALUATION-REPORT.md` — the 270-case evaluation and its findings
- `docs/DEMO-SCRIPT.md` — the prompt bank and its recorded live results

**Tertiary — present but not committed:**

- `docs/bugs/` (15 reports plus an index) and `docs/BUG-AUDIT.md`

**Verified during this reconstruction:** the existence of test names cited in the daily logs, and
the test-count claim for Day 06, which was re-run rather than copied.

---

## History That Could Be Reconstructed

Confidently, from commit content and timestamps:

- **The order in which the system was built.** Schema and seed before services; services before
  ranking; ranking and the LLM layer before the agent runtime; the agent runtime before the
  commerce schema; cart → approval → policy → orders → Razorpay → webhook → audit, in that
  sequence, each with its own tests and its own documentation commit.
- **Which milestone each commit belongs to.** The commit subjects name them (`feat: add the cart
  (M7)`), and the file lists corroborate them.
- **When the provider decision changed, and in which direction.** `3b483ed` adds a provisional
  Groq client; `78f6f4d` removes it under ADR-016; `657d490` reinstates Groq as the locked
  provider under ADR-018 two days later.
- **That the money path was code-complete two days before it was live-verified.** `74cbad6` is
  titled "record M11 and its unperformed live check"; the live verification appears on 4 September
  in `cc025d0` and in `docs/PROJECT_STATE.md`.
- **The five defects of 5 September**, which have both commits and regression tests.
- **Test counts per milestone**, as recorded at the time in `implementation-status.md`.

Reasonably, from documentation written at the time by whoever did the work:

- *How* several bugs were found — the price-drift loop surfacing while writing an integration
  test, the pydantic-settings crash hiding behind tests that never crossed the environment
  boundary, the audit finding the undeclared `razorpay` package by running the endpoint rather than
  believing the docs. These are self-reported, and are marked as narrative rather than as machine
  evidence below.

---

## History That Could Not Be Reconstructed

**Two gaps with no commits at all:**

| From | To | Duration |
| --- | --- | --- |
| 1 Sep 2026 06:24 | 3 Sep 2026 00:25 | ~42 hours |
| 3 Sep 2026 11:09 | 4 Sep 2026 10:55 | ~24 hours |

What happened in either period is **not established from repository evidence**. One partial
exception: the readiness audit in `docs/audit/` carries the date 3 September 2026 and names HEAD
`4081628`, so it was performed against the end state of Day 04 and committed the following day —
but the hours it was performed in are not established.

**Also not established:**

- Anything before the first commit (`621e5cb`, 30 Aug 22:19). `architecture.md` and the whole of
  `docs/analysis/` arrive in that commit already written. Where they came from, who wrote them and
  over what period is not in this repository.
- Whether the gaps above were idle time, work that was never committed, or work committed later in
  a single batch. Commits landing in tight clusters — nine milestones inside six hours on 1
  September — are consistent with either continuous work or batched commits of earlier work.
- Any conversation, meeting, review or decision that did not leave a file behind. No such event is
  described in the daily logs.
- The live-run outputs of days 1–5. Test counts are quoted from documentation written at the time,
  not re-executed. Only the Day 06 counts were re-run during this reconstruction.

---

## Timestamp Confidence

| Class | Status | Notes |
| --- | --- | --- |
| Commit dates and times | **Confirmed** | From `git log`, IST (+0530). These are *commit* times, not necessarily when the work was done. |
| Day boundaries | **Inferred** | Days are clusters of commit timestamps. Day 01 deliberately spans midnight because the commits do. |
| Duration of a day's work | **Inferred** | The window between first and last commit is a lower bound on elapsed time and says nothing about effort. |
| Readiness-audit date (3 Sep) | **Confirmed as a document date**, inferred as a work date | The document states it; the commit that contains it is dated 4 Sep. |
| Live-verification date for the money path (4 Sep) | **Confirmed by document**, not by machine evidence | Recorded in `PROJECT_STATE.md` and `cc025d0`. No provider log is in the repository. |
| `docs/bugs/` creation time (5 Sep, 13:08–13:10) | **Filesystem only** | Not in git. Filesystem times are weaker evidence than commits and can be changed by a copy. |
| Anything before 30 Aug 22:19 | **Unavailable** | — |

No time in the daily logs was rounded, adjusted or invented. Where only a date is known, the entry
says so.

---

## Documentation Limitations

**1. The history is AI pair-authored, and the logs are too.** All 77 commits are authored by
`shanmukhasuraz` and every one carries a `Co-Authored-By: Claude` trailer. The commit messages are
unusually long and explanatory as a result — they are strong evidence of *what changed and why it
was intended*, but they are authored prose, not observation. These daily logs were reconstructed by
the same kind of process and inherit the same limitation.

**2. Much of the "why" is self-reported.** `implementation-status.md` and
`bugs-found-during-development.md` were written by the process that did the work, close to when it
happened. They are the best available account of how defects were found, and they are not
independent of the work they describe. Statements taken from them appear in the logs as narrative;
statements taken from commits, code, migrations and test runs are machine-checkable.

**3. `docs/bugs/` and `docs/BUG-AUDIT.md` are untracked.** They exist in the working tree with
filesystem timestamps of 5 September 2026, 13:08–13:10, and are not in any commit. The daily logs
reference them because they are the detailed incident records the reader will want, but their
provenance cannot be established from git.

**4. Four test names cited in `docs/bugs/README.md` do not exist in the repository.** Checked
directly:

| Cited in the bug index | Present? |
| --- | --- |
| `backend/tests/test_dependencies.py` | No |
| `test_chat_and_rest_cart_schemas_match_frontend_contract` | No |
| `test_a_rate_limit_hint_in_the_header_is_honoured` | No |
| `test_an_order_placed_on_an_anonymous_session_appears_after_sign_in` | No |
| `test_price_drift_recovers_through_a_fresh_approval` | Yes — `tests/integration/test_scenarios.py` |
| `test_every_orm_relationship_resolves` | Yes — `tests/db/test_catalog_schema.py` |
| `test_the_razorpay_id_is_null_until_m11` | Yes — `tests/api/test_orders.py` |

The daily logs cite only test names verified to exist. The bug reports are still referenced for
their narrative, but their test citations should not be trusted without checking.

**5. Test counts before Day 06 were not re-executed.** They are quoted from the milestone records
written at the time. Re-running them today would measure today's code, not that milestone's.

**6. There is no remote and CI has never run.** `git remote -v` is empty (also recorded as open
audit recommendation R6). So there is no build history, no CI log and no external record against
which any of this could be cross-checked.

**7. The reconstruction stops at `b52a481`.** Work done after that commit is not covered.
