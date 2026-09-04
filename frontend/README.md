# EASY BUY frontend

React 18 + TypeScript on Vite (ADR-017). Chat, recommendations, cart, checkout, order status,
sign-in, and the merchant dashboard — see the repo root [`README.md`](../README.md) and
[`docs/SUBMISSION.md`](../docs/SUBMISSION.md) for the full picture.

```bash
npm install
echo "VITE_API_BASE_URL=http://127.0.0.1:8004" > .env   # git-ignored; see .env.example
npm run dev -- --host 127.0.0.1 --port 5173
npm run test        # vitest
npm run typecheck
npm run build
```

The backend must be running on the same port and must list this origin in
`CORS_ALLOWED_ORIGINS`:

```bash
cd ../backend && uvicorn app.main:app --host 127.0.0.1 --port 8004
```

Port 8000 may be occupied by an unrelated application on the build machine — this project
deliberately runs on 8004. If the health panel says the response was malformed, check **what is
actually listening on the port** `VITE_API_BASE_URL` points at.

## Rules this code follows

- **Money is a string, always** (`"999.00"`). Nothing here sums, multiplies or rounds a money
  value; totals come from the backend or they do not exist (ADR-008, F§12).
- **No secret ever lives here.** A backend test fails the build if one appears (ADR-017, ADR-018).
- **No global commerce store.** Cart, approval and order truth live in backend responses;
  a second client-side copy is the failure F§5 and F§29 warn about.
- **Every response is parsed through a Zod schema** at the fetch boundary, so contract drift is a
  loud error rather than an `undefined` deep in a component.
- **A business outcome is not a network error.** Policy refusals and out-of-stock findings arrive
  as an `error` body on HTTP 200 (ADR-010) and must render as recovery flows, not crashes.
