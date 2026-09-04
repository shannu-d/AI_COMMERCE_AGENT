/**
 * Formats a catalogue attribute value without altering its meaning.
 *
 * Attributes arrive as the catalogue stores them (`wattage: 20`,
 * `fast_charge: true`). Only presentation is adjusted here — a value is never
 * rewritten, rounded or unit-converted, because this UI has no authority to
 * restate a product fact.
 */
export function formatAttrValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value === null || value === undefined) return "—";
  return String(value);
}
