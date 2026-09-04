import { useMutation, useQueryClient } from "@tanstack/react-query";

import { addCartItem } from "../../api/endpoints";
import { useToast } from "../../components/toastContext";
import { readSessionId } from "../../session";
import type { ProductCardData } from "./productCardData";

/**
 * Adding to the cart. One mutation site, so the rules can only be wrong once.
 *
 * The request carries a `variant_id` and a quantity and nothing else. It cannot
 * carry a price, because no endpoint in this system accepts one (ADR-009) — the
 * server prices the line from the catalogue and returns the authoritative cart,
 * which is then written straight into the query cache.
 */
export function useAddToCart(
  item: Pick<ProductCardData, "variantId" | "name" | "variantName">,
  /** Overrides storage. The agent runtime owns the id it just minted, and
      reading storage instead would race the write on the very first turn. */
  sessionIdOverride?: string | null | undefined,
) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const sessionId = sessionIdOverride ?? readSessionId();

  return useMutation({
    mutationFn: () =>
      addCartItem({ session_id: sessionId!, variant_id: item.variantId, quantity: 1 }),
    onSuccess: (cart) => {
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
