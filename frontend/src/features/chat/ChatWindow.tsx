import { useEffect, useRef, useState } from "react";
import type { ApiError } from "../../api/schemas";
import { Alert, Button, Thinking } from "../../components/primitives";
import { RecommendationGrid } from "./RecommendationCard";
import type { Turn } from "./useChat";

/**
 * The conversation.
 *
 * Prose and data are drawn separately, because they are separate fields and only
 * one of them is authoritative: `message` is natural language carrying no
 * commerce fact, and `recommendations[]` is the ranking engine's output (F§9).
 */
export function ChatWindow({
  turns,
  pending,
  sessionId,
  onSend,
}: {
  turns: Turn[];
  pending: boolean;
  sessionId: string | null;
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
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        className="flex-1 space-y-4 overflow-y-auto p-4"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
      >
        {turns.length === 0 && !pending && <EmptyState />}

        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} sessionId={sessionId} />
        ))}

        {pending && (
          <div className="flex justify-start">
            <Thinking />
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="border-t border-zinc-200 bg-white p-3">
        <div className="flex gap-2">
          <label htmlFor="chat-input" className="sr-only">
            Message
          </label>
          <input
            id="chat-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Find me a case for my iPhone 16 under ₹1500"
            autoComplete="off"
            className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm
                       placeholder:text-zinc-400 focus:border-blue-600 focus:outline-none"
          />
          <Button type="submit" disabled={pending || draft.trim() === ""}>
            Send
          </Button>
        </div>
      </form>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto max-w-md py-10 text-center">
      <h2 className="text-sm font-semibold text-zinc-900">Ask for what you need</h2>
      <p className="mt-1 text-sm text-zinc-500">
        Describe the device and your budget. Compatibility, stock and pricing are checked against the
        catalogue — never guessed.
      </p>
    </div>
  );
}

function TurnView({ turn, sessionId }: { turn: Turn; sessionId: string | null }) {
  if (turn.kind === "buyer") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-2xl rounded-br-sm bg-blue-700 px-4 py-2 text-sm text-white">
          {turn.text}
        </p>
      </div>
    );
  }

  if (turn.kind === "transport-error") {
    return (
      <Alert tone="danger" title="Could not reach the assistant">
        <p>{turn.text}</p>
        {turn.retryable && <p className="mt-1">Sending the message again usually works.</p>}
      </Alert>
    );
  }

  return (
    <div className="space-y-3">
      {turn.text && (
        <div className="flex justify-start">
          <p className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-white px-4 py-2 text-sm text-zinc-800 ring-1 ring-zinc-200">
            {turn.text}
          </p>
        </div>
      )}

      {turn.error && <BusinessOutcome error={turn.error} />}

      <RecommendationGrid recommendations={turn.recommendations} sessionId={sessionId} />
    </div>
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
  const copy: Record<string, { title: string; body: string; tone: "warning" | "danger" }> = {
    OUT_OF_STOCK: {
      title: "That item just went out of stock",
      body: "Ask for an alternative and the catalogue will be searched again.",
      tone: "warning",
    },
    PRICE_CHANGED: {
      title: "The price changed",
      body: "The cart has been repriced. Review the new total before approving it.",
      tone: "warning",
    },
    APPROVAL_REQUIRED: {
      title: "This needs your explicit approval",
      body: "Review the cart and confirm the exact total to continue.",
      tone: "warning",
    },
    POLICY_FAILED: {
      title: "This purchase was refused",
      body: "A spending or stock rule was not satisfied. The details are shown with the cart.",
      tone: "danger",
    },
    VARIANT_NOT_FOUND: {
      title: "That product could not be found",
      body: "Try describing what you need again.",
      tone: "warning",
    },
    PRODUCT_NOT_FOUND: {
      title: "That product could not be found",
      body: "Try describing what you need again.",
      tone: "warning",
    },
    PAYMENT_PENDING: {
      title: "Payment is still being confirmed",
      body: "This can take a moment. The order page updates itself.",
      tone: "warning",
    },
    PAYMENT_FAILED: {
      title: "The payment did not go through",
      body: "Nothing has been charged. You can try again from the order.",
      tone: "danger",
    },
    ORDER_CREATION_FAILED: {
      title: "The order could not be created",
      body: "Nothing has been charged. Approving the cart again is safe.",
      tone: "danger",
    },
    SERVER_ERROR: {
      title: "Something went wrong on our side",
      body: "Nothing has been charged. Please try again.",
      tone: "danger",
    },
    VALIDATION_ERROR: {
      title: "That request could not be understood",
      body: "Try rephrasing.",
      tone: "warning",
    },
  };

  const entry = copy[error.code] ?? {
    title: "That did not work",
    body: error.message,
    tone: "danger" as const,
  };

  return (
    <Alert tone={entry.tone} title={entry.title}>
      <p>{entry.body}</p>
    </Alert>
  );
}
