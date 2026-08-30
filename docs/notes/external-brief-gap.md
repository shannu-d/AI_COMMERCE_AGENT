# External Brief — Input Gap (open question F11 / U2)

**Status:** Recorded as an external-input gap. **Not a coding blocker.**
**Date:** 2026-08-31
**Verified by:** a full-text search of this repository, described below.

---

## 1. What is referenced

`architecture.md` repeatedly attributes requirements to a **project brief that is not part of this
repository**. It cites three things from it:

- a **MUST-WORK** requirement tier,
- a **SHOULD-WORK** requirement tier,
- a **pre-submission gate**.

The prior analysis flagged this as open question **F11** and recommended obtaining the brief before
fixing scope.

## 2. What was actually searched

Run on 2026-08-31 against `L:\AI_COMMERCE`, the sole project root:

```bash
# by filename
find . -iname "*brief*" -o -iname "*requirement*" -o -iname "*gate*"

# by content
grep -rIn "MUST-WORK|MUST WORK|SHOULD-WORK|SHOULD WORK|pre-submission|presubmission" .
```

**Filename search: no matches.** No file in this repository is or contains the brief.

**Content search: matches only inside documents that themselves cite the brief** —
`architecture.md`, the derived analysis under `docs/analysis/`, `artifact-export.md`, and the ADRs
that quote `architecture.md`. Every hit is a *reference to* the brief, never the brief itself.

`L:\RazorPay\backend` was **not** searched and must not be: it is a separate, unrelated project
(see U1 in [`open-questions-status.md`](open-questions-status.md)).

## 3. What is missing

The brief's own text: the complete enumeration of what falls in each tier, and the full
pre-submission checklist. Nothing in this repository can reconstruct it, and **nothing in this
repository should try**. No MUST-WORK or SHOULD-WORK requirement has been invented, and none will be.

## 4. What *is* available — preserved verbatim

`architecture.md` does state, in its own words, a small number of brief-derived requirements. These
are the ones that genuinely exist in the supplied documentation, quoted exactly, with the line where
each appears. **This list is complete as of the search above — it is everything the supplied
documents say about the tiers and the gate.**

### MUST-WORK

| # | Requirement | Source |
| --- | --- | --- |
| MW-1 | "The project requires the audit log as a MUST-WORK component." | `architecture.md` A§40, line 10247 |

### SHOULD-WORK

| # | Requirement | Source |
| --- | --- | --- |
| SW-1 | "For the MVP, a visible agent trace is a SHOULD-WORK feature." | L§42, line 6891 |
| SW-2 | "The project identifies a mini evaluation suite as a SHOULD-WORK feature." | L§43, line 6981 |
| SW-3 | "This is a SHOULD-WORK feature, so implement it after the core flow is stable." — of the visible agent trace | AGENT-14, line 11403; restated A§39, line 10151 |

### Pre-submission gate

| # | Requirement | Source |
| --- | --- | --- |
| PG-1 | "The project's pre-submission gate explicitly requires out-of-stock products to be safely blocked." | A§29, line 9629 |
| PG-2 | "The project's pre-submission gate explicitly requires that the agent cannot invent SKUs, prices, stock, or payment status." | A§30, line 9657 |

Six statements. That is the whole of it. Anything beyond these six would be fabrication.

## 5. Why implementation can proceed

Every one of the six is **already covered** by a decision or by shipped code, and none of them
changes the build order:

| Requirement | Where it is already honoured |
| --- | --- |
| MW-1 audit log | `audit_events` designed at column level in ADR-006; implemented in M13 |
| SW-1 / SW-3 agent trace | ADR-010: returned per turn, not persisted, off by default; implemented in M13 after the core flow |
| SW-2 evaluation suite | Milestone M15 in `docs/analysis/02-dependency-map.md` |
| PG-1 out-of-stock blocked | ADR-005 makes inventory an eliminating hard filter, never a score; the Policy Engine re-checks live stock inside the order transaction (ADR-011). **M2's `InventoryService` is where this first becomes executable code.** |
| PG-2 no invented SKUs / prices / stock / payment status | ADR-001 and ADR-002 make PostgreSQL the sole authority; ADR-009 makes every model-supplied identifier a lookup key rather than a fact; ADR-012 makes a verified webhook the only source of payment truth. **M2's `CatalogService` is where this first becomes executable code.** |

The brief would therefore have to *contradict* the supplied architecture to change anything, and the
supplied architecture is the source of truth this project builds from. Implementation priorities have
**not** been adjusted on the basis of guessed requirements.

## 6. What to compare if the brief is later supplied

Do these five checks, in order, and record the outcome as an amendment to this note:

1. **Tier membership.** Confirm the audit log is the only MUST-WORK item, and that the agent trace
   and evaluation suite are the only SHOULD-WORK items. If the brief adds MUST-WORK items, they may
   outrank work currently scheduled later, and `docs/analysis/02-dependency-map.md` needs revisiting.
2. **Pre-submission gate completeness.** PG-1 and PG-2 are the only two gate items the supplied
   documents state. A longer gate becomes an acceptance checklist that M15 must satisfy.
3. **Contradictions with accepted ADRs.** Anything the brief states that conflicts with ADR-001
   through ADR-014 requires a *superseding* ADR, never an edit to an existing one — `docs/decisions/`
   is append-only.
4. **Scope beyond the MVP.** Refunds, cancellation, multi-currency and multi-user identity are all
   currently deferred (`deviations.md` §4). If the brief requires any of them, they become
   milestones rather than deferrals.
5. **The CircuitCraft catalog.** If the brief supplies real catalog data, it replaces the authored
   seed in `backend/app/seed/data/catalog.json`, and the fidelity tests in
   `tests/seed/test_catalog_seed.py` must be re-pointed at the supplied values.

## 7. Standing rule

Until the brief is supplied, **the supplied architecture and project documentation are the source of
truth**. No requirement is to be attributed to the brief unless it appears in §4 of this note.
