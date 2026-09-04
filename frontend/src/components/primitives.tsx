import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

import { cx } from "./cx";

/**
 * The component vocabulary.
 *
 * Two rules hold everything together:
 *
 * 1. **Small radii, real rules.** Structure comes from 1px lines and precise
 *    spacing, not from rounded cards and drop shadows. A datasheet has hairlines;
 *    a template has pill-shaped boxes with soft shadows.
 * 2. **Every reaction is `transform` or `opacity`.** Both are composited, so a
 *    hover on a grid of twenty cards cannot cost layout or paint.
 */

// -- actions -----------------------------------------------------------------

export function Button({
  variant = "primary",
  size = "base",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "volt";
  size?: "sm" | "base" | "lg";
}) {
  const base =
    "inline-flex select-none items-center justify-center gap-2 rounded-plate font-medium " +
    "transition-[transform,background-color,color,border-color] duration-fast ease-out " +
    // A 1px press. Enough to feel mechanical, small enough never to look bouncy.
    "active:translate-y-px disabled:pointer-events-none disabled:opacity-40";

  const sizes = {
    // 44px minimum touch target at `base` and `lg`; `sm` is for dense desktop
    // rows only and is never the sole affordance on a touch layout.
    sm: "h-9 px-3 text-2xs",
    base: "h-11 px-5 text-sm",
    lg: "h-12 px-6 text-[0.95rem]",
  } as const;

  const variants = {
    primary: "bg-ink text-paper hover:bg-ink-soft",
    secondary: "border border-rule bg-paper-raised text-ink hover:border-ink hover:bg-paper-sunken",
    ghost: "text-ink-soft hover:bg-paper-sunken hover:text-ink",
    danger: "border border-critical/25 bg-critical/5 text-critical hover:bg-critical/10",
    volt: "bg-volt text-volt-ink hover:brightness-95",
  } as const;

  return <button className={cx(base, sizes[size], variants[variant], className)} {...props} />;
}

// -- surfaces ----------------------------------------------------------------

/**
 * The plate: this design's card.
 *
 * Named for what it is — a technical plate, hairline-ruled — so nobody is
 * tempted to give it a 16px radius and a shadow and turn it back into a
 * generic card.
 */
export function Plate({
  className,
  interactive = false,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cx(
        "border border-rule bg-paper-raised",
        interactive &&
          "transition-[transform,border-color] duration-base ease-out " +
            "hover:-translate-y-0.5 hover:border-ink motion-reduce:hover:translate-y-0",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

/** A section label. Small, tracked, monospace — the datasheet's voice. */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cx("eyebrow", className)}>{children}</p>;
}

// -- data display ------------------------------------------------------------

/**
 * Stock, as a badge.
 *
 * Coarse by design: exact quantities never reach a buyer-facing payload
 * (ADR-009, closing E5), so there is no "3 left" to render even if the design
 * wanted one.
 */
export function StockBadge({
  status,
  className,
}: {
  status: "IN_STOCK" | "LOW_STOCK" | "OUT_OF_STOCK";
  className?: string;
}) {
  const map = {
    IN_STOCK: ["In stock", "text-positive before:bg-positive"],
    LOW_STOCK: ["Low stock", "text-caution before:bg-caution"],
    OUT_OF_STOCK: ["Out of stock", "text-ink-faint before:bg-ink-faint"],
  } as const;
  const [label, tone] = map[status];
  return (
    <span
      className={cx(
        "eyebrow inline-flex items-center gap-1.5",
        // A 5px square rather than a filled pill: a status light on an
        // instrument, not a badge on a dashboard.
        "before:h-[5px] before:w-[5px] before:content-['']",
        tone,
        className,
      )}
    >
      {label}
    </span>
  );
}

/**
 * A specification row.
 *
 * Attributes come straight from the catalogue (`material: polycarbonate`,
 * `wattage: 20`), so keys are snake_case machine names. Rendering them as-is
 * would look unfinished; rewriting their *values* would be inventing data. So
 * only the key is humanised, and the value is printed verbatim in mono.
 */
export function SpecRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-rule/60 py-1.5 last:border-0">
      <dt className="text-2xs uppercase tracking-[0.1em] text-ink-faint">
        {label.replace(/_/g, " ")}
      </dt>
      <dd className="tabular text-right text-2xs text-ink">{value}</dd>
    </div>
  );
}


// -- feedback ----------------------------------------------------------------

/**
 * The single "the agent is working" state.
 *
 * Deliberately one bounded state rather than granular tool narration
 * ("Searching catalog…", "Checking compatibility…"). The backend does not stream
 * and exposes no per-tool progress (ADR-010), so a granular indicator would be
 * describing work it cannot observe — and would misrepresent the turn whenever
 * the tool it named never ran.
 */
export function Thinking({ label = "Thinking", tone = "paper" }: { label?: string; tone?: "paper" | "ink" }) {
  return (
    <span
      className={cx(
        "eyebrow inline-flex items-center gap-2",
        tone === "ink" ? "text-paper/60" : "text-ink-faint",
      )}
      role="status"
    >
      <span className="flex gap-1" aria-hidden="true">
        {[0, 160, 320].map((delay) => (
          <span
            key={delay}
            className={cx(
              "h-1 w-1 rounded-full",
              tone === "ink" ? "bg-volt" : "bg-ink",
            )}
            style={{ animation: `pulse-dot 1.1s ${delay}ms ease-in-out infinite` }}
          />
        ))}
      </span>
      {label}
    </span>
  );
}

/**
 * A skeleton block.
 *
 * The sweep animates `transform` on an inner element rather than a background
 * position, so the browser composites it instead of repainting the block on
 * every frame — the difference is visible once a grid shows a dozen at once.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cx("relative overflow-hidden bg-paper-sunken", className)} aria-hidden="true">
      <div
        className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-paper-raised to-transparent"
        style={{ animation: "sweep 1.4s var(--ease-inout) infinite" }}
      />
    </div>
  );
}

export function Alert({
  tone = "critical",
  title,
  children,
  action,
}: {
  tone?: "critical" | "caution" | "info";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    critical: "border-critical/25 bg-critical-bg text-critical",
    caution: "border-caution/25 bg-caution-bg text-caution",
    info: "border-rule bg-paper-sunken text-ink",
  } as const;
  return (
    <div
      role="alert"
      className={cx("space-y-2 border-l-2 px-3 py-2.5 text-sm", tones[tone])}
    >
      <p className="font-medium">{title}</p>
      {children && <div className="text-ink-soft">{children}</div>}
      {action}
    </div>
  );
}

/** A horizontal rule with an optional label sitting on it — an editorial device. */
export function LabelledRule({ children }: { children?: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-px flex-1 bg-rule" />
      {children && <span className="eyebrow shrink-0">{children}</span>}
      <span className="h-px flex-1 bg-rule" />
    </div>
  );
}

/** Former name of `Plate`. Kept so existing call sites keep working;
    new code should use `Plate`, which says what it is. */
export const Card = Plate;
