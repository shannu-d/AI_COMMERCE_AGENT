import { useMutation, useQueryClient } from "@tanstack/react-query";

import { addCartItem } from "../../api/endpoints";
import { useToast } from "../../components/toastContext";
import { clearSessionId, isUnusableSession } from "../../session";
import { ensureSessionId } from "../../session.ensure";
import type { ProductCardData } from "./productCardData";

/**
 * Adding to the cart. One mutation site, so the rules can only be wrong once.
 *
 * The request carries a `variant_id` and a quantity and nothing else. It cannot
 * carry a price, because no endpoint in this system accepts one (ADR-009) — the
 * server prices the line from the catalogue and returns the authoritative cart,
 * which is then written straight into the query cache.
 *
 * The session is resolved **inside** the mutation, not read at render time: a
 * buyer who arrived by browsing has never spoken to the agent, so no session
 * exists until the first write mints one. Reading storage during render and
 * disabling the button on the result is how *Add to cart* ends up permanently
 * dead on a fresh browser.
 */
export function useAddToCart(
  item: Pick<ProductCardData, "variantId" | "name" | "variantName">,
  /** Overrides storage. The agent runtime owns the id it just minted, and
      reading storage instead would race the write on the very first turn. */
  sessionIdOverride?: string | null | undefined,
) {
  const queryClient = useQueryClient();
  const toast = useToast();

  return useMutation({
    mutationFn: async () => {
      const sessionId = sessionIdOverride ?? (await ensureSessionId());
      const add = (id: string) =>
        addCartItem({ session_id: id, variant_id: item.variantId, quantity: 1 });
      try {
        return { cart: await add(sessionId), sessionId };
      } catch (error) {
        // The stored session stopped being ours — claimed by an account this
        // browser is not signed into, or gone with a rebuilt database. The
        // backend cannot say which (404, never 403), and the id is spent either
        // way, so it is dropped and a fresh one minted. Once only: a second
        // refusal is a real failure. An explicit override is never replaced —
        // that id belongs to the caller, not to storage.
        if (sessionIdOverride || !isUnusableSession(error)) throw error;
        clearSessionId();
        const fresh = await ensureSessionId();
        return { cart: await add(fresh), sessionId: fresh };
      }
    },
    onSuccess: ({ cart, sessionId }) => {
      queryClient.setQueryData(["cart", sessionId], cart);
      void queryClient.invalidateQueries({ queryKey: ["cart"] });
      toast({ title: "Added to cart", detail: `${item.name} · ${item.variantName}` });
    },
    onError: (error) =>
      toast({
        title: "Could not add that",
        detail: error instanceof Error ? error.message : undefined,
        tone: "critical",
      }),
  });
}
