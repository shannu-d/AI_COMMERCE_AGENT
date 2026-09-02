import { request } from "./client";
import {
  ApprovalResponse,
  Cart,
  ChatResponse,
  CheckoutConfig,
  HealthResponse,
  OrderResponse,
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
