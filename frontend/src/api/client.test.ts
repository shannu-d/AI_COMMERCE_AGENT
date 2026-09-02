import { describe, expect, it, vi, afterEach } from "vitest";
import { z } from "zod";
import { request, ApiRequestError } from "./client";
import { Money, ApiError, API_ERROR_CODES, HealthResponse } from "./schemas";

const Ok = z.object({ ok: z.boolean() });

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("the response boundary", () => {
  it("parses a valid response through its schema", async () => {
    mockFetch(200, { ok: true });

    await expect(request("/x", Ok)).resolves.toEqual({ ok: true });
  });

  it("rejects a response whose shape drifted, rather than passing undefined on", async () => {
    // The failure this boundary exists for: a renamed field. Without Zod this
    // becomes `undefined` three components deep, at render time.
    mockFetch(200, { okay: true });

    await expect(request("/x", Ok)).rejects.toMatchObject({
      code: "MALFORMED_RESPONSE",
    });
  });

  it("reports a transport failure as a network error, not a server error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(request("/x", Ok)).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      status: 0,
    });
  });
});

describe("errors", () => {
  it("unwraps FastAPI's `detail` envelope and keeps the business code", async () => {
    mockFetch(409, {
      detail: { code: "PRICE_CHANGED", message: "the price moved", details: { sku: "AC-001" } },
    });

    const caught = await request("/x", Ok).catch((e: unknown) => e);

    expect(caught).toBeInstanceOf(ApiRequestError);
    expect(caught).toMatchObject({
      status: 409,
      code: "PRICE_CHANGED",
      message: "the price moved",
      details: { sku: "AC-001" },
    });
  });

  it("falls back to a generic code when the error body is not this API's shape", async () => {
    mockFetch(502, "<html>gateway</html>");

    await expect(request("/x", Ok)).rejects.toMatchObject({ code: "SERVER_ERROR" });
  });

  it("does NOT throw for a business outcome carried on a 200 (ADR-010)", async () => {
    // A policy refusal is a successful conversational turn with an `error` body.
    // If this threw, every recovery flow the UI must render would land in a
    // component's network-error branch instead.
    const Turn = z.object({ error: ApiError.nullable() });
    mockFetch(200, {
      error: { code: "POLICY_FAILED", message: "spending limit exceeded", details: {} },
    });

    const turn = await request("/chat", Turn);

    expect(turn.error?.code).toBe("POLICY_FAILED");
  });
});

describe("money", () => {
  it("accepts fixed-scale strings and keeps them as strings", () => {
    for (const value of ["999.00", "1299.00", "0.00", "10000.50"]) {
      const parsed = Money.parse(value);
      expect(parsed).toBe(value);
      expect(typeof parsed).toBe("string");
    }
  });

  it("rejects a JSON number, which is how precision gets lost (ADR-008)", () => {
    expect(() => Money.parse(999.0 as unknown as string)).toThrow();
  });

  it("rejects an unscaled string, so a total can never render as `1299`", () => {
    expect(() => Money.parse("1299")).toThrow();
    expect(() => Money.parse("1299.0")).toThrow();
  });
});

describe("the error vocabulary", () => {
  it("is exactly F§25's eleven codes", () => {
    // Mirrored from app/agent/errors.py. A backend test asserts the two agree;
    // this one asserts the count has not quietly grown on the frontend side.
    expect(API_ERROR_CODES).toHaveLength(11);
    expect(new Set(API_ERROR_CODES).size).toBe(11);
  });
});

describe("health", () => {
  it("parses the real health shape", () => {
    expect(() =>
      HealthResponse.parse({
        status: "ok",
        app: "Merchant AI Commerce Agent",
        version: "0.1.0",
        environment: "local",
        database: { configured: true, reachable: true, error_kind: null },
      }),
    ).not.toThrow();
  });
});
