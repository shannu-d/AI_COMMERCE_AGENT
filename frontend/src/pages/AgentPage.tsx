import { useEffect } from "react";

import { SmartAgentRecommendations } from "../features/agent/SmartAgentRecommendations";
import { useConcierge } from "../features/concierge/conciergeContext";

/**
 * Smart Agent — the dedicated product-discovery view.
 *
 * Two panes: this page holds the recommendation grid, and the concierge rail
 * (rendered by the shell) holds the conversation. Opening the rail on arrival is
 * the whole point of the page — the buyer talks on the right, the products land
 * on the left (ADR-020).
 *
 * Only on desktop, where the rail is a docked column beside the grid. On a phone
 * the rail is a bottom sheet that would cover the recommendations the buyer came
 * to see, so it stays behind its launcher until they summon it.
 */
export function AgentPage() {
  const { open } = useConcierge();

  useEffect(() => {
    const desktop =
      typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches;
    if (desktop) open();
  }, [open]);

  return (
    <div className="mx-auto max-w-shell px-4 py-10 sm:px-6">
      <SmartAgentRecommendations />
    </div>
  );
}
