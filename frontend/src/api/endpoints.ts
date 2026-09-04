import { request } from "./client";
import {
  ApprovalResponse,
  Cart,
  CategoryList,
  ChatResponse,
  CheckoutConfig,
  HealthResponse,
  OrderResponse,
  ProductDetailResponse,
  ProductListResponse,
  SessionResponse,
} from "./schemas";

/**
 * Every call this frontend makes. Nine endpoints, one module.
 *
 * Note what is absent: there is no catalog-browsing call, because the backend
 * has no route for one (the services exist; nothing routes to them). Products
 * reach the UI only as `recommendations[]` on a chat turn. That is a real
 * boundary, not an oversight — adding a mock for it here would be inventing
 * backend behaviour.
 */

export const getHealth = (signal?: AbortSignal) =>
  request("/api/health", HealthResponse, signal ? { signal } : {});

// -- chat -------------------------------------------------------------------

export const sendChat = (body: { session_id: string | null; message: string }) =>
  request("/api/chat", ChatResponse, {
    method: "POST",
    // `session_id` is omitted on the first turn; the server mints it. Sending
    // `null` explicitly would be rejected by `extra="forbid"`-adjacent typing,
    // so omit the key entirely.
    body: body.session_id === null ? { message: body.message } : body,
  });

// -- cart -------------------------------------------------------------------

export const getCart = (sessionId: string, signal?: AbortSignal) =>
  request(`/api/cart?session_id=${encodeURIComponent(sessionId)}`, Cart, signal ? { signal } : {});

export const addCartItem = (body: {
  session_id: string;
  variant_id: string;
  quantity: number;
}) => request("/api/cart/items", Cart, { method: "POST", body });

export const updateCartItem = (itemId: string, body: { session_id: string; quantity: number }) =>
  request(`/api/cart/items/${itemId}`, Cart, { method: "PATCH", body });

export const removeCartItem = (itemId: string, sessionId: string) =>
  request(
    `/api/cart/items/${itemId}?session_id=${encodeURIComponent(sessionId)}`,
    Cart,
    { method: "DELETE" },
  );

// -- approval ---------------------------------------------------------------

/**
 * The only path in the system that records an approval (ADR-007).
 *
 * `cart_version` is **what the buyer's screen was showing**, not what the cart
 * is now. Submitting it is the entire mechanism by which a stale view becomes
 * detectable instead of being silently applied to whatever the cart has since
 * become. A mismatch is a 409.
 */
export const approveCart = (body: {
  session_id: string;
  cart_version: number;
  expected_total: string;
}) => request("/api/cart/approve", ApprovalResponse, { method: "POST", body });

// -- orders -----------------------------------------------------------------

export const createOrder = (body: {
  session_id: string;
  cart_id: string;
  cart_version: number;
  idempotency_key: string;
}) => request("/api/orders", OrderResponse, { method: "POST", body });

export const getOrder = (orderId: string, signal?: AbortSignal) =>
  request(`/api/orders/${orderId}`, OrderResponse, signal ? { signal } : {});

export const startCheckout = (orderId: string) =>
  request(`/api/orders/${orderId}/checkout`, CheckoutConfig, { method: "POST" });

// -- catalog ----------------------------------------------------------------

/**
 * Browsing. Read-only, anonymous, and deliberately session-free — nothing here
 * is scoped to a buyer and nothing here can move money.
 *
 * These reach the same deterministic `CatalogService` the agent's tools use, so
 * a browsed price and a recommended price are the same row of the same table.
 */

export const getCategories = (signal?: AbortSignal) =>
  request("/api/categories", CategoryList, signal ? { signal } : {});

export const getProducts = (
  params: {
    category?: string | undefined;
    q?: string | undefined;
    maxPrice?: string | undefined;
    sort?: string | undefined;
    limit?: number | undefined;
  },
  signal?: AbortSignal,
) => {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.q) search.set("q", params.q);
  if (params.maxPrice) search.set("max_price", params.maxPrice);
  if (params.sort) search.set("sort", params.sort);
  if (params.limit) search.set("limit", String(params.limit));
  const query = search.toString();
  return request(
    `/api/products${query ? `?${query}` : ""}`,
    ProductListResponse,
    signal ? { signal } : {},
  );
};

export const getProduct = (slug: string, signal?: AbortSignal) =>
  request(
    `/api/products/${encodeURIComponent(slug)}`,
    ProductDetailResponse,
    signal ? { signal } : {},
  );

// -- sessions ---------------------------------------------------------------

/**
 * Start a session without talking to the agent.
 *
 * The chat route mints one on its first turn, which is fine for a conversation
 * but leaves a browsing buyer unable to hold a cart. This is the same
 * server-minted, anonymous identifier by a different door.
 */
export const createSession = () => request("/api/sessions", SessionResponse, { method: "POST" });
