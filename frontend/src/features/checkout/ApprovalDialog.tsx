import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { approveCart, createOrder } from "../../api/endpoints";
import { ApiRequestError } from "../../api/client";
import type { ApprovalResponse, Cart, OrderResponse } from "../../api/schemas";
import { Money } from "../../components/Money";
import { Alert, Button } from "../../components/primitives";

/**
 * The authorization step. The most load-bearing screen in the application.
 *
 * `POST /api/cart/approve` is the only path in the system that records an
 * approval (ADR-007), and it exists so the signal originates from a deliberate
 * human action rather than from a model's reading of "yeah, sure".
 *
 * Two values are submitted with it, and both are claims about **what this screen
 * displayed**, not about what the cart is now:
 *
 * - `cart_version` — the version the buyer was looking at. This is the whole
 *   stale-detection mechanism; a mismatch is a 409 rather than a silent
 *   application to whatever the cart has since become (A§26, A§27).
 * - `expected_total` — the total this screen rendered, as the same fixed-scale
 *   string it was given. Never re-derived, never parsed to a number.
 *
 * On success the backend mints an idempotency key bound to that exact state, and
 * order creation presents it. Presenting it twice yields one order (ADR-013).
 */
export function ApprovalDialog({
  cart,
  sessionId,
  onClose,
  onOrdered,
}: {
  cart: Cart;
  sessionId: string;
  onClose: () => void;
  onOrdered: (order: OrderResponse) => void;
}) {
  const queryClient = useQueryClient();
  const [approval, setApproval] = useState<ApprovalResponse | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Focus moves into the dialog, and Escape closes it. Without this a keyboard
  // user is left behind on the page underneath.
  useEffect(() => {
    dialogRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const approve = useMutation({
    mutationFn: () =>
      approveCart({
        session_id: sessionId,
        cart_version: cart.cart_version,
        expected_total: cart.total,
      }),
    onSuccess: (result) => {
      setApproval(result);
      queryClient.setQueryData(["cart", sessionId], result.cart);
    },
  });

  const place = useMutation({
    mutationFn: () => {
      if (!approval?.idempotency_key) {
        throw new Error("this approval carries no idempotency key");
      }
      return createOrder({
        session_id: sessionId,
        cart_id: cart.cart_id,
        cart_version: approval.cart_version,
        idempotency_key: approval.idempotency_key,
      });
    },
    onSuccess: onOrdered,
  });

  const failure = approve.error ?? place.error;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-title"
        tabIndex={-1}
        className="w-full max-w-md space-y-4 rounded-lg bg-white p-5 shadow-xl focus:outline-none"
      >
        <div>
          <h2 id="approval-title" className="text-base font-semibold text-zinc-900">
            Confirm your order
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            You are authorizing this exact total. Nothing is charged until you complete payment.
          </p>
        </div>

        <ul className="max-h-52 space-y-2 overflow-y-auto text-sm">
          {cart.items.map((item) => (
            <li key={item.item_id} className="flex justify-between gap-3">
              <span className="min-w-0 truncate text-zinc-700">
                {item.name} <span className="text-zinc-400">× {item.quantity}</span>
              </span>
              <Money amount={item.line_total} currency={item.currency} className="shrink-0" />
            </li>
          ))}
        </ul>

        <div className="flex items-baseline justify-between border-t border-zinc-200 pt-3">
          <span className="text-sm font-medium text-zinc-900">Total</span>
          <Money
            amount={cart.total}
            currency={cart.currency}
            className="text-lg font-semibold text-zinc-900"
          />
        </div>

        {failure && <ApprovalFailure error={failure} />}

        {approval && !place.isError && (
          <Alert tone="info" title="Approved">
            <p>
              Authorized <Money amount={approval.approved_total} currency={approval.currency} /> at
              version {approval.cart_version}.
            </p>
          </Alert>
        )}

        <div className="flex gap-2">
          <Button variant="secondary" className="flex-1" onClick={onClose}>
            Cancel
          </Button>
          {!approval ? (
            <Button
              className="flex-1"
              onClick={() => approve.mutate()}
              disabled={approve.isPending}
            >
              {approve.isPending ? "Approving…" : "Approve"}
            </Button>
          ) : (
            <Button className="flex-1" onClick={() => place.mutate()} disabled={place.isPending}>
              {place.isPending ? "Placing…" : "Place order"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Every recovery path in ADR-014 lands here, and each needs a different next
 * step. A generic "something went wrong" would tell a buyer whose cart was
 * repriced exactly nothing about what to do.
 */
function ApprovalFailure({ error }: { error: unknown }) {
  if (!(error instanceof ApiRequestError)) {
    return (
      <Alert tone="danger" title="Something went wrong">
        <p>Nothing has been charged.</p>
      </Alert>
    );
  }

  // 409 from `/cart/approve` means the cart moved under the buyer.
  if (error.status === 409) {
    return (
      <Alert tone="warning" title="The cart changed while you were reviewing it">
        <p>Close this and review the updated total — the earlier one is no longer valid.</p>
      </Alert>
    );
  }

  const byCode: Record<string, { title: string; body: string }> = {
    PRICE_CHANGED: {
      title: "The price changed",
      body: "Close this, review the new total, and approve again. Nothing has been charged.",
    },
    OUT_OF_STOCK: {
      title: "An item went out of stock",
      body: "Remove or replace it, then approve again.",
    },
    POLICY_FAILED: {
      title: "This purchase was refused",
      body: "A spending or stock rule was not satisfied. Nothing has been charged.",
    },
    APPROVAL_REQUIRED: {
      title: "Approval is needed first",
      body: "Approve the cart before placing the order.",
    },
    ORDER_CREATION_FAILED: {
      title: "The order could not be created",
      body: "Nothing has been charged. Approving again is safe — duplicate attempts create one order.",
    },
  };

  const entry = byCode[error.code] ?? {
    title: "That did not work",
    body: `${error.message} Nothing has been charged.`,
  };

  return (
    <Alert tone="danger" title={entry.title}>
      <p>{entry.body}</p>
    </Alert>
  );
}
