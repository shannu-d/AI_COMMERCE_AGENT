# Runbook — bringing the whole system up

Everything runs locally. Ports are fixed because CORS and the Razorpay webhook
depend on them.

| Service | Port | Command (from `backend/` unless noted) |
| --- | --- | --- |
| PostgreSQL | 5432 | `docker compose up -d db` (repo root), or any local PG 16 |
| Backend API | **8004** | `.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8004` |
| Frontend | **5173** | `cd frontend && npm run dev -- --host 127.0.0.1 --port 5173` |
| MCP server (AI buyers) | **8005** | `.venv/Scripts/python -m app.mcp` |
| ngrok (Razorpay webhooks) | 4040 | `ngrok http 8004 --domain=<your-reserved-domain>` |

> Port **8000** is used by an unrelated app on the build machine — do not use it.
> The backend deliberately runs on 8004.

---

## 1. One-time setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"

# .env — copy .env.example and fill in:
#   GROQ_API_KEY           (Groq console — free tier is fine)
#   RAZORPAY_KEY_ID        rzp_test_...   (Razorpay dashboard → Test Mode → API Keys)
#   RAZORPAY_KEY_SECRET
#   RAZORPAY_WEBHOOK_SECRET (Razorpay dashboard → Webhooks — must match exactly)
#   DEFAULT_MERCHANT_NAME=EASY BUY

# database
docker compose up -d db          # from repo root; also creates ai_commerce_test
cd backend
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m app.seed.circuitcraft        # idempotent — 51 products / 216 SKUs

# a merchant login (there is no self-service route for one — ADR-023)
.venv/Scripts/python -m app.admin.provision_merchant --email owner@easybuy.test
```

Frontend:

```bash
cd frontend
npm install
echo "VITE_API_BASE_URL=http://127.0.0.1:8004" > .env    # git-ignored
```

## 2. Start everything

```bash
# terminal 1 — backend
cd backend && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8004

# terminal 2 — frontend
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173

# terminal 3 — MCP server (only needed for the AI-buyer demo)
cd backend && .venv/Scripts/python -m app.mcp

# terminal 4 — public tunnel for Razorpay webhooks
ngrok http 8004 --domain=<your-reserved-domain>
```

## 3. Razorpay dashboard (Test Mode)

- **Webhooks → Add**: URL = `https://<your-domain>/api/webhooks/razorpay`
- **Secret** = the exact value of `RAZORPAY_WEBHOOK_SECRET` in `.env`
- **Active events**: `payment.captured`, `payment.failed`, `order.paid`
- Enable it.

Verify: `curl -X POST https://<your-domain>/api/webhooks/razorpay` should return
**400** `{"status":"rejected"}` (reached the handler, no signature) — not 502.

## 4. Health checks

```bash
curl http://127.0.0.1:8004/api/health          # {"status":"ok", database.reachable:true}
curl http://127.0.0.1:5173/                     # 200
curl http://127.0.0.1:5173/src/api/config.ts    # VITE_API_BASE_URL: "http://127.0.0.1:8004"

# MCP handshake
curl -s -X POST http://127.0.0.1:8005/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'
```

## 5. Tests

```bash
cd backend
TEST_DATABASE_URL="postgresql+psycopg://ai_commerce:ai_commerce@127.0.0.1:5432/ai_commerce_test" \
  .venv/Scripts/python -m pytest -q          # ~1422 passed, 0 skipped
.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .

cd ../frontend
npm run test && npx tsc -b --noEmit && npx eslint . --max-warnings 0 && npm run build
```

Use `127.0.0.1`, not `localhost`, for `TEST_DATABASE_URL` — a throwaway PG binds
IPv4-only and `localhost` resolves to `::1` first, silently skipping every
`requires_db` test.

## 6. Razorpay test payment instruments

International cards are **declined** on this test account (domestic only). Use:

- **Netbanking** — pick any bank, click **Success** on the simulator (no BIN issues)
- **UPI** — `success@razorpay` (or `failure@razorpay` to demo the failure path)
- **Card** — `4386 2894 0766 0153`, any future expiry, any CVV, OTP `1234`
