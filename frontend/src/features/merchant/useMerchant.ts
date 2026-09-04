import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../components/toastContext";
import * as api from "./api";
import type { ProductCreateInput, ProductUpdateInput, VariantInput } from "./api";

/**
 * Query and mutation hooks for the merchant dashboard.
 *
 * TanStack Query owns server state here exactly as it does on the storefront —
 * there is no second copy. After a write the affected queries are invalidated,
 * so the list, the detail and the overview all re-read from the backend rather
 * than being patched locally. A price the merchant just changed is shown
 * because the server returned it, never because the client remembered it.
 */

const KEYS = {
  overview: ["merchant", "overview"] as const,
  categories: ["merchant", "categories"] as const,
  products: (params: Record<string, unknown>) => ["merchant", "products", params] as const,
  product: (id: string) => ["merchant", "product", id] as const,
  inventory: (params: Record<string, unknown>) => ["merchant", "inventory", params] as const,
  orders: (params: Record<string, unknown>) => ["merchant", "orders", params] as const,
  order: (id: string) => ["merchant", "order", id] as const,
  activity: (params: Record<string, unknown>) => ["merchant", "activity", params] as const,
};

export function useMerchantOverview() {
  return useQuery({
    queryKey: KEYS.overview,
    queryFn: ({ signal }) => api.getOverview(signal),
    staleTime: 15_000,
  });
}

export function useMerchantCategories() {
  return useQuery({
    queryKey: KEYS.categories,
    queryFn: ({ signal }) => api.getMerchantCategories(signal),
    staleTime: 5 * 60_000,
  });
}

export function useMerchantProducts(params: Parameters<typeof api.listMerchantProducts>[0]) {
  return useQuery({
    queryKey: KEYS.products(params),
    queryFn: ({ signal }) => api.listMerchantProducts(params, signal),
    staleTime: 10_000,
    placeholderData: (previous) => previous,
  });
}

export function useMerchantProduct(productId: string | undefined) {
  return useQuery({
    queryKey: KEYS.product(productId ?? ""),
    queryFn: ({ signal }) => api.getMerchantProduct(productId!, signal),
    enabled: Boolean(productId),
  });
}

export function useMerchantInventory(params: Parameters<typeof api.listInventory>[0]) {
  return useQuery({
    queryKey: KEYS.inventory(params),
    queryFn: ({ signal }) => api.listInventory(params, signal),
    staleTime: 10_000,
    placeholderData: (previous) => previous,
  });
}

export function useMerchantOrders(params: Parameters<typeof api.listMerchantOrders>[0]) {
  return useQuery({
    queryKey: KEYS.orders(params),
    queryFn: ({ signal }) => api.listMerchantOrders(params, signal),
    staleTime: 10_000,
    placeholderData: (previous) => previous,
  });
}

export function useMerchantActivity(params: Parameters<typeof api.listMerchantActivity>[0]) {
  return useQuery({
    queryKey: KEYS.activity(params),
    queryFn: ({ signal }) => api.listMerchantActivity(params, signal),
    staleTime: 5_000,
    placeholderData: (previous) => previous,
  });
}

export function useMerchantOrder(orderId: string | undefined) {
  return useQuery({
    queryKey: KEYS.order(orderId ?? ""),
    queryFn: ({ signal }) => api.getMerchantOrder(orderId!, signal),
    enabled: Boolean(orderId),
  });
}

/** Everything a write touches: the catalogue lists, the detail, and the tiles. */
function useInvalidateCatalog() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["merchant", "products"] });
    void qc.invalidateQueries({ queryKey: ["merchant", "inventory"] });
    void qc.invalidateQueries({ queryKey: ["merchant", "overview"] });
    void qc.invalidateQueries({ queryKey: ["merchant", "categories"] });
    // Every catalogue write records an activity entry, so the log is stale too.
    void qc.invalidateQueries({ queryKey: ["merchant", "activity"] });
    // The storefront reads the same rows — keep its caches honest too.
    void qc.invalidateQueries({ queryKey: ["products"] });
    void qc.invalidateQueries({ queryKey: ["categories"] });
    void qc.invalidateQueries({ queryKey: ["product"] });
  };
}

export function useCreateProduct() {
  const toast = useToast();
  const invalidate = useInvalidateCatalog();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProductCreateInput) => api.createMerchantProduct(body),
    onSuccess: (detail) => {
      qc.setQueryData(KEYS.product(detail.product_id), detail);
      invalidate();
      toast({ title: "Product created", detail: detail.name });
    },
    onError: (error) => toast({ title: "Could not create the product", detail: msg(error), tone: "critical" }),
  });
}

export function useUpdateProduct(productId: string) {
  const toast = useToast();
  const invalidate = useInvalidateCatalog();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProductUpdateInput) => api.updateMerchantProduct(productId, body),
    onSuccess: (detail) => {
      qc.setQueryData(KEYS.product(productId), detail);
      invalidate();
      toast({ title: "Saved" });
    },
    onError: (error) => toast({ title: "Could not save", detail: msg(error), tone: "critical" }),
  });
}

export function useArchiveProduct() {
  const toast = useToast();
  const invalidate = useInvalidateCatalog();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, archive }: { productId: string; archive: boolean }) =>
      archive ? api.archiveMerchantProduct(productId) : api.restoreMerchantProduct(productId),
    onSuccess: (detail, { archive }) => {
      qc.setQueryData(KEYS.product(detail.product_id), detail);
      invalidate();
      toast({ title: archive ? "Product archived" : "Product restored" });
    },
    onError: (error) => toast({ title: "That did not work", detail: msg(error), tone: "critical" }),
  });
}

export function useAddVariant(productId: string) {
  const toast = useToast();
  const invalidate = useInvalidateCatalog();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: VariantInput) => api.addMerchantVariant(productId, body),
    onSuccess: (detail) => {
      qc.setQueryData(KEYS.product(productId), detail);
      invalidate();
      toast({ title: "Variant added" });
    },
    onError: (error) => toast({ title: "Could not add the variant", detail: msg(error), tone: "critical" }),
  });
}

export function useUpdateVariant(productId: string) {
  const toast = useToast();
  const invalidate = useInvalidateCatalog();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ variantId, body }: { variantId: string; body: Record<string, unknown> }) =>
      api.updateMerchantVariant(variantId, body),
    onSuccess: (detail) => {
      qc.setQueryData(KEYS.product(productId), detail);
      invalidate();
      toast({ title: "Saved" });
    },
    onError: (error) => toast({ title: "Could not save", detail: msg(error), tone: "critical" }),
  });
}

export function useSetStock() {
  const toast = useToast();
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: ({ variantId, quantity }: { variantId: string; quantity: number }) =>
      api.setVariantStock(variantId, quantity),
    onSuccess: (row) => {
      invalidate();
      toast({ title: "Stock updated", detail: `${row.sku} — ${row.available_quantity} available` });
    },
    onError: (error) => toast({ title: "Could not update stock", detail: msg(error), tone: "critical" }),
  });
}

export function useCreateCategory() {
  const toast = useToast();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; slug?: string; parent?: string | null }) =>
      api.createMerchantCategory(body),
    onSuccess: (category) => {
      void qc.invalidateQueries({ queryKey: ["merchant", "categories"] });
      void qc.invalidateQueries({ queryKey: ["categories"] });
      void qc.invalidateQueries({ queryKey: ["merchant", "overview"] });
      toast({ title: "Category created", detail: category.name });
    },
    onError: (error) => toast({ title: "Could not create the category", detail: msg(error), tone: "critical" }),
  });
}

function msg(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}
