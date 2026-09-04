import type { ReactElement, ReactNode } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { AuthProvider } from "../auth/AuthContext";

/**
 * Renders a component with the providers the app really uses.
 *
 * Retries are off and the cache is fresh per test: a retry would make a
 * deliberately-failing request take seconds, and a shared cache would let one
 * test's cart leak into the next.
 *
 * `AuthProvider` is included because the real tree has it, and because leaving
 * it out would let a component that reads auth state pass here and crash in the
 * browser. It boots anonymous — with no token in storage it makes no request —
 * so a test that does not care about sign-in is unaffected. A test that does
 * care signs in through the UI or seeds a token, exactly as a visitor would.
 */
export function renderWithProviders(ui: ReactElement, { route = "/" } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter
            initialEntries={[route]}
            future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
          >
            {children}
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    );
  }

  return { queryClient, ...render(ui, { wrapper: Wrapper }) };
}
