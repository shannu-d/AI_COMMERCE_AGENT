# ADR-003: Device Identifier Canonicalization

**Status:** Accepted (2026-08-30)
**Milestone:** Reference table and seed in M1; resolver service in M2
**Source references:** `architecture.md` R§5, D§13, D§14, D§28, L§18, A§11
**Related open questions:** B1 (BLOCKING), B3, B4, B5

## Context

`compatibility_rules.target_identifier` is a free-form `VARCHAR` holding values like `iphone_16`
(D§13). Compatibility matching is an exact-string lookup against that column, and the specification
is emphatic that the model must never decide compatibility (R§5: "The LLM must never guess
compatibility"; L§18: "the application/database must verify the actual compatibility").

The gap is that the model is nevertheless the component that produces the string. A buyer writes
"I just got an iPhone 16", "iphone16", "my new iphone", "iPhone16 Pro". Claude extracts *some*
identifier. Nothing in the specification maps any of those onto `iphone_16`, and nothing detects
when the mapping failed. A model that emits `iphone_16_pro` against a catalog that only knows
`iphone_16` silently returns zero compatible products — indistinguishable, from the outside, from a
catalog that genuinely has none.

That is the failure this ADR exists to prevent: **a compatibility miss that looks like a legitimate
no-match.**

## Problem

How does free-text device language become a canonical compatibility identifier, deterministically,
without the model being trusted to produce it — and what happens when it cannot?

## Decision

A three-stage pipeline, with the model responsible only for the first stage.

```
user text
  → [LLM]          extract a human-readable device phrase   ("iPhone 16")
  → [application]  normalize to a token                     ("iphone_16")
  → [application]  resolve against compatibility_targets    → canonical identifier + target kind
  → [application]  compatibility service queries compatibility_rules
```

**1. The model extracts a phrase, not an identifier.** The buyer-intent schema carries a
human-readable `device_text` field. Any canonical-looking identifier the model volunteers is treated
as free text and re-resolved from scratch; it is never used as a lookup key on trust.

**2. Normalization is a pure, deterministic function.** `normalize_token(text)` lowercases, strips
accents and surrounding whitespace, replaces every run of non-alphanumeric characters with a single
`_`, and trims leading and trailing `_`. It has no I/O, no configuration and no model involvement,
so it is exhaustively testable. `"iPhone 16"`, `"iphone-16"` and `" IPHONE  16 "` all yield
`iphone_16`.

**3. Resolution is database-backed, via a `compatibility_targets` reference table.**

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | UUID PK | internal identity |
| `target_type` | VARCHAR(64) | the *kind* of thing: `phone_model`, `laptop_model`, `device_port` |
| `canonical_identifier` | VARCHAR(128) | the token stored in `compatibility_rules.target_identifier` |
| `display_name` | VARCHAR(160) | what is shown to the buyer: "iPhone 16" |
| `aliases` | TEXT[] | additional already-normalized tokens that resolve here |
| `is_active` | BOOLEAN | retire a target without deleting history |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

`UNIQUE(target_type, canonical_identifier)`, plus a GIN index on `aliases` — alias lookup *is* the
query pattern, which is the condition D§24 sets for adding a GIN index.

Resolution order is: exact match on `canonical_identifier`, then containment match on `aliases`.
Exactly one active row must match.

**4. `target_type` on the rule and on the target mean different things, deliberately.** The
specification uses `phone_model` for cases, `device` for chargers and `device_port` for cables
(D§13, D§14). Those are not the same axis, so they are kept apart:

- `compatibility_targets.target_type` classifies **what the identifier is** — a phone model, a
  laptop model, a port. This is the identifier vocabulary.
- `compatibility_rules.target_type` classifies **how the product relates to it** — `phone_model`,
  `laptop_model`, `device_port`, or the broader `device` used for chargers.

A query for "products compatible with the phone `iphone_16`" therefore matches rules where
`target_identifier = 'iphone_16'` and `target_type IN ('phone_model', 'device')`. The specification's
own examples are preserved verbatim; the two meanings are simply no longer conflated.

**5. Unresolvable means clarify. Never guess.** If nothing matches, or more than one active row
matches, the compatibility service raises a structured `TARGET_UNRESOLVED` result. The agent asks
the buyer which device they mean. It MUST NOT fall back to substring matching, to "closest" match,
to the model's opinion, or to dropping the compatibility constraint. Dropping a compatibility
constraint to obtain results is the exact failure R§14 forbids ("Do NOT relax compatibility
silently").

**6. Canonical form is enforced by the database.** `compatibility_rules.target_type`,
`compatibility_rules.target_identifier`, `compatibility_targets.target_type` and
`compatibility_targets.canonical_identifier` all carry a `CHECK` constraint requiring the canonical
token shape `^[a-z0-9]+([-_][a-z0-9]+)*$`. A mixed-case or space-bearing identifier cannot be
inserted at all.

**7. Two adjacent open questions are closed here.**

- **B3 — what `constraints` JSONB means.** It is a set of predicates evaluated against **the
  product's own attributes**. A rule reading `{"minimum_wattage": 20, "fast_charge": true}` on a
  charger means "compatible with this device provided this product supplies at least 20W and
  supports fast charging". It is not a description of what the device requires. This is the only
  reading under which the rule is checkable from data the catalog actually holds.
- **B4 — the `rule_type` enum.** M1 permits `compatible` and nothing else, enforced by a `CHECK`
  constraint. `incompatible` and `requires` are deliberately *not* permitted: a value the filter
  does not know how to interpret is worse than a value that cannot be stored. Widening the enum
  requires a migration and a superseding ADR, at which point the filter semantics must be defined
  in the same change.

**8. Product-level compatibility is accepted for the MVP (B5).** `compatibility_rules.product_id`
points at a product, while price and stock live on the variant. A catalog where variants differ by
connector or length would need variant-level rules. The authored CircuitCraft catalog does not, so
the limitation is recorded rather than pre-solved. If it becomes real, the change is a nullable
`variant_id` on `compatibility_rules` plus a resolution rule that a variant-level row overrides a
product-level one.

## Alternatives considered

**Trust the model to emit the canonical identifier, and validate that it exists.** Cheapest, and it
catches typos. Rejected: validation only proves the token exists somewhere in the catalog, not that
it is the device the buyer meant. `iphone_15` is a perfectly valid token and a completely wrong
answer.

**Enumerate every valid identifier in the tool's JSON schema** so the model can only choose from
real values. Attractive, and it *is* used for category slugs (B2). Rejected here as the primary
mechanism: the device vocabulary grows with the catalog, the enumeration would have to be injected
into the prompt on every turn, and a constrained choice is still a model choice between plausible
neighbours. It remains available later as a defence-in-depth layer on top of resolution.

**Fuzzy matching — trigram similarity, edit distance, embeddings.** Rejected for the MVP: it turns a
deterministic lookup into a tuned one, it has no natural threshold, and its failure mode is
confidently returning the wrong device. R§8 requires determinism. An explicit alias list is boring,
auditable, and correct.

**Normalization alone, with no alias table.** Rejected: `normalize_token("iphone16")` is `iphone16`,
which does not equal `iphone_16`. Normalization handles punctuation and case; only aliases handle
the ways people actually write device names.

## Consequences

**Enables.** Compatibility lookups that are exact, deterministic and reproducible. A clean,
observable distinction between "we could not understand the device" and "we understood it and have
nothing compatible" — the second of which is a legitimate answer (R§14) and the first of which is a
question.

**Forecloses.** Recognising a device the catalog has never heard of. A buyer with a Galaxy S25 gets
a clarification request, not a guess. That is the intended behaviour.

**Costs.** One reference table and its seed data, maintained alongside the catalog. Adding a device
means adding a row. A missing alias produces an unnecessary clarification question — an annoyance,
not a correctness failure, and the safe direction to fail in.

## Implementation implications

- **M1:** `compatibility_targets` table in Alembic migration `0002`, kept separate from the seven
  specified tables in `0001` so the specified schema stays auditable in isolation. Seeded with the
  devices and ports the CircuitCraft catalog references, including `pixel_9` — a resolvable target
  with zero compatible products, which is what makes the R§14 no-match path testable.
- **M1 tests:** every `aliases` entry is already in normalized form; no alias collides with another
  target's canonical identifier or aliases; every `compatibility_rules.target_identifier` in the
  seed exists as a `compatibility_targets.canonical_identifier`. That last rule cannot be a foreign
  key because rule and target types live on different axes, so it is enforced by test and by the
  service layer.
- **M2:** `normalize_token()` in `app/services/compatibility_service.py` (pure function, unit
  tested against a table of inputs); `resolve_target(text, kind) -> ResolvedTarget | Unresolved`;
  `get_compatible_products(target)` querying with the `('phone_model','device')` style type
  expansion described above.
- **M2:** the `get_compatible_products` tool surfaces `TARGET_UNRESOLVED` as a structured tool error
  so the agent asks rather than proceeds.
- The buyer-intent schema carries `device_text: str`, not `device_id`.

## Status

**Accepted.** The reference table, its constraints and its seed land in M1. The resolver, the
normalization function and the compatibility service land in M2.
