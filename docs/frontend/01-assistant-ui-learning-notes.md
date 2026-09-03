# Assistant UI — learning notes

Written 2026-09-03, alongside [ADR-019](../decisions/ADR-019-assistant-ui-for-the-agent-chat-runtime.md).
This answers, in order, the eleven questions asked when the integration was commissioned. It is an
explanation, not a specification: where it disagrees with an ADR, the ADR wins.

> ⚠️ The sibling document `00-architecture-and-ux-specification.md` opens by stating that Groq is
> **not** the provider and Anthropic is. **That paragraph is out of date.** It was written before the
> owner reversed the decision; [ADR-018](../decisions/ADR-018-groq-as-the-locked-llm-provider.md)
> makes Groq the locked provider. Everything else in that document still stands.

---

## 1. What is Assistant UI?

A React library for building assistant/chat interfaces. It ships two separable things:

- **A runtime** — the state layer that owns the message list, the composer's contents, which run is
  in flight, and how to cancel it.
- **Headless UI primitives** — `ThreadPrimitive`, `ComposerPrimitive`, `MessagePrimitive` — unstyled
  building blocks that read from that runtime.

The two are independent. You can adopt the runtime and render the conversation yourself, which is
exactly what this project does.

## 2. Why we chose it (and what we deliberately did not take)

The owner asked for it. The audit's honest finding was that Assistant UI's *headline* features —
token streaming, tool-call rendering, multi-thread management — are all unavailable here:
`POST /api/chat` returns one JSON object per turn and streaming is a closed decision (ADR-010), the
frontend never sees individual tool calls, and a session is a single anonymous conversation.

So we took the part that carries its weight — the runtime — and kept the tested UI we already had.
The alternatives (rewriting the transcript into Assistant UI primitives; adding streaming so the
library's features apply) were put to the owner and declined. That is recorded in ADR-019.

## 3. What Assistant UI owns

Only the conversation's client-side state:

- the ordered list of user and assistant messages
- the composer (what is typed, whether it can be submitted)
- the run lifecycle: a run is in flight, it finished, it was aborted

## 4. What our backend owns

Everything that is true about commerce:

catalog facts · compatibility resolution · inventory · ranking and every score · cart contents and
every total · approvals · policy decisions · order state · payment truth · the audit log · which
tools exist and when they run · the conversation history in `session_messages`.

The frontend renders what the backend returned. It never computes a price, never sums a total, never
decides whether a product fits a device, and never authorizes money.

## 5. How the runtime works

```
useLocalRuntime(adapter)  →  AssistantRuntimeProvider  →  components read the runtime
```

`useLocalRuntime` keeps message state inside the runtime and calls **our adapter** whenever a run
starts. The adapter is one object with one method:

```ts
const adapter: ChatModelAdapter = {
  async run({ messages, abortSignal }) {
    const response = await sendChat({ session_id: readSessionId(), message: latestUserText });
    return { content: [{ type: "text", text: response.message }] };
  },
};
```

That `async run()` returning a **single object** — rather than an `async *run()` generator that
yields — is the officially documented non-streaming pattern. It is what makes Assistant UI fit a
backend that answers once per turn.

Our adapter lives in `frontend/src/features/agent/AgentRuntimeProvider.tsx`.

## 6. How the frontend talks to the backend

Unchanged from before the integration, which was the point:

```
browser → fetch → request() in src/api/client.ts → POST /api/chat → FastAPI
```

`request()` still parses every response through its Zod schema, so contract drift is a loud
`MALFORMED_RESPONSE` at the boundary. The adapter calls `sendChat` from `src/api/endpoints.ts` —
it did not open a second, unvalidated path to the API.

Only the newest buyer message is sent. The backend owns history in `session_messages`, keyed by
`session_id`; re-sending the transcript would hand the model a second, client-authored copy of a
history the server already has.

## 7. How streaming works

**It does not, and that is deliberate.** There is no token streaming anywhere in this system.

What the buyer sees during a turn is a single bounded "Thinking…" indicator, driven by the runtime's
`isRunning` flag. It reflects *that* a turn is in flight, never *what stage* it has reached, because
the frontend genuinely does not know — the trace, when enabled, arrives only after the turn is over.
Showing "Searching catalog…" would be inventing information.

Reintroducing streaming would mean superseding ADR-010, which is a backend architectural decision,
not a frontend styling choice.

## 8. How tool calls are represented

**They are not represented in the frontend at all.**

Assistant UI has a toolkit API for tools the *browser* executes and renders. Ours run entirely
server-side, behind the boundary: the model proposes a tool call, the backend's executor validates
and runs it against the trusted services, and the frontend receives only the finished turn. The
older `makeAssistantToolUI` API is in any case deprecated in current Assistant UI.

`create_order` is not a tool at all, in either layer (ADR-009).

## 9. How structured product cards are rendered

Not through Assistant UI. The turn's prose becomes the message content; `recommendations[]` is
captured separately by the adapter and rendered by the existing `RecommendationGrid` below the
message.

This preserves the rule that matters most in this UI (F§9): **a product appears on screen only
because the ranking engine returned it.** If the model writes a paragraph about a product that is
not in `recommendations[]`, no card appears — there is a test asserting exactly that.

Every card field comes from the response contract. Note there is **no product image** in
`Recommendation`; the frontend does not invent one, and the UX specification forbids fabricating card
fields.

## 10. How Groq stays behind the backend

```
browser → our FastAPI backend → app/llm/client.py → Groq
```

The browser has no idea which provider is in use; a chat request carries no provider name. Groq is
reached from exactly one backend module, and `GROQ_API_KEY` is read there and nowhere else
(ADR-018). Adding Assistant UI changed none of this — its adapter calls *our* API, not a model API.

Assistant UI's default examples use the Vercel AI SDK with OpenAI. We use none of that: no `ai`
package, no `@ai-sdk/*`, no provider SDK in the browser.

## 11. Why API keys are never exposed in the browser

Anything the browser can read, a user can read. There is no such thing as a secret in a frontend
bundle.

Vite makes this sharper: it **inlines** every `VITE_`-prefixed variable into the built JavaScript at
build time. A `VITE_GROQ_API_KEY` would not be "configuration" — it would be a published credential,
readable in DevTools by anyone who loads the page, and permanently baked into every deployed asset.

So the only credential that ever reaches this browser is the **public** Razorpay key id, which is
public by design and arrives in a response body at checkout time rather than from configuration.
`GROQ_API_KEY`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` stay on the server. A backend
test (`tests/api/test_frontend_contract.py`) fails the build if a secret-bearing name appears in
frontend source.

---

## The shape of the whole thing

```
buyer
  ↓  types into the composer
Assistant UI runtime            ← owns messages, composer, run lifecycle
  ↓  calls our ChatModelAdapter
src/api/client.ts (Zod)         ← validates every response
  ↓  POST /api/chat
FastAPI → agent runtime         ← owns tools, history, the boundary
  ↓
Groq (openai/gpt-oss-120b)      ← proposes; never decides
  ↓
catalog · compatibility · inventory · ranking · cart · policy · Razorpay
```

The library sits at the top of that stack and knows nothing about the rest of it. That is the
integration working as intended.
