import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./render";
import { Money } from "../components/Money";
import { CartPanel } from "../features/cart/CartPanel";
import { ApprovalDialog } from "../features/checkout/ApprovalDialog";
import { ChatWindow } from "../features/chat/ChatWindow";
import type { Turn } from "../features/chat/useChat";
import { approval, cart, chatTurn, order, aeroCase } from "./fixtures";

/**
 * The architectural invariants, asserted through the UI.
 *
 * These are not "does the button render" tests. Each one corresponds to a rule
 * the specification states and that a well-meaning change is likely to break.
 */

let calls: Array<{ url: string; method: string; body: unknown }>;

function stubFetch(handler: (url: string, init?: RequestInit) => { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const { status, body } = handler(String(url), init);
      return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
      } as Response;
    }),
  );
}

beforeEach(() => {
  calls = [];
});
afterEach(() => vi.unstubAllGlobals());

// ---------------------------------------------------------------------------

describe("money is displayed, never computed (ADR-008, F§12)", () => {
  it("renders the backend's fixed-scale string verbatim", () => {
    const { container } = renderWithProviders(<Money amount="1299.00" />);

    expect(container.textContent).toBe("₹1,299.00");
  });

  it("groups Indian-style, because the catalogue is priced in INR", () => {
    const { container } = renderWithProviders(<Money amount="1234567.00" />);

    // 12,34,567 — not 1,234,567.
    expect(container.textContent).toBe("₹12,34,567.00");
  });

  it("keeps trailing zeros, so a total never renders as ₹1299", () => {
    const { container } = renderWithProviders(<Money amount="1299.50" />);

    expect(container.textContent).toBe("₹1,299.50");
  });
});

describe("the cart never computes a total (F§12, F§29)", () => {
  it("shows the backend's total even when it disagrees with the line items", async () => {
    // A deliberately inconsistent cart: the lines sum to 1998.00 but the backend
    // says 1500.00 (a discount this frontend knows nothing about). The UI must
    // show what the backend said. If it ever renders 1998.00 here, something is
    // summing line items — the exact failure this test exists to catch.
    const discounted = { ...cart, total: "1500.00" };
    stubFetch(() => ({ status: 200, body: discounted }));

    renderWithProviders(<CartPanel sessionId="s-1" onApprove={() => {}} />);

    // Scope to the Total row: the line total legitimately renders 1,998.00, and
    // the point is that the *total* is the backend's number and not their sum.
    const totalTerm = await screen.findByText("Total");
    const totalValue = totalTerm.nextElementSibling;

    expect(totalValue).toHaveTextContent("₹1,500.00");
    expect(totalValue).not.toHaveTextContent("₹1,998.00");
  });
});

describe("products come from recommendations[], never from prose (F§9)", () => {
  it("renders nothing when the model describes a product it was not shown", () => {
    const turns: Turn[] = [
      {
        kind: "agent",
        id: "a1",
        // The model invents a product in prose.
        text: "I recommend the TitanCase Ultra at ₹499 — a great deal!",
        state: "RECOMMENDING",
        recommendations: [], // ...but the structured half is empty.
        error: null,
      },
    ];

    renderWithProviders(
      <ChatWindow turns={turns} pending={false} sessionId="s-1" onSend={() => {}} />,
    );

    // The prose is shown as prose; no product card is fabricated from it.
    expect(screen.getByText(/TitanCase Ultra/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add to cart/i })).not.toBeInTheDocument();
  });

  it("renders a card per structured recommendation", () => {
    const turns: Turn[] = [
      {
        kind: "agent",
        id: "a1",
        text: chatTurn().message,
        state: "RECOMMENDING",
        recommendations: chatTurn().recommendations,
        error: null,
      },
    ];

    renderWithProviders(
      <ChatWindow turns={turns} pending={false} sessionId="s-1" onSend={() => {}} />,
    );

    expect(screen.getByText("AeroCase Pro")).toBeInTheDocument();
    expect(screen.getByText("ShieldCase Premium")).toBeInTheDocument();
    // The engine's own deterministic label, not model prose.
    expect(screen.getByText("Best overall")).toBeInTheDocument();
  });
});

describe("a business outcome on HTTP 200 is a recovery flow, not a crash (ADR-010)", () => {
  it("renders a policy refusal as guidance with a next step", () => {
    const turns: Turn[] = [
      {
        kind: "agent",
        id: "a1",
        text: "",
        state: "POLICY_REJECTED",
        recommendations: [],
        error: { code: "POLICY_FAILED", message: "spending limit exceeded", details: {} },
      },
    ];

    renderWithProviders(
      <ChatWindow turns={turns} pending={false} sessionId="s-1" onSend={() => {}} />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/refused/i);
  });

  it("gives out-of-stock different copy from a policy refusal", () => {
    const turns: Turn[] = [
      {
        kind: "agent",
        id: "a1",
        text: "",
        state: "OUT_OF_STOCK",
        recommendations: [],
        error: { code: "OUT_OF_STOCK", message: "gone", details: {} },
      },
    ];

    renderWithProviders(
      <ChatWindow turns={turns} pending={false} sessionId="s-1" onSend={() => {}} />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/out of stock/i);
  });
});

describe("approval binds to what the buyer saw (ADR-007, A§26/A§27)", () => {
  it("submits the displayed cart_version and total, not a recomputed one", async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url.includes("/cart/approve")) return { status: 200, body: approval };
      if (url.includes("/orders")) return { status: 201, body: order };
      return { status: 200, body: cart };
    });

    renderWithProviders(
      <ApprovalDialog cart={cart} sessionId="s-1" onClose={() => {}} onOrdered={() => {}} />,
    );

    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      const approve = calls.find((c) => c.url.includes("/cart/approve"));
      expect(approve?.body).toEqual({
        session_id: "s-1",
        cart_version: 3,
        // The exact string the screen rendered — never parsed to a number.
        expected_total: "1998.00",
      });
    });
  });

  it("presents the backend's idempotency key in the ORDER BODY, not a header (ADR-013)", async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url.includes("/cart/approve")) return { status: 200, body: approval };
      return { status: 201, body: order };
    });

    renderWithProviders(
      <ApprovalDialog cart={cart} sessionId="s-1" onClose={() => {}} onOrdered={() => {}} />,
    );

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByRole("button", { name: "Place order" });
    await user.click(screen.getByRole("button", { name: "Place order" }));

    await waitFor(() => {
      const create = calls.find((c) => c.url.endsWith("/api/orders"));
      expect(create?.body).toMatchObject({
        idempotency_key: "idem-key-bound-to-version-3",
        cart_version: 3,
      });
    });
  });

  it("explains a 409 as a stale view rather than a generic failure", async () => {
    const user = userEvent.setup();
    stubFetch(() => ({
      status: 409,
      body: { detail: { code: "PRICE_CHANGED", message: "stale", details: {} } },
    }));

    renderWithProviders(
      <ApprovalDialog cart={cart} sessionId="s-1" onClose={() => {}} onOrdered={() => {}} />,
    );

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/changed while you were reviewing/i);
  });

  it("never sends a price when adding to the cart (ADR-009)", async () => {
    const user = userEvent.setup();
    stubFetch(() => ({ status: 200, body: cart }));

    const turns: Turn[] = [
      { kind: "agent", id: "a1", text: "", state: "RECOMMENDING", recommendations: [aeroCase], error: null },
    ];
    renderWithProviders(
      <ChatWindow turns={turns} pending={false} sessionId="s-1" onSend={() => {}} />,
    );

    await user.click(screen.getByRole("button", { name: /add to cart/i }));

    await waitFor(() => {
      const add = calls.find((c) => c.url.includes("/cart/items"));
      expect(add?.body).toEqual({ session_id: "s-1", variant_id: aeroCase.variant_id, quantity: 1 });
      // No price, no name, no total: a variant id is a lookup key, not a fact.
      expect(JSON.stringify(add?.body)).not.toContain("999");
    });
  });
});

describe("price drift is surfaced in both directions (ADR-014)", () => {
  it("shows a decrease as prominently as an increase", async () => {
    stubFetch(() => ({
      status: 200,
      body: {
        ...cart,
        price_changes: [
          {
            sku: "CC-CASE-AERO-BLK",
            name: "AeroCase Pro",
            previous_unit_price: "1199.00",
            current_unit_price: "999.00",
            increased: false,
          },
        ],
      },
    }));

    renderWithProviders(<CartPanel sessionId="s-1" onApprove={() => {}} />);

    expect(await screen.findByText(/a price changed/i)).toBeInTheDocument();
    expect(screen.getByText(/decreased/)).toBeInTheDocument();
    expect(screen.getByText(/no longer applies/i)).toBeInTheDocument();
  });
});
