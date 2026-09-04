import { Link } from "react-router-dom";

import { Money } from "../../components/Money";
import { Alert, Eyebrow, Skeleton } from "../../components/primitives";
import { cx } from "../../components/cx";
import { PageHead } from "../../features/merchant/MerchantShell";
import { useMerchantOverview } from "../../features/merchant/useMerchant";
import type { MerchantOverview } from "../../features/merchant/api";

/**
 * The dashboard's front page. Every number is a real aggregate the backend
 * derived from the catalogue and order tables — nothing here is a placeholder or
 * an estimate. Revenue counts only `PAYMENT_CONFIRMED` orders, because that is
 * the only money actually received.
 */
export function OverviewPage() {
  const { data, isPending, isError, refetch } = useMerchantOverview();

  return (
    <>
      <PageHead title="Overview" count={data ? `${data.currency}` : undefined} />

      {isError ? (
        <Alert tone="critical" title="Could not load the dashboard">
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-1 underline decoration-critical/40 underline-offset-2"
          >
            Try again
          </button>
        </Alert>
      ) : isPending ? (
        <div className="grid grid-cols-2 gap-px border border-rule bg-rule md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="bg-paper-raised p-4">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="mt-3 h-7 w-16" />
            </div>
          ))}
        </div>
      ) : (
        <Metrics data={data} />
      )}
    </>
  );
}

function Metrics({ data }: { data: MerchantOverview }) {
  const tiles: Array<{
    label: string;
    value: string;
    hint?: string | undefined;
    tone?: "warn" | "bad" | undefined;
  }> = [
    { label: "Active products", value: `${data.active_products}`, hint: `${data.total_products} total` },
    { label: "Active variants", value: `${data.active_variants}`, hint: `${data.total_variants} SKUs` },
    { label: "Categories", value: `${data.category_count}` },
    { label: "Inventory units", value: data.total_inventory_units.toLocaleString("en-IN") },
    {
      label: "Low stock",
      value: `${data.low_stock_variants}`,
      tone: data.low_stock_variants > 0 ? "warn" : undefined,
    },
    {
      label: "Out of stock",
      value: `${data.out_of_stock_variants}`,
      tone: data.out_of_stock_variants > 0 ? "bad" : undefined,
    },
    { label: "Orders placed", value: `${data.total_orders}`, hint: `${data.paid_orders} paid` },
  ];

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-px border border-rule bg-rule md:grid-cols-3 xl:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="animate-fade bg-paper-raised p-4">
            <p className="eyebrow">{t.label}</p>
            <p
              className={cx(
                "tabular mt-2 text-[1.6rem] font-medium leading-none",
                t.tone === "warn" && "text-caution",
                t.tone === "bad" && "text-critical",
                !t.tone && "text-ink",
              )}
            >
              {t.value}
            </p>
            {t.hint && <p className="mt-1.5 text-2xs text-ink-faint">{t.hint}</p>}
          </div>
        ))}
        <div className="animate-fade bg-paper-raised p-4">
          <p className="eyebrow">Revenue (paid)</p>
          <Money
            amount={data.revenue}
            currency={data.currency}
            className="tabular mt-2 block text-[1.6rem] font-medium leading-none text-ink"
          />
          <p className="mt-1.5 text-2xs text-ink-faint">confirmed payments only</p>
        </div>
      </div>

      {/* A single at-a-glance bar: the split of variants by stock health. */}
      <section>
        <Eyebrow>Stock health</Eyebrow>
        <StockBar
          inStock={data.active_variants - data.low_stock_variants - data.out_of_stock_variants}
          low={data.low_stock_variants}
          out={data.out_of_stock_variants}
        />
      </section>

      <div className="flex flex-wrap gap-3 text-sm">
        <Link to="/merchant/products/new" className="border border-ink bg-ink px-4 py-2 text-paper transition-colors hover:bg-ink-soft">
          Add a product
        </Link>
        <Link to="/merchant/inventory?low=1" className="border border-rule px-4 py-2 transition-colors hover:border-volt">
          Review low stock
        </Link>
      </div>
    </div>
  );
}

/** Inline SVG, transform/opacity only — no chart library (Part: performance). */
function StockBar({ inStock, low, out }: { inStock: number; low: number; out: number }) {
  const total = Math.max(1, inStock + low + out);
  const seg = (n: number) => `${(n / total) * 100}%`;
  return (
    <div className="mt-3">
      <div className="flex h-6 overflow-hidden border border-rule" role="img" aria-label={`${inStock} in stock, ${low} low, ${out} out of stock`}>
        <div style={{ width: seg(inStock) }} className="bg-volt/70" />
        <div style={{ width: seg(low) }} className="bg-caution/60" />
        <div style={{ width: seg(out) }} className="bg-critical/40" />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-ink-soft">
        <Legend swatch="bg-volt/70" label={`In stock · ${inStock}`} />
        <Legend swatch="bg-caution/60" label={`Low · ${low}`} />
        <Legend swatch="bg-critical/40" label={`Out · ${out}`} />
      </div>
    </div>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className={cx("h-2 w-2", swatch)} />
      {label}
    </span>
  );
}
