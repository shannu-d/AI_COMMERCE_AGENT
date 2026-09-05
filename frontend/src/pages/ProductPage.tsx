import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { cx } from "../components/cx";
import { Money } from "../components/Money";
import { Button, Eyebrow, Skeleton, SpecRow, StockBadge } from "../components/primitives";
import { formatAttrValue } from "../components/formatAttrValue";
import { SpecMark } from "../design/SpecMark";
import { useAddToCart } from "../features/catalog/useAddToCart";
import { useProduct } from "../features/catalog/useCatalog";
import { useConcierge } from "../features/concierge/conciergeContext";
import { CatalogUnavailable } from "./HomePage";

/**
 * Product detail.
 *
 * The page is a datasheet: identity, the sellable versions, the full attribute
 * table, and one action. Since there is no product photography in this system,
 * the left column is the specimen mark at size — honest about what it is, and
 * far better than a grey rectangle apologising for a missing image.
 *
 * "Ask about this" hands the current product to the concierge as context. That
 * is the join between browsing and the agent: a buyer who is unsure whether
 * something fits their phone does not have to re-describe the product.
 */
export function ProductPage() {
  const { slug } = useParams<{ slug: string }>();
  const query = useProduct(slug);

  // Memoised so the effect below does not see a new array identity on every
  // render, which would re-run it continuously.
  const variants = useMemo(() => query.data?.variants ?? [], [query.data?.variants]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Default to the first variant that can actually be bought, so the primary
  // action is not disabled on arrival whenever the cheapest option is sold out.
  useEffect(() => {
    if (variants.length === 0) return;
    const purchasable = variants.find((v) => v.stock_status !== "OUT_OF_STOCK");
    setSelectedId((current) => current ?? (purchasable ?? variants[0]!).variant_id);
  }, [variants]);

  const selected = variants.find((v) => v.variant_id === selectedId) ?? variants[0];

  if (query.isPending) return <ProductSkeleton />;
  if (query.isError) {
    return (
      <div className="mx-auto max-w-shell px-4 py-16 sm:px-6">
        <CatalogUnavailable />
      </div>
    );
  }
  if (!query.data || !selected) return null;

  const { product, related } = query.data;
  const attributes = Object.entries(selected.attributes).filter(
    ([, value]) => value !== null && value !== "",
  );

  return (
    <div className="mx-auto max-w-shell px-4 py-8 sm:px-6 sm:py-10">
      <nav aria-label="Breadcrumb" className="eyebrow">
        <Link to="/" className="transition-colors hover:text-ink">
          Home
        </Link>
        <span aria-hidden="true"> / </span>
        <Link to={`/c/${product.category}`} className="capitalize transition-colors hover:text-ink">
          {product.category.replace(/_/g, " ")}
        </Link>
        <span aria-hidden="true"> / </span>
        <span className="text-ink">{product.name}</span>
      </nav>

      <div className="mt-6 grid gap-8 lg:grid-cols-12 lg:gap-10">
        {/* ---- Specimen -------------------------------------------------- */}
        <div className="lg:col-span-5">
          <div className="animate-rise sticky top-24 border border-rule bg-paper-raised">
            <div className="aspect-square">
              <SpecMark sku={selected.sku} category={product.category} />
            </div>
            <div className="flex items-center justify-between border-t border-rule px-3 py-2">
              <span className="eyebrow">Specimen · {product.category.replace(/_/g, " ")}</span>
              <span className="eyebrow tabular">{selected.sku}</span>
            </div>
          </div>
        </div>

        {/* ---- Identity and action --------------------------------------- */}
        <div className="lg:col-span-7">
          <Eyebrow>{product.brand ?? "CircuitCraft"}</Eyebrow>
          <h1 className="mt-2 text-title font-medium text-ink">{product.name}</h1>

          {product.description && (
            <p className="mt-3 max-w-prose text-[0.95rem] leading-relaxed text-ink-soft">
              {product.description}
            </p>
          )}

          <div className="mt-6 flex items-baseline gap-4 border-y border-rule py-4">
            <Money
              amount={selected.price}
              currency={selected.currency}
              className="tabular text-2xl font-medium text-ink"
            />
            <StockBadge status={selected.stock_status} />
          </div>

          {variants.length > 1 && (
            <fieldset className="mt-6">
              <legend className="eyebrow mb-2">
                Version · {variants.length} available
              </legend>
              <div className="grid gap-px border border-rule bg-rule sm:grid-cols-2">
                {variants.map((variant) => {
                  const active = variant.variant_id === selected.variant_id;
                  const gone = variant.stock_status === "OUT_OF_STOCK";
                  return (
                    <label
                      key={variant.variant_id}
                      className={cx(
                        "flex cursor-pointer items-center justify-between gap-3 bg-paper-raised p-3",
                        "transition-colors duration-fast",
                        active && "bg-ink text-paper",
                        !active && "hover:bg-paper-sunken",
                        gone && !active && "opacity-55",
                      )}
                    >
                      <span className="min-w-0">
                        <input
                          type="radio"
                          name="variant"
                          className="sr-only"
                          checked={active}
                          onChange={() => setSelectedId(variant.variant_id)}
                        />
                        <span className="block truncate text-sm">{variant.variant_name}</span>
                        <span
                          className={cx(
                            "tabular block truncate text-2xs",
                            active ? "text-paper/50" : "text-ink-faint",
                          )}
                        >
                          {variant.sku}
                        </span>
                      </span>
                      <Money
                        amount={variant.price}
                        currency={variant.currency}
                        className="tabular shrink-0 text-sm"
                      />
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}

          <AddToCart item={selected} />

          {attributes.length > 0 && (
            <section className="mt-10">
              <h2 className="eyebrow">Specification</h2>
              <dl className="mt-2 border-t border-rule">
                {attributes.map(([key, value]) => (
                  <SpecRow key={key} label={key} value={formatAttrValue(value)} />
                ))}
              </dl>
              <p className="mt-3 text-2xs leading-relaxed text-ink-faint">
                Values are the catalogue's own. Compatibility with a specific device is resolved by
                the concierge against the merchant's rules, never inferred from this table.
              </p>
            </section>
          )}

          {related.length > 0 && (
            <section className="mt-10">
              <h2 className="eyebrow">Related</h2>
              <ul className="mt-2 grid gap-px border border-rule bg-rule sm:grid-cols-2">
                {related.map((item) => (
                  <li key={item.id}>
                    <Link
                      to={`/p/${item.slug}`}
                      className="group flex items-center gap-3 bg-paper-raised p-3 transition-colors duration-fast hover:bg-paper-sunken"
                    >
                      <span className="h-10 w-10 shrink-0">
                        <SpecMark sku={item.slug} category={item.category} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-ink">{item.name}</span>
                        <span className="eyebrow block capitalize">
                          {item.category.replace(/_/g, " ")}
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-2xs text-ink-faint">
                Related items are catalogue links, not recommendations — nothing here has been
                checked against your device.
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function AddToCart({
  item,
}: {
  item: { variant_id: string; name: string; variant_name: string; stock_status: string };
}) {
  const { ask } = useConcierge();
  const add = useAddToCart({
    variantId: item.variant_id,
    name: item.name,
    variantName: item.variant_name,
  });
  const gone = item.stock_status === "OUT_OF_STOCK";

  return (
    <div className="mt-6 flex flex-col gap-2 sm:flex-row">
      <Button
        size="lg"
        onClick={() => add.mutate()}
        disabled={gone || add.isPending}
        className="flex-1"
      >
        {add.isPending ? "Adding…" : gone ? "Out of stock" : "Add to cart"}
      </Button>
      <Button
        size="lg"
        variant="secondary"
        onClick={() => ask(`Does the ${item.name} (${item.variant_name}) fit my phone?`)}
      >
        Ask about this
      </Button>
    </div>
  );
}

function ProductSkeleton() {
  return (
    <div className="mx-auto max-w-shell px-4 py-10 sm:px-6" aria-hidden="true">
      <div className="grid gap-8 lg:grid-cols-12 lg:gap-10">
        <div className="lg:col-span-5">
          <Skeleton className="aspect-square border border-rule" />
        </div>
        <div className="space-y-4 lg:col-span-7">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-9 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      </div>
    </div>
  );
}
