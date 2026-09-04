import { useState } from "react";
import { useParams, Link } from "react-router-dom";

import { Money } from "../../components/Money";
import { Alert, Eyebrow, Skeleton } from "../../components/primitives";
import { cx } from "../../components/cx";
import { DashTable, PageHead, Pager } from "../../features/merchant/MerchantShell";
import { useMerchantOrder, useMerchantOrders } from "../../features/merchant/useMerchant";
import type { MerchantOrder } from "../../features/merchant/api";

const LIMIT = 25;

const STATUS_TONE: Record<string, string> = {
  PAYMENT_CONFIRMED: "text-positive",
  PAYMENT_FAILED: "text-critical",
  ORDER_FAILED: "text-critical",
  CANCELLED: "text-ink-faint",
};

/**
 * Read-only. The order state machine belongs to `create_order` and the verified
 * webhook (ADR-011, ADR-012); the dashboard observes it. No control here can
 * advance, refund or cancel an order.
 */
export function OrdersPage() {
  const [offset, setOffset] = useState(0);
  const query = useMerchantOrders({ limit: LIMIT, offset });

  return (
    <>
      <PageHead title="Orders" count={query.data ? `${query.data.total}` : undefined} />

      {query.isError ? (
        <Alert tone="critical" title="Could not load orders" />
      ) : query.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <>
          <DashTable<MerchantOrder>
            rows={query.data.items}
            rowKey={(o) => o.order_id}
            empty="No orders yet. Orders appear here the moment a buyer places one."
            columns={[
              {
                header: "Order",
                cell: (o) => (
                  <Link
                    to={`/merchant/orders/${o.order_id}`}
                    className="tabular text-2xs text-ink-soft underline decoration-rule underline-offset-2 hover:text-volt"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {o.order_id.slice(0, 8)}
                  </Link>
                ),
              },
              { header: "Placed", cell: (o) => <span className="text-2xs text-ink-soft">{fmtDate(o.created_at)}</span> },
              {
                header: "Status",
                cell: (o) => (
                  <span className={cx("text-2xs", STATUS_TONE[o.status] ?? "text-ink")}>
                    {o.status.replace(/_/g, " ").toLowerCase()}
                  </span>
                ),
              },
              { header: "Items", align: "right", mobile: false, cell: (o) => o.items.reduce((n, l) => n + l.quantity, 0) },
              { header: "Total", align: "right", cell: (o) => <Money amount={o.total_amount} currency={o.currency} /> },
            ]}
          />
          <Pager total={query.data.total} limit={LIMIT} offset={offset} onOffset={setOffset} />
        </>
      )}
    </>
  );
}

export function OrderDetailPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const { data, isPending, isError } = useMerchantOrder(orderId);

  if (isError) return <Alert tone="critical" title="Could not load this order" />;
  if (isPending || !data) {
    return (
      <>
        <PageHead title="Order" />
        <Skeleton className="h-64 w-full max-w-xl" />
      </>
    );
  }

  return (
    <>
      <PageHead title={`Order ${data.order_id.slice(0, 8)}`} count={<span className="tabular">{data.status.replace(/_/g, " ")}</span>}>
        <Link to="/merchant/orders" className="text-2xs text-ink-soft underline underline-offset-4 hover:text-volt">
          ← All orders
        </Link>
      </PageHead>

      <div className="max-w-xl space-y-6">
        <dl className="grid grid-cols-2 gap-px border border-rule bg-rule text-sm">
          <Cell term="Placed" value={fmtDate(data.created_at)} />
          <Cell term="Status" value={data.status.replace(/_/g, " ").toLowerCase()} />
          <Cell term="Cart version" value={`v${data.cart_version}`} />
          <Cell term="Razorpay order" value={data.razorpay_order_id ?? "—"} />
        </dl>

        <section>
          <Eyebrow>Lines</Eyebrow>
          <ul className="mt-3 space-y-px border border-rule bg-rule">
            {data.items.map((line) => (
              <li key={line.sku} className="flex items-baseline justify-between gap-4 bg-paper-raised p-3 text-sm">
                <span className="min-w-0">
                  <span className="font-medium text-ink">{line.product_name}</span>
                  <span className="text-ink-faint"> · {line.variant_name}</span>
                  <span className="tabular block text-2xs text-ink-faint">
                    {line.sku} · {line.quantity} × <Money amount={line.unit_price} currency={data.currency} />
                  </span>
                </span>
                <Money amount={line.line_total} currency={data.currency} className="tabular shrink-0" />
              </li>
            ))}
          </ul>
        </section>

        <div className="flex items-baseline justify-between border-t border-rule pt-3">
          <span className="eyebrow">Total</span>
          <Money amount={data.total_amount} currency={data.currency} className="tabular text-lg font-medium" />
        </div>
      </div>
    </>
  );
}

function Cell({ term, value }: { term: string; value: string }) {
  return (
    <div className="bg-paper-raised p-3">
      <dt className="eyebrow">{term}</dt>
      <dd className="mt-1 truncate">{value}</dd>
    </div>
  );
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
