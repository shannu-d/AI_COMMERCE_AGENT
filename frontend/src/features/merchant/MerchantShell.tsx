import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { NavLink, Link, Outlet, useLocation } from "react-router-dom";

import { cx } from "../../components/cx";

/**
 * The merchant dashboard's own shell — a sidebar and a workspace.
 *
 * Deliberately *not* the storefront `Shell`. This is a different job for a
 * different person: no concierge rail, no cart, no category bar. It keeps the
 * project's visual language — warm paper, hairline rules, the volt accent
 * (#94DD26) only for what is active, focused or a primary action — so it reads
 * as the same product seen from behind the counter, not a bolted-on admin
 * template.
 *
 * There is **no authentication** (ADR-022): the dashboard operates on the one
 * configured merchant, resolved server-side. Anyone who reaches `/merchant` sees
 * it. That is a documented limitation of the MVP, not an oversight.
 */

const NAV: Array<{ to: string; label: string; end?: boolean | undefined }> = [
  { to: "/merchant", label: "Overview", end: true },
  { to: "/merchant/products", label: "Products" },
  { to: "/merchant/inventory", label: "Inventory" },
  { to: "/merchant/orders", label: "Orders" },
  { to: "/merchant/categories", label: "Categories" },
  { to: "/merchant/settings", label: "Settings" },
];

export function MerchantShell() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { pathname } = useLocation();

  // Close the mobile drawer on navigation.
  useEffect(() => setDrawerOpen(false), [pathname]);

  return (
    <div className="flex min-h-[100dvh] flex-col bg-paper text-ink lg:flex-row">
      {/* -- sidebar (desktop) / drawer (mobile) -- */}
      <Sidebar className="hidden lg:flex" />

      {drawerOpen && (
        <>
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setDrawerOpen(false)}
            className="animate-fade fixed inset-0 z-30 bg-ink/40 lg:hidden"
          />
          <Sidebar className="animate-rail fixed inset-y-0 left-0 z-40 flex w-64 lg:hidden" />
        </>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* -- top bar -- */}
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-rule bg-paper/90 px-4 backdrop-blur-[6px] sm:px-6 lg:h-16">
          <button
            type="button"
            aria-label="Open menu"
            onClick={() => setDrawerOpen(true)}
            className="grid h-9 w-9 place-items-center rounded-plate text-ink-soft transition-colors duration-fast hover:text-volt lg:hidden"
          >
            <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              <path d="M3 6h14M3 10h14M3 14h14" />
            </svg>
          </button>
          <span className="eyebrow hidden sm:inline">Merchant dashboard</span>
          <span className="text-sm font-medium sm:hidden">Dashboard</span>
          <Link
            to="/"
            className="ml-auto text-2xs text-ink-soft underline decoration-rule underline-offset-4 transition-colors hover:text-volt hover:decoration-volt"
          >
            View storefront →
          </Link>
        </header>

        <main id="main" className="flex-1">
          <div className="mx-auto max-w-shell px-4 py-8 sm:px-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

function Sidebar({ className }: { className?: string }) {
  return (
    <aside className={cx("flex-col border-r border-rule bg-paper-raised", className)}>
      <Link
        to="/merchant"
        className="flex h-14 shrink-0 items-center gap-2 border-b border-rule px-5 lg:h-16"
      >
        <span
          aria-hidden="true"
          className="-skew-x-6 text-[1.05rem] font-bold italic tracking-[-0.04em] text-volt"
        >
          EASY BUY
        </span>
        <span className="eyebrow">admin</span>
      </Link>

      <nav aria-label="Dashboard" className="flex flex-1 flex-col gap-0.5 p-3">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end === true}
            className={({ isActive }) =>
              cx(
                "flex items-center gap-2.5 border-l-2 px-3 py-2 text-sm transition-colors duration-fast",
                isActive
                  ? "border-volt bg-paper-sunken font-medium text-ink"
                  : "border-transparent text-ink-soft hover:border-rule hover:text-ink",
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <p className="border-t border-rule px-5 py-3 text-2xs leading-relaxed text-ink-faint">
        Single-tenant, no sign-in. Every figure here is read from the live
        catalogue and order tables.
      </p>
    </aside>
  );
}

// -- shared dashboard building blocks -------------------------------------

/** A section heading + optional action, matched to the storefront's rhythm. */
export function PageHead({
  title,
  count,
  children,
}: {
  title: string;
  count?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
      <div className="flex items-baseline gap-3">
        <h1 className="text-title font-medium tracking-tight text-ink">{title}</h1>
        {count !== undefined && <span className="eyebrow">{count}</span>}
      </div>
      {children}
    </div>
  );
}

/**
 * The dashboard table. A real table on desktop; a stack of labelled cards on a
 * phone, because a six-column table at 390px is unreadable (Part 12).
 */
export function DashTable<Row>({
  rows,
  columns,
  rowKey,
  empty,
  onRowClick,
}: {
  rows: Row[];
  columns: Array<{
    header: string;
    cell: (row: Row) => ReactNode;
    align?: "left" | "right";
    /** Hidden on the mobile card view when false. */
    mobile?: boolean;
  }>;
  rowKey: (row: Row) => string;
  empty: ReactNode;
  onRowClick?: (row: Row) => void;
}) {
  if (rows.length === 0) {
    return <div className="border border-rule bg-paper-raised p-8 text-center text-sm text-ink-soft">{empty}</div>;
  }

  return (
    <>
      {/* desktop */}
      <div className="hidden overflow-x-auto border border-rule sm:block">
        <table className="w-full min-w-[40rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule bg-paper-sunken">
              {columns.map((c) => (
                <th
                  key={c.header}
                  className={cx(
                    "eyebrow px-3 py-2.5 font-normal",
                    c.align === "right" ? "text-right" : "text-left",
                  )}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cx(
                  "border-b border-rule/60 bg-paper-raised transition-colors duration-fast last:border-0",
                  onRowClick && "cursor-pointer hover:bg-paper-sunken",
                )}
              >
                {columns.map((c) => (
                  <td
                    key={c.header}
                    className={cx("px-3 py-2.5 align-middle", c.align === "right" && "text-right tabular")}
                  >
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* mobile */}
      <ul className="space-y-px border border-rule bg-rule sm:hidden">
        {rows.map((row) => (
          <li
            key={rowKey(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            className={cx("bg-paper-raised p-3", onRowClick && "active:bg-paper-sunken")}
          >
            <dl className="space-y-1">
              {columns
                .filter((c) => c.mobile !== false)
                .map((c) => (
                  <div key={c.header} className="flex items-baseline justify-between gap-3">
                    <dt className="eyebrow shrink-0">{c.header}</dt>
                    <dd className={cx("min-w-0 text-right text-sm", c.align === "right" && "tabular")}>
                      {c.cell(row)}
                    </dd>
                  </div>
                ))}
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Prev/next pager for a `{ total, limit, offset }` list. */
export function Pager({
  total,
  limit,
  offset,
  onOffset,
}: {
  total: number;
  limit: number;
  offset: number;
  onOffset: (next: number) => void;
}) {
  if (total <= limit) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="mt-4 flex items-center justify-between text-2xs text-ink-soft">
      <span className="tabular">
        {from}–{to} of {total}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={offset === 0}
          onClick={() => onOffset(Math.max(0, offset - limit))}
          className="border border-rule px-2.5 py-1 transition-colors duration-fast hover:border-volt disabled:opacity-40"
        >
          ← Prev
        </button>
        <button
          type="button"
          disabled={to >= total}
          onClick={() => onOffset(offset + limit)}
          className="border border-rule px-2.5 py-1 transition-colors duration-fast hover:border-volt disabled:opacity-40"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
