import type { CheckoutConfig } from "../../api/schemas";

/**
 * Razorpay Checkout, loaded the way Razorpay ships it.
 *
 * Their web SDK is a script tag that defines `window.Razorpay`, not an npm
 * package, so it is injected once and cached.
 *
 * **The success callback is not payment truth** (P§28, ADR-012). Razorpay calls
 * it in the browser, where anything can call anything; only a signature-verified
 * webhook advances an order past `RAZORPAY_ORDER_CREATED`. So the callback here
 * does exactly one thing — tell the caller to go and re-read the order from the
 * backend. It never marks anything paid.
 *
 * The only credential involved is the **public** key id, handed over per request
 * by `POST /orders/{id}/checkout`. No secret exists in this file, this bundle, or
 * any `VITE_` variable.
 */

const SDK_URL = "https://checkout.razorpay.com/v1/checkout.js";

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}

let loader: Promise<void> | null = null;

export function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  if (loader) return loader;

  loader = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SDK_URL;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      loader = null;
      reject(new Error("Could not load the payment provider."));
    };
    document.head.appendChild(script);
  });
  return loader;
}

export type CheckoutOutcome =
  | { kind: "closed" }
  | { kind: "submitted"; razorpay_payment_id: string | null };

/**
 * Opens Checkout and resolves when the buyer leaves it.
 *
 * `submitted` means the buyer completed the provider's flow — **not** that the
 * payment succeeded. The caller re-reads the order; the webhook decides.
 */
export async function openCheckout(config: CheckoutConfig): Promise<CheckoutOutcome> {
  await loadRazorpay();
  const Razorpay = window.Razorpay;
  if (!Razorpay) throw new Error("The payment provider did not initialise.");

  return new Promise<CheckoutOutcome>((resolve) => {
    let settled = false;
    const settle = (outcome: CheckoutOutcome) => {
      if (!settled) {
        settled = true;
        resolve(outcome);
      }
    };

    const checkout = new Razorpay({
      key: config.key,
      order_id: config.razorpay_order_id,
      // Minor units, straight from the backend. Never computed here, and never
      // displayed — the buyer sees `total_amount`, the fixed-scale string.
      amount: config.amount,
      currency: config.currency,
      name: config.name,
      description: `Order ${config.receipt}`,
      handler: (response: { razorpay_payment_id?: string }) =>
        settle({ kind: "submitted", razorpay_payment_id: response.razorpay_payment_id ?? null }),
      modal: { ondismiss: () => settle({ kind: "closed" }) },
      theme: { color: "#1d4ed8" },
    });

    checkout.open();
  });
}
