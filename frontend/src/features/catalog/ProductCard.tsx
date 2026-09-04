import { Link } from "react-router-dom";

import { Money } from "../../components/Money";
import { cx } from "../../components/cx";
import { formatAttrValue } from "../../components/formatAttrValue";
import { Button, Plate, SpecRow, StockBadge } from "../../components/primitives";
import { SpecMark } from "../../design/SpecMark";
import { readSessionId } from "../../session";
import type { ProductCardData } from "./productCardData";
import { useAddToCart } from "./useAddToCart";

/**
 * One product, rendered from structured data — the single card in this app.
 *
 * **Why one component for two sources.** A product reaches the UI two ways: the
 * buyer browsed to it, or the agent recommended it. If those rendered
 * differently, the concierge would look like a separate widget grafted onto a
 * shop. Rendering both through this component is most of what makes the
 * assistant feel native — an agent result *is* a storefront product, because it
 * is literally the same row of the same table.
 *
 * The only difference a recommendation carries is provenance: a rank and the
 * ranking engine's own `reason`. Those render as an extra rail, never as a
 * different card.
 *
 * Nothing here computes a commerce fact. The price is displayed, never
 * recomputed; there is no "was/now" or discount arithmetic, because this UI has
 * no authority to assert either (ADR-008, F§12).
 */

export function ProductCard({
  item,
  stagger = 0,
  className,
  sessionId: sessionIdOverride,
}: {
  item: ProductCardData;
  /** Index in a list; drives the CSS entrance delay. */
  stagger?: number;
  className?: string;
  sessionId?: string | null | undefined;
}) {
  const outOfStock = item.stockStatus === "OUT_OF_STOCK";
  const add = useAddToCart(item, sessionIdOverride);
  const sessionId = sessionIdOverride ?? readSessionId();

  const specs = Object.entries(item.attributes)
    .filter(([, value]) => value !== null && value !== "")
    .slice(0, 3);

  const title = (
    <>
      <h3 className="text-[0.95rem] font-medium leading-tight text-ink">{item.name}</h3>
      <p className="tabular mt-0.5 text-2xs text-ink-faint">
        {item.variantName} · {item.sku}
      </p>
    </>
  );

  return (
    <Plate
      interactive
      className={cx("group animate-rise flex h-full flex-col", className)}
      style={{ "--stagger": `${Math.min(stagger, 10) * 45}ms` } as React.CSSProperties}
    >
      {/* The mark. Derived from the SKU, so a product is recognisable across the
          listing, the cart and the concierge without any image existing. */}
      <div className="relative aspect-[4/3] overflow-hidden border-b border-rule bg-paper-sunken">
        <div className="absolute inset-0 transition-transform duration-base ease-out group-hover:scale-[1.04] motion-reduce:group-hover:scale-100">
          <SpecMark sku={item.sku} category={item.category} />
        </div>

        {item.rank !== undefined && (
          <span
            className="tabular absolute left-0 top-0 bg-ink px-2 py-1 text-2xs text-paper"
            aria-label={`Ranked ${item.rank}`}
          >
            #{item.rank}
          </span>
        )}
        <span className="eyebrow absolute bottom-2 right-2 text-ink-faint">
          {item.category.replace(/_/g, " ")}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="min-w-0">
          {item.productSlug ? (
            <Link
              to={`/p/${item.productSlug}`}
              className="block outline-offset-4 after:absolute after:inset-0 after:content-['']"
            >
              {title}
            </Link>
          ) : (
            title
          )}
        </div>

        <div className="flex items-baseline justify-between gap-2">
          <Money
            amount={item.price}
            currency={item.currency}
            className="tabular text-[1.05rem] font-medium text-ink"
          />
          <StockBadge status={item.stockStatus} />
        </div>

        {/* The engine's own words for why this ranked where it did — never a
            sentence the model wrote about arithmetic it did not perform. */}
        {item.reason && (
          <p className="border-l border-volt pl-2 text-2xs leading-relaxed text-ink-soft">
            {item.reason}
          </p>
        )}

        {specs.length > 0 && (
          <dl className="mt-auto">
            {specs.map(([key, value]) => (
              <SpecRow key={key} label={key} value={formatAttrValue(value)} />
            ))}
          </dl>
        )}

        <Button
          onClick={() => add.mutate()}
          disabled={outOfStock || add.isPending || !sessionId}
          size="sm"
          /* `relative` lifts the button above the link's ::after overlay so the
             card can be a link and still contain a working button. */
          className="relative z-10 mt-auto w-full"
        >
          {add.isPending ? "Adding…" : outOfStock ? "Unavailable" : "Add to cart"}
        </Button>
      </div>
    </Plate>
  );
}

/** A responsive grid of cards, with a staggered entrance. */
export function ProductGrid({
  items,
  className,
  sessionId,
}: {
  items: ProductCardData[];
  className?: string;
  sessionId?: string | null | undefined;
}) {
  if (items.length === 0) return null;
  return (
    <ul
      className={cx(
        "grid grid-cols-1 gap-px border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
        className,
      )}
    >
      {items.map((item, index) => (
        /* The grid is a 1px-gap bg-rule sheet, so the hairlines *between* cards
           are the grid itself — a datasheet table rather than floating cards. */
        <li key={item.variantId} className="flex">
          <ProductCard item={item} stagger={index} className="w-full" sessionId={sessionId} />
        </li>
      ))}
    </ul>
  );
}
