import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addCartItem } from "../../api/endpoints";
import type { Recommendation } from "../../api/schemas";
import { Money } from "../../components/Money";
import { Button, Card, StockBadge } from "../../components/primitives";
import { cx } from "../../components/cx";

/**
 * One product, rendered from structured data.
 *
 * Every field here came from `recommendations[]` — the ranking engine's own
 * output. In particular `reason` is the engine's deterministic label, not a
 * sentence the model wrote about arithmetic it did not perform (ADR-004, A7).
 *
 * The price is displayed, never recomputed, and there is deliberately no
 * "was/now" or discount arithmetic: this UI has no authority to assert either.
 */
export function RecommendationCard({
  recommendation,
  sessionId,
  onAdded,
}: {
  recommendation: Recommendation;
  sessionId: string | null;
  onAdded?: () => void;
}) {
  const queryClient = useQueryClient();
  const outOfStock = recommendation.stock_status === "OUT_OF_STOCK";

  const add = useMutation({
    mutationFn: () =>
      addCartItem({
        session_id: sessionId!,
        // A lookup key the backend resolves. The client never sends a price:
        // no endpoint in this system accepts one (ADR-009).
        variant_id: recommendation.variant_id,
        quantity: 1,
      }),
    onSuccess: (cart) => {
      queryClient.setQueryData(["cart", sessionId], cart);
      onAdded?.();
    },
  });

  const attributes = Object.entries(recommendation.attributes)
    .filter(([, value]) => value !== null && value !== "")
    .slice(0, 4);

  return (
    <Card className={cx("flex flex-col gap-3 p-4", outOfStock && "opacity-70")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-zinc-900">{recommendation.name}</h3>
          <p className="truncate text-xs text-zinc-500">
            {recommendation.variant_name} · {recommendation.sku}
          </p>
        </div>
        <span
          className="shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-medium text-zinc-600"
          aria-label={`Ranked ${recommendation.rank}`}
        >
          #{recommendation.rank}
        </span>
      </div>

      <div className="flex items-baseline gap-2">
        <Money
          amount={recommendation.price}
          currency={recommendation.currency}
          className="text-lg font-semibold text-zinc-900"
        />
        <StockBadge status={recommendation.stock_status} />
      </div>

      {/* The engine's own words for why this ranked where it did. */}
      <p className="text-sm text-zinc-600">{recommendation.reason}</p>

      {attributes.length > 0 && (
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
          {attributes.map(([key, value]) => (
            <div key={key} className="flex gap-1">
              <dt className="capitalize">{key.replace(/_/g, " ")}:</dt>
              <dd className="font-medium text-zinc-700">{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-auto flex items-center gap-2 pt-1">
        <Button
          onClick={() => add.mutate()}
          disabled={outOfStock || add.isPending || !sessionId}
          className="flex-1"
        >
          {add.isPending ? "Adding…" : outOfStock ? "Unavailable" : "Add to cart"}
        </Button>
      </div>

      {add.isError && (
        <p role="alert" className="text-xs text-red-700">
          {add.error instanceof Error ? add.error.message : "Could not add this item."}
        </p>
      )}
    </Card>
  );
}

export function RecommendationGrid({
  recommendations,
  sessionId,
}: {
  recommendations: Recommendation[];
  sessionId: string | null;
}) {
  if (recommendations.length === 0) return null;
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {recommendations.map((recommendation) => (
        <li key={recommendation.variant_id} className="flex">
          <RecommendationCard
            recommendation={recommendation}
            sessionId={sessionId}
            // The card writes the cart into the query cache itself; this hook is
            // for anything the parent wants to do as well.
          />
        </li>
      ))}
    </ul>
  );
}
