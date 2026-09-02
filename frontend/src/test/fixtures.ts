import type {
  ApprovalResponse,
  Cart,
  ChatResponse,
  OrderResponse,
  Recommendation,
} from "../api/schemas";

/**
 * Fixtures shaped like the real backend's responses.
 *
 * The prices are the seeded catalogue's actual values, and the R§10 worked
 * example's products, so a test that renders them is rendering something the
 * backend really produces rather than a plausible invention.
 */

export const aeroCase: Recommendation = {
  product_id: "11111111-1111-5111-8111-111111111111",
  variant_id: "22222222-2222-5222-8222-222222222222",
  sku: "CC-CASE-AERO-BLK",
  name: "AeroCase Pro",
  variant_name: "Black",
  category: "phone_case",
  price: "999.00",
  currency: "INR",
  stock_status: "IN_STOCK",
  attributes: { material: "polycarbonate", colour: "black" },
  brand: "CircuitCraft",
  rank: 1,
  reason: "Best overall",
  reason_code: "BEST_OVERALL",
  score: null,
};

export const shieldCase: Recommendation = {
  ...aeroCase,
  product_id: "33333333-3333-5333-8333-333333333333",
  variant_id: "44444444-4444-5444-8444-444444444444",
  sku: "CC-CASE-SHIELD-BLK",
  name: "ShieldCase Premium",
  price: "1299.00",
  stock_status: "LOW_STOCK",
  rank: 2,
  reason: "Closest match to your requirements",
  reason_code: "CLOSEST_MATCH",
};

export const cart: Cart = {
  cart_id: "55555555-5555-5555-8555-555555555555",
  cart_version: 3,
  status: "ACTIVE",
  currency: "INR",
  subtotal: "1998.00",
  total: "1998.00",
  items: [
    {
      item_id: "66666666-6666-5666-8666-666666666666",
      variant_id: aeroCase.variant_id,
      product_id: aeroCase.product_id,
      sku: aeroCase.sku,
      name: aeroCase.name,
      variant_name: "Black",
      quantity: 2,
      unit_price: "999.00",
      line_total: "1998.00",
      currency: "INR",
      stock_status: "IN_STOCK",
      available: true,
    },
  ],
  price_changes: [],
};

export const chatTurn = (over: Partial<ChatResponse> = {}): ChatResponse => ({
  session_id: "77777777-7777-5777-8777-777777777777",
  state: "RECOMMENDING",
  message: "Here are three cases that fit an iPhone 16 under ₹1500.",
  recommendations: [aeroCase, shieldCase],
  cart: null,
  trace: null,
  error: null,
  ...over,
});

export const approval: ApprovalResponse = {
  approval_id: "88888888-8888-5888-8888-888888888888",
  status: "APPROVED",
  cart_version: 3,
  approved_total: "1998.00",
  currency: "INR",
  approved_at: "2026-09-02T12:00:00Z",
  expires_at: "2026-09-02T12:15:00Z",
  idempotency_key: "idem-key-bound-to-version-3",
  cart,
};

export const order: OrderResponse = {
  order_id: "99999999-9999-5999-8999-999999999999",
  status: "ORDER_CREATED",
  total_amount: "1998.00",
  total_amount_minor: 199800,
  currency: "INR",
  razorpay_order_id: null,
  replayed: false,
};
