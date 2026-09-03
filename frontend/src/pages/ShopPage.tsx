import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Cart } from "../api/schemas";
import { CartPanel } from "../features/cart/CartPanel";
import { ChatWindow } from "../features/chat/ChatWindow";
import { AgentRuntimeProvider } from "../features/agent/AgentRuntimeProvider";
import { useAgentChat } from "../features/agent/useAgentChat";
import { ApprovalDialog } from "../features/checkout/ApprovalDialog";

/**
 * The one screen of the MVP: conversation on the left, cart on the right.
 *
 * `architecture.md` F§3 is explicit — *"For the MVP, keep the frontend small…
 * Do NOT build a large e-commerce UI. The important demonstration is:
 * conversational commerce → recommendations → cart → policy validation →
 * payment → auditability."* This is that, and nothing more.
 *
 * `AgentRuntimeProvider` wraps the screen because Assistant UI's runtime owns
 * the conversation's state, and both the transcript and the cart need the
 * `session_id` the first turn mints.
 */
export function ShopPage() {
  return (
    <AgentRuntimeProvider>
      <ShopScreen />
    </AgentRuntimeProvider>
  );
}

function ShopScreen() {
  const navigate = useNavigate();
  const { turns, pending, sessionId, send } = useAgentChat();
  const [approving, setApproving] = useState<Cart | null>(null);

  return (
    <div className="flex h-screen flex-col bg-zinc-50">
      <header className="flex items-center justify-between border-b border-zinc-200 bg-white px-4 py-3">
        <div>
          <h1 className="text-sm font-semibold text-zinc-900">CircuitCraft</h1>
          <p className="text-xs text-zinc-500">Ask for what you need — prices and stock are live.</p>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <section
          className="flex min-h-0 flex-1 flex-col border-b border-zinc-200 lg:border-b-0 lg:border-r"
          aria-label="Assistant"
        >
          <ChatWindow turns={turns} pending={pending} sessionId={sessionId} onSend={send} />
        </section>

        <aside
          className="min-h-0 shrink-0 overflow-y-auto bg-white lg:w-80 xl:w-96"
          aria-label="Cart"
        >
          <CartPanel sessionId={sessionId} onApprove={setApproving} />
        </aside>
      </div>

      {approving && sessionId && (
        <ApprovalDialog
          cart={approving}
          sessionId={sessionId}
          onClose={() => setApproving(null)}
          onOrdered={(order) => {
            setApproving(null);
            navigate(`/orders/${order.order_id}`);
          }}
        />
      )}
    </div>
  );
}
