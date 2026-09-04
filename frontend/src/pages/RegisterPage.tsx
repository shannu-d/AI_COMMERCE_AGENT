import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiRequestError } from "../api/client";
import { Alert, Button, Eyebrow, Plate } from "../components/primitives";
import { useAuth } from "../auth/context";
import { Field } from "./LoginPage";

/** The server's minimum. Stated here so the form can say so before a round trip. */
const MIN_PASSWORD_LENGTH = 10;

/**
 * Create an account.
 *
 * **There is no role selector, and there is no field for one.** Signing up here
 * makes a customer; a merchant administrator is provisioned by an operator, and
 * the backend has no route that could do otherwise (ADR-023). A page that
 * offered the choice would be describing a capability the API does not have.
 *
 * An email that is already registered fails with the same message as a wrong
 * password, because the server answers both identically on purpose — this form
 * is not an oracle for which addresses exist.
 */
export function RegisterPage() {
  const { signUp } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Please use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setBusy(true);
    try {
      await signUp(email, password, name.trim() || undefined);
      navigate(from, { replace: true });
    } catch (cause) {
      setError(
        cause instanceof ApiRequestError
          ? cause.message
          : "Could not create the account. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-sm px-4 py-16">
      <Eyebrow>Account</Eyebrow>
      <h1 className="mt-2 font-display text-2xl text-ink">Create an account</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Keeps your orders together. Anything already in your cart comes with you.
      </p>

      <Plate className="mt-6 p-5">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            value={email}
            onChange={setEmail}
            required
          />
          <Field
            label="Name"
            type="text"
            name="display_name"
            autoComplete="name"
            value={name}
            onChange={setName}
            hint="Optional."
          />
          <Field
            label="Password"
            type="password"
            name="new-password"
            autoComplete="new-password"
            value={password}
            onChange={setPassword}
            required
            hint={
              tooShort
                ? `${MIN_PASSWORD_LENGTH - password.length} more character${
                    MIN_PASSWORD_LENGTH - password.length === 1 ? "" : "s"
                  } needed.`
                : `At least ${MIN_PASSWORD_LENGTH} characters. There is no maximum.`
            }
          />
          {error && <Alert title="Could not create the account">{error}</Alert>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Creating…" : "Create account"}
          </Button>
        </form>
      </Plate>

      <p className="mt-4 text-sm text-ink-soft">
        Already have one?{" "}
        <Link to="/login" state={{ from }} className="text-ink underline hover:text-volt-ink">
          Sign in
        </Link>
        .
      </p>
    </div>
  );
}
