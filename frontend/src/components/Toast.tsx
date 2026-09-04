import { useCallback, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { cx } from "./cx";
import { ToastContext, type ToastInput, type ToastTone } from "./toastContext";

/**
 * Toasts, hand-rolled.
 *
 * A toast library would be roughly the same amount of code as this file plus a
 * dependency, and none of the ones worth using are small. What is actually
 * needed here is narrow: confirm a cart change, report a failure, auto-dismiss,
 * and stay announceable.
 *
 * The region is `aria-live="polite"` and `role="status"`, so a confirmation is
 * spoken without stealing focus — a cart addition should never interrupt what
 * someone is reading.
 */

type Toast = { id: number; title: string; detail?: string | undefined; tone: ToastTone };

const LIFETIME_MS = 3600;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const push = useCallback((t: ToastInput) => {
    const id = nextId.current++;
    setToasts((prev) => [...prev.slice(-2), { ...t, id, tone: t.tone ?? "default" }]);
    window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), LIFETIME_MS);
  }, []);

  // The provider value is stable, so consuming a toast function never re-renders
  // a component for an unrelated toast.
  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cx(
              "animate-sheet pointer-events-auto flex w-full max-w-sm items-start gap-3 border px-4 py-3 shadow-[0_1px_0_rgb(var(--rule))]",
              toast.tone === "critical"
                ? "border-critical/30 bg-critical-bg"
                : "border-ink bg-ink text-paper",
            )}
          >
            <span
              aria-hidden="true"
              className={cx(
                "mt-1.5 h-1.5 w-1.5 shrink-0",
                toast.tone === "critical" ? "bg-critical" : "bg-volt",
              )}
            />
            <div className="min-w-0">
              <p className="text-sm font-medium">{toast.title}</p>
              {toast.detail && (
                <p
                  className={cx(
                    "mt-0.5 truncate text-2xs",
                    toast.tone === "critical" ? "text-critical/80" : "text-paper/60",
                  )}
                >
                  {toast.detail}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
