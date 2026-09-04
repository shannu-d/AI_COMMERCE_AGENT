import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
} from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { RequireCustomer, RequireMerchant } from "./auth/guards";
import { AgentRuntimeProvider } from "./features/agent/AgentRuntimeProvider";
import { ConciergeProvider } from "./features/concierge/Concierge";
import { MerchantShell } from "./features/merchant/MerchantShell";
import { Shell } from "./layout/Shell";
import { AccountPage } from "./pages/AccountPage";
import { AgentPage } from "./pages/AgentPage";
import { CartPage } from "./pages/CartPage";
import { CategoryPage } from "./pages/CategoryPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OrderPage } from "./pages/OrderPage";
import { ProductPage } from "./pages/ProductPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ActivityPage } from "./pages/merchant/ActivityPage";
import { CategoriesPage } from "./pages/merchant/CategoriesPage";
import { InventoryPage } from "./pages/merchant/InventoryPage";
import { MerchantLoginPage } from "./pages/merchant/MerchantLoginPage";
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
 *
 * `AuthProvider` wraps the router so a sign-in survives navigation, and the two
 * `Require*` guards decide which pages are worth *drawing*. They are not the
 * authorization boundary — the API refuses an unauthenticated or wrong-role
 * caller regardless of what the browser believes (ADR-023 §6). The sign-in pages
 * sit **outside** their guards, or a signed-out visitor would be redirected in a
 * loop.
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
    <BrowserRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <AuthProvider>
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
                <Route path="/login" element={<LoginPage />} />
                <Route path="/register" element={<RegisterPage />} />
                <Route element={<RequireCustomer />}>
                  <Route path="/account" element={<AccountPage />} />
                </Route>
                <Route path="*" element={<NotFoundPage />} />
              </Route>

              <Route path="/merchant/login" element={<MerchantLoginPage />} />

              <Route element={<RequireMerchant />}>
                <Route path="/merchant" element={<MerchantShell />}>
                  <Route index element={<OverviewPage />} />
                  <Route path="products" element={<ProductsPage />} />
                  <Route path="products/new" element={<ProductEditorPage />} />
                  <Route
                    path="products/:productId"
                    element={<ProductEditorPage />}
                  />
                  <Route path="inventory" element={<InventoryPage />} />
                  <Route path="orders" element={<OrdersPage />} />
                  <Route path="orders/:orderId" element={<OrderDetailPage />} />
                  <Route path="categories" element={<CategoriesPage />} />
                <Route path="activity" element={<ActivityPage />} />
                  <Route path="settings" element={<SettingsPage />} />
                  <Route
                    path="*"
                    element={<Navigate to="/merchant" replace />}
                  />
                </Route>
              </Route>
            </Routes>
          </ConciergeProvider>
        </AgentRuntimeProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
