import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiRequestError } from "../../api/client";
import { getCart, removeCartItem, updateCartItem } from "../../api/endpoints";
import type { Cart, PriceChange } from "../../api/schemas";
import { Money } from "../../components/Money";
import { cx } from "../../components/cx";
import { Alert, Button, Eyebrow, Skeleton, StockBadge } from "../../components/primitives";
import { SpecMark } from "../../design/SpecMark";

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

  const {
    data: cart,
    isPending,
    error,
  } = useQuery({
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
  if (isPending) return <CartSkeleton />;
  if (error instanceof ApiRequestError && error.status === 404)
    return <Aside>Your cart is empty.</Aside>;
  if (error) return <Aside>Could not load the cart.</Aside>;
  if (!cart || cart.items.length === 0) return <Aside>Your cart is empty.</Aside>;

  const busy = setQuantity.isPending || remove.isPending;
  const unavailable = cart.items.some((item) => !item.available);

  return (
    <div className="flex min-h-0 flex-col">
      <header className="flex items-baseline justify-between border-b border-rule px-4 py-3">
        <h2 className="text-sm font-medium text-ink">Cart</h2>
        {/* Shown because an approval binds to it, and a stale version is the
            thing the buyer will be told about if it moves under them. */}
        <span className="eyebrow tabular">v{cart.cart_version}</span>
      </header>

      {cart.price_changes.length > 0 && <PriceChangeNotice changes={cart.price_changes} />}

      <ul className={cx("scroll-quiet flex-1 overflow-y-auto", busy && "opacity-60")}>
        {cart.items.map((item) => (
          <li key={item.item_id} className="border-b border-rule/60 p-4 last:border-0">
            <div className="flex gap-3">
              <span className="h-12 w-12 shrink-0 border border-rule bg-paper-sunken">
                <SpecMark sku={item.sku} category="default" />
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{item.name}</p>
                    <p className="tabular truncate text-2xs text-ink-faint">
                      {item.variant_name} · {item.sku}
                    </p>
                  </div>
                  <Money
                    amount={item.line_total}
                    currency={item.currency}
                    className="tabular shrink-0 text-sm font-medium"
                  />
                </div>

                <div className="mt-2.5 flex flex-wrap items-center gap-2">
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
                    className="tabular h-8 border border-rule bg-paper-raised px-2 text-2xs text-ink transition-colors duration-fast hover:border-ink focus:border-ink focus:outline-none"
                  >
                    {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                  <span className="tabular text-2xs text-ink-faint">
                    <Money amount={item.unit_price} currency={item.currency} /> each
                  </span>
                  {!item.available && <StockBadge status="OUT_OF_STOCK" />}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    disabled={busy}
                    onClick={() => remove.mutate(item.item_id)}
                  >
                    Remove
                  </Button>
                </div>
              </div>
            </div>
          </li>
        ))}
      </ul>

      <footer className="space-y-3 border-t border-rule p-4">
        <dl className="space-y-1.5">
          <div className="flex justify-between text-sm text-ink-soft">
            <dt>Subtotal</dt>
            <dd className="tabular">
              <Money amount={cart.subtotal} currency={cart.currency} />
            </dd>
          </div>
          <div className="flex items-baseline justify-between border-t border-rule pt-2">
            <dt className="text-sm font-medium text-ink">Total</dt>
            <dd className="tabular text-lg font-medium text-ink">
              <Money amount={cart.total} currency={cart.currency} />
            </dd>
          </div>
        </dl>

        <p className="text-2xs leading-relaxed text-ink-faint">
          Computed by the server from the live catalogue. Re-checked before any payment is taken.
        </p>

        {unavailable && (
          <Alert tone="caution" title="An item is unavailable">
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
    <div className="border-b border-caution/25 bg-caution-bg p-4">
      <p className="text-sm font-medium text-caution">
        {changes.length === 1 ? "A price changed" : `${changes.length} prices changed`}
      </p>
      <ul className="mt-1.5 space-y-1 text-2xs text-caution">
        {changes.map((change) => (
          <li key={change.sku} className="tabular">
            {change.name}: <Money amount={change.previous_unit_price} /> →{" "}
            <Money amount={change.current_unit_price} />{" "}
            {change.increased ? "(increased)" : "(decreased)"}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-2xs text-caution">
        Any earlier approval no longer applies. Confirm the new total to continue.
      </p>
    </div>
  );
}

function CartSkeleton() {
  return (
    <div className="space-y-3 p-4" aria-hidden="true">
      {[0, 1].map((i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="h-12 w-12 shrink-0" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        </div>
      ))}
    </div>
  );
}

function Aside({ children }: { children: React.ReactNode }) {
  return (
    <div className="p-6">
      <Eyebrow>Cart</Eyebrow>
      <p className="mt-2 text-sm text-ink-soft">{children}</p>
    </div>
  );
}
