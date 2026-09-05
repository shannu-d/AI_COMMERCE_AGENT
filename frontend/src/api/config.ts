/**
 * Where the backend lives.
 *
 * A base URL is the only thing about the API that may be configured from the
 * browser side. **No secret may ever be put in a `VITE_` variable** — Vite
 * inlines them into the bundle at build time, so a `VITE_`-prefixed secret is a
 * published secret (ADR-017, ADR-018). The backend holds `GROQ_API_KEY`,
 * `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET`; the only credential that
 * ever reaches this code is the *public* Razorpay key id, and it arrives in a
 * response body at checkout time rather than from configuration.
 */
//
// The fallback is **:8004, the port the runbook starts the backend on** - not
// :8000. Port 8000 is the FastAPI default and was the fallback here, which made
// a checkout that skipped the `frontend/.env` step fail against whatever else
// happened to be listening. `frontend/.env` is git-ignored, so the fallback is
// what a fresh clone actually uses.
export const API_BASE_URL: string =
  import.meta.env["VITE_API_BASE_URL"] ?? "http://127.0.0.1:8004";
