import { createSession } from "./api/endpoints";
import { readSessionId, writeSessionId } from "./session";

/**
 * The session id, creating one if this browser does not have one yet.
 *
 * Every cart write needs a session, and a buyer who arrived by browsing has
 * never spoken to the agent, so nothing has minted one. Rather than disabling
 * *Add to cart* until someone opens the concierge — which would make the
 * storefront look broken — the first write mints a session on demand.
 *
 * Concurrent callers are de-duplicated through a module-level promise, so two
 * quick clicks cannot create two sessions and split the cart between them.
 */
let inFlight: Promise<string> | null = null;

export async function ensureSessionId(): Promise<string> {
  const existing = readSessionId();
  if (existing) return existing;

  inFlight ??= createSession()
    .then((response) => {
      writeSessionId(response.session_id);
      return response.session_id;
    })
    .finally(() => {
      inFlight = null;
    });

  return inFlight;
}
