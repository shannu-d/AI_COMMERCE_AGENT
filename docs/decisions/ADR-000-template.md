# ADR-000: Template

**Status:** Template — not a decision
**Date:** 2026-08-30
**Milestone:** —
**Source references:** —
**Related open questions:** —

## Context

What `architecture.md` says about this area, and what it leaves open. Quote or cite the specific
sections. State the facts before stating the problem.

## Problem

The precise question that must be answered before code can be written. One question per ADR.

## Decision

The chosen resolution, stated concretely enough that code can be written against it without
further interpretation. Use MUST / MUST NOT where the rule is binding.

## Alternatives considered

Each realistic alternative, with the reason it was not chosen. An alternative with no stated
drawback was not seriously considered.

## Consequences

What this enables, what it forecloses, and what it costs. Include the bad consequences.

## Implementation implications

Concrete, checkable obligations: tables, columns, modules, function signatures, tests, error codes.
This is the section the implementation is audited against.

## Status

Proposed | **Accepted** | Superseded by ADR-NNN. With the date the status last changed.

---

## Conventions for this directory

- ADRs are **append-only**. A decision that changes is superseded by a new ADR; the old file keeps
  its text and gains a "Superseded by" status line.
- `architecture.md` is never edited. Every place the implementation resolves an ambiguity in it,
  or departs from its letter, is recorded here.
- An ADR that is decided but not yet implemented says so explicitly, and names the milestone that
  will implement it.
