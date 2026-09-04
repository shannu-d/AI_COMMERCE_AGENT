import type { z } from "zod";
import { readToken } from "../auth/token";
import { API_BASE_URL } from "./config";
import { ApiError, type ApiErrorCode } from "./schemas";

/**
 * The one place this frontend talks to the backend.
 *
 * Two rules it exists to enforce:
 *
 * **A business outcome is not a network error.** The backend answers HTTP 200
 * for any turn it completed, *including* one that ends in a policy refusal or an
 * out-of-stock finding (ADR-010) — those arrive as an `error` body on a 200. A
 * 4xx means the request was malformed or the session is unknown; a 5xx means the
 * server broke. Only the latter two become thrown `ApiRequestError`s, so
 * recovery flows the UI must render never end up in a component's
 * "something went wrong" branch.
 *
 * **Nothing is trusted on the way in.** Every response is parsed through its Zod
 * schema, so a renamed field fails here with a legible message instead of
 * becoming `undefined` three components deep.
 *
 * **The bearer token is attached here and nowhere else** (ADR-023). It is sent
 * explicitly rather than by the browser, which is exactly why this API has no
 * CSRF surface, and putting it in one place means no call site can forget it or
 * send somebody else's.
 */

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: ApiErrorCode | "NETWORK_ERROR" | "MALFORMED_RESPONSE",
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

function authHeaders(hasBody: boolean): Record<string, string> {
  const headers: Record<string, string> = {};
  if (hasBody) headers["Content-Type"] = "application/json";
  const token = readToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  { method = "GET", body, signal }: RequestOptions = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      // Content-Type when there is a body, plus the bearer token when the
      // visitor is signed in. Every *other* identifier this API trusts —
      // session_id, cart_version, idempotency_key — still travels in the body,
      // and the backend allowlists only these two headers (ADR-017, ADR-023).
      headers: authHeaders(body !== undefined),
      body: body === undefined ? null : JSON.stringify(body),
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    // A genuine transport failure: the API is down, DNS failed, or CORS refused
    // the request before it was sent.
    throw new ApiRequestError(0, "NETWORK_ERROR", "Could not reach the server.", {
      cause: String(cause),
    });
  }

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    // FastAPI wraps this application's error bodies in `detail`.
    const raw =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    const parsed = ApiError.safeParse(raw);
    if (parsed.success) {
      throw new ApiRequestError(
        response.status,
        parsed.data.code,
        parsed.data.message,
        parsed.data.details,
      );
    }
    throw new ApiRequestError(
      response.status,
      "SERVER_ERROR",
      `Request failed with status ${response.status}.`,
    );
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    // A contract drift. Loud, and named, rather than an `undefined` later.
    throw new ApiRequestError(
      response.status,
      "MALFORMED_RESPONSE",
      `The server's response did not match the expected shape for ${path}.`,
      { issues: parsed.error.issues },
    );
  }
  return parsed.data;
}
