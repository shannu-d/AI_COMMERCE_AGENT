# Bug — Missing CORS Middleware and Pydantic List Parsing Startup Crash

**Date:** September 3, 2026  
**Time:** 00:26:08 +0530

### Question

Can a web browser running the React frontend on `http://localhost:5173` communicate with the FastAPI backend on `http://localhost:8004` without encountering Cross-Origin Resource Sharing (CORS) blocks, and does the backend configuration boot cleanly with comma-separated origins?

### What I Expected

The FastAPI backend should serve standard CORS headers (`Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, etc.) matching the frontend dev server, and `CORS_ALLOWED_ORIGINS` configured in `.env` should parse into a list of strings at startup.

### What Actually Happened

Two distinct defects occurred:
1. **Zero CORS Support:** The backend initially had no CORS middleware configured anywhere. Any request from a browser frontend was blocked by Chrome/Firefox due to missing CORS headers.
2. **Startup Crash on Settings Parse:** When the developer added `CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173` to `.env` and typed `cors_allowed_origins: list[str]` in `Settings`, the backend crashed on boot with `pydantic_core._pydantic_core.ValidationError`:
   Pydantic attempted to run `json.loads()` on the string because the field type was `list[str]`. Since `http://localhost:5173,...` is not valid JSON, parsing failed immediately at application import time!

### Why Was This a Problem?

The application could not boot if `CORS_ALLOWED_ORIGINS` was configured as standard comma-separated environment variables, and even when booted, no web browser could communicate with the API.

### Root Cause

1. `app/main.py` omitted FastAPI's `CORSMiddleware`.
2. In Pydantic Settings v2, complex types like `list[str]` default to JSON deserialization unless configured otherwise or wrapped in a custom validator.

### Decision

We decided to configure `CORSMiddleware` in `app/main.py` explicitly refusing wildcard `*` (since credentials and session IDs must be scoped), and to wrap `cors_allowed_origins` with a custom validator or `NoDecode` to split comma-separated strings cleanly.

### Fix

In commits `6d147a9` and `4081628`:
1. Updated `app/config.py` to parse comma-separated lists without requiring JSON syntax:
   ```python
   cors_allowed_origins: list[str] = Field(
       default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
   )
   @field_validator("cors_allowed_origins", mode="before")
   def _split_comma_origins(cls, value: Any) -> list[str]:
       if isinstance(value, str):
           return [origin.strip() for origin in value.split(",") if origin.strip()]
       return value
   ```
2. Added `CORSMiddleware` in `app/main.py`:
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=settings.cors_allowed_origins,
       allow_credentials=True,
       allow_methods=["*"],
       allow_headers=["*"],
   )
   ```

### Verification

Tested with `curl` sending `Origin: http://localhost:5173`.
Response headers included:
`Access-Control-Allow-Origin: http://localhost:5173`
`Access-Control-Allow-Credentials: true`
Frontend tests in `frontend/src/test/` and live Vite dev server connected without CORS errors.

### Result

PASS. Browser frontend connects and executes cross-origin requests seamlessly.

### Evidence

- Git commits: `6d147a9 feat: add the frontend and open the API to the browser (M14, F0-F9)`, `4081628 feat: run the agent chat on Assistant UI's runtime (M14, ADR-019)`
- Files: [`backend/app/main.py`](file:///l:/AI_COMMERCE/backend/app/main.py), [`backend/app/config.py`](file:///l:/AI_COMMERCE/backend/app/config.py)
- Regression test: [`backend/tests/test_config.py`](file:///l:/AI_COMMERCE/backend/tests/test_config.py)
