# ADR-023 — Authentication and authorization: one `users` table, opaque bearer tokens, ownership through the session

**Status:** Accepted · **Date:** 2026-09-04 · **Supersedes:** the single-tenant/no-auth stance of **ADR-022** · **Superseded by:** nothing

Relates to ADR-002 (merchant scoping is server-resolved), ADR-006 (the commerce schema, and its
explicit note that authentication means adding `users`), ADR-009/ADR-010 (the agent boundary),
ADR-017 (Vite + a separate browser origin), ADR-022 (the merchant dashboard).

---

## Context

Until now the system had **no authentication of any kind**. Verified in code before designing
anything:

- 19 tables, none for identity. No `users`, no `passwords`, no tokens.
- No auth dependency in `pyproject.toml`; no hashing, JWT, or session library.
- `sessions` is anonymous: `id`, `merchant_id`, `conversation_state`, `intent`, `last_seen_at`.
- **`carts.session_id` and `orders.session_id` both point at `sessions`.** The anonymous session id
  *is* the entire claim "this cart is mine".
- That id travels in the **request body**, never a cookie — deliberately. The CORS validator refuses
  a wildcard origin for exactly this reason and notes that "no credentials are sent automatically".
- The merchant dashboard resolved its merchant from `settings.default_merchant_id`, server-side
  (ADR-022) — single-tenant, and the reachability of `/merchant` was a documented limitation.

The project owner now requires authentication and authorization for **both** customers and
merchants, with real ownership enforcement in each direction.

ADR-006 already anticipated this: *"Introducing authentication later means adding `users` and a
nullable [foreign key]."* This ADR follows that plan rather than inventing a different one.

## Decision

### 1. One `users` table with a role, not two identity tables

```
users
  id            uuid pk
  email         citext-ish, UNIQUE (stored lowercased)
  password_hash text                     -- argon2id, never a plaintext column
  role          'CUSTOMER' | 'MERCHANT'  -- CHECK
  merchant_id   uuid NULL -> merchants   -- NOT NULL in effect for MERCHANT, NULL for CUSTOMER
  display_name  text NULL
  is_active     bool
  created_at / updated_at
```

A CHECK enforces the role/merchant pairing in the database, not merely in a service:
`(role = 'MERCHANT' AND merchant_id IS NOT NULL) OR (role = 'CUSTOMER' AND merchant_id IS NULL)`.

`merchants` stays what it is — the **business** that owns a catalogue. A merchant *login* is a
person who administers one, which is a `users` row pointing at it. Two identity tables would
duplicate the password column, the token table, the login route and every test, and would make
"is this request authenticated" two questions instead of one.

### 2. Ownership derives through the session — `carts` and `orders` are not touched

The only schema change to existing tables is **`sessions.user_id`** (nullable FK to `users`).

```
users ──< sessions ──< carts
                   └─< orders
```

A cart or an order is mine if its session's `user_id` is me. `carts` and `orders` keep their exact
shape, their exact constraints, and their exact code paths. This is the smallest migration that
produces real ownership, and it means **no data migration** for the rows that already exist: an
anonymous session simply has `user_id IS NULL`, which is what it always was.

### 3. Anonymous shopping is kept, and login *claims* the session

Browsing, the Smart Agent, the cart and checkout all work logged-out today, and that is a product
property worth keeping — forcing a login before a shopper can ask the agent a question would be a
regression. So:

- An anonymous visitor gets a `sessions` row exactly as now.
- **On login or registration, the caller's current anonymous session is claimed**: its `user_id` is
  set to the authenticating user, provided it is not already owned by someone else. The cart hangs
  off the session, so it follows automatically.
- There is **no cart-merge algorithm**, because there is nothing to merge: the same cart row simply
  gains an owner. A session already owned by another user is never re-pointed — the login just
  proceeds with a fresh session instead.

### 4. Opaque server-side bearer tokens, not JWT and not cookies

```
auth_tokens
  id           uuid pk
  token_hash   text UNIQUE   -- sha256 of the token; the token itself is never stored
  user_id      uuid -> users ON DELETE CASCADE
  issued_at / expires_at / last_used_at / revoked_at
```

The client sends `Authorization: Bearer <token>`.

**Why opaque server-side rather than JWT.** The project already keeps server-side state and already
treats an identifier as a credential; a token row costs one indexed lookup per request. Logout and
revocation are a row update. A JWT would add a signing secret to protect, an expiry/refresh dance,
and *no* revocation — trading a real property (immediate invalidation) for a scaling property this
system does not need.

**Why a header rather than a cookie.** The API deliberately carries every trusted identifier in the
request body or an explicit header, so nothing is attached ambiently. Keeping that:

- **no ambient credential ⇒ no CSRF ⇒ no CSRF tokens, no double-submit, no SameSite reasoning.**
- The frontend is a different origin (`:5173` → `:8000`, ADR-017). A cookie there needs
  `SameSite=None; Secure` in production plus CSRF defence — real complexity bought for nothing.

`Authorization` is added to the CORS `allow_headers` list; the origin allow-list is unchanged and
still refuses `*`.

**The tradeoff, stated honestly.** A bearer token in `sessionStorage` is readable by injected
script; an `HttpOnly` cookie would not be. We accept that, for the reasons above, and mitigate the
other side: tokens expire, are revocable, are stored only as a SHA-256 hash, and are never logged
(the existing redaction filter already masks `authorization`). If the threat model later prioritises
XSS over CSRF, this decision is the single place to revisit.

### 5. Passwords

`argon2id` via `argon2-cffi`, with the library's defaults. **Only the hash is ever stored**; there is
no plaintext column and no reversible encoding. A registration that reuses an email fails with the
same generic message as a wrong password would, so the endpoint is not a user-enumeration oracle.
Password minimum length is enforced at the schema; there is no maximum-length truncation.

### 6. Authorization is explicit, per-route, and derived server-side

Three FastAPI dependencies, and nothing else may decide identity:

| Dependency | Meaning |
| --- | --- |
| `optional_user` | resolves a token if present; `None` otherwise. For routes that work both ways (cart, chat). |
| `require_customer` | 401 without a token, 403 if the user is not a CUSTOMER. |
| `require_merchant` | 401 without a token, 403 if not a MERCHANT. **Yields the merchant id from `users.merchant_id`.** |

- **Public** (unchanged): `/api/health`, `/api/categories`, `/api/products[/{slug}]`,
  `/api/sessions`, `/api/chat`, the Razorpay webhook. The catalogue does not become private.
- **Ownership-checked**: cart and order routes accept the existing `session_id`, and when a user is
  authenticated the session must belong to them. An anonymous session keeps working exactly as
  before.
- **Merchant-only**: every `/api/merchant/*` route. `merchant_id` now comes from the authenticated
  user, so ADR-022's guarantee gets stronger, not weaker: the client still cannot name a merchant,
  and now it cannot reach *any* merchant without proving it administers one.

**The frontend is never the authority.** No route reads a user id, a role or a merchant id from a
request body, a query parameter or a header other than the bearer token it verifies.

### 7. `merchant_activity` — a second log, not a wider `audit_events`

A dashboard that can change a price is a dashboard whose changes need attributing. The record is a
new append-only table, `merchant_activity`, and **not** rows in `audit_events`.

`audit_events` answers *"how did this transaction reach its outcome"*. Every row hangs off a session,
a cart, an order or a payment, and its vocabulary is RZP-07's twelve money-path events plus four
failure cases. A price edit has none of those anchors. Folding administration into it would mean
widening two `CHECK` constraints, adding two columns that are null for every existing row, and
leaving one table answering two unrelated questions — reconstructing a purchase would then start by
filtering out stock edits.

```
merchant_activity
  id            uuid pk
  seq           bigint identity, UNIQUE   -- a total order; timestamps tie inside a transaction
  merchant_id   uuid -> merchants
  actor_user_id uuid NULL -> users        -- ON DELETE SET NULL
  actor_email   text                      -- copied at write time, so history survives the account
  action        CHECK (one of eleven)
  entity_type   'PRODUCT' | 'VARIANT' | 'CATEGORY'
  entity_id     uuid NULL                 -- deliberately no FK: the log outlives the row
  subject       text NULL                 -- a SKU or a name, so the entry reads without a join
  payload       jsonb                     -- before-and-after; never a secret
  created_at    timestamptz
```

Three properties are load-bearing:

- **Writes only.** Eleven actions, all mutations. Logging reads would bury the entries that can
  actually change what a buyer is quoted.
- **The actor is the token.** `ActivityService.record` takes an `AuthenticatedUser`, not an id or an
  email, so no call site can attribute an action to somebody who did not perform it.
- **It shares the transaction with the change.** Recording is a `flush`, never a `commit`. A refused
  edit logs nothing; a log full of changes that never happened would be worse than no log.

`GET /api/merchant/activity` reads it, ordered by `seq` and scoped to the token's own merchant.

### 8. What this does not change

The commerce invariant is untouched and is *strengthened* by having a real principal at the
authorization step:

> LLM proposes → application validates → **user authorizes** → Razorpay executes → verified webhook
> confirms → system audits.

Groq remains the provider (ADR-018). The agent gains no new authority: identity is not something the
model can assert, and no tool takes a user, a role or a merchant. `create_order` is still not a tool.
Prices, stock, policy and payment state remain exactly where they were.

## What was rejected

| Rejected | Why |
| --- | --- |
| Separate `customers` and `merchant_users` tables | Duplicates password storage, token issuance, login and every test; makes "authenticated?" two questions. |
| A `user_id` column on `carts` and `orders` | Redundant — they already point at `sessions`. It would need a data migration and two places that can disagree about who owns a cart. |
| JWT / access+refresh pair | No revocation, a signing secret to protect, expiry complexity. This system already has server state. |
| `HttpOnly` cookies + CSRF tokens | Would introduce CSRF where none exists today, and needs `SameSite=None; Secure` for the cross-origin dev and deploy topology. |
| Dropping anonymous shopping | Would break browsing and the Smart Agent for logged-out visitors — a product regression. |
| A cart-merge algorithm | Unnecessary once login claims the session: the cart row is already the right one. |
| OAuth / social login | An external dependency and a redirect flow for an MVP that needs email + password. |

## Consequences

**Positive.** Customers own their carts and orders; merchants own their catalogue, inventory,
orders and analytics; neither can reach the other's data or another tenant's. The merchant dashboard
stops being reachable by anyone with the URL. Anonymous shopping is preserved. The migration is one
new table pair plus one nullable column.

**Negative, and accepted.** A bearer token in `sessionStorage` is XSS-readable (see §4). Every
authenticated request costs one token lookup. There is no password reset, no email verification and
no rate limiting on login in this milestone — all recorded as limitations, none of them silently.

**Superseded.** ADR-022's "single-tenant, no authentication — and that is the isolation guarantee"
is replaced by this ADR. The *structural* part of that guarantee survives verbatim: the client still
never names a merchant. What changes is where the server gets the merchant id from —
`settings.default_merchant_id` becomes `current_user.merchant_id`.
