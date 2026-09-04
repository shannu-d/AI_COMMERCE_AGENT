import { memo, useMemo } from "react";

import { cx } from "../components/cx";

/**
 * The product mark.
 *
 * **Why this exists.** The backend's product contract carries no image field,
 * and F§9 forbids inventing one. The usual fallback — a grey rectangle with a
 * camera glyph — reads as a broken page and makes every product look identical.
 *
 * So instead of pretending to be a photograph, this draws a *technical plate*:
 * a category glyph over a dot matrix whose arrangement is derived from the
 * product's own SKU. It is honest (nothing here claims to depict the object),
 * deterministic (the same SKU always draws the same mark, so a product is
 * visually recognisable across the listing, the cart and the concierge), and
 * cheap (inline SVG, no network request, no layout cost).
 *
 * It is also the design's memorable anchor: a catalogue that looks like a
 * datasheet rather than a shop.
 */

export type MarkCategory = string;

/** FNV-1a. Small, stable, and no dependency — the arrangement must not drift. */
function hash(input: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * The glyph per category, drawn on a 100×100 field.
 *
 * These are schematic, not illustrative — the vocabulary of an exploded diagram
 * rather than an icon set. Anything not listed falls back to a component grid,
 * so a category added to the seed later still renders deliberately.
 */
function glyph(category: string) {
  switch (category) {
    case "phone_case":
      return (
        <>
          <rect x="34" y="20" width="32" height="60" rx="7" />
          <rect x="39" y="27" width="22" height="46" rx="3" opacity="0.35" />
          <circle cx="50" cy="24" r="1.6" />
        </>
      );
    case "screen_protector":
      return (
        <>
          <rect x="30" y="22" width="34" height="56" rx="4" opacity="0.3" />
          <rect x="36" y="26" width="34" height="56" rx="4" />
          <path d="M36 26 L70 26" strokeWidth="2.5" />
        </>
      );
    case "charger":
      return (
        <>
          <rect x="32" y="30" width="36" height="30" rx="5" />
          <path d="M42 60 L42 74 M58 60 L58 74" />
          <path d="M52 36 L44 48 L50 48 L48 56 L58 43 L52 43 Z" strokeWidth="2" />
        </>
      );
    case "power_bank":
      return (
        <>
          <rect x="28" y="34" width="44" height="32" rx="4" />
          <rect x="33" y="39" width="9" height="22" opacity="0.5" />
          <rect x="45" y="39" width="9" height="22" opacity="0.3" />
          <path d="M72 44 L76 44 L76 56 L72 56" />
        </>
      );
    case "usb_cable":
      return (
        <>
          <rect x="20" y="42" width="14" height="16" rx="3" />
          <rect x="66" y="42" width="14" height="16" rx="3" />
          <path d="M34 50 C 44 50, 44 34, 50 34 C 56 34, 56 50, 66 50" strokeWidth="2.5" />
        </>
      );
    case "earbuds":
      return (
        <>
          <circle cx="38" cy="42" r="11" />
          <circle cx="62" cy="42" r="11" />
          <path d="M38 53 L38 72 M62 53 L62 72" />
          <circle cx="38" cy="42" r="3.5" opacity="0.4" />
          <circle cx="62" cy="42" r="3.5" opacity="0.4" />
        </>
      );
    case "laptop_sleeve":
    case "laptop_accessories":
      return (
        <>
          <rect x="22" y="32" width="56" height="34" rx="4" />
          <path d="M18 66 L82 66 L78 74 L22 74 Z" />
        </>
      );
    default:
      return (
        <>
          <rect x="30" y="30" width="40" height="40" rx="3" />
          <path d="M30 50 L70 50 M50 30 L50 70" opacity="0.4" />
        </>
      );
  }
}

/**
 * A dot matrix seeded by the SKU.
 *
 * Purely decorative, but *derived* rather than random: the same product always
 * gets the same field, which is what makes the mark function as identity.
 */
function matrix(seed: number) {
  const dots: Array<{ x: number; y: number; r: number }> = [];
  let state = seed;
  for (let row = 0; row < 7; row += 1) {
    for (let col = 0; col < 7; col += 1) {
      // xorshift — deterministic and cheap; this runs once per product.
      state ^= state << 13;
      state ^= state >>> 17;
      state ^= state << 5;
      state >>>= 0;
      if (state % 5 === 0) {
        dots.push({ x: 14 + col * 12, y: 14 + row * 12, r: state % 7 === 0 ? 1.7 : 1 });
      }
    }
  }
  return dots;
}

export const SpecMark = memo(function SpecMark({
  sku,
  category,
  className,
  tone = "paper",
}: {
  sku: string;
  category: MarkCategory;
  className?: string;
  /** `ink` inverts the mark for dark surfaces such as the concierge rail. */
  tone?: "paper" | "ink";
}) {
  const dots = useMemo(() => matrix(hash(sku) || 1), [sku]);

  return (
    <svg
      viewBox="0 0 100 100"
      className={cx("h-full w-full", className)}
      role="presentation"
      aria-hidden="true"
      /* No focusable, no title: this is decoration derived from data, and the
         product's real name and SKU are already adjacent in the DOM. */
    >
      <g className={tone === "ink" ? "text-paper/25" : "text-ink/[0.13]"} fill="currentColor">
        {dots.map((d) => (
          <circle key={`${d.x}-${d.y}`} cx={d.x} cy={d.y} r={d.r} />
        ))}
      </g>
      <g
        className={tone === "ink" ? "text-paper/80" : "text-ink/70"}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="square"
      >
        {glyph(category)}
      </g>
    </svg>
  );
});
