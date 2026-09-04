import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Money } from "../../components/Money";
import { Alert, Skeleton, StockBadge } from "../../components/primitives";
import { cx } from "../../components/cx";
import { DashTable, PageHead, Pager } from "../../features/merchant/MerchantShell";
import { useMerchantCategories, useMerchantProducts } from "../../features/merchant/useMerchant";
import type { MerchantVariant } from "../../features/merchant/api";

const LIMIT = 25;

export function ProductsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { data: categories } = useMerchantCategories();

  const category = params.get("category") ?? undefined;
  const stock = params.get("stock") ?? undefined;
  const q = params.get("q") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const [draft, setDraft] = useState(q);

  const query = useMerchantProducts({
    ...(category ? { category } : {}),
    ...(q ? { q } : {}),
    ...(stock ? { stock_status: stock } : {}),
    limit: LIMIT,
    offset,
  });

  function set(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setParams(next, { replace: true });
  }

  return (
    <>
      <PageHead title="Products" count={query.data ? `${query.data.total} SKUs` : undefined}>
        <Link
          to="/merchant/products/new"
          className="border border-ink bg-ink px-3.5 py-1.5 text-sm text-paper transition-colors hover:bg-ink-soft"
        >
          Add product
        </Link>
      </PageHead>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          set("q", draft.trim() || null);
        }}
        className="mb-5 flex flex-wrap items-center gap-2"
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Search name or SKU"
          className="h-9 min-w-0 flex-1 border border-rule bg-paper-raised px-3 text-sm placeholder:text-ink-faint focus:border-volt focus:outline-none sm:flex-none sm:w-64"
        />
        <Select value={category ?? ""} onChange={(v) => set("category", v || null)} label="All categories">
          {(categories ?? [])
            .filter((c) => c.parent_slug)
            .map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name}
              </option>
            ))}
        </Select>
        <Select value={stock ?? ""} onChange={(v) => set("stock", v || null)} label="Any stock">
          <option value="IN_STOCK">In stock</option>
          <option value="LOW_STOCK">Low stock</option>
          <option value="OUT_OF_STOCK">Out of stock</option>
        </Select>
        {(category || stock || q) && (
          <button
            type="button"
            onClick={() => setParams(new URLSearchParams(), { replace: true })}
            className="text-2xs text-ink-soft underline underline-offset-4 hover:text-volt"
          >
            Clear
          </button>
        )}
      </form>

      {query.isError ? (
        <Alert tone="critical" title="Could not load products" />
      ) : query.isPending ? (
        <div className="space-y-px border border-rule bg-rule">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="bg-paper-raised p-3">
              <Skeleton className="h-4 w-2/3" />
            </div>
          ))}
        </div>
      ) : (
        <div className={cx(query.isFetching && "opacity-60 transition-opacity")}>
          <DashTable<MerchantVariant>
            rows={query.data.items}
            rowKey={(r) => r.variant_id}
            onRowClick={(r) => navigate(`/merchant/products/${r.product_id}`)}
            empty="No products match those filters."
            columns={[
              {
                header: "Product",
                cell: (r) => (
                  <span className={cx(!r.variant_active && "text-ink-faint line-through")}>
                    <span className="font-medium text-ink">{r.product_name}</span>
                    <span className="text-ink-faint"> · {r.variant_name}</span>
                  </span>
                ),
              },
              { header: "SKU", cell: (r) => <span className="tabular text-2xs text-ink-soft">{r.sku}</span> },
              { header: "Category", cell: (r) => <span className="text-2xs text-ink-soft">{r.category}</span>, mobile: false },
              { header: "Price", align: "right", cell: (r) => <Money amount={r.price} currency={r.currency} /> },
              {
                header: "Stock",
                align: "right",
                cell: (r) => (
                  <span className="inline-flex items-center gap-2">
                    <span className="tabular text-2xs text-ink-faint">{r.available_quantity}</span>
                    <StockBadge status={r.stock_status} />
                  </span>
                ),
              },
              {
                header: "Status",
                align: "right",
                mobile: false,
                cell: (r) =>
                  r.product_active && r.variant_active ? (
                    <span className="text-2xs text-ink-faint">Live</span>
                  ) : (
                    <span className="text-2xs text-caution">Archived</span>
                  ),
              },
            ]}
          />
          <Pager
            total={query.data.total}
            limit={LIMIT}
            offset={offset}
            onOffset={(next) => set("offset", next ? String(next) : null)}
          />
        </div>
      )}
    </>
  );
}

function Select({
  value,
  onChange,
  label,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-9 appearance-none border border-rule bg-paper-raised px-3 text-2xs text-ink transition-colors hover:border-ink focus:border-volt focus:outline-none"
    >
      <option value="">{label}</option>
      {children}
    </select>
  );
}
