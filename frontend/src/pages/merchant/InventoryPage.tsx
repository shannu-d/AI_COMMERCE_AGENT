import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Money } from "../../components/Money";
import { Alert, Skeleton, StockBadge } from "../../components/primitives";
import { cx } from "../../components/cx";
import { DashTable, PageHead, Pager } from "../../features/merchant/MerchantShell";
import { useMerchantInventory, useSetStock } from "../../features/merchant/useMerchant";
import type { MerchantVariant } from "../../features/merchant/api";

const LIMIT = 50;

/**
 * Inventory, lowest available first. Stock is edited inline and goes through
 * `PATCH /api/merchant/inventory/{variant}` — a validated backend write, never a
 * direct mutation. The storefront and the Smart Agent re-read the same rows, so
 * a number set here is a number they will honour.
 */
export function InventoryPage() {
  const [params, setParams] = useSearchParams();
  const lowOnly = params.get("low") === "1";
  const offset = Number(params.get("offset") ?? 0);
  const setStock = useSetStock();

  const query = useMerchantInventory({ low_only: lowOnly, limit: LIMIT, offset });

  function set(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setParams(next, { replace: true });
  }

  return (
    <>
      <PageHead title="Inventory" count={query.data ? `${query.data.total} SKUs` : undefined}>
        <label className="flex items-center gap-2 text-2xs text-ink-soft">
          <input
            type="checkbox"
            checked={lowOnly}
            onChange={(e) => set("low", e.target.checked ? "1" : null)}
            className="accent-volt"
          />
          Low & out of stock only
        </label>
      </PageHead>

      {query.isError ? (
        <Alert tone="critical" title="Could not load inventory" />
      ) : query.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className={cx(query.isFetching && "opacity-60 transition-opacity")}>
          <DashTable<MerchantVariant>
            rows={query.data.items}
            rowKey={(r) => r.variant_id}
            empty={lowOnly ? "Nothing is low on stock." : "No inventory rows."}
            columns={[
              {
                header: "Product",
                cell: (r) => (
                  <span>
                    <span className="font-medium text-ink">{r.product_name}</span>
                    <span className="text-ink-faint"> · {r.variant_name}</span>
                  </span>
                ),
              },
              { header: "SKU", cell: (r) => <span className="tabular text-2xs text-ink-soft">{r.sku}</span> },
              { header: "Price", align: "right", mobile: false, cell: (r) => <Money amount={r.price} currency={r.currency} /> },
              {
                header: "Reserved",
                align: "right",
                mobile: false,
                cell: (r) => <span className="tabular text-2xs text-ink-faint">{r.reserved_quantity}</span>,
              },
              {
                header: "Available",
                align: "right",
                cell: (r) => (
                  <StockCell
                    variant={r}
                    busy={setStock.isPending}
                    onSet={(quantity) => setStock.mutate({ variantId: r.variant_id, quantity })}
                  />
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

function StockCell({
  variant,
  onSet,
  busy,
}: {
  variant: MerchantVariant;
  onSet: (quantity: number) => void;
  busy: boolean;
}) {
  const [value, setValue] = useState(String(variant.available_quantity));
  const dirty = Number(value) !== variant.available_quantity;
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <StockBadge status={variant.stock_status} />
      <input
        className="h-8 w-16 border border-rule bg-paper px-2 text-right text-sm tabular focus:border-volt focus:outline-none"
        value={value}
        inputMode="numeric"
        disabled={busy}
        onChange={(e) => setValue(e.target.value.replace(/\D/g, ""))}
        onKeyDown={(e) => {
          if (e.key === "Enter" && dirty) onSet(Number(value) || 0);
        }}
        onBlur={() => dirty && onSet(Number(value) || 0)}
      />
    </span>
  );
}
