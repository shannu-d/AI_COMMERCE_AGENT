import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiRequestError } from "../../api/client";
import { Alert, Button, Eyebrow, Plate } from "../../components/primitives";
import { useAuth } from "../../auth/context";
import { Field } from "../LoginPage";

/**
 * The dashboard's sign-in.
 *
 * **There is no "create a merchant account" link, and there is no route behind
 * one.** Self-service registration makes customers; an administrator is
 * provisioned by an operator against a specific merchant, because a request body
 * that could ask for a role is the one thing a registration endpoint most often
 * gets wrong (ADR-023).
 *
 * Signing in here goes through the same `/api/auth/login` a shopper uses — there
 * is one identity system, not two — and the role on the answer decides where the
 * visitor lands. A customer who signs in on this page is sent to the storefront
 * rather than shown an empty dashboard, because their token would be refused by
 * every route on it.
 */
export function MerchantLoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await signIn(email, password);
      if (user.role !== "MERCHANT") {
        setError("That account is a shopper account, not a merchant administrator.");
        navigate("/", { replace: true });
        return;
      }
      navigate("/merchant", { replace: true });
    } catch (cause) {
      setError(
        cause instanceof ApiRequestError ? cause.message : "Could not sign in. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-sm px-4 py-16">
      <Eyebrow>EASY BUY</Eyebrow>
      <h1 className="mt-2 font-display text-2xl text-ink">Merchant sign-in</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Administrator access to the catalogue, inventory and orders.
      </p>

      <Plate className="mt-6 p-5">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field
            label="Email"
            type="email"
            name="merchant-email"
            autoComplete="email"
            value={email}
            onChange={setEmail}
            required
          />
          <Field
            label="Password"
            type="password"
            name="merchant-password"
            autoComplete="current-password"
            value={password}
            onChange={setPassword}
            required
          />
          {error && <Alert title="Sign-in failed">{error}</Alert>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Plate>

      <p className="mt-4 text-2xs text-ink-faint">
        Merchant accounts are provisioned by an operator. There is no sign-up here.
      </p>
    </div>
  );
}
