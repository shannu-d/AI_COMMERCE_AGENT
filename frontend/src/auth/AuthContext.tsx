import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { getAuthSession, login as loginCall, logout as logoutCall, register } from "../api/endpoints";
import type { AuthUser } from "../api/schemas";
import { clearSessionId, readSessionId } from "../session";
import { AuthContext, type AuthState } from "./context";
import { clearToken, readToken, writeToken } from "./token";

/**
 * Who is signed in, for rendering purposes only.
 *
 * **This is not an authorization boundary and must never be treated as one.**
 * Every protected route re-asks the server on the next request; what this
 * provider decides is which links and pages to *draw*. A visitor who edits
 * `sessionStorage` changes what their own browser renders and gains access to
 * nothing, because the server derives identity from the token it verifies and
 * from nowhere else (ADR-023).
 *
 * The boot call is `/api/auth/session`, which answers `null` rather than 401 for
 * an anonymous visitor — so the ordinary logged-out case is not an error in the
 * console and does not trip the client's error handling.
 *
 * On sign-in the anonymous session travels with the request so the cart the
 * visitor already built **gains an owner**. When the server answers
 * `session_claimed: false` the cart belonged to someone else, and the local
 * session id is dropped rather than kept pointing at a session this user cannot
 * read.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    if (!readToken()) {
      setLoading(false);
      return () => controller.abort();
    }
    getAuthSession(controller.signal)
      .then((who) => setUser(who))
      .catch(() => {
        // **An abort is not a rejection.** React 18's StrictMode mounts an
        // effect, tears it down and mounts it again, so the first request is
        // always cancelled — and treating that cancellation as "the server
        // refused this token" signed a visitor straight back out on every page
        // load in development. Anything a cleanup caused is ignored here.
        if (controller.signal.aborted) return;
        // A genuinely expired or revoked token. Clearing it means the next
        // request is made as an honest anonymous one rather than as a rejected
        // caller.
        clearToken();
        setUser(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const adopt = useCallback((token: string, who: AuthUser, sessionClaimed: boolean) => {
    writeToken(token);
    setUser(who);
    if (!sessionClaimed) clearSessionId();
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const sessionId = readSessionId();
      const result = await loginCall({
        email,
        password,
        ...(sessionId ? { session_id: sessionId } : {}),
      });
      adopt(result.access_token, result.user, result.session_claimed);
      return result.user;
    },
    [adopt],
  );

  const signUp = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const sessionId = readSessionId();
      const result = await register({
        email,
        password,
        ...(displayName ? { display_name: displayName } : {}),
        ...(sessionId ? { session_id: sessionId } : {}),
      });
      adopt(result.access_token, result.user, result.session_claimed);
      return result.user;
    },
    [adopt],
  );

  const signOut = useCallback(async () => {
    try {
      await logoutCall();
    } catch {
      // Logging out must never fail visibly. The token is dropped locally
      // regardless; the server's copy expires on its own if the call did not
      // land.
    }
    clearToken();
    // The cart belongs to the account now, not to this tab. Keeping the session
    // id would leave the next visitor pointing at a session they cannot read.
    clearSessionId();
    setUser(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, loading, signIn, signUp, signOut }),
    [user, loading, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
