import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./render";
import { ChatWindow } from "../features/chat/ChatWindow";
import { ApprovalDialog } from "../features/checkout/ApprovalDialog";
import { CartPanel } from "../features/cart/CartPanel";
import { cart } from "./fixtures";

/**
 * F§13's accessibility requirements, asserted rather than asserted-in-a-comment.
 *
 * These cover the parts that are easy to get wrong and invisible when you do:
 * an unlabelled input, a dialog that strands keyboard focus, a live region that
 * never announces, and a status that only exists as colour.
 */

afterEach(() => vi.unstubAllGlobals());

function stubFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: status < 300, status, json: async () => body }) as Response),
  );
}

describe("the conversation is operable and announced", () => {
  it("labels the message input", () => {
    renderWithProviders(
      <ChatWindow turns={[]} pending={false} onSend={() => {}} />,
    );

    expect(screen.getByLabelText("Message")).toBeInTheDocument();
  });

  it("marks the transcript as a live region, so new turns are announced", () => {
    renderWithProviders(
      <ChatWindow turns={[]} pending={false} onSend={() => {}} />,
    );

    const log = screen.getByRole("log", { name: "Conversation" });
    expect(log).toHaveAttribute("aria-live", "polite");
  });

  it("exposes the thinking state as a status, not only as animation", () => {
    renderWithProviders(
      <ChatWindow turns={[]} pending={true} onSend={() => {}} />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/thinking/i);
  });

  it("can be driven entirely from the keyboard", async () => {
    const user = userEvent.setup();
    const sent: string[] = [];
    renderWithProviders(
      <ChatWindow turns={[]} pending={false} onSend={(t) => sent.push(t)} />,
    );

    await user.tab();
    await user.keyboard("a case for iPhone 16{Enter}");

    expect(sent).toEqual(["a case for iPhone 16"]);
  });

  it("refuses to send an empty message", async () => {
    const user = userEvent.setup();
    const sent: string[] = [];
    renderWithProviders(
      <ChatWindow turns={[]} pending={false} onSend={(t) => sent.push(t)} />,
    );

    await user.click(screen.getByLabelText("Message"));
    await user.keyboard("   {Enter}");

    expect(sent).toEqual([]);
  });

  it("does not let a second message interleave with one in flight", async () => {
    const user = userEvent.setup();
    const sent: string[] = [];
    renderWithProviders(
      <ChatWindow turns={[]} pending={true} onSend={(t) => sent.push(t)} />,
    );

    await user.click(screen.getByLabelText("Message"));
    await user.keyboard("second message{Enter}");

    expect(sent).toEqual([]);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});

describe("the approval dialog is a real dialog", () => {
  beforeEach(() => stubFetch(cart));

  it("is announced as a modal dialog with a name", () => {
    renderWithProviders(
      <ApprovalDialog cart={cart} sessionId="s-1" onClose={() => {}} onOrdered={() => {}} />,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName(/confirm your order/i);
  });

  it("closes on Escape, so a keyboard user is not trapped", async () => {
    const user = userEvent.setup();
    let closed = false;
    renderWithProviders(
      <ApprovalDialog
        cart={cart}
        sessionId="s-1"
        onClose={() => {
          closed = true;
        }}
        onOrdered={() => {}}
      />,
    );

    await user.keyboard("{Escape}");

    expect(closed).toBe(true);
  });

  it("moves focus into the dialog when it opens", async () => {
    renderWithProviders(
      <ApprovalDialog cart={cart} sessionId="s-1" onClose={() => {}} onOrdered={() => {}} />,
    );

    await waitFor(() => expect(screen.getByRole("dialog")).toHaveFocus());
  });
});

describe("stock is conveyed as text, not only as colour", () => {
  it("labels each quantity control with the product it belongs to", async () => {
    stubFetch(cart);
    renderWithProviders(<CartPanel sessionId="s-1" onApprove={() => {}} />);

    expect(await screen.findByLabelText(/quantity for aerocase pro/i)).toBeInTheDocument();
  });

  it("names an unavailable line in words", async () => {
    stubFetch({
      ...cart,
      items: [{ ...cart.items[0]!, available: false, stock_status: "OUT_OF_STOCK" }],
    });
    renderWithProviders(<CartPanel sessionId="s-1" onApprove={() => {}} />);

    expect(await screen.findByText("Out of stock")).toBeInTheDocument();
    // ...and the approve affordance is withdrawn rather than left to fail later.
    expect(screen.getByRole("button", { name: /review and approve/i })).toBeDisabled();
  });
});
