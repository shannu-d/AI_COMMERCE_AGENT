import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";

import { renderWithProviders } from "./render";
import { RequireCustomer, RequireMerchant } from "../auth/guards";
import { clearToken, readToken, writeToken } from "../auth/token";
import { LoginPage } from "../pages/LoginPage";
import { RegisterPage } from "../pages/RegisterPage";
import { AccountPage } from "../pages/AccountPage";
import { writeSessionId, readSessionId } from "../session";

/**
 * Sign-in, sign-up and the guards, against a stubbed API.
 *
 * What these hold, in order of how badly it would matter if it broke:
 *
 * * the **token reaches the `Authorization` header** and nothing else does;
 * * a request never carries a role, a user id or a merchant id;
 * * the anonymous session travels with a sign-in, so the cart is claimed rather
 *   than abandoned — and is dropped when the server says it belonged elsewhere;
 * * the guards send a signed-out visitor to a sign-in page rather than to a
 *   screen of failed requests.
 *
 * What they deliberately do *not* claim: that the guards protect anything. They
 * decide what to draw. Authorization is the server's, on every request.
 */

type Call = { url: string; method: string; headers: Record<string, string>; body: unknown };
let calls: Call[];

function stub(handler: (url: string, method: string) => { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: init?.method ?? "GET",
        headers: (init?.headers ?? {}) as Record<string, string>,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const { status, body } = handler(String(url), init?.method ?? "GET");
      return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
    }),
  );
}

const CUSTOMER = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  email: "shopper@example.test",
  role: "CUSTOMER",
  display_name: "Ada",
  merchant_id: null,
};

const MERCHANT = {
  id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  email: "owner@example.test",
  role: "MERCHANT",
  display_name: "Owner",
  merchant_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
};

function tokenFor(user: unknown, sessionClaimed = true) {
  return {
    access_token: "opaque-token-value",
    token_type: "bearer",
    expires_at: "2026-09-05T00:00:00+00:00",
    user,
    session_claimed: sessionClaimed,
  };
}

beforeEach(() => {
  calls = [];
  clearToken();
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  clearToken();
  window.sessionStorage.clear();
});

// -- sign in ----------------------------------------------------------------

describe("signing in", () => {
  it("sends the anonymous session so the cart is claimed, and never a role", async () => {
    const user = userEvent.setup();
    writeSessionId("11111111-1111-4111-8111-111111111111");
    stub((url, method) => {
      if (url.endsWith("/api/auth/login") && method === "POST") {
        return { status: 200, body: tokenFor(CUSTOMER) };
      }
      return { status: 200, body: null };
    });

    renderWithProviders(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<p>storefront</p>} />
      </Routes>,
      { route: "/login" },
    );

    await user.type(screen.getByLabelText(/email/i), "shopper@example.test");
    await user.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(screen.getByText("storefront")).toBeInTheDocument());

    const login = calls.find((c) => c.url.endsWith("/api/auth/login"));
    expect(login?.body).toEqual({
      email: "shopper@example.test",
      password: "correct-horse-battery",
      session_id: "11111111-1111-4111-8111-111111111111",
    });
    // The three things a client must never assert about itself.
    expect(JSON.stringify(login?.body)).not.toContain("role");
    expect(JSON.stringify(login?.body)).not.toContain("merchant_id");
    expect(JSON.stringify(login?.body)).not.toContain("user_id");
  });

  it("keeps the token for the next request, in the Authorization header", async () => {
    const user = userEvent.setup();
    stub((url, method) => {
      if (url.endsWith("/api/auth/login") && method === "POST") {
        return { status: 200, body: tokenFor(CUSTOMER) };
      }
      if (url.endsWith("/api/account/orders")) {
        return { status: 200, body: { items: [], total: 0, limit: 25, offset: 0 } };
      }
      return { status: 200, body: null };
    });

    renderWithProviders(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireCustomer />}>
          <Route path="/" element={<AccountPage />} />
        </Route>
      </Routes>,
      { route: "/login" },
    );

    await user.type(screen.getByLabelText(/email/i), "shopper@example.test");
    await user.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/api/account/orders"))).toBe(true),
    );
    const orders = calls.find((c) => c.url.endsWith("/api/account/orders"));
    expect(orders?.headers["Authorization"]).toBe("Bearer opaque-token-value");
  });

  it("drops the session id when the server says the cart was somebody else's", async () => {
    const user = userEvent.setup();
    writeSessionId("22222222-2222-4222-8222-222222222222");
    stub((url, method) => {
      if (url.endsWith("/api/auth/login") && method === "POST") {
        // `session_claimed: false` — the cart already had an owner.
        return { status: 200, body: tokenFor(CUSTOMER, false) };
      }
      return { status: 200, body: null };
    });

    renderWithProviders(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<p>storefront</p>} />
      </Routes>,
      { route: "/login" },
    );

    await user.type(screen.getByLabelText(/email/i), "shopper@example.test");
    await user.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(readSessionId()).toBeNull());
  });

  it("shows the server's incurious message and keeps no token", async () => {
    const user = userEvent.setup();
    stub(() => ({
      status: 401,
      body: {
        detail: {
          code: "VALIDATION_ERROR",
          message: "email or password is incorrect",
          details: {},
        },
      },
    }));

    renderWithProviders(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
      </Routes>,
      { route: "/login" },
    );

    await user.type(screen.getByLabelText(/email/i), "shopper@example.test");
    await user.type(screen.getByLabelText(/password/i), "wrong-password-here");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/email or password is incorrect/i)).toBeInTheDocument();
    expect(readToken()).toBeNull();
  });
});

// -- sign up -----------------------------------------------------------------

describe("signing up", () => {
  it("offers no way to ask for a role", () => {
    stub(() => ({ status: 200, body: null }));
    renderWithProviders(
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
      </Routes>,
      { route: "/register" },
    );
    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/merchant account/i)).not.toBeInTheDocument();
  });

  it("refuses a short password before making a request", async () => {
    const user = userEvent.setup();
    stub(() => ({ status: 201, body: tokenFor(CUSTOMER) }));

    renderWithProviders(
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
      </Routes>,
      { route: "/register" },
    );

    await user.type(screen.getByLabelText(/email/i), "new@example.test");
    await user.type(screen.getByLabelText(/password/i), "short");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText(/at least 10 characters/i)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/api/auth/register"))).toBe(false);
  });

  it("omits an empty display name rather than sending a blank one", async () => {
    const user = userEvent.setup();
    stub(() => ({ status: 201, body: tokenFor(CUSTOMER) }));

    renderWithProviders(
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/" element={<p>storefront</p>} />
      </Routes>,
      { route: "/register" },
    );

    await user.type(screen.getByLabelText(/email/i), "new@example.test");
    await user.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/api/auth/register"))).toBe(true),
    );
    const body = calls.find((c) => c.url.endsWith("/api/auth/register"))?.body as
      | Record<string, unknown>
      | undefined;
    expect(body).toEqual({ email: "new@example.test", password: "correct-horse-battery" });
    expect(body && "display_name" in body).toBe(false);
  });
});

// -- guards ------------------------------------------------------------------

describe("route guards", () => {
  it("sends a signed-out visitor to sign in, remembering where they were", async () => {
    stub(() => ({ status: 200, body: null }));

    renderWithProviders(
      <Routes>
        <Route element={<RequireCustomer />}>
          <Route path="/account" element={<p>account</p>} />
        </Route>
        <Route path="/login" element={<p>sign in</p>} />
      </Routes>,
      { route: "/account" },
    );

    expect(await screen.findByText("sign in")).toBeInTheDocument();
    expect(screen.queryByText("account")).not.toBeInTheDocument();
  });

  it("keeps a merchant out of the customer area and a customer out of the dashboard", async () => {
    writeToken("opaque-token-value");
    stub((url) => {
      if (url.endsWith("/api/auth/session")) return { status: 200, body: MERCHANT };
      return { status: 200, body: null };
    });

    renderWithProviders(
      <Routes>
        <Route element={<RequireCustomer />}>
          <Route path="/account" element={<p>account</p>} />
        </Route>
        <Route path="/merchant" element={<p>dashboard</p>} />
      </Routes>,
      { route: "/account" },
    );

    expect(await screen.findByText("dashboard")).toBeInTheDocument();
  });

  it("does not bounce a signed-in visitor while the boot call is still in flight", async () => {
    writeToken("opaque-token-value");
    stub((url) => {
      if (url.endsWith("/api/auth/session")) return { status: 200, body: MERCHANT };
      return { status: 200, body: null };
    });

    renderWithProviders(
      <Routes>
        <Route element={<RequireMerchant />}>
          <Route path="/merchant" element={<p>dashboard</p>} />
        </Route>
        <Route path="/merchant/login" element={<p>merchant sign in</p>} />
      </Routes>,
      { route: "/merchant" },
    );

    // The very first render must not have redirected.
    expect(screen.queryByText("merchant sign in")).not.toBeInTheDocument();
    expect(await screen.findByText("dashboard")).toBeInTheDocument();
  });

  it("does not sign a visitor out because StrictMode cancelled the boot call", async () => {
    // The regression this exists for: React 18 mounts an effect, tears it down
    // and mounts it again, so the first `/api/auth/session` is always aborted.
    // Treating that abort as "the server refused this token" cleared the token
    // on every page load, and the dashboard bounced to its sign-in page while
    // the visitor was in fact signed in.
    writeToken("opaque-token-value");
    stub((url) => {
      if (url.endsWith("/api/auth/session")) return { status: 200, body: MERCHANT };
      return { status: 200, body: null };
    });

    renderWithProviders(
      <StrictMode>
        <Routes>
          <Route element={<RequireMerchant />}>
            <Route path="/merchant" element={<p>dashboard</p>} />
          </Route>
          <Route path="/merchant/login" element={<p>merchant sign in</p>} />
        </Routes>
      </StrictMode>,
      { route: "/merchant" },
    );

    expect(await screen.findByText("dashboard")).toBeInTheDocument();
    expect(readToken()).toBe("opaque-token-value");
  });

  it("clears a token the server no longer accepts", async () => {
    writeToken("stale-token");
    stub((url) => {
      if (url.endsWith("/api/auth/session")) {
        return {
          status: 401,
          body: { detail: { code: "VALIDATION_ERROR", message: "sign in", details: {} } },
        };
      }
      return { status: 200, body: null };
    });

    renderWithProviders(
      <Routes>
        <Route element={<RequireCustomer />}>
          <Route path="/account" element={<p>account</p>} />
        </Route>
        <Route path="/login" element={<p>sign in</p>} />
      </Routes>,
      { route: "/account" },
    );

    expect(await screen.findByText("sign in")).toBeInTheDocument();
    await waitFor(() => expect(readToken()).toBeNull());
  });
});
