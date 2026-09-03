# ADR-019 — Assistant UI owns the agent chat runtime, and nothing else

**Status:** Accepted · **Date:** 2026-09-03 · **Supersedes:** nothing · **Superseded by:** nothing

Relates to ADR-010 (no streaming), ADR-017 (Vite + React), ADR-009 (`create_order` is not a tool),
ADR-018 (Groq is the locked provider).

---

## Context

The project owner asked for [Assistant UI](https://assistant-ui.com) to be used for the AI agent
frontend experience, with the explicit constraints that it remain a frontend UI/runtime layer, that
it not replace the backend agent runtime, and that no business logic, catalog truth, ranking,
policy decision or provider credential move into the browser.

The frontend already had a working conversational surface (`features/chat/`) built to
`docs/frontend/00-architecture-and-ux-specification.md`, with 35 passing tests. The question was
therefore not "how do we build a chat UI" but "what, if anything, should Assistant UI take over".

Three findings from the audit shaped the answer, and all three are **existing closed decisions**
rather than gaps:

1. **There is no streaming.** `POST /api/chat` returns one JSON object per turn. ADR-010 and
   `architecture.md` F§28 both reject token streaming, and the UX specification lists it under
   "should NOT be implemented" (§20.H).
2. **There is no per-tool-call visibility.** The agent trace, when enabled at all, is returned
   *after* the turn completes. The UX specification is explicit that presenting granular
   "Searching catalog…" steps "would be inventing information the frontend does not have" (§4.2).
3. **Tool execution is entirely server-side.** Assistant UI's toolkit API describes tools the
   *browser* executes; ADR-009 and the agent runtime keep every tool behind the boundary.

Assistant UI's headline capabilities are streaming, tool-call rendering and thread management. In
this application the first two are unavailable by design and the third is meaningless — a session is
a single anonymous conversation (ADR-006 has no `users` table).

## Decision

**Assistant UI owns the agent conversation's runtime — the message list, composer state, run
lifecycle and cancellation — and nothing else.**

Concretely:

- `useLocalRuntime` is driven by a custom `ChatModelAdapter` whose `run()` is a plain `async`
  function returning a single result, **not** an async generator. This is an officially documented
  Assistant UI pattern, and it maps one-to-one onto a backend that answers one JSON object per turn.
  **No closed decision was reopened and no stream is simulated.**
- The adapter calls the same Zod-validated `sendChat` the rest of the application uses, so the money
  rules, the closed error vocabulary (F§25) and the "a business outcome is not a network error"
  boundary (ADR-010) all continue to hold unchanged.
- `recommendations[]`, the cart, the approval dialog and the order page are **untouched**. Products
  continue to render from the structured array only, never parsed out of prose (F§9).
- The presentational transcript (`ChatWindow`) is **kept**, fed by a `useAgentChat` bridge that
  projects Assistant UI's thread state into the props it already accepted. Its accessibility
  behaviour — `role="log"`, `aria-live="polite"`, focus and Escape handling — is preserved along
  with the tests that assert it.

### What was rejected, and why

| Rejected | Why |
| --- | --- |
| `npx assistant-ui@latest init` | Documented for **Next.js**, and it works by running `shadcn add`. This project is Vite (ADR-017) and deliberately does not use shadcn — it has a hand-built Tailwind design system. Running it would have installed a component library the project does not use and rewritten configuration it does. **The command was not run.** |
| Assistant UI `Thread`/`Composer` primitives replacing the transcript | Would rewrite tested accessibility behaviour to gain styling the project already has. Reuse was preferred over replacement. |
| Toolkits / `makeAssistantToolUI` for product cards | `makeAssistantToolUI` is deprecated in current Assistant UI, and toolkits describe browser-executed tools. Our tools execute server-side behind the Policy Engine; recommendations are not tool calls. Product cards stay ordinary components fed by the response contract. |
| Adding streaming so the library's features apply | Would supersede ADR-010 — an architectural decision, not a frontend one. Raised with the owner and explicitly declined. |

## Consequences

**Positive.** The run lifecycle, cancellation and message state are now a maintained library's
concern rather than hand-rolled `useState` in `useChat`. If streaming is ever adopted, the adapter is
the single place that changes. The integration is covered by seven new tests that exercise the
adapter and bridge directly, including the F§9 "prose names a product that was never recommended"
invariant and the ADR-010 "business outcome on HTTP 200" boundary.

**Negative, and accepted.** The production bundle grew from **287 kB to 518 kB** (+80%, 153 kB gzipped) for a
runtime whose differentiating features this architecture cannot use. This is a real cost and is
recorded here rather than glossed: it buys a maintained state layer and a migration path, not new
user-visible capability today.

**Unchanged.** `GROQ_API_KEY` is not reachable from the browser. The adapter calls our API; our API
calls Groq (ADR-018). No product fact, price, ranking, compatibility judgement or policy decision is
computed in the frontend. `create_order` remains absent as a tool (ADR-009).

**`features/chat/useChat.ts` is now unused by the application** but retained: it still defines the
`Turn` type the bridge and `ChatWindow` share. Removing it is a separate tidy-up.

## Verification

Verified live on 2026-09-03 against the real backend on port 8001 and a seeded catalog, driving the
actual browser:

- A real Groq turn returned three grounded recommendations, and the cards rendered at the backend's
  exact prices (AeroCase Pro ₹999.00 ×2, ShieldCase Premium ₹1,299.00 `Low stock`) with the ranking
  engine's own `reason` text.
- Add-to-cart produced a backend-computed cart (v2, total ₹999.00) and the approval dialog opened on
  that total.
- A Groq `429` mid-turn — the documented free-tier limit — surfaced as the designed calm recovery
  message rather than a crash, confirming the ADR-010 boundary holds through the new runtime.
