import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { cx } from "../../components/cx";
import { ConciergeContext, useConcierge } from "./conciergeContext";
import { useAgentChat } from "../agent/useAgentChat";
import { ChatWindow, ConciergeHeader } from "../chat/ChatWindow";

/**
 * The shopping concierge.
 *
 * **The architectural decision this file encodes:** the assistant is *not* a
 * floating bubble in the corner. A bubble says "chatbot bolted on" — it sits
 * above the page, belongs to nothing, and every interaction with it is a
 * departure from shopping.
 *
 * Instead it is a **docked rail**: on desktop it takes real estate beside the
 * storefront, so a conversation and the Smart Agent recommendation grid are
 * visible at once and moving between them is a glance rather than a context
 * switch. On touch, where there is no room to dock anything, it becomes a bottom
 * sheet — the native pattern for a secondary surface you summon and dismiss.
 *
 * The rail carries the conversation only. The products a turn grounded its
 * answer on render on the `/agent` page as the same `ProductCard` the catalogue
 * uses (ADR-020), so a recommendation is a storefront product that happens to
 * have arrived through a conversation.
 *
 * The whole surface is driven from one context so any page can open it — the
 * home hero, a product page's "ask about this", an empty search — and the
 * conversation survives navigation because the runtime lives above the router.
 */

export function ConciergeProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const { send } = useAgentChat();
  const navigate = useNavigate();

  const open = useCallback((prefill?: string) => {
    setOpen(true);
    if (prefill) setPending(prefill);
  }, []);
  const close = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => setOpen((v) => !v), []);

  // Sending a message takes the buyer to the Smart Agent view, where the reply
  // and the product cards it grounds land side by side (ADR-020). `open()` alone
  // — from the header or the mobile launcher — leaves them where they are.
  const ask = useCallback(
    (text: string) => {
      setOpen(true);
      setPending(text);
      navigate("/agent");
    },
    [navigate],
  );

  // A queued message is sent after the panel mounts, so the transcript is on
  // screen before the turn starts rather than appearing mid-flight.
  useEffect(() => {
    if (pending === null) return;
    const id = window.setTimeout(() => {
      send(pending);
      setPending(null);
    }, 60);
    return () => window.clearTimeout(id);
  }, [pending, send]);

  const value = useMemo(
    () => ({ isOpen, open, close, toggle, ask }),
    [isOpen, open, close, toggle, ask],
  );

  return <ConciergeContext.Provider value={value}>{children}</ConciergeContext.Provider>;
}

/**
 * The panel itself.
 *
 * Rendered once, by the shell. On desktop it participates in layout (the grid
 * column shrinks); on mobile it is a fixed sheet with a scrim.
 */
export function ConciergePanel() {
  const { isOpen, close } = useConcierge();
  const { turns, pending, send } = useAgentChat();
  const panelRef = useRef<HTMLDivElement>(null);

  // Escape closes the sheet. Only bound while open, so the storefront does not
  // carry a global key listener it has no use for.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, close]);

  if (!isOpen) return null;

  return (
    <>
      {/* Scrim, touch only. `lg:hidden` rather than a JS breakpoint check so
          there is no resize listener and no hydration mismatch. */}
      <button
        type="button"
        aria-label="Close concierge"
        onClick={close}
        className="animate-fade fixed inset-0 z-30 bg-ink/40 lg:hidden"
      />

      <aside
        ref={panelRef}
        aria-label="Shopping concierge"
        className={cx(
          // Mobile: a bottom sheet that leaves the page visible above it.
          "animate-sheet fixed inset-x-0 bottom-0 z-40 flex h-[85dvh] flex-col border-t border-ink",
          // Desktop: a docked rail in normal flow, full height, no scrim.
          "lg:animate-rail lg:sticky lg:inset-auto lg:top-0 lg:z-auto lg:h-[100dvh] lg:w-[380px]",
          "lg:shrink-0 lg:border-l lg:border-t-0 lg:border-rule xl:w-[440px]",
        )}
      >
        <ConciergeHeader onClose={close} />
        <ChatWindow turns={turns} pending={pending} onSend={send} />
      </aside>
    </>
  );
}

/**
 * The persistent way in, for every page that is not the home hero.
 *
 * Deliberately a **bar docked to the bottom on mobile** and a header control on
 * desktop, rather than a circular floating action button — an FAB reads as
 * "help widget", and this is meant to read as the way you shop here.
 */
export function ConciergeLauncher() {
  const { isOpen, open } = useConcierge();
  if (isOpen) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 p-3 lg:hidden">
      <button
        type="button"
        onClick={() => open()}
        className={cx(
          "pointer-events-auto flex w-full items-center gap-3 border border-ink bg-ink px-4 py-3",
          "text-left transition-transform duration-fast ease-out active:translate-y-px",
        )}
      >
        <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 bg-volt" />
        <span className="flex-1 text-sm text-paper/70">Ask the concierge…</span>
        <span className="eyebrow text-paper/40">AI</span>
      </button>
    </div>
  );
}
