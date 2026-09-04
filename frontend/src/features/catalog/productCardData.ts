import type { CatalogItem, Recommendation, StockStatus } from "../../api/schemas";

/**
 * The shape both product sources are narrowed to.
 *
 * A product reaches the UI two ways: the buyer browsed to it, or the agent
 * recommended it. Narrowing both to one type is what lets a single card render
 * either — which is most of why the concierge feels like part of the storefront
 * rather than a widget beside it.
 */
export type ProductCardData = {
  productId: string;
  variantId: string;
  productSlug: string | null;
  sku: string;
  name: string;
  variantName: string;
  category: string;
  price: string;
  currency: string;
  stockStatus: StockStatus;
  attributes: Record<string, unknown>;
  brand: string | null;
  /** Present only when the ranking engine produced this row. */
  rank?: number;
  reason?: string;
};

export function fromCatalogItem(item: CatalogItem): ProductCardData {
  return {
    productId: item.product_id,
    variantId: item.variant_id,
    productSlug: item.product_slug,
    sku: item.sku,
    name: item.name,
    variantName: item.variant_name,
    category: item.category,
    price: item.price,
    currency: item.currency,
    stockStatus: item.stock_status,
    attributes: item.attributes,
    brand: item.brand,
  };
}

/**
 * A recommendation carries no `product_slug` — the chat contract predates the
 * catalog routes and F§9 forbids inventing the field. So an agent result links
 * nowhere, and the card renders no link rather than guessing a URL.
 */
export function fromRecommendation(rec: Recommendation): ProductCardData {
  return {
    productId: rec.product_id,
    variantId: rec.variant_id,
    productSlug: null,
    sku: rec.sku,
    name: rec.name,
    variantName: rec.variant_name,
    category: rec.category,
    price: rec.price,
    currency: rec.currency,
    stockStatus: rec.stock_status,
    attributes: rec.attributes,
    brand: rec.brand,
    rank: rec.rank,
    reason: rec.reason,
  };
}
