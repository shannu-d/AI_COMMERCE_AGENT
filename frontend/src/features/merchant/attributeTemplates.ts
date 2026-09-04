/**
 * Category-shaped attribute hints for the product form — **frontend scaffolding
 * only**.
 *
 * The backend catalogue is category-agnostic (ADR-021): `products.attributes`
 * and `product_variants.attributes` are free-form JSONB, and the ranking engine
 * matches on whatever keys are present. There is no per-category schema in the
 * database and this file does not add one. It only decides which fields the
 * editor *offers* for a given category, so a merchant adding a t-shirt sees
 * "size / material / fit" rather than a blank JSON box. A merchant can still add
 * any key they like, and the request still submits a plain `attributes` object.
 */

export type AttrField = { key: string; label: string; placeholder?: string; scope: "product" | "variant" };

const CLOTHING_PRODUCT: AttrField[] = [
  { key: "material", label: "Material", placeholder: "cotton", scope: "product" },
  { key: "fit", label: "Fit", placeholder: "regular", scope: "product" },
  { key: "gender", label: "Gender", placeholder: "unisex", scope: "product" },
];
const CLOTHING_VARIANT: AttrField[] = [
  { key: "color", label: "Colour", placeholder: "black", scope: "variant" },
  { key: "size", label: "Size", placeholder: "m", scope: "variant" },
];

const FURNITURE_PRODUCT: AttrField[] = [
  { key: "material", label: "Material", placeholder: "solid_oak", scope: "product" },
  { key: "room", label: "Room", placeholder: "living", scope: "product" },
  { key: "assembly_required", label: "Assembly required", placeholder: "true / false", scope: "product" },
];
const FURNITURE_VARIANT: AttrField[] = [
  { key: "finish", label: "Finish", placeholder: "oak", scope: "variant" },
  { key: "color", label: "Colour", placeholder: "natural", scope: "variant" },
  { key: "width_cm", label: "Width (cm)", placeholder: "120", scope: "variant" },
];

const ELECTRONICS_PRODUCT: AttrField[] = [
  { key: "material", label: "Material", placeholder: "polycarbonate", scope: "product" },
  { key: "port_type", label: "Port type", placeholder: "usb_c", scope: "product" },
];
const ELECTRONICS_VARIANT: AttrField[] = [
  { key: "color", label: "Colour", placeholder: "black", scope: "variant" },
];

const CLOTHING = new Set(["t_shirt", "shirt", "jeans", "hoodie", "jacket", "dress", "clothing"]);
const FURNITURE = new Set(["chair", "table", "desk", "sofa", "bed", "shelving", "furniture"]);

export function attributeTemplate(categorySlug: string): {
  product: AttrField[];
  variant: AttrField[];
} {
  if (CLOTHING.has(categorySlug)) return { product: CLOTHING_PRODUCT, variant: CLOTHING_VARIANT };
  if (FURNITURE.has(categorySlug)) return { product: FURNITURE_PRODUCT, variant: FURNITURE_VARIANT };
  return { product: ELECTRONICS_PRODUCT, variant: ELECTRONICS_VARIANT };
}

/** Best-effort typing so "true" → true and "20" → 20 before the request. */
export function coerceAttrValue(raw: string): string | number | boolean {
  const trimmed = raw.trim();
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (/^-?\d+$/.test(trimmed)) return Number(trimmed);
  if (/^-?\d*\.\d+$/.test(trimmed)) return Number(trimmed);
  return trimmed;
}
