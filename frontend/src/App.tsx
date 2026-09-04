import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AgentRuntimeProvider } from "./features/agent/AgentRuntimeProvider";
import { ConciergeProvider } from "./features/concierge/Concierge";
import { MerchantShell } from "./features/merchant/MerchantShell";
import { Shell } from "./layout/Shell";
import { AgentPage } from "./pages/AgentPage";
import { CartPage } from "./pages/CartPage";
import { CategoryPage } from "./pages/CategoryPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OrderPage } from "./pages/OrderPage";
import { ProductPage } from "./pages/ProductPage";
import { CategoriesPage } from "./pages/merchant/CategoriesPage";
import { InventoryPage } from "./pages/merchant/InventoryPage";
import { OrderDetailPage, OrdersPage } from "./pages/merchant/OrdersPage";
import { OverviewPage } from "./pages/merchant/OverviewPage";
import { ProductEditorPage } from "./pages/merchant/ProductEditorPage";
import { ProductsPage } from "./pages/merchant/ProductsPage";
import { SettingsPage } from "./pages/merchant/SettingsPage";

/**
 * Routes, and the provider order that makes the concierge work.
 *
 * `AgentRuntimeProvider` sits **above** the router on purpose: the conversation
 * is owned by the runtime, so navigating from a product page to the cart does
 * not discard it. An assistant that forgot the conversation every time you
 * looked at something would not be a shopping concierge.
 *
 * The application has two shells. `Shell` is the storefront — header, category
 * bar, docked concierge rail. `MerchantShell` is the dashboard — a sidebar and a
 * workspace, no concierge, no cart. They are sibling layout routes rather than
 * one shell with a mode flag, because they are genuinely two products for two
 * people (ADR-022).
 */
function StorefrontLayout() {
  return (
    <Shell>
      <Outlet />
    </Shell>
  );
}

export function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AgentRuntimeProvider>
        <ConciergeProvider>
          <Routes>
            <Route element={<StorefrontLayout />}>
              <Route path="/" element={<HomePage />} />
              <Route path="/agent" element={<AgentPage />} />
              <Route path="/c/:slug" element={<CategoryPage />} />
              <Route path="/p/:slug" element={<ProductPage />} />
              <Route path="/cart" element={<CartPage />} />
              <Route path="/orders/:orderId" element={<OrderPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>

            <Route path="/merchant" element={<MerchantShell />}>
              <Route index element={<OverviewPage />} />
              <Route path="products" element={<ProductsPage />} />
              <Route path="products/new" element={<ProductEditorPage />} />
              <Route path="products/:productId" element={<ProductEditorPage />} />
              <Route path="inventory" element={<InventoryPage />} />
              <Route path="orders" element={<OrdersPage />} />
              <Route path="orders/:orderId" element={<OrderDetailPage />} />
              <Route path="categories" element={<CategoriesPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/merchant" replace />} />
            </Route>
          </Routes>
        </ConciergeProvider>
      </AgentRuntimeProvider>
    </BrowserRouter>
  );
}
