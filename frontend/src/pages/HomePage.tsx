import { useState } from "react";
import { Link } from "react-router-dom";

import { cx } from "../components/cx";
import { Button, Eyebrow, Skeleton } from "../components/primitives";
import { SpecMark } from "../design/SpecMark";
import { ProductGrid } from "../features/catalog/ProductCard";
import { fromCatalogItem } from "../features/catalog/productCardData";
import { useCategories, useProducts } from "../features/catalog/useCatalog";
import { useConcierge } from "../features/concierge/conciergeContext";

/**
 * Home.
 *
 * **The one decision that matters here:** the hero input is not a search box
 * that also has a chatbot somewhere. It *is* the concierge. Typing a sentence
 * and pressing return opens the rail and starts a turn.
 *
 * That is the honest design for this backend. There is no keyword search
 * endpoint worth putting front and centre, and there *is* an agent that
 * resolves a device name, applies a budget, checks compatibility and stock, and
 * returns ranked results. Making the primary input a natural-language one
 * matches what the system is actually good at, instead of demoting its best
 * capability to a bubble in the corner.
 */
export function HomePage() {
  const { ask } = useConcierge();
  const [draft, setDraft] = useState("");

  const featured = useProducts({ sort: "price_asc", limit: 8 });
  // `total` is how many variants matched, which with no filters is the
  // catalogue's size - the server's number, never one counted here.
  const skuCount = featured.data?.total ?? null;
  const { data: categories } = useCategories();

  const browsable = (categories ?? []).filter((c) =>
    ["phone_case", "charger", "usb_cable", "earbuds", "power_bank", "screen_protector"].includes(
      c.slug,
    ),
  );

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    ask(text);
    setDraft("");
  }

  return (
    <>
      {/* ---- Hero ------------------------------------------------------- */}
      <section className="border-b border-rule">
        <div className="mx-auto grid max-w-shell gap-10 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-12 lg:gap-8">
          <div className="lg:col-span-7">
            {/* The SKU count is read from the catalogue, not typed here. It
                said "32 SKUs" long after the catalogue passed three hundred,
                which is the storefront making a claim about stock it had not
                checked - the one thing the rest of this application refuses to
                do. Rendered only once the count has actually arrived. */}
            <Eyebrow className="animate-rise">
              EASY BUY{skuCount === null ? "" : ` · ${skuCount} SKUs`} · shipped from India
            </Eyebrow>

            {/* The asymmetric, oversized headline is the page's anchor. It is
                type doing structural work rather than an image doing it, which
                is also the only honest option: this catalogue has no imagery. */}
            <h1
              className="animate-rise mt-5 text-display font-semibold text-ink"
              style={{ "--stagger": "60ms" } as React.CSSProperties}
            >
              Say what it
              <br />
              needs to <span className="relative inline-block">
                fit
                <span
                  aria-hidden="true"
                  className="absolute -bottom-1 left-0 h-[6px] w-full bg-volt"
                />
              </span>
              .
            </h1>

            <p
              className="animate-rise mt-6 max-w-lg text-[0.95rem] leading-relaxed text-ink-soft"
              style={{ "--stagger": "120ms" } as React.CSSProperties}
            >
              Describe the device and the budget. The concierge resolves what fits against the real
              catalogue — compatibility, stock and price are checked, never guessed.
            </p>

            <form
              onSubmit={submit}
              className="animate-rise mt-8 max-w-xl"
              style={{ "--stagger": "180ms" } as React.CSSProperties}
            >
              <label htmlFor="hero-ask" className="sr-only">
                Describe what you need
              </label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  id="hero-ask"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder="A case for my iPhone 16 under ₹1500"
                  autoComplete="off"
                  className={cx(
                    "h-12 min-w-0 flex-1 border border-ink bg-paper-raised px-4 text-sm text-ink",
                    "placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-ink focus:ring-offset-2 focus:ring-offset-paper",
                  )}
                />
                <Button
                  type="submit"
                  size="lg"
                  disabled={draft.trim() === ""}
                  className="transition-colors hover:bg-volt hover:text-volt-ink"
                >
                  Ask the concierge
                </Button>
              </div>
            </form>

            <ul
              className="animate-rise mt-4 flex flex-wrap gap-2"
              style={{ "--stagger": "240ms" } as React.CSSProperties}
            >
              {[
                "Fast charger for an iPhone 16",
                "Earbuds with noise cancelling",
                "USB-C cable, 2 metres",
              ].map((example) => (
                <li key={example}>
                  <button
                    type="button"
                    onClick={() => ask(example)}
                    className="border border-rule px-3 py-1.5 text-2xs text-ink-soft transition-colors duration-fast hover:border-volt hover:text-ink"
                  >
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {/* A specimen plate rather than a stock photograph. It states what the
              site is — a technical catalogue — without pretending to show a
              product that has no image in the database. */}
          <div className="hidden lg:col-span-5 lg:block">
            <div
              className="animate-rise relative aspect-square border border-rule bg-paper-raised"
              style={{ "--stagger": "260ms" } as React.CSSProperties}
            >
              <div className="absolute inset-0 grid grid-cols-2 grid-rows-2">
                {["phone_case", "charger", "earbuds", "usb_cable"].map((category, index) => (
                  <div
                    key={category}
                    className={cx(
                      "relative",
                      index % 2 === 0 && "border-r border-rule",
                      index < 2 && "border-b border-rule",
                    )}
                  >
                    <SpecMark sku={`SPECIMEN-${category}`} category={category} />
                  </div>
                ))}
              </div>
              <div className="absolute inset-x-0 bottom-0 flex items-center justify-between border-t border-rule bg-paper px-3 py-2">
                <span className="eyebrow">Fig. 1 — Catalogue families</span>
                <span className="eyebrow tabular">04 / 32</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---- Categories -------------------------------------------------- */}
      <section className="mx-auto max-w-shell px-4 py-14 sm:px-6">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-title font-medium text-ink">Browse by family</h2>
          <Eyebrow>{browsable.length} categories</Eyebrow>
        </div>

        <ul className="mt-6 grid grid-cols-2 gap-px border border-rule bg-rule md:grid-cols-3 lg:grid-cols-6">
          {browsable.map((category, index) => (
            <li key={category.slug}>
              <Link
                to={`/c/${category.slug}`}
                className="group animate-rise flex aspect-square flex-col justify-between bg-paper-raised p-3 transition-colors duration-base hover:bg-paper-sunken"
                style={{ "--stagger": `${index * 40}ms` } as React.CSSProperties}
              >
                <div className="h-14 w-14 transition-transform duration-base ease-out group-hover:-translate-y-0.5 motion-reduce:group-hover:translate-y-0">
                  <SpecMark sku={`CAT-${category.slug}`} category={category.slug} />
                </div>
                <span className="text-sm leading-tight text-ink transition-colors duration-fast group-hover:text-volt">
                  {category.name}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* ---- Featured ---------------------------------------------------- */}
      <section className="mx-auto max-w-shell px-4 pb-16 sm:px-6">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-title font-medium text-ink">Starting points</h2>
          <Link
            to="/c/phone_case"
            className="text-sm text-ink-soft underline decoration-rule underline-offset-4 transition-colors hover:text-ink hover:decoration-volt"
          >
            See everything
          </Link>
        </div>
        <p className="mt-2 max-w-lg text-sm text-ink-soft">
          The most affordable variant of each family, priced from the catalogue.
        </p>

        <div className="mt-6">
          {featured.isPending ? (
            <ProductGridSkeleton count={8} />
          ) : featured.isError ? (
            <CatalogUnavailable />
          ) : (
            <ProductGrid items={(featured.data?.items ?? []).map(fromCatalogItem)} />
          )}
        </div>
      </section>
    </>
  );
}

/** Mirrors the grid's exact geometry so nothing shifts when data lands. */
export function ProductGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div
      className="grid grid-cols-1 gap-px border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      aria-hidden="true"
    >
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="bg-paper-raised">
          <Skeleton className="aspect-[4/3] border-b border-rule" />
          <div className="space-y-3 p-4">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-9 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function CatalogUnavailable() {
  return (
    <div className="border border-rule bg-paper-raised p-8 text-center">
      <p className="text-sm font-medium text-ink">The catalogue could not be loaded</p>
      <p className="mx-auto mt-1 max-w-sm text-sm text-ink-soft">
        Nothing has been charged and your cart is untouched. Refreshing usually works.
      </p>
      <Button variant="secondary" className="mt-4" onClick={() => window.location.reload()}>
        Try again
      </Button>
    </div>
  );
}
