import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./render";
import { aeroCase } from "./fixtures";
import { AgentRuntimeProvider } from "../features/agent/AgentRuntimeProvider";
import { useAgentChat } from "../features/agent/useAgentChat";
import { SmartAgentRecommendations } from "../features/agent/SmartAgentRecommendations";
import { ChatWindow } from "../features/chat/ChatWindow";
import type { ChatResponse } from "../api/schemas";
import { clearSessionId } from "../session";

/**
 * The Assistant UI integration.
 *
 * These exercise the runtime itself — `AgentRuntimeProvider`'s `ChatModelAdapter`
 * and the `useAgentChat` bridge — rather than rendering `ChatWindow` with props,
 * which is what the other suites do. Without them the integration would have no
 * coverage at all: the older tests pass whether or not a runtime exists.
 */

type Call = { url: string; method: string; body: Record<string, unknown> | undefined };

let calls: Call[];

function stubFetch(handler: (url: string) => { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const { status, body } = handler(String(url));
      return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
    }),
  );
}

const turn = (over: Partial<ChatResponse> = {}): ChatResponse => ({
  session_id: "55555555-5555-5555-8555-555555555555",
  state: "RECOMMENDING",
  message: "Here is what fits.",
  recommendations: [aeroCase],
  cart: null,
  trace: null,
  error: null,
  ...over,
});

/**
 * The two panes as the app wires them: the recommendation surface and the
 * transcript, both under one runtime. Products land in the first; prose in the
 * second (ADR-020).
 */
function Harness() {
  const { turns, pending, send } = useAgentChat();
  return (
    <>
      <SmartAgentRecommendations />
      <ChatWindow turns={turns} pending={pending} onSend={send} />
    </>
  );
}

const renderAgent = () =>
  renderWithProviders(
    <AgentRuntimeProvider>
      <Harness />
    </AgentRuntimeProvider>,
  );

async function ask(text = "a case for my iPhone 16") {
  const user = userEvent.setup();
  await user.type(screen.getByRole("textbox"), text);
  await user.keyboard("{Enter}");
  return user;
}

const chatCalls = () => calls.filter((c) => c.url.includes("/api/chat"));

beforeEach(() => {
  calls = [];
  // `clearSessionId()` rather than `sessionStorage.clear()`: session.ts keeps a
  // module-level in-memory fallback for browsers that block site data, and that
  // survives clearing storage, so one test's minted id would leak into the next.
  clearSessionId();
});
afterEach(() => vi.unstubAllGlobals());

describe("the agent runtime talks to our backend", () => {
  it("sends the buyer's message to POST /api/chat", async () => {
    stubFetch(() => ({ status: 200, body: turn() }));
    renderAgent();
    await ask();

    await waitFor(() => {
      const chat = chatCalls()[0];
      expect(chat?.method).toBe("POST");
      expect(chat?.body?.["message"]).toBe("a case for my iPhone 16");
    });
  });

  it("omits session_id on the first turn and reuses the minted one after", async () => {
    stubFetch(() => ({ status: 200, body: turn() }));
    renderAgent();
    const user = await ask("first");

    await waitFor(() => expect(screen.getByText("Here is what fits.")).toBeInTheDocument());

    await user.type(screen.getByRole("textbox"), "second");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(chatCalls()).toHaveLength(2);
      expect(chatCalls()[0]?.body?.["session_id"]).toBeUndefined();
      expect(chatCalls()[1]?.body?.["session_id"]).toBe("55555555-5555-5555-8555-555555555555");
    });
  });

  it("loads products into the recommendations panel, at the backend's price", async () => {
    stubFetch(() => ({ status: 200, body: turn() }));
    renderAgent();
    await ask();

    await waitFor(() => expect(screen.getByText("AeroCase Pro")).toBeInTheDocument());
    expect(screen.getByText(/999\.00/)).toBeInTheDocument();
  });

  it("keeps the cards out of the transcript, pointing at the panel instead (ADR-020)", async () => {
    stubFetch(() => ({ status: 200, body: turn({ message: "One case fits." }) }));
    renderAgent();
    await ask();

    await waitFor(() => expect(screen.getByText("One case fits.")).toBeInTheDocument());
    const log = screen.getByRole("log", { name: "Conversation" });
    // The transcript has the prose and the pointer, not the card.
    expect(log).toHaveTextContent(/1 product in your recommendations/i);
    expect(log).not.toHaveTextContent("AeroCase Pro");
  });

  it("shows no product when the prose names one but recommendations[] is empty", async () => {
    // F§9. A model describing a product it was never shown must not put a card
    // on screen anywhere; the structured half of the turn is the only source.
    stubFetch(() => ({
      status: 200,
      body: turn({ message: "The AeroCase Pro would suit you.", recommendations: [] }),
    }));
    renderAgent();
    await ask();

    await waitFor(() =>
      expect(screen.getByText("The AeroCase Pro would suit you.")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /add to cart/i })).not.toBeInTheDocument();
    expect(screen.getByText(/no matches/i)).toBeInTheDocument();
  });

  it("replaces the recommendation set when the conversation moves on", async () => {
    const first = turn({ message: "A case.", recommendations: [aeroCase] });
    const second = turn({
      message: "A charger instead.",
      recommendations: [
        {
          ...aeroCase,
          variant_id: "aaaaaaaa-aaaa-5aaa-8aaa-aaaaaaaaaaaa",
          name: "VoltEdge 20W",
        },
      ],
    });
    let call = 0;
    stubFetch(() => ({ status: 200, body: call++ === 0 ? first : second }));
    renderAgent();

    const user = await ask("a case");
    await waitFor(() => expect(screen.getByText("AeroCase Pro")).toBeInTheDocument());

    await user.type(screen.getByRole("textbox"), "a charger instead");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(screen.getByText("VoltEdge 20W")).toBeInTheDocument());
    // The previous set is gone, not appended.
    expect(screen.queryByText("AeroCase Pro")).not.toBeInTheDocument();
  });

  it("shows a retry affordance when the turn could not load recommendations", async () => {
    stubFetch(() => ({ status: 500, body: { detail: "boom" } }));
    renderAgent();
    await ask();

    await waitFor(() =>
      expect(screen.getByText(/couldn.t load product recommendations/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("treats a business outcome on HTTP 200 as a turn, not a transport failure", async () => {
    // ADR-010: a policy refusal or an out-of-stock finding arrives as `error` on
    // a 200 and must render as a recovery flow, never as "could not reach the
    // server".
    stubFetch(() => ({
      status: 200,
      body: turn({
        state: "OUT_OF_STOCK",
        message: "That one just sold out.",
        recommendations: [],
        error: { code: "OUT_OF_STOCK", message: "Out of stock", details: {} },
      }),
    }));
    renderAgent();
    await ask();

    await waitFor(() => expect(screen.getByText("That one just sold out.")).toBeInTheDocument());
    expect(screen.queryByText(/could not reach the server/i)).not.toBeInTheDocument();
  });

  it("surfaces a 5xx as a transport error", async () => {
    stubFetch(() => ({ status: 500, body: { detail: "boom" } }));
    renderAgent();
    await ask();

    await waitFor(() =>
      expect(screen.getByText(/status 500|something went wrong/i)).toBeInTheDocument(),
    );
  });

  it("never sends a price to the backend", async () => {
    // ADR-009: no endpoint in this system accepts a price. The adapter forwards
    // the buyer's text and nothing else.
    stubFetch(() => ({ status: 200, body: turn() }));
    renderAgent();
    await ask();

    await waitFor(() => expect(chatCalls()).toHaveLength(1));
    expect(JSON.stringify(chatCalls()[0]?.body)).not.toMatch(/price|amount|total/i);
  });
});
