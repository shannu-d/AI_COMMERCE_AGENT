import { useQuery } from "@tanstack/react-query";

import { getCategories, getProduct, getProducts } from "../../api/endpoints";

/**
 * Catalog reads.
 *
 * Browsing is anonymous, so none of these is keyed by session — which is also
 * why they can be cached for far longer than anything cart-shaped. A price or a
 * stock level shown here is still only a *display*: the authoritative values are
 * re-read inside the order transaction, so a slightly stale card cannot cause a
 * wrong charge (ADR-011). That is what makes a generous `staleTime` safe here
 * and unsafe for the cart.
 */

/** Categories change with the seed, not with the session. */
export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: ({ signal }) => getCategories(signal),
    staleTime: 10 * 60_000,
  });
}

export type ProductQuery = {
  category?: string | undefined;
  q?: string | undefined;
  maxPrice?: string | undefined;
  sort?: string | undefined;
  limit?: number | undefined;
};

export function useProducts(params: ProductQuery) {
  return useQuery({
    // The params object is the key, so a filter change is a different cache
    // entry rather than a refetch that briefly shows the previous result.
    queryKey: ["products", params],
    queryFn: ({ signal }) => getProducts(params, signal),
    staleTime: 60_000,
    // Keeps the previous page on screen while the next one loads, so changing a
    // filter dims the grid instead of collapsing the page to a spinner.
    placeholderData: (previous) => previous,
  });
}

export function useProduct(slug: string | undefined) {
  return useQuery({
    queryKey: ["product", slug],
    queryFn: ({ signal }) => getProduct(slug!, signal),
    enabled: Boolean(slug),
    staleTime: 60_000,
  });
}
