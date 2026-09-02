import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sendChat } from "../../api/endpoints";
import { ApiRequestError } from "../../api/client";
import type { ApiError, ChatResponse, Recommendation } from "../../api/schemas";
import { readSessionId, writeSessionId } from "../../session";

/**
 * One conversation.
 *
 * The transcript is UI state — what to draw on screen — and nothing more. It is
 * **not** a second copy of commerce truth: recommendations and the cart are held
 * as whatever the latest turn returned, and the cart query is invalidated after
 * every turn so anything that changed is re-read from the backend rather than
 * patched locally (F§5, F§29).
 *
 * Turns are strictly serialised. A second send while one is in flight would
 * interleave two `session_messages` writes and produce a transcript whose order
 * does not match the server's.
 */

export type Turn =
  | { kind: "buyer"; id: string; text: string }
  | {
      kind: "agent";
      id: string;
      text: string;
      state: ChatResponse["state"];
      recommendations: Recommendation[];
      error: ApiError | null;
    }
  | { kind: "transport-error"; id: string; text: string; retryable: boolean };

let counter = 0;
const nextId = () => `t${++counter}`;

export function useChat() {
  const queryClient = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(() => readSessionId());
  const [latestCart, setLatestCart] = useState<ChatResponse["cart"]>(null);
  const inFlight = useRef(false);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || inFlight.current) return;

      inFlight.current = true;
      setPending(true);
      setTurns((prev) => [...prev, { kind: "buyer", id: nextId(), text: message }]);

      try {
        const response = await sendChat({ session_id: readSessionId(), message });

        // The server mints the id on the first turn; every later turn echoes it.
        if (response.session_id !== readSessionId()) {
          writeSessionId(response.session_id);
          setSessionId(response.session_id);
        }

        setTurns((prev) => [
          ...prev,
          {
            kind: "agent",
            id: nextId(),
            text: response.message,
            state: response.state,
            // Products come from here and only here. Nothing is parsed out of
            // `message`: a model that describes something it was never shown
            // produces a turn whose structured half does not contain it, and
            // showing nothing is the correct rendering of that (F§9).
            recommendations: response.recommendations,
            error: response.error,
          },
        ]);
        setLatestCart(response.cart);

        // A turn may have changed the cart (`propose_cart`). Re-read rather than
        // trusting the embedded copy to stay current.
        void queryClient.invalidateQueries({ queryKey: ["cart"] });
      } catch (error) {
        // Only transport and 4xx/5xx failures land here. A policy refusal or an
        // out-of-stock finding arrives as an `error` body on a 200 and is an
        // agent turn above, not this branch (ADR-010).
        const isApi = error instanceof ApiRequestError;
        setTurns((prev) => [
          ...prev,
          {
            kind: "transport-error",
            id: nextId(),
            text: isApi ? error.message : "Something went wrong.",
            retryable: !isApi || error.code === "NETWORK_ERROR" || error.status >= 500,
          },
        ]);
      } finally {
        inFlight.current = false;
        setPending(false);
      }
    },
    [queryClient],
  );

  return { turns, pending, sessionId, latestCart, send };
}
