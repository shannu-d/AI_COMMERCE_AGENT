import { createContext, useContext } from "react";
import type { ApiError, ChatResponse, Recommendation } from "../../api/schemas";

/**
 * The contexts the agent runtime publishes, kept apart from the provider
 * component: a module exporting both components and plain functions breaks
 * React Fast Refresh for that module.
 */

/** What one completed turn produced, beyond its prose. */
export type AgentTurnData = {
  /**
   * A monotonic id stamped when the run *starts*, so "the current
   * recommendations" is `max(seq)` rather than "last appended". Runs are already
   * serialised by the runtime, so completion order equals send order today; this
   * makes the guarantee explicit, and keeps a slow request from overwriting a
   * newer one's results if that ever stops holding.
   */
  seq: number;
  state: ChatResponse["state"];
  recommendations: Recommendation[];
  error: ApiError | null;
  /** Set when the request itself failed, rather than the turn reporting an outcome. */
  transportError: { message: string; retryable: boolean } | null;
};

export const AgentTurnsContext = createContext<AgentTurnData[]>([]);
export const SessionIdContext = createContext<string | null>(null);

/** Per-assistant-run payloads, in arrival order. */
export const useAgentTurnData = () => useContext(AgentTurnsContext);
export const useAgentSessionId = () => useContext(SessionIdContext);
