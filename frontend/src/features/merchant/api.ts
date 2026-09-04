import { z } from "zod";

import { request } from "../../api/client";
import { Money, StockStatus } from "../../api/schemas";

/**
 * The merchant dashboard's slice of the API — `/api/merchant/*`.
 *
 * Same rules as the storefront client: every response is parsed through a Zod
 * schema at the fetch boundary, and money is a **string** and stays one
 * (ADR-008). Nothing here sums, multiplies or rounds a price.
 *
 * There is no `merchant_id` anywhere in this file, in a request or a response —
 * the backend resolves the merchant server-side and a client cannot name one
 * (ADR-022). This module could not target another merchant's catalogue if it
 * tried.
 */

// -- response schemas ---------------------------------------------------------

export const MerchantVariant = z.object({
  variant_id: z.string().uuid(),
  product_id: z.string().uuid(),
  product_slug: z.string(),
  product_name: z.string(),
  variant_name: z.string(),
  sku: z.string(),
  category: z.string(),
  price: Money,
  currency: z.string(),
  quantity: z.number().int(),
  reserved_quantity: z.number().int(),
  available_quantity: z.number().int(),
  stock_status: StockStatus,
  product_active: z.boolean(),
  variant_active: z.boolean(),
  attributes: z.record(z.unknown()),
});
export type MerchantVariant = z.infer<typeof MerchantVariant>;

export const MerchantProductList = z.object({
  items: z.array(MerchantVariant),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type MerchantProductList = z.infer<typeof MerchantProductList>;

export const MerchantProductDetail = z.object({
  product_id: z.string().uuid(),
  slug: z.string(),
  name: z.string(),
  category: z.string(),
  description: z.string().nullable(),
  brand: z.string().nullable(),
  is_active: z.boolean(),
  attributes: z.record(z.unknown()),
  tags: z.array(z.string()),
  variants: z.array(MerchantVariant),
});
export type MerchantProductDetail = z.infer<typeof MerchantProductDetail>;

export const MerchantCategory = z.object({
  id: z.string().uuid(),
  slug: z.string(),
  name: z.string(),
  parent_slug: z.string().nullable(),
});
export type MerchantCategory = z.infer<typeof MerchantCategory>;

export const MerchantOverview = z.object({
  currency: z.string(),
  total_products: z.number().int(),
  active_products: z.number().int(),
  archived_products: z.number().int(),
  total_variants: z.number().int(),
  active_variants: z.number().int(),
  total_inventory_units: z.number().int(),
  out_of_stock_variants: z.number().int(),
  low_stock_variants: z.number().int(),
  category_count: z.number().int(),
  total_orders: z.number().int(),
  paid_orders: z.number().int(),
  revenue: Money,
});
export type MerchantOverview = z.infer<typeof MerchantOverview>;

export const MerchantOrderLine = z.object({
  sku: z.string(),
  product_name: z.string(),
  variant_name: z.string(),
  quantity: z.number().int(),
  unit_price: Money,
  line_total: Money,
});

export const MerchantOrder = z.object({
  order_id: z.string().uuid(),
  status: z.string(),
  currency: z.string(),
  subtotal_amount: Money,
  total_amount: Money,
  cart_version: z.number().int(),
  razorpay_order_id: z.string().nullable(),
  created_at: z.string(),
  items: z.array(MerchantOrderLine),
});
export type MerchantOrder = z.infer<typeof MerchantOrder>;

export const MerchantOrderPage = z.object({
  items: z.array(MerchantOrder),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type MerchantOrderPage = z.infer<typeof MerchantOrderPage>;

// -- request payloads -------------------------------------------------------

export type VariantInput = {
  sku: string;
  name: string;
  /** A decimal string — never a JS number (ADR-008). */
  price: string;
  quantity: number;
  attributes?: Record<string, string | number | boolean>;
};

export type ProductCreateInput = {
  name: string;
  category: string;
  description?: string | null;
  brand?: string | null;
  slug?: string | null;
  attributes?: Record<string, string | number | boolean>;
  tags?: string[];
  variants?: VariantInput[];
};

export type ProductUpdateInput = Partial<{
  name: string;
  category: string;
  description: string | null;
  brand: string | null;
  attributes: Record<string, string | number | boolean>;
  tags: string[];
  is_active: boolean;
}>;

// -- calls ----------------------------------------------------------------

export const getOverview = (signal?: AbortSignal) =>
  request("/api/merchant/overview", MerchantOverview, signal ? { signal } : {});

export const getMerchantCategories = (signal?: AbortSignal) =>
  request("/api/merchant/categories", z.array(MerchantCategory), signal ? { signal } : {});

export const createMerchantCategory = (body: { name: string; slug?: string; parent?: string | null }) =>
  request("/api/merchant/categories", MerchantCategory, { method: "POST", body });

export const listMerchantProducts = (
  params: {
    category?: string;
    q?: string;
    stock_status?: string;
    active?: boolean;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
) => {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.q) search.set("q", params.q);
  if (params.stock_status) search.set("stock_status", params.stock_status);
  if (params.active !== undefined) search.set("active", String(params.active));
  if (params.limit) search.set("limit", String(params.limit));
  if (params.offset) search.set("offset", String(params.offset));
  const query = search.toString();
  return request(
    `/api/merchant/products${query ? `?${query}` : ""}`,
    MerchantProductList,
    signal ? { signal } : {},
  );
};

export const getMerchantProduct = (productId: string, signal?: AbortSignal) =>
  request(`/api/merchant/products/${productId}`, MerchantProductDetail, signal ? { signal } : {});

export const createMerchantProduct = (body: ProductCreateInput) =>
  request("/api/merchant/products", MerchantProductDetail, { method: "POST", body });

export const updateMerchantProduct = (productId: string, body: ProductUpdateInput) =>
  request(`/api/merchant/products/${productId}`, MerchantProductDetail, {
    method: "PATCH",
    body,
  });

export const archiveMerchantProduct = (productId: string) =>
  request(`/api/merchant/products/${productId}/archive`, MerchantProductDetail, { method: "POST" });

export const restoreMerchantProduct = (productId: string) =>
  request(`/api/merchant/products/${productId}/restore`, MerchantProductDetail, { method: "POST" });

export const addMerchantVariant = (productId: string, body: VariantInput) =>
  request(`/api/merchant/products/${productId}/variants`, MerchantProductDetail, {
    method: "POST",
    body,
  });

export const updateMerchantVariant = (
  variantId: string,
  body: Partial<{ name: string; price: string; attributes: Record<string, unknown>; is_active: boolean }>,
) =>
  request(`/api/merchant/variants/${variantId}`, MerchantProductDetail, {
    method: "PATCH",
    body,
  });

export const listInventory = (
  params: { low_only?: boolean; limit?: number; offset?: number },
  signal?: AbortSignal,
) => {
  const search = new URLSearchParams();
  if (params.low_only) search.set("low_only", "true");
  if (params.limit) search.set("limit", String(params.limit));
  if (params.offset) search.set("offset", String(params.offset));
  const query = search.toString();
  return request(
    `/api/merchant/inventory${query ? `?${query}` : ""}`,
    MerchantProductList,
    signal ? { signal } : {},
  );
};

export const setVariantStock = (variantId: string, quantity: number) =>
  request(`/api/merchant/inventory/${variantId}`, MerchantVariant, {
    method: "PATCH",
    body: { quantity },
  });

export const listMerchantOrders = (
  params: { status?: string; limit?: number; offset?: number },
  signal?: AbortSignal,
) => {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.limit) search.set("limit", String(params.limit));
  if (params.offset) search.set("offset", String(params.offset));
  const query = search.toString();
  return request(
    `/api/merchant/orders${query ? `?${query}` : ""}`,
    MerchantOrderPage,
    signal ? { signal } : {},
  );
};

export const getMerchantOrder = (orderId: string, signal?: AbortSignal) =>
  request(`/api/merchant/orders/${orderId}`, MerchantOrder, signal ? { signal } : {});
