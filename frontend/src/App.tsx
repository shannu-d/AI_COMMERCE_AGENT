import { BrowserRouter, Outlet, Route, Routes } from "react-router-dom";

import { AgentRuntimeProvider } from "./features/agent/AgentRuntimeProvider";
import { ConciergeProvider } from "./features/concierge/Concierge";
import { Shell } from "./layout/Shell";
import { AgentPage } from "./pages/AgentPage";
import { CartPage } from "./pages/CartPage";
import { CategoryPage } from "./pages/CategoryPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OrderPage } from "./pages/OrderPage";
import { ProductPage } from "./pages/ProductPage";

/**
 * Routes, and the provider order that makes the concierge work.
 *
 * `AgentRuntimeProvider` sits **above** the router on purpose: the conversation
 * is owned by the runtime, so navigating from a product page to the cart does
 * not discard it. An assistant that forgot the conversation every time you
 * looked at something would not be a shopping concierge.
 *
 * `Shell` is the storefront layout — header, category bar, docked concierge
 * rail — applied as a layout route so every page renders inside it.
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
          </Routes>
        </ConciergeProvider>
      </AgentRuntimeProvider>
    </BrowserRouter>
  );
}
