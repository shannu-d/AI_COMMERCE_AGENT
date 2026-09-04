import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import type { ApiError } from "../../api/schemas";
import { cx } from "../../components/cx";
import { Alert, Button, Thinking } from "../../components/primitives";
import type { Turn } from "./useChat";

/**
 * The conversation.
 *
 * Prose and data are drawn separately, because they are separate fields and only
 * one of them is authoritative: `message` is natural language carrying no
 * commerce fact, and `recommendations[]` is the ranking engine's output (F§9).
 *
 * The transcript carries the prose only. The products a turn grounded its answer
 * on render in the Smart Agent recommendations panel, not inside a chat bubble
 * (ADR-020) — a turn that produced any points at them with a single line.
 *
 * Visually this is a *transcript*, not a messaging app. There are no chat
 * bubbles facing each other, because the metaphor is wrong: the buyer is
 * consulting a catalogue, not texting a friend. Each turn is a ruled block with
 * a monospace speaker label — the form of an interview in a magazine, which is
 * also what keeps the agent's results feeling like part of the storefront.
 */
export function ChatWindow({
  turns,
  pending,
  onSend,
}: {
  turns: Turn[];
  pending: boolean;
  onSend: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, pending]);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    onSend(text);
    setDraft("");
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-paper">
      <div
        className="scroll-quiet flex-1 space-y-6 overflow-y-auto px-4 py-5 sm:px-5"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
      >
        {turns.length === 0 && !pending && <EmptyState />}

        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} />
        ))}

        {pending && (
          <div className="animate-fade flex justify-start">
            <Thinking />
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* The composer is the dark band at the foot of the rail: the one place
          the buyer speaks, given the weight of a physical control. */}
      <form onSubmit={submit} className="on-dark border-t border-ink bg-ink p-3">
        <div className="flex gap-2">
          <label htmlFor="chat-input" className="sr-only">
            Message
          </label>
          <input
            id="chat-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="A case for my iPhone 16 under ₹1500"
            autoComplete="off"
            className="h-11 flex-1 rounded-plate border border-paper/20 bg-transparent px-3 text-sm
                       text-paper placeholder:text-paper/35 focus:border-volt focus:outline-none"
          />
          <Button type="submit" variant="volt" disabled={pending || draft.trim() === ""}>
            Send
          </Button>
        </div>
      </form>
    </div>
  );
}

/**
 * The empty state carries the product's promise, not an apology for being empty.
 *
 * The three examples are real capabilities of this catalogue — compatibility
 * resolution, a budget constraint and a stock check — so a buyer who taps one
 * gets a genuinely good first turn rather than a demo that misses.
 */
function EmptyState() {
  return (
    <div className="animate-rise py-6">
      <p className="eyebrow">Concierge</p>
      <h2 className="mt-3 text-title font-medium leading-[1.1] tracking-tight text-ink">
        Describe what
        <br />
        you need.
      </h2>
      <p className="mt-3 max-w-sm text-sm leading-relaxed text-ink-soft">
        Compatibility, stock and pricing are checked against the catalogue on every answer — never
        guessed, never invented.
      </p>
      <ul className="mt-5 space-y-px border-y border-rule">
        {[
          "A case for my iPhone 16 under ₹1500",
          "Fast charger that works with my phone",
          "Earbuds with noise cancelling",
        ].map((example) => (
          <li key={example} className="border-b border-rule/60 py-2 last:border-0">
            <span className="tabular text-2xs text-ink-faint">→ </span>
            <span className="text-sm text-ink-soft">{example}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  if (turn.kind === "buyer") {
    return (
      <div className="animate-rise border-l-2 border-ink pl-3">
        <p className="eyebrow mb-1">You</p>
        <p className="text-sm leading-relaxed text-ink">{turn.text}</p>
      </div>
    );
  }

  if (turn.kind === "transport-error") {
    return (
      <Alert tone="critical" title="Could not reach the assistant">
        <p>{turn.text}</p>
        {turn.retryable && <p className="mt-1">Sending the message again usually works.</p>}
      </Alert>
    );
  }

  return (
    <div className="animate-rise space-y-4">
      {turn.text && (
        <div className="border-l-2 border-volt pl-3">
          <p className="eyebrow mb-1">Concierge</p>
          {/* `whitespace-pre-wrap` preserves the model's own line breaks. Nothing
              is parsed out of this text — it carries no commerce fact (F§9). */}
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-soft">{turn.text}</p>
        </div>
      )}

      {turn.error && <BusinessOutcome error={turn.error} />}

      {turn.recommendations.length > 0 && (
        <RecommendationHint count={turn.recommendations.length} />
      )}
    </div>
  );
}

/**
 * The pointer from a turn to its products.
 *
 * The cards themselves live in the Smart Agent recommendations panel (ADR-020);
 * this is the one line that says a turn produced some, so the buyer knows to
 * look left rather than scroll a wall of table text here.
 */
function RecommendationHint({ count }: { count: number }) {
  return (
    <Link
      to="/agent"
      className={cx(
        "group flex items-center gap-2 border border-rule bg-paper-raised px-3 py-2",
        "text-2xs text-ink-soft transition-colors duration-fast hover:border-volt hover:text-ink",
      )}
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 bg-volt" />
      <span className="tabular">
        {count} {count === 1 ? "product" : "products"} in your recommendations
      </span>
      <span
        aria-hidden="true"
        className="ml-auto transition-transform duration-fast group-hover:translate-x-0.5 motion-reduce:transform-none"
      >
        →
      </span>
    </Link>
  );
}

/**
 * A business outcome the backend reported on a successful turn.
 *
 * These are not crashes. Each is a state the buyer can act on, and each of
 * F§25's codes gets its own sentence rather than a generic apology — an
 * out-of-stock finding and a policy refusal need different next steps.
 */
function BusinessOutcome({ error }: { error: ApiError }) {
  const copy: Record<string, { title: string; body: string; tone: "caution" | "critical" }> = {
    OUT_OF_STOCK: {
      title: "That item just went out of stock",
      body: "Ask for an alternative and the catalogue will be searched again.",
      tone: "caution",
    },
    PRICE_CHANGED: {
      title: "The price changed",
      body: "The cart has been repriced. Review the new total before approving it.",
      tone: "caution",
    },
    APPROVAL_REQUIRED: {
      title: "This needs your explicit approval",
      body: "Review the cart and confirm the exact total to continue.",
      tone: "caution",
    },
    POLICY_FAILED: {
      title: "This purchase was refused",
      body: "A spending or stock rule was not satisfied. The details are shown with the cart.",
      tone: "critical",
    },
    VARIANT_NOT_FOUND: {
      title: "That product could not be found",
      body: "Try describing what you need again.",
      tone: "caution",
    },
    PRODUCT_NOT_FOUND: {
      title: "That product could not be found",
      body: "Try describing what you need again.",
      tone: "caution",
    },
    PAYMENT_PENDING: {
      title: "Payment is still being confirmed",
      body: "This can take a moment. The order page updates itself.",
      tone: "caution",
    },
    PAYMENT_FAILED: {
      title: "The payment did not go through",
      body: "Nothing has been charged. You can try again from the order.",
      tone: "critical",
    },
    ORDER_CREATION_FAILED: {
      title: "The order could not be created",
      body: "Nothing has been charged. Approving the cart again is safe.",
      tone: "critical",
    },
    SERVER_ERROR: {
      title: "Something went wrong on our side",
      body: "Nothing has been charged. Please try again.",
      tone: "critical",
    },
    VALIDATION_ERROR: {
      title: "That request could not be understood",
      body: "Try rephrasing.",
      tone: "caution",
    },
  };

  const entry = copy[error.code] ?? {
    title: "That did not work",
    body: error.message,
    tone: "critical" as const,
  };

  return (
    <Alert tone={entry.tone} title={entry.title}>
      <p>{entry.body}</p>
    </Alert>
  );
}

/** Shared by the rail and the mobile sheet so their headers cannot drift apart. */
export function ConciergeHeader({ onClose }: { onClose?: (() => void) | undefined }) {
  return (
    <div className="on-dark flex items-center justify-between gap-3 border-b border-ink bg-ink px-4 py-3">
      <div className="flex items-center gap-2.5">
        <span aria-hidden="true" className="h-1.5 w-1.5 bg-volt" />
        <div>
          <p className="text-sm font-medium leading-none text-paper">Concierge</p>
          <p className="eyebrow mt-1 text-paper/45">Grounded in the live catalogue</p>
        </div>
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close concierge"
          className={cx(
            "grid h-9 w-9 place-items-center rounded-plate text-paper/60",
            "transition-colors duration-fast hover:bg-paper/10 hover:text-paper",
          )}
        >
          <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
            <path
              d="M3 3 L13 13 M13 3 L3 13"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
            />
          </svg>
        </button>
      )}
    </div>
  );
}
