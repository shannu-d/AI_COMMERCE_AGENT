import { Link } from "react-router-dom";

import { Button, Eyebrow } from "../components/primitives";
import { useConcierge } from "../features/concierge/conciergeContext";

/** A 404 that offers the two things that actually help: browse, or just ask. */
export function NotFoundPage() {
  const { ask } = useConcierge();
  return (
    <div className="mx-auto flex max-w-shell flex-col items-start px-4 py-24 sm:px-6">
      <Eyebrow>Error 404</Eyebrow>
      <h1 className="animate-rise mt-4 text-display font-semibold text-ink">Not here.</h1>
      <p className="mt-4 max-w-md text-[0.95rem] leading-relaxed text-ink-soft">
        That address does not match anything in the catalogue. Nothing has been charged and your cart
        is untouched.
      </p>
      <div className="mt-8 flex flex-wrap gap-2">
        <Link to="/">
          <Button size="lg">Back to the catalogue</Button>
        </Link>
        <Button size="lg" variant="secondary" onClick={() => ask("What do you recommend?")}>
          Ask the concierge
        </Button>
      </div>
    </div>
  );
}
