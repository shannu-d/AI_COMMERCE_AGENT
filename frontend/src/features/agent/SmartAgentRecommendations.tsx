import { useMemo } from "react";

import type { Recommendation } from "../../api/schemas";
import { Button, Eyebrow } from "../../components/primitives";
import { cx } from "../../components/cx";
import { ProductGrid } from "../catalog/ProductCard";
import { fromRecommendation } from "../catalog/productCardData";
import { ProductGridSkeleton } from "../../pages/HomePage";
import { useAgentRecommendations, type RecommendationsStatus } from "./useAgentRecommendations";

/**
 * The Smart Agent's product-discovery area.
 *
 * The concierge answers in prose; the products it grounded that answer on render
 * here, as the ordinary `ProductCard` the rest of the storefront uses. Keeping
 * the two apart is the point (ADR-020): the chat stays a short conversation, and
 * the buyer inspects and buys from real cards rather than reading a table inside
 * a chat bubble.
 *
 * Every product still comes from `recommendations[]` on a completed turn, never
 * from the assistant's words (F§9).
 */

export function SmartAgentRecommendations() {
  const { recommendations, status, sessionId, refreshing, retry } = useAgentRecommendations();
  return (
    <RecommendationsView
      recommendations={recommendations}
      status={status}
      sessionId={sessionId}
      refreshing={refreshing}
      onRetry={retry}
    />
  );
}

export function RecommendationsView({
  recommendations,
  status,
  sessionId,
  refreshing = false,
  onRetry,
}: {
  recommendations: Recommendation[];
  status: RecommendationsStatus;
  sessionId: string | null;
  refreshing?: boolean;
  onRetry?: (() => void) | undefined;
}) {
  const items = useMemo(() => recommendations.map(fromRecommendation), [recommendations]);
  // A signature of the current set, so a changed result re-runs the entrance
  // animation while an unchanged one (a re-render) does not.
  const signature = recommendations.map((r) => r.variant_id).join("|");

  return (
    <section aria-labelledby="smart-agent-recs-heading" className="min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1
          id="smart-agent-recs-heading"
          className="text-title font-medium tracking-tight text-ink"
        >
          Smart Agent Recommendations
        </h1>
        {status === "ready" && (
          <Eyebrow aria-live="polite">
            {recommendations.length} {recommendations.length === 1 ? "product" : "products"}
          </Eyebrow>
        )}
      </div>

      <p className="mt-2 max-w-lg text-sm text-ink-soft">
        Everything the concierge finds for you appears here — compatibility, stock and price come
        from the live catalogue, never guessed.
      </p>

      <div className="mt-8">
        {status === "idle" && <DiscoveryState />}

        {status === "loading" &&
          (items.length > 0 ? (
            <div
              className="transition-opacity duration-base"
              style={{ opacity: refreshing ? 0.55 : 1 }}
              aria-busy="true"
            >
              <ProductGrid items={items} sessionId={sessionId} />
            </div>
          ) : (
            <ProductGridSkeleton count={6} />
          ))}

        {status === "empty" && <NoMatchState />}

        {status === "error" && <ErrorState onRetry={onRetry} />}

        {status === "ready" && (
          <div key={signature} className="animate-fade">
            <ProductGrid items={items} sessionId={sessionId} />
          </div>
        )}
      </div>
    </section>
  );
}

/** Before the first turn: the agent's promise, not an apology for being empty. */
function DiscoveryState() {
  return (
    <div className="animate-rise border border-rule bg-paper-raised px-6 py-14 text-center">
      <Eyebrow>Smart Agent</Eyebrow>
      <p className="mx-auto mt-3 max-w-sm text-[0.95rem] leading-relaxed text-ink">
        Tell me what you&rsquo;re looking for.
      </p>
      <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">
        Describe a device and a budget in the concierge, and the products that fit will load here.
      </p>
    </div>
  );
}

/**
 * A turn completed with no results. Not an error — a real answer.
 *
 * The copy deliberately does **not** defer to the concierge for detail. These
 * cards are built from `recommendations[]`, which comes from the ranking engine
 * over the merchant's own catalogue; the assistant's prose is not a second
 * source and is not always right about it. A live turn once named two products
 * that do not exist in the catalogue at all, and this panel correctly showed
 * nothing — telling the buyer to go back to the concierge for the details would
 * have pointed them at the one half of the screen that was wrong.
 *
 * It stops short of claiming the thing does not exist: a real product can be
 * absent here because it broke a stated budget or device requirement, which is
 * a different fact from not being stocked.
 */
function NoMatchState() {
  return (
    <div className="animate-fade border border-rule bg-paper-raised px-6 py-14 text-center">
      <Eyebrow>No matches</Eyebrow>
      <p className="mx-auto mt-3 max-w-sm text-[0.95rem] leading-relaxed text-ink">
        Nothing in the catalogue matched that search.
      </p>
      <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">
        Only products shown here have been checked against the catalogue and can be added to your
        cart. Try describing it differently, or raising the budget.
      </p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry?: (() => void) | undefined }) {
  return (
    <div className={cx("animate-fade border border-rule bg-paper-raised px-6 py-12 text-center")}>
      <Eyebrow>Recommendations unavailable</Eyebrow>
      <p className="mx-auto mt-3 max-w-sm text-[0.95rem] leading-relaxed text-ink">
        I couldn&rsquo;t load product recommendations just then.
      </p>
      <p className="mx-auto mt-1 max-w-sm text-sm text-ink-soft">
        Nothing has been charged and your cart is untouched.
      </p>
      {onRetry && (
        <Button variant="secondary" className="mt-5" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
