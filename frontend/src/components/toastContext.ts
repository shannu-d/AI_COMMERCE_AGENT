import { createContext, useContext } from "react";

/**
 * The toast context, kept apart from the provider component: a module exporting
 * both components and plain functions breaks React Fast Refresh for that module.
 */

export type ToastTone = "default" | "critical";

export type ToastInput = {
  title: string;
  detail?: string | undefined;
  tone?: ToastTone | undefined;
};

export const ToastContext = createContext<(t: ToastInput) => void>(() => {});

export const useToast = () => useContext(ToastContext);
