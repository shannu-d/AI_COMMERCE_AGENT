import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { getMyOrders } from "../api/endpoints";
import type { OrderStatus } from "../api/schemas";
import { Money } from "../components/Money";
import { Alert, Button, Eyebrow, Plate, Skeleton } from "../components/primitives";
import { useAuth } from "../auth/context";

/**
 * The signed-in customer's account: who they are, and what they have bought.
 *
 * The order list comes from `/api/account/orders`, which derives ownership from
 * the session join rather than from anything this page could send (ADR-023 §2).
 * There is no customer id in the request, so there is none to get wrong.
 *
 * Statuses are shown exactly as the backend reports them. `PAYMENT_CONFIRMED`
 * appears only when a signature-verified webhook has said so (ADR-012) — this
 * page never infers that a payment succeeded.
 */
export function AccountPage() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  const { data, isPending, error } = useQuery({
    queryKey: ["account", "orders"],
    queryFn: ({ signal }) => getMyOrders(signal),
    enabled: Boolean(user),
  });

  if (!user) return null; // `RequireCustomer` has already redirected.

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-12">
      <Eyebrow>Account</Eyebrow>
      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-display text-2xl text-ink">{user.display_name || user.email}</h1>
        <Button
          variant="secondary"
          size="sm"
          onClick={async () => {
            await signOut();
            navigate("/");
          }}
        >
          Sign out
        </Button>
      </div>
      <p className="mt-1 text-sm text-ink-soft">{user.email}</p>

      <h2 className="mt-10 font-display text-lg text-ink">Orders</h2>

      {isPending && (
        <div className="mt-4 space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {error && (
        <div className="mt-4">
          <Alert title="Could not load your orders">
            {error instanceof Error ? error.message : "Please try again."}
          </Alert>
        </div>
      )}

      {data && data.items.length === 0 && (
        <Plate className="mt-4 p-6 text-sm text-ink-soft">
          Nothing yet.{" "}
          <Link to="/" className="text-ink underline hover:text-volt-ink">
            Start browsing
          </Link>
          .
        </Plate>
      )}

      {data && data.items.length > 0 && (
        <ul className="mt-4 divide-y divide-rule border-y border-rule">
          {data.items.map((order) => (
            <li key={order.order_id}>
              <Link
                to={`/orders/${order.order_id}`}
                className="flex items-center justify-between gap-4 py-4 transition-colors duration-fast hover:bg-paper-sunken"
              >
                <div className="min-w-0">
                  <p className="truncate font-mono text-2xs text-ink-faint">{order.order_id}</p>
                  <p className="mt-0.5 text-sm text-ink">{label(order.status)}</p>
                </div>
                <p className="shrink-0 text-sm font-medium text-ink">
                  <Money amount={order.total_amount} currency={order.currency} />
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The backend's vocabulary, in plain words. No status is invented or merged. */
function label(status: OrderStatus): string {
  const words: Record<string, string> = {
    ORDER_CREATED: "Awaiting payment",
    RAZORPAY_ORDER_CREATED: "Awaiting payment",
    PAYMENT_PENDING: "Payment pending",
    PAYMENT_CONFIRMED: "Paid",
    PAYMENT_FAILED: "Payment failed",
    CANCELLED: "Cancelled",
  };
  return words[status] ?? status;
}
