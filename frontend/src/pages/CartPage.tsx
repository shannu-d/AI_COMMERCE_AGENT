import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { Cart } from "../api/schemas";
import { Button, Eyebrow } from "../components/primitives";
import { CartPanel } from "../features/cart/CartPanel";
import { ApprovalDialog } from "../features/checkout/ApprovalDialog";
import { useConcierge } from "../features/concierge/conciergeContext";
import { readSessionId } from "../session";

/**
 * The cart, as a page.
 *
 * `CartPanel` already owns every cart rule — server-computed totals, price-drift
 * notices, availability — so this page is composition, not logic. The panel is
 * reused verbatim rather than reimplemented for a wider layout, because a second
 * cart implementation is a second place the money rules could be wrong.
 *
 * The right column states what happens next, in order. A buyer about to
 * authorise a payment should be able to see the whole sequence before starting
 * it, and specifically should be told that nothing is charged at approval.
 */
export function CartPage() {
  const sessionId = readSessionId();
  const [approving, setApproving] = useState<Cart | null>(null);
  const navigate = useNavigate();
  const { ask } = useConcierge();

  return (
    <div className="mx-auto max-w-shell px-4 py-10 sm:px-6">
      <nav aria-label="Breadcrumb" className="eyebrow">
        <Link to="/" className="transition-colors hover:text-ink">
          Home
        </Link>
        <span aria-hidden="true"> / </span>
        <span className="text-ink">Cart</span>
      </nav>

      <h1 className="mt-4 text-title font-medium text-ink">Your cart</h1>

      <div className="mt-8 grid gap-8 lg:grid-cols-12 lg:gap-10">
        <div className="lg:col-span-7 xl:col-span-8">
          <div className="animate-rise border border-rule bg-paper-raised">
            <CartPanel sessionId={sessionId} onApprove={setApproving} />
          </div>

          {!sessionId && (
            <div className="mt-4 flex flex-wrap gap-2">
              <Button onClick={() => ask("What do you recommend?")}>Ask the concierge</Button>
              <Button variant="secondary" onClick={() => navigate("/")}>
                Browse the catalogue
              </Button>
            </div>
          )}
        </div>

        <aside className="lg:col-span-5 xl:col-span-4">
          <div
            className="animate-rise border border-rule bg-paper-raised p-5"
            style={{ "--stagger": "80ms" } as React.CSSProperties}
          >
            <Eyebrow>What happens next</Eyebrow>
            <ol className="mt-4 space-y-4">
              {[
                {
                  title: "You approve an exact total",
                  body: "The amount is bound to this cart and this version. Nothing is charged at this step.",
                },
                {
                  title: "The server re-checks everything",
                  body: "Price and stock are read again inside the order transaction. If either moved, the order is refused and you are asked to confirm the new total.",
                },
                {
                  title: "Razorpay takes the payment",
                  body: "Only after the order exists, and only for the amount you approved.",
                },
                {
                  title: "The order is recorded",
                  body: "Every step is written to an audit log you can trace.",
                },
              ].map((step, index) => (
                <li key={step.title} className="flex gap-3">
                  <span className="tabular mt-0.5 text-2xs text-ink-faint">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span>
                    <span className="block text-sm font-medium text-ink">{step.title}</span>
                    <span className="mt-0.5 block text-2xs leading-relaxed text-ink-soft">
                      {step.body}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </aside>
      </div>

      {approving && sessionId && (
        <ApprovalDialog
          cart={approving}
          sessionId={sessionId}
          onClose={() => setApproving(null)}
          onOrdered={(order) => navigate(`/orders/${order.order_id}`)}
        />
      )}
    </div>
  );
}
