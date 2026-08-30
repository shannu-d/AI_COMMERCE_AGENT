# ADR-008: Money Representation

**Status:** Accepted (2026-08-30)
**Milestone:** Catalog half implemented in M1; the Razorpay boundary lands in M11
**Source references:** `architecture.md` D§8, D§9, P§5, P§7, P§29, F§12, F§29
**Related open questions:** C4 (BLOCKING), B9

## Context

`architecture.md` fixes the catalog price type as `NUMERIC(12,2)` (D§8) and carries an explicit
`currency` column on both `merchants` and `product_variants`. Every example is in rupees:
₹999, ₹1,499, ₹1,798.

Razorpay's API transacts in **integer minor units** — paise for INR. ₹1,798.00 is `179800`.

The specification never mentions this conversion. It is the single highest-consequence omission in
the document, because a wrong conversion is silent: the buyer approves ₹1,798, Razorpay charges
₹17.98 or ₹179,800, and nothing in the system notices, since every component is internally
consistent.

Compounding it, the Policy Engine's input sketch (P§5) shows `"displayed_total": 1798` — a bare
integer with no stated scale. Read as rupees it is ₹1,798; read as paise it is ₹17.98.

## Problem

Fix a single money representation for the application and the database, fix the conversion to
Razorpay's units, fix where the conversion happens, and make an incorrect conversion impossible to
introduce without failing a test.

## Decision

### `Decimal` in the application, `NUMERIC(12,2)` in the database

Every monetary value inside the application is a Python `decimal.Decimal` with an exact scale of 2.
Every monetary column is `NUMERIC(12,2)`. Every monetary value is accompanied by an explicit
currency; there is no implicit default at the point of use.

### Floating point is prohibited for money

`float` MUST NOT appear in any arithmetic on a monetary value, in any Pydantic model field carrying
money, in any JSON parsed into money, or in any test fixture. `0.1 + 0.2 != 0.3` is not an
acceptable property for a payment system.

Concretely:

- Pydantic money fields are typed `condecimal(max_digits=12, decimal_places=2)`.
- JSON seed and fixture data carry money as **strings** (`"999.00"`), parsed with `Decimal(str)`.
  `json.loads` would otherwise turn `999.00` into a float before any validation could intervene.
- SQLAlchemy columns are `Numeric(12, 2, asdecimal=True)`.
- API responses serialize money as a fixed-scale string, not as a JSON number, so no client's JSON
  parser silently introduces a float.

### Conversion happens exactly once, at the Razorpay client boundary

```
Decimal("1798.00")  ──to_minor_units()──▶  179800  ──▶ Razorpay
Decimal("1798.00")  ◀──from_minor_units()──  179800  ◀── Razorpay webhook
```

Two functions in one module, `app/payments/money.py`, are the only code in the repository permitted
to move between the two representations:

```python
def to_minor_units(amount: Decimal, currency: str) -> int
def from_minor_units(minor: int, currency: str) -> Decimal
```

`to_minor_units` quantizes to the currency's exponent with `ROUND_HALF_UP`, then raises
`MoneyPrecisionError` if quantization changed the value — an amount that needs rounding to reach
minor units is a bug upstream, not something to silently round at the payment boundary. Both raise
on an unknown currency. Neither has a default currency parameter.

### Currency exponents are data, not an assumption

A `CURRENCY_EXPONENT` mapping holds `{"INR": 2}` for the MVP. The functions never assume 2. Adding
JPY (exponent 0) or KWD (exponent 3) is a data change, and until such a currency is added the
functions reject it rather than guessing.

### Single currency for the MVP

INR only (closes B9). Currency is stored and compared explicitly at every boundary; a mismatch
between a cart item, its cart, and the merchant is a `CURRENCY_MISMATCH` error. **No conversion is
implemented.** A system that silently converts currencies is a system that can charge the wrong
amount in a new way.

### The integer is persisted alongside the decimal

`orders.total_amount_minor BIGINT` and `payments.amount_minor BIGINT` store the exact integers
exchanged with Razorpay, next to the `NUMERIC(12,2)` values. This is deliberate redundancy: it makes
the boundary auditable after the fact, and it lets reconciliation assert
`to_minor_units(total_amount) == total_amount_minor` on stored rows rather than only in the code
path that wrote them.

### P§5's ambiguous integer is resolved

`displayed_total` and every other amount crossing the policy boundary is a **decimal major-unit
amount with an explicit currency**, typed in the `TransactionContext` model. Minor units exist only
inside `app/payments/`.

## Alternatives considered

**Integer paise everywhere, including the catalog.** Genuinely defensible; several payment systems
do exactly this, and it removes the conversion. Rejected because D§8 fixes `NUMERIC(12,2)` for
catalog price, so adopting it would mean either contradicting the specified schema or maintaining
two money representations in one database — which is strictly worse than one conversion behind two
tested functions.

**`float` with rounding at the boundary.** Rejected. Binary floating point cannot represent ₹0.10
exactly, errors accumulate across cart lines, and the failure is silent and intermittent.

**Convert wherever convenient, with a helper.** Rejected: a helper that anyone may call is a helper
that will be called with an already-converted value. Restricting conversion to one module makes
double conversion visible in review and detectable by a lint rule.

**Store only the minor-unit integer on orders and derive the decimal.** Rejected: the decimal is
what the buyer approved and what the audit trail must show. Both are kept, and their agreement is
asserted.

**Round instead of raising when quantization changes the value.** Rejected: at that point the
application is guessing what the buyer agreed to. An amount arriving at the payment boundary with
more precision than the currency supports means something upstream computed money wrongly.

## Consequences

**Enables.** A conversion that is impossible to get wrong twice — one implementation, one test
suite, round-trip properties asserted over a range of values. It also makes the money path
auditable: the stored integer is the number Razorpay actually saw.

**Forecloses.** Multi-currency carts and any automatic conversion. Both are additions, not
redesigns.

**Costs.** `Decimal` is more verbose than `float` and slower, which is irrelevant at this scale.
Serializing money as strings means frontend code must parse and format rather than doing arithmetic
on numbers — which F§12 already requires, since the frontend must never compute an authoritative
total.

## Implementation implications

- `app/payments/money.py` — `to_minor_units`, `from_minor_units`, `CURRENCY_EXPONENT`,
  `MoneyPrecisionError`, `UnsupportedCurrencyError`. No other module converts.
- A shared Pydantic type alias `Money = condecimal(max_digits=12, decimal_places=2)`; every schema
  field carrying an amount uses it and sits next to a `currency` field.
- Seed and fixture JSON carry money as strings; a test asserts that no monetary value anywhere in
  `catalog.json` parses as a JSON number.
- **M1 test (implemented):** every seed price is a `Decimal` with scale ≤ 2 and value ≥ 0, and none
  was ever a `float`.
- **M11 tests:** `from_minor_units(to_minor_units(x, "INR"), "INR") == x` across a generated range
  including `0.01`, `0.05`, `999.99`, `1798.00` and `99999999.99`; `to_minor_units(Decimal("1798.00"),
  "INR") == 179800` exactly; an unsupported currency raises; an over-precise amount raises rather
  than rounding.
- **M11 reconciliation test:** for every stored order, `to_minor_units(total_amount, currency) ==
  total_amount_minor`.
- The Razorpay client accepts a `Decimal` and a currency, converts internally, and never exposes a
  minor-unit parameter to its callers.

## Status

**Accepted.** The catalog half — `NUMERIC(12,2)`, string-encoded seed money, no floats — is
implemented and tested in M1. The conversion functions and their tests land in M11, before the first
Razorpay call.
