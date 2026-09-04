import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { cx } from "../components/cx";
import { Button, Eyebrow } from "../components/primitives";
import { ProductGrid } from "../features/catalog/ProductCard";
import { fromCatalogItem } from "../features/catalog/productCardData";
import { useCategories, useProducts } from "../features/catalog/useCatalog";
import { useConcierge } from "../features/concierge/conciergeContext";
import { CatalogUnavailable, ProductGridSkeleton } from "./HomePage";

/**
 * Product listing.
 *
 * Filters live in the URL, so a filtered view is linkable and the back button
 * does what a shopper expects. Sorting is a closed set the backend enumerates —
 * there is no "sort by relevance score", because scores belong to the ranking
 * engine and reach a buyer only through the concierge (ADR-005).
 */

const SORTS = [
  { value: "relevance", label: "Catalogue order" },
  { value: "price_asc", label: "Price, low to high" },
  { value: "price_desc", label: "Price, high to low" },
  { value: "name", label: "Name" },
] as const;

/** Budget steps chosen to straddle the catalogue's real price bands. */
const BUDGETS = ["499.00", "999.00", "1500.00", "2500.00"] as const;

export function CategoryPage() {
  const { slug } = useParams<{ slug: string }>();
  const [params, setParams] = useSearchParams();
  const { ask } = useConcierge();

  const sort = params.get("sort") ?? "relevance";
  const maxPrice = params.get("max_price") ?? undefined;

  const { data: categories } = useCategories();
  const category = categories?.find((c) => c.slug === slug);

  const query = useProducts({ category: slug, sort, maxPrice, limit: 60 });

  function setParam(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  const items = useMemo(
    () => (query.data?.items ?? []).map(fromCatalogItem),
    [query.data?.items],
  );

  const title = category?.name ?? slug?.replace(/_/g, " ") ?? "Catalogue";

  return (
    <div className="mx-auto max-w-shell px-4 py-10 sm:px-6">
      <nav aria-label="Breadcrumb" className="eyebrow">
        <Link to="/" className="transition-colors hover:text-ink">
          Home
        </Link>
        <span aria-hidden="true"> / </span>
        <span className="text-ink">{title}</span>
      </nav>

      <div className="mt-4 flex flex-wrap items-end justify-between gap-4 border-b border-rule pb-6">
        <div>
          <h1 className="text-title font-medium capitalize text-ink">{title}</h1>
          <p className="mt-1.5 text-sm text-ink-soft">
            {query.isPending ? (
              <span className="text-ink-faint">Loading…</span>
            ) : (
              <>
                <span className="tabular">{query.data?.total ?? 0}</span> variants
                {maxPrice && (
                  <>
                    {" "}
                    under <span className="tabular">₹{maxPrice}</span>
                  </>
                )}
              </>
            )}
          </p>
        </div>

        <Filters
          sort={sort}
          maxPrice={maxPrice}
          onSort={(value) => setParam("sort", value)}
          onBudget={(value) => setParam("max_price", value)}
        />
      </div>

      <div
        className={cx(
          "mt-6 transition-opacity duration-base",
          // While a filter refetches, dim rather than unmount: the grid keeps
          // its height, so the page never jumps under the cursor.
          query.isFetching && !query.isPending && "opacity-60",
        )}
      >
        {query.isPending ? (
          <ProductGridSkeleton count={8} />
        ) : query.isError ? (
          <CatalogUnavailable />
        ) : items.length === 0 ? (
          <EmptyResults
            onClear={() => setParams(new URLSearchParams(), { replace: true })}
            onAsk={() => ask(`What ${title} do you recommend?`)}
            hasFilters={Boolean(maxPrice)}
          />
        ) : (
          <ProductGrid items={items} />
        )}
      </div>
    </div>
  );
}

function Filters({
  sort,
  maxPrice,
  onSort,
  onBudget,
}: {
  sort: string;
  maxPrice: string | undefined;
  onSort: (value: string) => void;
  onBudget: (value: string | null) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Budget is the filter this catalogue actually needs — every price band
          in the seed sits either side of one of these lines. */}
      <div className="hidden items-center gap-1 sm:flex" role="group" aria-label="Budget">
        <Eyebrow className="mr-1">Under</Eyebrow>
        {BUDGETS.map((budget) => {
          const active = maxPrice === budget;
          return (
            <button
              key={budget}
              type="button"
              aria-pressed={active}
              onClick={() => onBudget(active ? null : budget)}
              className={cx(
                "tabular border px-2.5 py-1.5 text-2xs transition-colors duration-fast",
                active
                  ? "border-ink bg-ink text-paper"
                  : "border-rule text-ink-soft hover:border-ink hover:text-ink",
              )}
            >
              ₹{budget.replace(".00", "")}
            </button>
          );
        })}
      </div>

      <div className="relative">
        <label htmlFor="sort" className="sr-only">
          Sort products
        </label>
        <select
          id="sort"
          value={sort}
          onChange={(event) => onSort(event.target.value)}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          className={cx(
            "h-9 appearance-none border border-rule bg-paper-raised py-1.5 pl-3 pr-8 text-2xs text-ink",
            "transition-colors duration-fast hover:border-ink focus:border-ink focus:outline-none",
          )}
        >
          {SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <svg
          aria-hidden="true"
          viewBox="0 0 10 6"
          className={cx(
            "pointer-events-none absolute right-3 top-1/2 h-1.5 w-2.5 -translate-y-1/2 text-ink-faint transition-transform duration-fast",
            open && "rotate-180",
          )}
        >
          <path d="M1 1 L5 5 L9 1" stroke="currentColor" strokeWidth="1.5" fill="none" />
        </svg>
      </div>
    </div>
  );
}

function EmptyResults({
  onClear,
  onAsk,
  hasFilters,
}: {
  onClear: () => void;
  onAsk: () => void;
  hasFilters: boolean;
}) {
  return (
    <div className="animate-rise border border-rule bg-paper-raised px-6 py-16 text-center">
      <Eyebrow>No matches</Eyebrow>
      <p className="mx-auto mt-3 max-w-sm text-[0.95rem] leading-relaxed text-ink">
        {hasFilters
          ? "Nothing in this family fits that budget."
          : "This family has no sellable variants right now."}
      </p>
      <p className="mx-auto mt-2 max-w-sm text-sm text-ink-soft">
        The concierge can search across the whole catalogue and explain what does fit.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {hasFilters && (
          <Button variant="secondary" onClick={onClear}>
            Clear filters
          </Button>
        )}
        <Button onClick={onAsk}>Ask the concierge</Button>
      </div>
    </div>
  );
}
