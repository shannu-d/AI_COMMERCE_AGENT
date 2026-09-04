# 11 — Frontend Audit

**Stack:** Vite 6.4, React 18.3, TypeScript 5.9 (strict), TanStack Query 5.62, Zod 3.24, Tailwind
3.4, Vitest 3.2, `@assistant-ui/react` 0.15.17. 30 files, 3,120 lines.

## Checks run

| Check | Result |
| --- | --- |
| `tsc --noEmit` (strict) | **CLEAN** |
| `eslint . --max-warnings 0` | **CLEAN** |
| `vitest run` | **42 passed / 4 files / 0 skipped** |
| `vite build` | **518.16 kB** (gzip 153.08 kB) |

## Routing

Two routes, and only two: `/` (`ShopPage`) and `/orders/:orderId` (`OrderPage`), with `*` falling
back to `ShopPage`. Home, product listing, product detail and order history **do not exist** — the UX
specification marks them blocked on catalog endpoints the backend does not expose (§5, §20.C.2). This
is a deliberate deferral, not an omission.

There is consequently **no "View Product" affordance**, because there is no product page to view.

## Assistant UI integration — correctly scoped

Assistant UI owns the chat **runtime** only: message list, composer state, run lifecycle,
cancellation. It does not own the transcript rendering, the cards, the cart, the approval dialog or
the order page (ADR-019).

The adapter is a `ChatModelAdapter` whose `run()` is a plain `async` function returning a single
result rather than an async generator — the documented non-streaming pattern, matching a backend that
answers once per turn. **No stream is simulated and ADR-010 was not reopened.**

`npx assistant-ui@latest init` was deliberately not run: it targets Next.js and installs through
`shadcn`, neither of which this project uses.

**Cost, recorded rather than glossed:** the bundle grew from 287 kB to 518 kB (+80%) for a library
whose headline features — streaming, tool-call rendering, thread management — this architecture
cannot use. It buys a maintained state layer, not new user-visible capability.

## The frontend never treats its own data as authoritative — verified

| Guarantee | Mechanism | Verified |
| --- | --- | --- |
| Never computes a price | No arithmetic on money anywhere in `src/` | ✅ |
| Never sums a total | Totals rendered from `cart.total` | ✅ browser: ₹999.00 matched the API |
| Money is a string | `Money` Zod schema rejects a JSON number and an unscaled string | ✅ |
| Never invents a product | Cards render from `recommendations[]` only | ✅ dedicated test + browser |
| Never decides stock | `stock_status` and `available` come from the response | ✅ `LOW_STOCK` rendered |
| Never authorizes | Approval posts `cart_version` + `expected_total` for the server to check | ✅ |

The strongest of these is the F§9 guarantee, and it has a test that scripts the exact failure it
prevents: prose naming a product that is absent from `recommendations[]` renders **no card**.

## Contract safety

Every response is parsed through a Zod schema at the fetch boundary, so contract drift becomes a loud
`MALFORMED_RESPONSE` rather than an `undefined` deep inside a component. `request()` throws only for
4xx/5xx and transport failures — a business outcome on HTTP 200 stays on the success path, so
recovery flows never land in an error branch.

## State management

No global store — deliberately (F§5, F§29). TanStack Query owns server state; the Assistant UI
runtime owns conversation state; React state owns the rest. Session id lives in `sessionStorage` with
an in-memory fallback for browsers that block site data.

## Browser verification (performed)

Driven in a real Chrome instance against the live backend and a seeded catalogue:

| Step | Result |
| --- | --- |
| App loads, empty state | ✅ "Ask for what you need", cart panel prompt |
| Send a message | ✅ user bubble, `Thinking…` from `isRunning` |
| Real Groq turn | ✅ prose plus 3 cards |
| Card fidelity | ✅ ₹999.00 / ₹999.00 / ₹1,299.00, ranks #1–#3, `In stock` / `Low stock`, engine `reason` text |
| Add to cart | ✅ cart v2, total ₹999.00 |
| Approval dialog | ✅ "Confirm your order", correct total, Cancel/Approve |
| Error path | ✅ a real Groq `429` rendered as a calm recovery message, not a crash |

## Accessibility

`role="log"` with `aria-live="polite"` for the transcript, `role="dialog"` with `aria-modal` for
approval, labelled input, keyboard-only operation, Escape to close, focus management. Eleven a11y
tests, including "can be driven entirely from the keyboard" and "does not let a second message
interleave with one in flight".

`aria-describedby` is used nowhere — a minor gap for associating error text with its control (P3).

## Responsive — NOT VISUALLY VERIFIED

Stated honestly: an attempt to resize the browser to mobile (390×844) reported success, but the
captured viewport did not change, so **mobile and tablet rendering were not visually confirmed**.

Source inspection shows a real but thin responsive implementation — **8 breakpoint utilities across
3 files**: `ShopPage` (`lg:flex-row`, `lg:w-80`, `lg:border-r`, `lg:border-b-0`),
`RecommendationCard` (`sm:grid-cols-2`, `lg:grid-cols-3`), `ApprovalDialog` (`sm:items-center`,
`xl:w-96`). The intent — stacked on mobile, side-by-side from `lg` — is clear and plausible, but
**intent is not verification**.

## Findings

| # | Finding | Severity |
| --- | --- | --- |
| 1 | Assistant prose renders as **raw markdown** — Groq emits tables and `**bold**` that display as literal characters | **P1** (most visible user-facing defect) |
| 2 | Mobile and tablet layouts never visually verified | P2 |
| 3 | `OrderPage` never driven end to end in a browser | P2 |
| 4 | `features/chat/useChat.ts` superseded; retained only for the `Turn` type | P3 |
| 5 | Bundle +80% for unusable library features | P3 |
| 6 | No `aria-describedby` on error associations | P3 |

## Verdict

**PARTIAL — strong but with one visible defect.** The architecture is right, the trust boundary is
respected, the tests are meaningful, and the browser run confirmed the core journey. Markdown
rendering is the one thing a user would notice immediately.
