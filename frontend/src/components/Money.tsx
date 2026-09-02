/**
 * Displays a money value. **Never computes one.**
 *
 * The value arrives as a fixed-scale string from the backend (`"1299.00"`) and
 * is rendered as one. This component does not parse it to a number, does not
 * add, and has no `total` variant that sums a list — every total in this UI is a
 * field the backend sent (ADR-008, F§12, F§29).
 *
 * Grouping separators are applied to the integer part by string manipulation,
 * so the decimal digits pass through untouched.
 */
export function Money({
  amount,
  currency = "INR",
  className,
}: {
  amount: string;
  currency?: string;
  className?: string;
}) {
  const symbol = currency === "INR" ? "₹" : `${currency} `;
  const negative = amount.startsWith("-");
  const [whole = "0", fraction = "00"] = (negative ? amount.slice(1) : amount).split(".");
  const grouped = groupIndian(whole);

  return (
    <span className={className} translate="no">
      {negative ? "-" : ""}
      {symbol}
      {grouped}.{fraction}
    </span>
  );
}

/**
 * Indian digit grouping: the last three digits, then pairs (12,34,567).
 *
 * The catalog is priced in INR and the specification's own examples are written
 * that way, so Western thousands-grouping would misrender the currency it
 * actually uses.
 */
function groupIndian(whole: string): string {
  if (whole.length <= 3) return whole;
  const last3 = whole.slice(-3);
  const rest = whole.slice(0, -3);
  return `${rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${last3}`;
}
