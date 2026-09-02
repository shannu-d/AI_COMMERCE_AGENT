import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ShopPage } from "./pages/ShopPage";
import { OrderPage } from "./pages/OrderPage";

/**
 * Two routes. The order page is separate so its URL can be saved and returned
 * to — a buyer who closes the tab while a webhook is still in flight has
 * somewhere to come back to, which is the whole reason F§33 asks for it.
 */
export function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/" element={<ShopPage />} />
        <Route path="/orders/:orderId" element={<OrderPage />} />
        <Route path="*" element={<ShopPage />} />
      </Routes>
    </BrowserRouter>
  );
}
