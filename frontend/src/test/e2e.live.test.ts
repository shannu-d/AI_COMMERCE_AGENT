import { describe, expect, it } from "vitest";
import {
  addCartItem,
  approveCart,
  createOrder,
  getCart,
  getHealth,
  sendChat,
} from "../api/endpoints";
import { Cart, ChatResponse } from "../api/schemas";

/**
 * The flagship scenario, end to end, against a REAL running backend.
 *
 * Opt-in only: `E2E_BASE_URL=http://127.0.0.1:8001 npx vitest run e2e.live`.
 * It is excluded from the default suite because it needs a server, a seeded
 * database and a live model — none of which CI has, and the last of which
 * ADR-015 forbids the ordinary suite from touching.
 *
 * What it proves that a mocked test cannot: that the Zod schemas match what the
 * backend actually emits, field for field, on every step of the money path.
 */

const BASE = process.env["E2E_BASE_URL"];
const describeLive = BASE ? describe : describe.skip;

describeLive("the flagship scenario, live", () => {
  it("goes chat -> recommendation -> cart -> approval -> order", async () => {
    // 1. The API is reachable and its shape is what the schema says.
    const health = await getHealth();
    expect(health.status).toBe("ok");
    expect(health.database.reachable).toBe(true);

    // 2. A conversational turn. The response is parsed by the real schema, so a
    //    drift in any of ChatResponse's fields fails here.
    const turn: ChatResponse = await sendChat({
      session_id: null,
      message: "Find me a case for my iPhone 16 under 1500 rupees",
    });
    expect(turn.session_id).toBeTruthy();

    // The turn may legitimately be rate-limited by the provider's free tier;
    // that is a real state, not a failure of this contract.
    if (turn.error) {
      expect(turn.error.code).toBe("SERVER_ERROR");
      return;
    }

    expect(turn.recommendations.length).toBeGreaterThan(0);
    const first = turn.recommendations[0]!;
    // Money is a fixed-scale string, all the way from PostgreSQL.
    expect(first.price).toMatch(/^\d+\.\d{2}$/);

    // 3. Add to cart by variant id. No price is ever sent.
    const afterAdd: Cart = await addCartItem({
      session_id: turn.session_id,
      variant_id: first.variant_id,
      quantity: 1,
    });
    expect(afterAdd.items.length).toBe(1);
    expect(afterAdd.total).toMatch(/^\d+\.\d{2}$/);

    // 4. The cart reads back identically.
    const reread = await getCart(turn.session_id);
    expect(reread.cart_version).toBe(afterAdd.cart_version);
    expect(reread.total).toBe(afterAdd.total);

    // 5. Approve exactly what was displayed.
    const approval = await approveCart({
      session_id: turn.session_id,
      cart_version: reread.cart_version,
      expected_total: reread.total,
    });
    expect(approval.approved_total).toBe(reread.total);
    expect(approval.idempotency_key).toBeTruthy();

    // 6. Create the order with the backend-minted key.
    const order = await createOrder({
      session_id: turn.session_id,
      cart_id: reread.cart_id,
      cart_version: approval.cart_version,
      idempotency_key: approval.idempotency_key!,
    });
    expect(order.total_amount).toBe(reread.total);
    expect(order.replayed).toBe(false);

    // 7. ADR-013: presenting the same key again yields ONE order, not a second.
    const replay = await createOrder({
      session_id: turn.session_id,
      cart_id: reread.cart_id,
      cart_version: approval.cart_version,
      idempotency_key: approval.idempotency_key!,
    });
    expect(replay.order_id).toBe(order.order_id);
    expect(replay.replayed).toBe(true);
  }, 120_000);
});
