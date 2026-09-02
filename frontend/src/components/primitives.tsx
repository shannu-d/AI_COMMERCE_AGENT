import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cx } from "./cx";

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium " +
    "transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const variants = {
    primary: "bg-blue-700 text-white hover:bg-blue-800",
    secondary: "border border-zinc-300 bg-white text-zinc-900 hover:bg-zinc-50",
    ghost: "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900",
    danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50",
  } as const;
  return <button className={cx(base, variants[variant], className)} {...props} />;
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx("rounded-lg border border-zinc-200 bg-white", className)}>{children}</div>
  );
}

/**
 * Stock, as a badge.
 *
 * Coarse by design: exact quantities never reach a buyer-facing payload
 * (ADR-009, closing E5), so there is no "3 left" to render even if the design
 * wanted one.
 */
export function StockBadge({ status }: { status: "IN_STOCK" | "LOW_STOCK" | "OUT_OF_STOCK" }) {
  const map = {
    IN_STOCK: ["In stock", "bg-green-50 text-green-800 ring-green-600/20"],
    LOW_STOCK: ["Low stock", "bg-amber-50 text-amber-800 ring-amber-600/20"],
    OUT_OF_STOCK: ["Out of stock", "bg-zinc-100 text-zinc-600 ring-zinc-500/20"],
  } as const;
  const [label, classes] = map[status];
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        classes,
      )}
    >
      {label}
    </span>
  );
}

/**
 * The single "the agent is working" state.
 *
 * Deliberately one bounded state rather than granular tool narration
 * ("Searching catalog…", "Checking compatibility…"). The backend does not stream
 * and exposes no per-tool progress (ADR-010), so a granular indicator would be
 * describing work it cannot observe — and would misrepresent the turn whenever
 * the tool it named never ran.
 */
export function Thinking({ label = "Thinking" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-zinc-500" role="status">
      <span className="flex gap-1" aria-hidden="true">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
      {label}…
    </span>
  );
}

export function Alert({
  tone = "danger",
  title,
  children,
  action,
}: {
  tone?: "danger" | "warning" | "info";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    danger: "border-red-200 bg-red-50 text-red-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    info: "border-blue-200 bg-blue-50 text-blue-900",
  } as const;
  return (
    <div role="alert" className={cx("space-y-2 rounded-md border p-3 text-sm", tones[tone])}>
      <p className="font-medium">{title}</p>
      {children && <div className="opacity-90">{children}</div>}
      {action}
    </div>
  );
}
