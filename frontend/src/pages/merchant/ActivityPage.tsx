import { useState } from "react";

import { Alert, Skeleton } from "../../components/primitives";
import { cx } from "../../components/cx";
import { DashTable, PageHead, Pager } from "../../features/merchant/MerchantShell";
import { useMerchantActivity } from "../../features/merchant/useMerchant";
import type { MerchantActivityItem } from "../../features/merchant/api";

const LIMIT = 50;

/**
 * Who changed what, newest first (ADR-023 §7).
 *
 * The catalogue this dashboard edits is the catalogue the agent recommends
 * from, so "who set this price and when" needs an answer written at the moment
 * of the change. Every row here was recorded by the write itself, inside the
 * same transaction — a refused edit appears nowhere.
 *
 * Read-only, and there is no route that could make it otherwise: the table is
 * append-only and nothing in the application updates or deletes a row.
 *
 * Amounts in `payload` are rendered exactly as stored. They are strings, and
 * nothing on this page parses, sums or reformats one (ADR-008).
 */
export function ActivityPage() {
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState<string>("");
  const query = useMerchantActivity({
    limit: LIMIT,
    offset,
    ...(action ? { action } : {}),
  });

  return (
    <>
      <PageHead title="Activity" count={query.data ? `${query.data.total}` : undefined} />

      <div className="mb-3 flex flex-wrap gap-1.5">
        {FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            onClick={() => {
              setAction(filter.value);
              setOffset(0);
            }}
            className={cx(
              "border px-2.5 py-1 text-2xs transition-colors duration-fast",
              action === filter.value
                ? "border-ink bg-paper-sunken text-ink"
                : "border-rule text-ink-soft hover:border-ink hover:text-ink",
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {query.isError ? (
        <Alert tone="critical" title="Could not load the activity log" />
      ) : query.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <>
          <DashTable<MerchantActivityItem>
            rows={query.data.items}
            rowKey={(row) => row.id}
            empty="Nothing recorded yet. Every catalogue, price and stock change lands here."
            columns={[
              {
                header: "When",
                cell: (row) => (
                  <span className="text-2xs text-ink-soft">{fmtDate(row.created_at)}</span>
                ),
              },
              {
                header: "Action",
                cell: (row) => (
                  <span className={cx("text-2xs", TONE[row.action] ?? "text-ink")}>
                    {row.action.replace(/_/g, " ").toLowerCase()}
                  </span>
                ),
              },
              {
                header: "Subject",
                cell: (row) => (
                  <span className="text-sm text-ink">{row.subject ?? "—"}</span>
                ),
              },
              {
                header: "Change",
                mobile: true,
                cell: (row) => <Change item={row} />,
              },
              {
                header: "By",
                mobile: false,
                cell: (row) => (
                  <span className="text-2xs text-ink-faint">{row.actor_email}</span>
                ),
              },
            ]}
          />
          <Pager total={query.data.total} limit={LIMIT} offset={offset} onOffset={setOffset} />
        </>
      )}
    </>
  );
}

const FILTERS = [
  { label: "Everything", value: "" },
  { label: "Prices", value: "PRICE_CHANGED" },
  { label: "Stock", value: "STOCK_CHANGED" },
  { label: "New products", value: "PRODUCT_CREATED" },
  { label: "Archived", value: "PRODUCT_ARCHIVED" },
];

const TONE: Record<string, string> = {
  PRICE_CHANGED: "text-volt-ink",
  PRODUCT_ARCHIVED: "text-critical",
  PRODUCT_RESTORED: "text-positive",
};

/**
 * The before-and-after, when there is one worth showing.
 *
 * Deliberately literal. A price is printed as the string it was stored as, so
 * what an administrator reads here is the value the catalogue actually held.
 */
function Change({ item }: { item: MerchantActivityItem }) {
  const payload = item.payload as Record<string, unknown>;
  const from = payload["from"];
  const to = payload["to"];

  if (from !== undefined || to !== undefined) {
    return (
      <span className="tabular text-2xs text-ink-soft">
        {String(from ?? "—")} <span aria-hidden="true">→</span>{" "}
        <span className="text-ink">{String(to ?? "—")}</span>
      </span>
    );
  }

  const changed = payload["changed"];
  if (Array.isArray(changed) && changed.length > 0) {
    return <span className="text-2xs text-ink-soft">{changed.join(", ")}</span>;
  }

  const variants = payload["variants"];
  if (Array.isArray(variants)) {
    return (
      <span className="text-2xs text-ink-soft">
        {variants.length} variant{variants.length === 1 ? "" : "s"}
      </span>
    );
  }

  return <span className="text-2xs text-ink-faint">—</span>;
}

function fmtDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
}
