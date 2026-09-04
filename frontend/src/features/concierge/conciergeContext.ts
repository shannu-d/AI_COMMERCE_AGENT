import { createContext, useContext } from "react";

/** The concierge's control surface, kept apart from its components so React
    Fast Refresh keeps working for the panel and the launcher. */
export type ConciergeApi = {
  isOpen: boolean;
  open: (prefill?: string) => void;
  close: () => void;
  toggle: () => void;
  /** Opens the panel and sends one message — the join between page and agent. */
  ask: (text: string) => void;
};

export const ConciergeContext = createContext<ConciergeApi>({
  isOpen: false,
  open: () => {},
  close: () => {},
  toggle: () => {},
  ask: () => {},
});

export const useConcierge = () => useContext(ConciergeContext);
