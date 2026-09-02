# ADR-017: Vite, and How the Browser Is Let In

**Status:** Accepted, **partially implemented (M14/F1: the CORS half)**
**Date:** 2026-09-02
**Milestone:** M14 (F0–F1) / binding on every frontend phase after it
**Source references:** L§44 (implementation technology, "React / Next.js"), F§3 (keep the frontend
small), F§5 and F§29 (the frontend must not invent or duplicate state), F§35 ("the most important
design rule"), L§45 and P§39/RZP-01 (secrets never reach frontend code)
**Related open questions:** F6 (frontend framework — this ADR closes it)
**Related decisions:** ADR-006 (no users table), ADR-010 (no streaming), ADR-011 (the Razorpay
order boundary), ADR-013 (idempotency)

## Context

`architecture.md` L§44 names the frontend technology as "React / Next.js" and never picks one.
`docs/notes/open-questions-status.md` has carried this as **F6**, recorded as *"OPEN, and now
due"* — M13 is complete, M15's backend scenarios pass, and M14 is the next milestone. The choice
shapes every file of the frontend, so it cannot be deferred past the scaffold.

A second question arrives at the same moment and has nothing to do with taste: **no browser can
call this API today at all.** There is no CORS middleware anywhere in `backend/app/`. A frontend on
any origin but the API's own is refused by the browser before the request is even attempted. This
blocks every frontend of every scope and every framework, so it is settled here rather than in a
document of its own.

## Problem

Two decisions, one of which has been made wrongly in this repository once already.

**F6.** `PROGRESS.md` recommended Next.js, reasoning that an SSR framework gives
`RAZORPAY_KEY_SECRET` a natural server-side home. That recommendation was written before anyone
checked what the backend actually hands the browser.

**CORS.** FastAPI's `CORSMiddleware` is three lines, which is exactly why it tends to be added
without a decision — most commonly as `allow_origins=["*"]` with `allow_credentials=True`. This API
has a property that makes the reflexive configuration worth refusing deliberately.

## Decision

### 1. React 18 + TypeScript on **Vite**, not Next.js

The deciding fact is what `RazorpayClient.checkout_config()` returns
(`backend/app/payments/razorpay_client.py`). Everything the frontend needs in order to open
Razorpay Checkout is the **public** key ID, an amount, a currency and a provider order ID — all
minted by the backend, per request, and all safe in a browser. `RAZORPAY_KEY_SECRET` and
`RAZORPAY_WEBHOOK_SECRET` are read only by backend modules and never appear in any API response;
that is already enforced, and it is what the specification requires (L§45, P§39).

So the frontend holds **no secret**. The server layer Next.js supplies would be protecting nothing.
With that removed, nothing else argues for it:

- **No SEO requirement.** This is a conversational commerce demo, not a content site. Nothing in
  `architecture.md` asks for indexable pages.
- **No server-rendering need.** Every page's content comes from a session-scoped API call that has
  to happen at interaction time regardless.
- **F§3 says the opposite.** *"For the MVP, keep the frontend small... Do NOT build a large
  e-commerce UI."* Next.js's routing, rendering and caching model is a layer between the browser
  and FastAPI that would have to be understood and justified; here it would be paid for and unused.

Vite is chosen for the simpler dev loop and build model, paired with React Router v6 for routing.
**This supersedes `PROGRESS.md`'s Next.js recommendation**, which was made without inspecting
`checkout_config()` and is wrong on its own stated grounds.

*If a buyer identity model is ever adopted (ADR-006 closed this as "no users table"), revisit this
rather than working around it — a login introduces exactly the secret-handling and session-cookie
concerns that Vite alone does not answer.*

### 2. CORS origins are listed explicitly; `*` is refused

`CORS_ALLOWED_ORIGINS` is a real setting, validated at startup like `RANKING_PROFILE`, defaulting
to the Vite dev server (`http://localhost:5173`, `http://127.0.0.1:5173`).

`Settings` **rejects `"*"` outright**, with a message naming this ADR. The reasoning is specific
rather than ritual: this API mints and trusts `session_id` with no other authentication — a session
identifier is the entire claim *"this cart is mine"* (ADR-006 deliberately has no users table).
Today a wildcard would not by itself hand a cart to an attacker, because the identifier is an
unguessable UUID carried **in the request body**, so no browser attaches it ambiently to a
cross-origin request. But that safety is a property of the current design, not a promise the
architecture makes. `*` would silently outlive the design it depends on, and the failure would be
invisible on the day it stopped being true.

`Settings` also rejects an origin carrying a trailing slash or a path. The `Origin` header is
scheme, host and port and nothing else, so `http://localhost:5173/` matches no request a browser
will ever send. The symptom — every cross-origin call failing against a configuration that looks
correct — is expensive to diagnose and cheap to prevent.

### 3. Credentials are off; only `Content-Type` is allowed

`allow_credentials=False`. Nothing in `backend/app/api/` reads a cookie or an `Authorization`
header — a grep for `Header` and `Cookie` across the package returns nothing — because every
identifier this API trusts (`session_id`, `cart_version`, `idempotency_key`) travels in the request
body. There is therefore no ambient authority for a cross-origin page to borrow, and enabling
credentials would manufacture one for no gain.

For the same reason `allow_headers` is exactly `["Content-Type"]`. There is no custom request
header to permit. In particular there is **no `Idempotency-Key` header**: ADR-013's key is a body
field on `CreateOrderRequest`, and allowlisting a header nothing sends would advertise a transport
that does not exist.

`allow_methods` names `GET, POST, PATCH, DELETE, OPTIONS` explicitly rather than relying on a
default, because `PATCH` and `DELETE` are real routes on `/api/cart` and a narrower default would
have removed the ability to edit a cart from a browser while every backend test still passed.

## Consequences

- **F6 is closed.** M14 scaffolds a Vite + React + TypeScript app; §2.1 of
  `docs/frontend/00-architecture-and-ux-specification.md` is confirmed rather than overridden.
- **A browser can reach the API**, which unblocks F2 onward at any scope.
- **Deploying the frontend anywhere real requires setting `CORS_ALLOWED_ORIGINS`.** This is
  deliberate: the failure mode is a loud refusal at a known configuration point, not a silent
  wildcard.
- **`.env.example` carries the setting**, so the requirement is visible to anyone setting the
  project up rather than discovered when the first fetch fails.
- **A secret reaching frontend code remains a defect**, not a configuration choice. Nothing in this
  decision creates a place to put one.

## Alternatives considered

**Next.js.** Rejected on the evidence above: its principal advantage here would be protecting a
secret the frontend never receives. Reconsider if identity or authentication lands.

**`allow_origins=["*"]` for the MVP, tightened later.** Rejected. "Tightened later" is not a
mechanism, and the wildcard's safety here rests on an implementation detail — body-carried
identifiers — that no test asserts and no document promises.

**Regex origins (`allow_origin_regex`).** Rejected for now: a pattern is harder to review than a
list, and there is exactly one frontend.

**Putting CORS behind a reverse proxy instead.** Rejected as an MVP answer. It moves a security
decision into infrastructure that does not exist yet, and the development loop needs this working
across two localhost ports today.
