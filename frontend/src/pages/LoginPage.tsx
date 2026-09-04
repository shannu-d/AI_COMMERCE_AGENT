import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiRequestError } from "../api/client";
import { Alert, Button, Eyebrow, Plate } from "../components/primitives";
import { useAuth } from "../auth/context";

/**
 * Sign in.
 *
 * The failure message is deliberately incurious — "email or password is
 * incorrect" — and that is the server's wording, not a softening applied here.
 * A wrong password and an unknown address answer identically, so this page
 * cannot be used to find out which addresses are registered.
 *
 * The cart the visitor is already holding travels with the request, so signing
 * in *claims* it rather than discarding it. Nothing is copied and nothing is
 * merged (ADR-023).
 */
export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Where to land afterwards: back where the visitor was sent from, or home.
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await signIn(email, password);
      navigate(user.role === "MERCHANT" ? "/merchant" : from, { replace: true });
    } catch (cause) {
      setError(
        cause instanceof ApiRequestError
          ? cause.message
          : "Could not sign in. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-sm px-4 py-16">
      <Eyebrow>Account</Eyebrow>
      <h1 className="mt-2 font-display text-2xl text-ink">Sign in</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Your cart comes with you — anything you have added stays where it is.
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
            label="Password"
            type="password"
            name="password"
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

      <p className="mt-4 text-sm text-ink-soft">
        No account yet?{" "}
        <Link to="/register" state={{ from }} className="text-ink underline hover:text-volt-ink">
          Create one
        </Link>
        .
      </p>
    </div>
  );
}

/** A labelled input. Local to the auth pages — two forms, one shape. */
export function Field({
  label,
  value,
  onChange,
  hint,
  ...props
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value">) {
  const id = `field-${props.name ?? label.toLowerCase()}`;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-2xs uppercase tracking-wide text-ink-soft">
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-full rounded-plate border border-rule bg-paper px-3 text-sm text-ink outline-none transition-colors duration-fast focus:border-ink"
        {...props}
      />
      {hint && <p className="text-2xs text-ink-soft">{hint}</p>}
    </div>
  );
}
