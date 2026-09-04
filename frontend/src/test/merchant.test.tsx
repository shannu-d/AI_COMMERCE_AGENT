import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";

import { renderWithProviders } from "./render";
import { MerchantShell } from "../features/merchant/MerchantShell";
import { OverviewPage } from "../pages/merchant/OverviewPage";
import { ProductsPage } from "../pages/merchant/ProductsPage";
import { ProductEditorPage } from "../pages/merchant/ProductEditorPage";
import { InventoryPage } from "../pages/merchant/InventoryPage";

/**
 * The merchant dashboard against a stubbed API.
 *
 * The properties under test: real numbers render (no placeholders), a create
 * form submits a string price and a category to the merchant API, an inventory
 * edit `PATCH`es the validated endpoint, and the failure/empty branches show
 * something sensible.
 */

type Call = { url: string; method: string; body: Record<string, unknown> | undefined };
let calls: Call[];

function stub(handler: (url: string, method: string) => { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const { status, body } = handler(String(url), init?.method ?? "GET");
      return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
    }),
  );
}

const OVERVIEW = {
  currency: "INR",
  total_products: 51,
  active_products: 50,
  archived_products: 1,
  total_variants: 216,
  active_variants: 210,
  total_inventory_units: 2680,
  out_of_stock_variants: 9,
  low_stock_variants: 22,
  category_count: 24,
  total_orders: 3,
  paid_orders: 1,
  revenue: "4499.00",
};

const CATEGORIES = [
  { id: "11111111-1111-4111-8111-111111111111", slug: "clothing", name: "Clothing", parent_slug: null },
  { id: "22222222-2222-4222-8222-222222222222", slug: "t_shirt", name: "T-Shirts", parent_slug: "clothing" },
];

const VARIANT = {
  variant_id: "33333333-3333-4333-8333-333333333333",
  product_id: "44444444-4444-4444-8444-444444444444",
  product_slug: "everyday_cotton_crew",
  product_name: "Everyday Cotton Crew Tee",
  variant_name: "Black / M",
  sku: "TSHIRT-CREW-BLK-M",
  category: "t_shirt",
  price: "799.00",
  currency: "INR",
  quantity: 4,
  reserved_quantity: 0,
  available_quantity: 4,
  stock_status: "LOW_STOCK",
  product_active: true,
  variant_active: true,
  attributes: { color: "black", size: "m" },
};

const PRODUCT_LIST = { items: [VARIANT], total: 1, limit: 25, offset: 0 };

beforeEach(() => {
  calls = [];
});
afterEach(() => vi.unstubAllGlobals());

describe("Overview", () => {
  it("renders the real aggregates, not placeholders", async () => {
    stub(() => ({ status: 200, body: OVERVIEW }));
    renderWithProviders(<OverviewPage />, { route: "/merchant" });

    expect(await screen.findByText("50")).toBeInTheDocument(); // active products
    expect(screen.getByText("216 SKUs")).toBeInTheDocument();
    // Money renders in split text nodes; assert on the composed text.
    expect(
      screen.getByText((_, el) => el?.textContent === "₹4,499.00" && el.tagName === "SPAN"),
    ).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument(); // out of stock tile
  });

  it("shows a retry affordance when the API fails", async () => {
    stub(() => ({ status: 500, body: { detail: "boom" } }));
    renderWithProviders(<OverviewPage />, { route: "/merchant" });
    expect(await screen.findByText(/could not load the dashboard/i)).toBeInTheDocument();
  });
});

describe("Products", () => {
  it("lists variants from the merchant API", async () => {
    stub((url) => {
      if (url.includes("/categories")) return { status: 200, body: CATEGORIES };
      return { status: 200, body: PRODUCT_LIST };
    });
    renderWithProviders(<ProductsPage />, { route: "/merchant/products" });

    // jsdom renders both the desktop table and the mobile card list (no CSS),
    // so each cell appears twice — assert presence, not uniqueness.
    expect((await screen.findAllByText("Everyday Cotton Crew Tee")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("TSHIRT-CREW-BLK-M").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText((_, el) => el?.textContent === "₹799.00").length,
    ).toBeGreaterThan(0);
  });

  it("renders the empty state when nothing matches", async () => {
    stub((url) =>
      url.includes("/categories")
        ? { status: 200, body: CATEGORIES }
        : { status: 200, body: { items: [], total: 0, limit: 25, offset: 0 } },
    );
    renderWithProviders(<ProductsPage />, { route: "/merchant/products" });
    expect(await screen.findByText(/no products match/i)).toBeInTheDocument();
  });
});

describe("Product create form", () => {
  it("submits a string price and category to the merchant API", async () => {
    const user = userEvent.setup();
    stub((url, method) => {
      if (url.includes("/categories")) return { status: 200, body: CATEGORIES };
      if (method === "POST" && url.endsWith("/api/merchant/products")) {
        return {
          status: 201,
          body: {
            product_id: VARIANT.product_id,
            slug: "new_thing",
            name: "New Thing",
            category: "t_shirt",
            description: null,
            brand: null,
            is_active: true,
            attributes: {},
            tags: [],
            variants: [VARIANT],
          },
        };
      }
      return { status: 200, body: {} };
    });

    renderWithProviders(
      <Routes>
        <Route path="/merchant" element={<MerchantShell />}>
          <Route path="products/new" element={<ProductEditorPage />} />
          <Route path="products/:productId" element={<div>editor</div>} />
        </Route>
      </Routes>,
      { route: "/merchant/products/new" },
    );

    await user.type(await screen.findByLabelText(/^name/i), "New Thing");
    await user.selectOptions(screen.getByLabelText(/^category/i), "t_shirt");
    await user.type(screen.getByLabelText(/^sku/i), "new-thing-1");
    await user.type(screen.getByLabelText(/price/i), "1299.00");
    await user.click(screen.getByRole("button", { name: /create product/i }));

    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/api/merchant/products"),
      );
      expect(post).toBeDefined();
      expect(post!.body).toMatchObject({ name: "New Thing", category: "t_shirt" });
      // SKU upper-cased, price kept as a string.
      const v = (post!.body!.variants as Array<Record<string, unknown>>)[0]!;
      expect(v.sku).toBe("NEW-THING-1");
      expect(v.price).toBe("1299.00");
      expect(typeof v.price).toBe("string");
    });
    // No merchant_id anywhere in the request.
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.stringify(post!.body)).not.toMatch(/merchant_id/);
  });
});

describe("Inventory", () => {
  it("PATCHes the validated stock endpoint on edit", async () => {
    const user = userEvent.setup();
    stub((_url, method) => {
      if (method === "PATCH")
        return {
          status: 200,
          body: { ...VARIANT, quantity: 0, available_quantity: 0, stock_status: "OUT_OF_STOCK" },
        };
      return { status: 200, body: PRODUCT_LIST };
    });
    renderWithProviders(<InventoryPage />, { route: "/merchant/inventory" });

    // Both the desktop and mobile rows render in jsdom; edit the first.
    const input = (await screen.findAllByDisplayValue("4"))[0]!;
    await user.clear(input);
    await user.type(input, "0");
    await user.tab();

    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH");
      expect(patch?.url).toContain(`/api/merchant/inventory/${VARIANT.variant_id}`);
      expect(patch?.body).toEqual({ quantity: 0 });
    });
  });
});

describe("the dashboard shell", () => {
  it("links back to the storefront and has no cart or concierge", async () => {
    stub(() => ({ status: 200, body: OVERVIEW }));
    renderWithProviders(
      <Routes>
        <Route path="/merchant" element={<MerchantShell />}>
          <Route index element={<OverviewPage />} />
        </Route>
      </Routes>,
      { route: "/merchant" },
    );
    const nav = await screen.findByRole("navigation", { name: /dashboard/i });
    expect(within(nav).getByText("Products")).toBeInTheDocument();
    expect(screen.getByText(/view storefront/i)).toBeInTheDocument();
    expect(screen.queryByText(/concierge/i)).not.toBeInTheDocument();
  });
});
