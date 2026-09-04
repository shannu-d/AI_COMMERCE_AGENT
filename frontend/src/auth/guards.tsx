import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Skeleton } from "../components/primitives";
import { useAuth } from "./context";

/**
 * Route guards — **a rendering convenience, never a security boundary.**
 *
 * Everything these components do can be defeated by editing `sessionStorage`,
 * and defeating them buys nothing: the API answers 401 without a valid token and
 * 403 for the wrong role, and derives the merchant from `users.merchant_id`
 * rather than from anything a browser sends (ADR-023 §6). What guards buy is
 * that a visitor sees a sign-in page instead of a dashboard full of failed
 * requests.
 *
 * They wait for the boot call rather than redirecting on the first render.
 * Redirecting while `loading` is still true would bounce a signed-in visitor to
 * the login page on every refresh.
 */

function Waiting() {
  return (
    <div className="mx-auto w-full max-w-md space-y-3 px-4 py-16" aria-busy="true">
      <Skeleton className="h-8 w-1/2" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

/** A signed-in CUSTOMER, or a redirect to sign in and come back. */
export function RequireCustomer() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <Waiting />;
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  // A merchant administrator has no account area — the dashboard is not a
  // shopping surface, and `/api/account/orders` would answer 403.
  if (user.role !== "CUSTOMER") return <Navigate to="/merchant" replace />;
  return <Outlet />;
}

/** A signed-in MERCHANT, or the dashboard's own sign-in page. */
export function RequireMerchant() {
  const { user, loading } = useAuth();

  if (loading) return <Waiting />;
  if (!user) return <Navigate to="/merchant/login" replace />;
  if (user.role !== "MERCHANT") return <Navigate to="/" replace />;
  return <Outlet />;
}
