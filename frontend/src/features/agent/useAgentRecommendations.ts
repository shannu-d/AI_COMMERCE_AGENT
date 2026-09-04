import { useMemo } from "react";
import { useAuiState } from "@assistant-ui/react";

import type { Recommendation } from "../../api/schemas";
import { useAgentChat } from "./useAgentChat";
import { useAgentSessionId, useAgentTurnData, type AgentTurnData } from "./agentContext";

/**
 * The recommendation surface's state, derived from the agent conversation.
 *
 * **Separate from the transcript, same source of truth.** Products still come
 * only from `recommendations[]` on a completed turn (F§9) — this hook just
 * projects the newest turn's array into a standalone panel instead of embedding
 * it in the chat message it arrived with (ADR-020). Nothing is parsed out of the
 * assistant's prose.
 *
 * **"Newest" means newest request, not newest response.** Runs are serialised by
 * the runtime, so today those are the same; picking `max(seq)` keeps a slow
 * request from painting stale cards over a newer one's results if that ever
 * changes.
 */

export type RecommendationsStatus = "idle" | "loading" | "ready" | "empty" | "error";

/**
 * The turn whose results the panel should show: newest *request*, by `seq`.
 *
 * Not `turnData.at(-1)` — that is newest *completion*. They match while runs are
 * serialised, but if a slow request ever finishes after a newer one, last-appended
 * would be the stale one. Picking `max(seq)` makes the newer request win.
 */
export function pickLatestTurn(
  turnData: readonly AgentTurnData[],
): AgentTurnData | undefined {
  return turnData.reduce<AgentTurnData | undefined>(
    (best, entry) => (best === undefined || entry.seq > best.seq ? entry : best),
    undefined,
  );
}

export type AgentRecommendationsState = {
  /** The products to show. Empty for every status except `ready` and `loading`. */
  recommendations: Recommendation[];
  status: RecommendationsStatus;
  sessionId: string | null;
  /** True while a turn is in flight and there are prior results still on screen. */
  refreshing: boolean;
  /** Re-sends the last buyer message. No-op if there is nothing to retry. */
  retry: () => void;
};

export function useAgentRecommendations(): AgentRecommendationsState {
  const turnData = useAgentTurnData();
  const sessionId = useAgentSessionId();
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const { turns, send } = useAgentChat();

  const latest = useMemo(() => pickLatestTurn(turnData), [turnData]);

  const lastBuyerText = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const turn = turns[i];
      if (turn?.kind === "buyer") return turn.text;
    }
    return null;
  }, [turns]);

  return useMemo<AgentRecommendationsState>(() => {
    const retry = () => {
      if (lastBuyerText) send(lastBuyerText);
    };

    // A run is in flight: keep whatever is already on screen and mark it stale,
    // rather than blanking the panel (a layout jump on every message).
    if (isRunning) {
      return {
        recommendations: latest?.recommendations ?? [],
        status: "loading",
        sessionId,
        refreshing: (latest?.recommendations.length ?? 0) > 0,
        retry,
      };
    }

    if (latest === undefined) {
      return { recommendations: [], status: "idle", sessionId, refreshing: false, retry };
    }

    if (latest.transportError !== null || latest.error !== null) {
      return { recommendations: [], status: "error", sessionId, refreshing: false, retry };
    }

    if (latest.recommendations.length === 0) {
      return { recommendations: [], status: "empty", sessionId, refreshing: false, retry };
    }

    return {
      recommendations: latest.recommendations,
      status: "ready",
      sessionId,
      refreshing: false,
      retry,
    };
  }, [isRunning, latest, sessionId, lastBuyerText, send]);
}
