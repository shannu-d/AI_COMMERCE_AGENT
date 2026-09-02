import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getCart, removeCartItem, updateCartItem } from "../../api/endpoints";
import { ApiRequestError } from "../../api/client";
import type { Cart, PriceChange } from "../../api/schemas";
import { Money } from "../../components/Money";
import { Alert, Button, StockBadge } from "../../components/primitives";

/**
 * The cart.
 *
 * Every amount shown is a field the backend computed. This component has no
 * `reduce` over line totals and no quantity × price anywhere: the subtotal and
 * total are read from the response, and after any mutation the response that
 * comes back *is* the new cart (F§12, F§29).
 */
export function CartPanel({
  sessionId,
  onApprove,
}: {
  sessionId: string | null;
  onApprove: (cart: Cart) => void;
}) {
  const queryClient = useQueryClient();

  const { data: cart, isPending, error } = useQuery({
    queryKey: ["cart", sessionId],
    queryFn: ({ signal }) => getCart(sessionId!, signal),
    enabled: Boolean(sessionId),
    // A 404 means "no cart yet", which is a normal empty state rather than a
    // failure worth retrying.
    retry: (count, err) => !(err instanceof ApiRequestError && err.status === 404) && count < 1,
  });

  const setQuantity = useMutation({
    mutationFn: ({ itemId, quantity }: { itemId: string; quantity: number }) =>
      updateCartItem(itemId, { session_id: sessionId!, quantity }),
    onSuccess: (next) => queryClient.setQueryData(["cart", sessionId], next),
  });

  const remove = useMutation({
    mutationFn: (itemId: string) => removeCartItem(itemId, sessionId!),
    onSuccess: (next) => queryClient.setQueryData(["cart", sessionId], next),
  });

  if (!sessionId) return <Aside>Start a conversation to build a cart.</Aside>;
  if (isPending) return <Aside>Loading…</Aside>;
  if (error instanceof ApiRequestError && error.status === 404) return <Aside>Your cart is empty.</Aside>;
  if (error) return <Aside>Could not load the cart.</Aside>;
  if (!cart || cart.items.length === 0) return <Aside>Your cart is empty.</Aside>;

  const busy = setQuantity.isPending || remove.isPending;
  const unavailable = cart.items.some((item) => !item.available);

  return (
    <div className="flex min-h-0 flex-col">
      <header className="flex items-baseline justify-between border-b border-zinc-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-900">Cart</h2>
        {/* Shown because an approval binds to it, and a stale version is the
            thing the buyer will be told about if it moves under them. */}
        <span className="text-xs text-zinc-400">v{cart.cart_version}</span>
      </header>

      {cart.price_changes.length > 0 && <PriceChangeNotice changes={cart.price_changes} />}

      <ul className="flex-1 divide-y divide-zinc-100 overflow-y-auto">
        {cart.items.map((item) => (
          <li key={item.item_id} className="space-y-2 p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-zinc-900">{item.name}</p>
                <p className="truncate text-xs text-zinc-500">{item.variant_name}</p>
              </div>
              <Money
                amount={item.line_total}
                currency={item.currency}
                className="shrink-0 text-sm font-semibold"
              />
            </div>

            <div className="flex items-center gap-2">
              <label className="sr-only" htmlFor={`qty-${item.item_id}`}>
                Quantity for {item.name}
              </label>
              <select
                id={`qty-${item.item_id}`}
                value={item.quantity}
                disabled={busy}
                onChange={(event) =>
                  setQuantity.mutate({
                    itemId: item.item_id,
                    quantity: Number(event.target.value),
                  })
                }
                className="rounded border border-zinc-300 px-2 py-1 text-xs"
              >
                {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              <span className="text-xs text-zinc-400">
                <Money amount={item.unit_price} currency={item.currency} /> each
              </span>
              {!item.available && <StockBadge status="OUT_OF_STOCK" />}
              <Button
                variant="ghost"
                className="ml-auto px-2 py-1 text-xs"
                disabled={busy}
                onClick={() => remove.mutate(item.item_id)}
              >
                Remove
              </Button>
            </div>
          </li>
        ))}
      </ul>

      <footer className="space-y-3 border-t border-zinc-200 p-4">
        <dl className="space-y-1 text-sm">
          <div className="flex justify-between text-zinc-500">
            <dt>Subtotal</dt>
            <dd>
              <Money amount={cart.subtotal} currency={cart.currency} />
            </dd>
          </div>
          <div className="flex justify-between text-base font-semibold text-zinc-900">
            <dt>Total</dt>
            <dd>
              <Money amount={cart.total} currency={cart.currency} />
            </dd>
          </div>
        </dl>

        {unavailable && (
          <Alert tone="warning" title="An item is unavailable">
            <p>Remove it before continuing.</p>
          </Alert>
        )}

        <Button className="w-full" onClick={() => onApprove(cart)} disabled={busy || unavailable}>
          Review and approve
        </Button>
      </footer>
    </div>
  );
}

/**
 * ADR-014: a price change in **either** direction invalidates an approval.
 *
 * A cheaper cart is still not the cart the buyer agreed to, so a decrease is
 * surfaced just as prominently as an increase rather than being quietly
 * accepted as good news.
 */
function PriceChangeNotice({ changes }: { changes: PriceChange[] }) {
  return (
    <div className="border-b border-amber-200 bg-amber-50 p-4">
      <p className="text-sm font-medium text-amber-900">
        {changes.length === 1 ? "A price changed" : `${changes.length} prices changed`}
      </p>
      <ul className="mt-1 space-y-0.5 text-xs text-amber-800">
        {changes.map((change) => (
          <li key={change.sku}>
            {change.name}: <Money amount={change.previous_unit_price} /> →{" "}
            <Money amount={change.current_unit_price} />{" "}
            {change.increased ? "(increased)" : "(decreased)"}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-amber-800">
        Any earlier approval no longer applies. Confirm the new total to continue.
      </p>
    </div>
  );
}

function Aside({ children }: { children: React.ReactNode }) {
  return <p className="p-4 text-sm text-zinc-500">{children}</p>;
}
