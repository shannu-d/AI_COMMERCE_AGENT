# ADR-020 — The recommendation cards are a surface of their own, not part of the transcript

**Status:** Accepted · **Date:** 2026-09-04 · **Supersedes:** nothing · **Superseded by:** nothing

Relates to ADR-010 (the chat API contract), ADR-019 (Assistant UI owns the chat runtime),
ADR-009 / F§9 (products come from `recommendations[]`, never from prose), ADR-017 (Vite + React).

---

## Context

`POST /api/chat` returns one object per turn: prose in `message`, ranked products in
`recommendations[]`, plus `cart`, `state`, `error` (ADR-010). Both halves already exist and are
Zod-validated at the fetch boundary; nothing about the contract needed to change.

Two problems with how a turn was presented:

1. **The assistant's prose dumped the whole result as a Markdown table.** The system prompt said
   nothing about reply length or format, so when the model received a structured tool result it
   helpfully tabulated every column — SKU, colour, stock, reason — inside the chat bubble. The buyer
   then had to read a database table in a chat window to find out what was recommended.

2. **The frontend rendered `recommendations[]` inside the transcript.** `ChatWindow` drew a
   one-column `RecommendationGrid` under each agent turn's prose. The
   `docs/frontend/00-architecture-and-ux-specification.md` design put it there on purpose
   (§4.2, and the state table at line 517: *"embedded in the chat message it arrived with, not
   hoisted elsewhere"*). In the narrow concierge rail a product card is cramped, and stacking the
   table prose above the cards made every answer a wall of text.

The project owner asked for the reference interaction instead: a dedicated **Smart Agent
Recommendations** area beside the conversation, with the chat kept to a short natural-language
answer.

## Decision

**The recommendation cards are their own surface — the `/agent` page — driven by the newest turn's
`recommendations[]`. The transcript carries prose and a one-line pointer, nothing more.**

Concretely:

- **`/agent` route → `AgentPage`.** The page renders `SmartAgentRecommendations` (the grid) in the
  main column; the concierge rail (rendered by the shell, unchanged) holds the conversation. On
  desktop the page opens the rail on arrival, so the buyer talks on the right and products land on
  the left. On a phone the rail is a bottom sheet that would cover the grid, so it waits behind its
  launcher.
- **The recommendation state is derived, not stored twice.** `AgentRuntimeProvider` already
  publishes one `AgentTurnData` per completed run through an app-wide context. A new selector,
  `useAgentRecommendations`, projects the newest entry into `{ recommendations, status, retry }`
  where status is `idle | loading | ready | empty | error`. No second store, no reducer.
- **"Newest" is by request order, not completion order.** Each run stamps a monotonic `seq` when it
  *starts*; the selector picks `max(seq)`. Runs are serialised by the runtime today, so this only
  matters if that ever stops holding — a slow request must not repaint stale cards over a newer
  one's results. `pickLatestTurn` is a pure function with its own test.
- **The card is unchanged.** `SmartAgentRecommendations` renders the same `ProductCard` /
  `ProductGrid` the catalogue uses, via the existing `fromRecommendation` adapter. `useAddToCart`,
  its validation and the "no price in the request" rule (ADR-009) are untouched. The thin
  `features/chat/RecommendationCard.tsx` adapter, now redundant, was removed.
- **The transcript keeps the F§9 invariant.** `ChatWindow` shows the prose and, when a turn
  produced any products, a single line — *"N products in your recommendations →"* — linking to
  `/agent`. Nothing is parsed out of the prose; a turn whose `recommendations[]` is empty shows no
  pointer even if the prose names a product.
- **The system prompt gained a "Writing your reply" section** (`system_prompt.md`, version
  `1.1.0`): be brief, never emit a table or an attribute dump, name each recommended product with
  its price, say the cards are in the recommendations. This makes the agent write well; it is not a
  control — the same L§29 / ADR-009 caveat as every other prompt rule applies, and the products the
  buyer sees still come from `recommendations[]` regardless of what the prose says.

### What was rejected, and why

| Rejected | Why |
| --- | --- |
| A new `recommendations` field on the chat response, or a second endpoint | `recommendations[]` already carries exactly this, validated. A parallel contract would be two sources of the same truth. |
| Changing the backend to strip the table server-side | The prose is the model's to write (ADR-010); the fix is to ask for a better one, not to post-process it. Post-processing model output is the "helpful coercion" the LLM layer forbids. |
| Keeping the cards in the transcript *and* adding the panel | Two places rendering the same turn's products, drifting. The transcript gets a pointer, not a copy. |
| An Assistant UI tool-UI / `makeAssistantToolUI` for the cards | Rejected already in ADR-019: recommendations are not tool calls, tools run server-side, and that API is deprecated. |
| Auto-opening the rail on mobile | The sheet covers 85 dvh — it would hide the grid the buyer came to see. Desktop only; mobile summons it. |

## Consequences

**Positive.** The chat is a short conversation again. The recommendation grid gets real width and
the same multi-column card layout as the catalogue, with proper loading / empty / error states and
a retry. The recommendation state is one derived selector over state that already existed, not a new
store. The stale-request guarantee is now explicit and tested rather than incidental.

**Negative, and accepted.** This departs from the frontend UX spec's stated design (§4.2, line 517).
The spec's rationale — "a recommendation is a fact about one turn, not a standing catalog" — still
holds and is honoured: the panel shows *one turn's* results and replaces them when the conversation
moves on; it does not accumulate a catalogue. What changed is only *where* that one turn's cards are
drawn. Recorded in `deviations.md` (D8).

**Unchanged.** `GROQ_API_KEY` is not reachable from the browser. No product fact, price, ranking,
compatibility judgement or policy decision moves to the frontend. `create_order` remains absent as a
tool. The chat contract, the cart contract, the approval dialog and the order page are untouched.
Assistant UI still owns the conversation runtime and only that (ADR-019).

## Verification

Frontend: 50 tests (8 new), typecheck, eslint, production build — all green. New tests cover the
transcript carrying a pointer and not the cards, the panel rendering a card per structured
recommendation, the empty and error states, the set being replaced when the conversation moves on,
and `pickLatestTurn` choosing the newest request over the last appended.

Backend: `system_prompt` version bump and the new rule phrases asserted in `test_prompts.py`; full
no-database suite (917) green, plus the chat / llm / agent suites (407, 8 pre-existing PostgreSQL
skips).

Driven in a real browser against the seeded catalogue on port 8004: a query returned five grounded
cards in the panel at the backend's exact prices and ranking labels, the transcript showed the
prose plus the *"5 products in your recommendations →"* pointer, add-to-cart produced a
server-computed cart (`POST /api/cart/items` 200, total ₹3,697.00 from three lines), a homepage
quick-prompt navigated to `/agent` and started the turn, and Groq rate-limit / malformed-response
conditions each rendered as the designed retry state rather than a crash. The concise-prose change
itself needs the backend process restarted to load `system_prompt.md` 1.1.0 — the running instance
had 1.0.0 cached — and is verified by the prompt test rather than live.
