/**
 * The session identifier, and why it is kept the way it is.
 *
 * A session is anonymous and unauthenticated: `ADR-006` deliberately has no
 * `users` table for the MVP. The id is server-minted on the first chat turn and
 * is the **entire** claim "this cart is mine", so it is treated as a credential
 * even though it is not one:
 *
 * - It lives in `sessionStorage`, not `localStorage`. Closing the tab ends the
 *   session, which is the correct lifetime for an anonymous cart nobody can
 *   recover anyway, and it keeps one buyer's cart out of the next person's tab
 *   on a shared machine.
 * - It is never put in a URL. A query parameter leaks through history, logs and
 *   `Referer` headers.
 *
 * Storage can throw outright (private mode, blocked site data), so every access
 * is guarded and the app degrades to a session that lasts as long as the page.
 */
import { ApiRequestError } from "./api/client";

const KEY = "circuitcraft.session_id";

let memoryFallback: string | null = null;

export function readSessionId(): string | null {
  try {
    return window.sessionStorage.getItem(KEY) ?? memoryFallback;
  } catch {
    return memoryFallback;
  }
}

export function writeSessionId(id: string): void {
  memoryFallback = id;
  try {
    window.sessionStorage.setItem(KEY, id);
  } catch {
    // Storage unavailable. The in-memory copy carries the page's lifetime.
  }
}

export function clearSessionId(): void {
  memoryFallback = null;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}

/**
 * Is this the backend saying the stored session is not ours to use?
 *
 * The session routes answer **404, never 403** — a session that does not exist
 * and one owned by somebody else are deliberately indistinguishable, so that the
 * money path never confirms a session exists to a caller who cannot use it.
 * The consequence for this side is that 404 is the whole signal, and it has two
 * causes: the row is gone (a rebuilt database), or the row was claimed by an
 * account this browser is not signed into.
 *
 * Either way the stored id is spent. Without this, the id sits in storage
 * forever and every turn fails identically — "Request failed with status 404",
 * with no way out but clearing site data, which no buyer will think to do.
 */
export function isUnusableSession(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}
