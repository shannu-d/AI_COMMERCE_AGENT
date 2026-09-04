import { z } from "zod";

/**
 * Zod schemas for what the backend returns.
 *
 * The backend validates every *request* with Pydantic and `extra="forbid"`.
 * Nothing validated on the way back until this file existed. A schema per
 * response turns a silent contract drift — a renamed field, a widened enum —
 * into a caught error at the fetch boundary instead of a runtime `undefined`
 * deep inside a component.
 *
 * **Money is a string, everywhere, always.** `"999.00"`, never `999.00`. The
 * backend sends fixed-scale strings precisely because a JSON number would
 * already be a lossy float before any validator could intervene (ADR-008), and
 * parsing one here would throw that guarantee away at the last step. Nothing in
 * this frontend may sum, multiply or round a money value: totals come from the
 * backend or they do not exist (F§12, F§29).
 *
 * **No field here has a Zod `.default()`, deliberately.** The backend's own
 * contract states that every field is always present and that absent data is
 * `null` or `[]` rather than a missing key. A default would quietly repair a
 * breach of that instead of reporting it, which is the opposite of what this
 * boundary is for.
 */

/** A fixed-scale decimal string, e.g. `"1299.00"`. Never converted to a number. */
export const Money = z.string().regex(/^-?\d+\.\d{2}$/, "money must be a fixed-scale string");

/**
 * F§25's closed vocabulary — exactly eleven, and the backend will not add to it
 * without a decision. Mirrored from `app/agent/errors.py::ApiErrorCode`; a
 * backend test (`test_frontend_contract.py`) reads this array and fails if the
 * two ever disagree, so the copy cannot drift silently.
 */
export const API_ERROR_CODES = [
  "VALIDATION_ERROR",
  "PRODUCT_NOT_FOUND",
  "VARIANT_NOT_FOUND",
  "OUT_OF_STOCK",
  "PRICE_CHANGED",
  "APPROVAL_REQUIRED",
  "POLICY_FAILED",
  "ORDER_CREATION_FAILED",
  "PAYMENT_FAILED",
  "PAYMENT_PENDING",
  "SERVER_ERROR",
] as const;

export const ApiErrorCode = z.enum(API_ERROR_CODES);
export type ApiErrorCode = z.infer<typeof ApiErrorCode>;

export const ApiError = z.object({
  code: ApiErrorCode,
  message: z.string(),
  details: z.record(z.unknown()),
});
export type ApiError = z.infer<typeof ApiError>;

/**
 * A§25's twenty display states.
 *
 * The UI reads this to choose affordances. It **authorizes nothing** — a session
 * whose state says `APPROVED` has not approved anything; only an `approvals` row
 * does, and only the Policy Engine reads that (ADR-006, ADR-007). Three separate
 * enums in this system share value names and none is derived from another.
 */
export const ConversationState = z.enum([
  "NEW_SESSION",
  "UNDERSTANDING_INTENT",
  "SEARCHING_PRODUCTS",
  "VALIDATING_PRODUCTS",
  "RECOMMENDING",
  "PRODUCT_SELECTED",
  "CART_PROPOSED",
  "WAITING_FOR_APPROVAL",
  "APPROVED",
  "POLICY_VALIDATION",
  "ORDER_CREATED",
  "PAYMENT_PENDING",
  "PAYMENT_CONFIRMED",
  "NEED_CLARIFICATION",
  "OUT_OF_STOCK",
  "PRICE_CHANGED",
  "POLICY_REJECTED",
  "PAYMENT_FAILED",
  "TOOL_ERROR",
  "ORDER_FAILED",
]);
export type ConversationState = z.infer<typeof ConversationState>;

/** Coarse only. Exact quantities never reach a buyer-facing payload (ADR-009). */
export const StockStatus = z.enum(["IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"]);
export type StockStatus = z.infer<typeof StockStatus>;

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const HealthResponse = z.object({
  status: z.string(),
  app: z.string(),
  version: z.string(),
  environment: z.string(),
  database: z.object({
    configured: z.boolean(),
    reachable: z.boolean(),
    error_kind: z.string().nullable(),
  }),
});
export type HealthResponse = z.infer<typeof HealthResponse>;

// ---------------------------------------------------------------------------
// Cart
// ---------------------------------------------------------------------------

export const CartItem = z.object({
  item_id: z.string().uuid(),
  variant_id: z.string().uuid(),
  product_id: z.string().uuid(),
  sku: z.string(),
  name: z.string(),
  variant_name: z.string(),
  quantity: z.number().int(),
  unit_price: Money,
  line_total: Money,
  currency: z.string(),
  stock_status: StockStatus,
  available: z.boolean(),
});
export type CartItem = z.infer<typeof CartItem>;

/**
 * A line whose live price differs from what the buyer last saw (ADR-014).
 *
 * Reported in **both directions**: a cheaper cart is still not the cart the
 * buyer agreed to, and an approval bound to the old total is stale either way.
 */
export const PriceChange = z.object({
  sku: z.string(),
  name: z.string(),
  previous_unit_price: Money,
  current_unit_price: Money,
  increased: z.boolean(),
});
export type PriceChange = z.infer<typeof PriceChange>;

export const Cart = z.object({
  cart_id: z.string().uuid(),
  cart_version: z.number().int(),
  status: z.string(),
  currency: z.string(),
  subtotal: Money,
  total: Money,
  items: z.array(CartItem),
  price_changes: z.array(PriceChange),
});
export type Cart = z.infer<typeof Cart>;

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export const ScoreBreakdown = z.object({
  final: z.string(),
  profile: z.string(),
  components: z.record(z.string()),
});

/**
 * One ranked product.
 *
 * Emitted by the ranking engine, never extracted from prose and never authored
 * by the model — `reason` in particular is the engine's own deterministic label.
 * **Render products from this array only.** A model that describes something it
 * was never shown produces a turn whose structured half does not contain it, and
 * the UI must then show nothing rather than the prose's claim (F§9).
 */
export const Recommendation = z.object({
  product_id: z.string().uuid(),
  variant_id: z.string().uuid(),
  sku: z.string(),
  name: z.string(),
  variant_name: z.string(),
  category: z.string(),
  price: Money,
  currency: z.string(),
  stock_status: StockStatus,
  attributes: z.record(z.unknown()),
  brand: z.string().nullable(),
  rank: z.number().int(),
  reason: z.string(),
  reason_code: z.string(),
  score: ScoreBreakdown.nullable(),
});
export type Recommendation = z.infer<typeof Recommendation>;

export const ChatResponse = z.object({
  session_id: z.string().uuid(),
  state: ConversationState,
  /** Natural language only. Carries no commerce fact. Never parsed. */
  message: z.string(),
  recommendations: z.array(Recommendation),
  cart: Cart.nullable(),
  trace: z.record(z.unknown()).nullable(),
  error: ApiError.nullable(),
});
export type ChatResponse = z.infer<typeof ChatResponse>;

// ---------------------------------------------------------------------------
// Approval
// ---------------------------------------------------------------------------

export const ApprovalResponse = z.object({
  approval_id: z.string().uuid(),
  status: z.string(),
  cart_version: z.number().int(),
  approved_total: Money,
  currency: z.string(),
  approved_at: z.string().nullable(),
  expires_at: z.string(),
  /**
   * Minted with the approval and bound to its exact state (ADR-013). The client
   * presents it on `POST /api/orders`; presenting it twice yields one order and
   * the same answer. It is **not** a header — it travels in the request body.
   */
  idempotency_key: z.string().nullable(),
  cart: Cart,
});
export type ApprovalResponse = z.infer<typeof ApprovalResponse>;

// ---------------------------------------------------------------------------
// Orders
// ---------------------------------------------------------------------------

export const OrderStatus = z.enum([
  "ORDER_CREATED",
  "RAZORPAY_ORDER_CREATED",
  "PAYMENT_PENDING",
  "PAYMENT_CONFIRMED",
  "PAYMENT_FAILED",
  "ORDER_FAILED",
  "CANCELLED",
]);
export type OrderStatus = z.infer<typeof OrderStatus>;

export const OrderResponse = z.object({
  order_id: z.string().uuid(),
  status: OrderStatus,
  total_amount: Money,
  /** Minor units, computed once at order creation. Display uses `total_amount`. */
  total_amount_minor: z.number().int(),
  currency: z.string(),
  /**
   * Null until Razorpay accepts the order (M11). An order in `ORDER_CREATED`
   * with this null is the state ADR-011 designs for, not a broken one.
   */
  razorpay_order_id: z.string().nullable(),
  /** Lets a client tell "I created this" from "this already existed". */
  replayed: z.boolean(),
});
export type OrderResponse = z.infer<typeof OrderResponse>;

/**
 * What the frontend needs to open Razorpay Checkout (P§21, RZP-03).
 *
 * `key` is the **public** key id. `RAZORPAY_KEY_SECRET` and
 * `RAZORPAY_WEBHOOK_SECRET` never appear in any response, and a backend test
 * asserts that by checking values rather than trusting a docstring.
 *
 * The success callback Razorpay invokes is **not payment truth** (ADR-012). Only
 * a verified webhook advances an order, so the UI re-reads the order afterwards
 * rather than believing the browser.
 */
export const CheckoutConfig = z.object({
  key: z.string(),
  razorpay_order_id: z.string(),
  /** Minor units — this is what Razorpay's SDK expects. Never displayed. */
  amount: z.number().int(),
  currency: z.string(),
  name: z.string(),
  receipt: z.string(),
});
export type CheckoutConfig = z.infer<typeof CheckoutConfig>;

/* ---------------------------------------------------------------------------
   Catalog browsing (added with the storefront)

   `CatalogItem` mirrors `Recommendation` field for field, minus the four
   members only a ranking can produce (`rank`, `reason`, `reason_code`,
   `score`). That is deliberate: one shape means a browsed product and an
   agent-recommended product render through the same component, which is what
   lets the concierge feel like part of the storefront rather than a panel
   bolted beside it.

   `ProductCard` below is the union both paths are narrowed to.
--------------------------------------------------------------------------- */

export const CategoryItem = z.object({
  id: z.string().uuid(),
  slug: z.string(),
  name: z.string(),
  parent_slug: z.string().nullable(),
});
export type CategoryItem = z.infer<typeof CategoryItem>;

export const CatalogItem = z.object({
  product_id: z.string().uuid(),
  variant_id: z.string().uuid(),
  product_slug: z.string(),
  sku: z.string(),
  name: z.string(),
  variant_name: z.string(),
  category: z.string(),
  price: Money,
  currency: z.string(),
  stock_status: StockStatus,
  attributes: z.record(z.unknown()),
  tags: z.array(z.string()),
  brand: z.string().nullable(),
  description: z.string().nullable(),
});
export type CatalogItem = z.infer<typeof CatalogItem>;

export const ProductListResponse = z.object({
  items: z.array(CatalogItem),
  total: z.number().int(),
  categories: z.array(CategoryItem),
});
export type ProductListResponse = z.infer<typeof ProductListResponse>;

export const ProductSummaryItem = z.object({
  id: z.string().uuid(),
  slug: z.string(),
  name: z.string(),
  category: z.string(),
  brand: z.string().nullable(),
  description: z.string().nullable(),
});
export type ProductSummaryItem = z.infer<typeof ProductSummaryItem>;

export const ProductDetailResponse = z.object({
  product: ProductSummaryItem,
  variants: z.array(CatalogItem),
  related: z.array(ProductSummaryItem),
});
export type ProductDetailResponse = z.infer<typeof ProductDetailResponse>;

export const CategoryList = z.array(CategoryItem);

/** A server-minted anonymous session id. Authorizes nothing on its own. */
export const SessionResponse = z.object({ session_id: z.string().uuid() });
export type SessionResponse = z.infer<typeof SessionResponse>;

// -- identity (ADR-023) ------------------------------------------------------

/**
 * A 204. `request()` reads the body as JSON and falls back to `null` when there
 * is none, so this is what an endpoint that answers nothing parses against —
 * rather than lying about a shape the server never sent.
 */
export const NoContent = z.null();

/**
 * The signed-in principal, as the server describes them.
 *
 * `role` is the **server's** answer, never a client decision: it arrives in a
 * response body and is used only to choose what to render. Every actual
 * authorization decision is made again, server-side, on the next request — so a
 * tampered value in the browser changes what a page looks like and nothing else.
 */
export const AuthUser = z.object({
  id: z.string().uuid(),
  email: z.string(),
  role: z.enum(["CUSTOMER", "MERCHANT"]),
  display_name: z.string().nullable().optional(),
  merchant_id: z.string().uuid().nullable().optional(),
});
export type AuthUser = z.infer<typeof AuthUser>;

/**
 * A successful sign-in. `session_claimed` false means the anonymous cart the
 * client was holding already belonged to somebody else, so the client should
 * start a fresh session rather than keep pointing at one it cannot read.
 */
export const AuthToken = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_at: z.string(),
  user: AuthUser,
  session_claimed: z.boolean(),
});
export type AuthToken = z.infer<typeof AuthToken>;

/** `/api/auth/session` answers `null` for an anonymous caller, never a 401. */
export const AuthSession = AuthUser.nullable();

export const MerchantMe = z.object({
  id: z.string().uuid(),
  email: z.string(),
  role: z.string(),
  display_name: z.string().nullable().optional(),
  merchant_id: z.string().uuid(),
  merchant_name: z.string(),
});
export type MerchantMe = z.infer<typeof MerchantMe>;

/** A page of the signed-in customer's own orders. */
export const AccountOrderPage = z.object({
  items: z.array(OrderResponse),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});
export type AccountOrderPage = z.infer<typeof AccountOrderPage>;
