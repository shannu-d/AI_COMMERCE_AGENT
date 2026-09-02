import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { getOrder, startCheckout } from "../api/endpoints";
import type { OrderStatus } from "../api/schemas";
import { Money } from "../components/Money";
import { Alert, Button, Card } from "../components/primitives";
import { openCheckout } from "../features/checkout/razorpay";

/**
 * An order's state, driven entirely by the backend.
 *
 * The page **polls** rather than believing the browser. Razorpay's success
 * callback fires client-side and proves nothing; an order advances past
 * `RAZORPAY_ORDER_CREATED` only when a signature-verified webhook says so
 * (ADR-012). So after checkout closes, this re-reads the order until the backend
 * reports a settled state.
 *
 * Polling stops at a terminal state so a finished order is not queried forever.
 */
export function OrderPage() {
  const { orderId = "" } = useParams();
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  const { data: order, isPending, error, refetch } = useQuery({
    queryKey: ["order", orderId],
    queryFn: ({ signal }) => getOrder(orderId, signal),
    enabled: Boolean(orderId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return 3000;
      return isSettled(status) ? false : 3000;
    },
  });

  const pay = useMutation({
    mutationFn: async () => {
      setCheckoutError(null);
      const config = await startCheckout(orderId);
      return openCheckout(config);
    },
    onSuccess: () => {
      // Whatever the buyer did, the backend is the only thing that knows what
      // happened. Re-read; the poller takes it from here.
      void refetch();
    },
    onError: (err) => setCheckoutError(err instanceof Error ? err.message : "Checkout failed."),
  });

  if (isPending) return <Shell>Loading order…</Shell>;
  if (error || !order) return <Shell>That order could not be found.</Shell>;

  const payable = order.status === "ORDER_CREATED" || order.status === "RAZORPAY_ORDER_CREATED";

  return (
    <Shell>
      <Card className="space-y-5 p-6">
        <header className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-zinc-500">Order</p>
          <h1 className="font-mono text-sm text-zinc-900">{order.order_id}</h1>
        </header>

        <StatusBanner status={order.status} />

        <dl className="space-y-1 text-sm">
          <div className="flex justify-between text-base font-semibold">
            <dt>Total</dt>
            <dd>
              <Money amount={order.total_amount} currency={order.currency} />
            </dd>
          </div>
          {order.razorpay_order_id && (
            <div className="flex justify-between text-xs text-zinc-500">
              <dt>Provider reference</dt>
              <dd className="font-mono">{order.razorpay_order_id}</dd>
            </div>
          )}
        </dl>

        {checkoutError && (
          <Alert tone="danger" title="Could not start payment">
            <p>{checkoutError} Nothing has been charged.</p>
          </Alert>
        )}

        {payable && (
          <Button className="w-full" onClick={() => pay.mutate()} disabled={pay.isPending}>
            {pay.isPending ? "Opening payment…" : "Pay now"}
          </Button>
        )}

        <Link to="/" className="block text-center text-sm text-blue-700 hover:underline">
          Back to the assistant
        </Link>
      </Card>
    </Shell>
  );
}

function isSettled(status: OrderStatus): boolean {
  return (
    status === "PAYMENT_CONFIRMED" ||
    status === "PAYMENT_FAILED" ||
    status === "ORDER_FAILED" ||
    status === "CANCELLED"
  );
}

/**
 * One banner per order state.
 *
 * `PAYMENT_PENDING` is deliberately calm and explicitly expected: a buyer
 * watching "verifying" for ten to thirty seconds while a webhook arrives must
 * read that as normal, not as something broken (F§15).
 */
function StatusBanner({ status }: { status: OrderStatus }) {
  const map: Record<OrderStatus, { tone: "info" | "warning" | "danger"; title: string; body: string }> = {
    ORDER_CREATED: {
      tone: "info",
      title: "Ready for payment",
      body: "Your order is reserved. Nothing has been charged yet.",
    },
    RAZORPAY_ORDER_CREATED: {
      tone: "info",
      title: "Ready for payment",
      body: "Your order is reserved. Nothing has been charged yet.",
    },
    PAYMENT_PENDING: {
      tone: "warning",
      title: "Verifying your payment",
      body: "This usually takes a few seconds. This page updates itself — you can leave it open.",
    },
    PAYMENT_CONFIRMED: {
      tone: "info",
      title: "Payment confirmed",
      body: "Confirmed by the payment provider. Your order is complete.",
    },
    PAYMENT_FAILED: {
      tone: "danger",
      title: "Payment failed",
      body: "You have not been charged. You can start a new order from the assistant.",
    },
    ORDER_FAILED: {
      tone: "danger",
      title: "Order failed",
      body: "You have not been charged.",
    },
    CANCELLED: {
      tone: "warning",
      title: "Order cancelled",
      body: "You have not been charged.",
    },
  };
  const entry = map[status];
  return (
    <Alert tone={entry.tone} title={entry.title}>
      <p>{entry.body}</p>
    </Alert>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-lg p-6">{children}</main>;
}
