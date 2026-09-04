import { createContext, useContext } from "react";
import type { AuthUser } from "../api/schemas";

/**
 * The context object and its hook, in their own module.
 *
 * Separated from the provider so the file that exports a component exports only
 * components — which is what keeps `react-refresh/only-export-components` quiet
 * and hot reload working, the same split `toastContext.ts` already makes.
 */
export type AuthState = {
  /** `null` while anonymous. Never a source of authority — see `AuthContext`. */
  user: AuthUser | null;
  /** True until the boot call has answered, so a page can avoid flashing. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<AuthUser>;
  signUp: (email: string, password: string, displayName?: string) => Promise<AuthUser>;
  signOut: () => Promise<void>;
};

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (value === null) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
