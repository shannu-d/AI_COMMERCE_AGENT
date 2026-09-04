/**
 * Where the bearer token lives, and why it lives there.
 *
 * ADR-023 chose an opaque server-side token in the `Authorization` header over
 * a cookie. That decision is what keeps this API free of CSRF — nothing is
 * attached ambiently by the browser — and its cost, stated plainly, is that the
 * token is readable by injected script. The mitigations are on the server:
 * tokens expire, are revocable, and are stored only as a SHA-256 hash.
 *
 * `sessionStorage`, not `localStorage`, for the same reason `session.ts` uses
 * it: closing the tab ends the sign-in, and one person's account does not stay
 * signed in for the next user of a shared machine.
 *
 * Storage can throw outright (private mode, blocked site data), so every access
 * is guarded and the app degrades to a sign-in that lasts as long as the page.
 *
 * **Nothing here is authority.** The token is a claim the server checks on every
 * request; the role and merchant it returns are the server's answer, never a
 * value this module decides. A `user` object cached in memory is a convenience
 * for rendering, and no UI decision made from it can grant access to anything.
 */
const KEY = "easybuy.auth_token";

let memoryFallback: string | null = null;

export function readToken(): string | null {
  try {
    return window.sessionStorage.getItem(KEY) ?? memoryFallback;
  } catch {
    return memoryFallback;
  }
}

export function writeToken(token: string): void {
  memoryFallback = token;
  try {
    window.sessionStorage.setItem(KEY, token);
  } catch {
    // Storage unavailable. The in-memory copy carries the page's lifetime.
  }
}

export function clearToken(): void {
  memoryFallback = null;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}
