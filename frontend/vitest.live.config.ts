import { defineConfig } from "vitest/config";

/**
 * The opt-in live suite.
 *
 * Separate from `vite.config.ts` so the default run can never pick it up by
 * accident: these tests need a running backend, a seeded database and a real
 * model, none of which the ordinary suite may depend on (ADR-015).
 *
 *   npm run test:live      # with a backend on E2E_BASE_URL
 */
export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    include: ["src/**/*.live.test.ts"],
    testTimeout: 120_000,
  },
});
