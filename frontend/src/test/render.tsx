import type { ReactElement, ReactNode } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

/**
 * Renders a component with the providers the app really uses.
 *
 * Retries are off and the cache is fresh per test: a retry would make a
 * deliberately-failing request take seconds, and a shared cache would let one
 * test's cart leak into the next.
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
        <MemoryRouter
          initialEntries={[route]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }

  return { queryClient, ...render(ui, { wrapper: Wrapper }) };
}
