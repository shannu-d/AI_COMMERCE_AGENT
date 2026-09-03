import { useCallback, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { ApiRequestError } from "../../api/client";
import { sendChat } from "../../api/endpoints";
import { readSessionId, writeSessionId } from "../../session";
import { AgentTurnsContext, SessionIdContext, type AgentTurnData } from "./agentContext";

/**
 * Assistant UI supplies the *runtime* for the agent conversation — message
 * list, composer state, run lifecycle, cancellation — and nothing else.
 *
 * **Why `useLocalRuntime` with a plain `async run()` rather than a streaming
 * adapter.** `POST /api/chat` answers one JSON object per turn. There is no
 * token stream and no per-tool-call event, and that is a closed decision
 * (ADR-010; `architecture.md` F§28; the UX specification lists token streaming
 * under "should NOT be implemented"). Assistant UI supports exactly this shape:
 * an adapter whose `run` returns a single result instead of yielding. Nothing
 * here fakes a stream, and no closed decision was reopened to add one.
 *
 * **The backend stays the source of truth.** The adapter calls the same
 * Zod-validated `sendChat` the rest of the app uses, so the money rules, the
 * closed error vocabulary and the "business outcome is not a network error"
 * boundary all still apply. No product fact, price, ranking or policy decision
 * is computed here, and `GROQ_API_KEY` is not reachable from this process —
 * the browser talks to our API, which talks to Groq.
 *
 * **Structured data does not travel inside the message text.** `recommendations[]`
 * and the cart are captured per run and rendered by the existing
 * `RecommendationGrid`; the assistant's prose is the only thing that becomes
 * message content. Nothing is ever parsed back out of that prose (F§9).
 */

export function AgentRuntimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [turnData, setTurnData] = useState<AgentTurnData[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(() => readSessionId());

  // The adapter is created once. It reads the session id from storage at call
  // time rather than closing over state, so a re-render can never send a stale
  // one, and it appends through the functional setter so two runs cannot
  // clobber each other's entry.
  const append = useCallback((data: AgentTurnData) => {
    setTurnData((prev) => [...prev, data]);
  }, []);

  const inFlight = useRef(false);

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async run({ messages, abortSignal }) {
        abortSignal.throwIfAborted();

        // Only the newest buyer message is sent. The backend owns conversation
        // history in `session_messages` keyed by `session_id`; re-sending the
        // transcript would hand the model a second, client-authored copy of a
        // history the server already has (L§26).
        const last = messages[messages.length - 1];
        const text = (last?.content ?? [])
          .flatMap((part) => (part.type === "text" ? [part.text] : []))
          .join("\n")
          .trim();

        if (!text) return { content: [] };

        inFlight.current = true;
        try {
          const response = await sendChat({ session_id: readSessionId(), message: text });

          // Server-minted on the first turn; echoed thereafter.
          if (response.session_id !== readSessionId()) {
            writeSessionId(response.session_id);
            setSessionId(response.session_id);
          }

          append({
            state: response.state,
            recommendations: response.recommendations,
            error: response.error,
            transportError: null,
          });

          // A turn may have changed the cart. Re-read rather than trusting an
          // embedded copy to stay current (F§5, F§29).
          void queryClient.invalidateQueries({ queryKey: ["cart"] });

          return { content: [{ type: "text" as const, text: response.message }] };
        } catch (error) {
          // Only transport and 4xx/5xx land here. A policy refusal or an
          // out-of-stock finding arrives as `error` on an HTTP 200 and is a
          // normal turn above, never this branch (ADR-010).
          const isApi = error instanceof ApiRequestError;
          const message = isApi ? error.message : "Something went wrong.";
          append({
            state: "TOOL_ERROR",
            recommendations: [],
            error: null,
            transportError: {
              message,
              retryable: !isApi || error.code === "NETWORK_ERROR" || error.status >= 500,
            },
          });
          // Returned rather than thrown: the existing UI renders this as its
          // own retryable state, and throwing would replace that with Assistant
          // UI's generic error surface.
          return { content: [{ type: "text" as const, text: "" }] };
        } finally {
          inFlight.current = false;
        }
      },
    }),
    [append, queryClient],
  );

  const runtime = useLocalRuntime(adapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <SessionIdContext.Provider value={sessionId}>
        <AgentTurnsContext.Provider value={turnData}>{children}</AgentTurnsContext.Provider>
      </SessionIdContext.Provider>
    </AssistantRuntimeProvider>
  );
}
