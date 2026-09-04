# 01 — Project Overview

## What this is

A conversational commerce agent for a single merchant catalogue (CircuitCraft, 32 sellable variants
across 21 products). A buyer describes a need in prose; the system answers with grounded product
recommendations, builds a cart, takes an explicit authorization, validates it against live data, and
only then moves money.

## The invariant

Every part of the specification restates one sentence:

> **LLM proposes → application validates → user authorizes → Razorpay executes → system audits.**

This audit's central question is whether that holds in the code as built. **It does.** The evidence
is in [03-spec-vs-code](03-spec-vs-code.md) and [08-commerce-flow-audit](08-commerce-flow-audit.md);
the summary is that the model's output is treated as a *request*, never as a *fact*, at every layer.

## Scale

| Measure | Value |
| --- | --- |
| Specification (`architecture.md`) | 16,736 lines, never edited |
| Backend application code | 15,433 lines across 103 Python files |
| Backend tests | 16,766 lines across 58 files — **more test code than application code** |
| Frontend | 3,120 lines across 30 TypeScript files |
| Database | 20 tables, 4 migrations |
| Architectural decisions | 19 ADRs (plus a template) |
| Documentation | 34 Markdown files |

That the test corpus is larger than the application is itself a finding: this is a codebase where
the reasoning has been written down, not just the behaviour.

## Technology

**Backend** — Python 3.14, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL 16 (mandatory in every
environment, including tests — ADR-002), Pydantic Settings, `groq` SDK.

**Frontend** — Vite 6, React 18.3, TypeScript 5.9 (strict), TanStack Query, Zod, Tailwind,
Vitest, `@assistant-ui/react` 0.15.17 for the chat runtime only (ADR-019).

**LLM** — Groq, model `openai/gpt-oss-120b`. **Permanent and locked (ADR-018).**

**Payments** — Razorpay, test mode.

## Milestone shape

Seventeen units of work (M0–M15 plus M4-R, the Groq provider reconciliation). Fourteen are complete
and runtime-verified, one is blocked on a missing package, two are partial. The build order is
`docs/analysis/02-dependency-map.md`, and the specification is emphatic that this must not be built
in one pass — the repository's git history shows it was not.

## What makes this codebase unusual

Three things stood out during the audit and are worth stating plainly, because they are the reason
so much of it verified cleanly:

1. **Boundaries are enforced by tests, not by convention.** AST-walking guards assert that the
   deterministic packages never import the model layer, that only one module imports the provider
   SDK, and that no module named for a forbidden tool exists.
2. **Money is a `Decimal` and a fixed-scale string end to end.** Integer minor units exist only
   inside `app/payments/`. The database confirms it: all twelve business money columns are
   `NUMERIC(12,2)`.
3. **The dangerous capability was removed rather than guarded.** `create_order` is not a registered
   tool that fails — it does not exist as a tool at all, and four separate tests keep it that way.
