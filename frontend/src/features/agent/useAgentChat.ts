import { useMemo } from "react";
import { useAui, useAuiState } from "@assistant-ui/react";
import type { Turn } from "../chat/useChat";
import { useAgentSessionId, useAgentTurnData } from "./agentContext";

/**
 * Adapts Assistant UI's thread state to the shape `ChatWindow` already renders.
 *
 * The runtime owns the messages; this only projects them. Assistant UI messages
 * carry the prose, and `useAgentTurnData()` carries what each completed run
 * returned alongside it — the structured half, which must never be recovered by
 * parsing the prose (F§9). The two are zipped by position: one assistant
 * message per run, appended in the same order.
 */
export function useAgentChat() {
  const messages = useAuiState((s) => s.thread.messages);
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const turnData = useAgentTurnData();
  const sessionId = useAgentSessionId();
  const aui = useAui();

  const turns = useMemo<Turn[]>(() => {
    let assistantIndex = 0;
    const out: Turn[] = [];

    for (const message of messages) {
      const text = message.content
        .flatMap((part) => (part.type === "text" ? [part.text] : []))
        .join("\n");

      if (message.role === "user") {
        out.push({ kind: "buyer", id: message.id, text });
        continue;
      }
      if (message.role !== "assistant") continue;

      const data = turnData[assistantIndex];
      assistantIndex += 1;
      if (!data) continue;

      if (data.transportError) {
        out.push({
          kind: "transport-error",
          id: message.id,
          text: data.transportError.message,
          retryable: data.transportError.retryable,
        });
        continue;
      }

      out.push({
        kind: "agent",
        id: message.id,
        text,
        state: data.state,
        recommendations: data.recommendations,
        error: data.error,
      });
    }
    return out;
  }, [messages, turnData]);

  const send = (text: string) => {
    const message = text.trim();
    // The runtime serialises runs itself; guarding on `isRunning` additionally
    // keeps a second send from queueing a turn the backend would interleave in
    // `session_messages`.
    if (!message || isRunning) return;
    aui.thread.append({ role: "user", content: [{ type: "text", text: message }] });
  };

  return { turns, pending: isRunning, sessionId, send };
}
