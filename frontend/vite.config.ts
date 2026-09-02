// `defineConfig` from vitest/config, not vite: the `test` block below is Vitest's
// and vite's own UserConfig does not know about it.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Port 5173 is not incidental: it is what the backend's CORS_ALLOWED_ORIGINS
// defaults to (ADR-017). Changing it here means changing it there, or every
// request fails with an error the browser reports and the server does not.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // The live end-to-end suite needs a running backend, a seeded database
    // and a real model. It is opt-in via `--project live` style invocation
    // (see src/test/e2e.live.test.ts) and never part of the default run.
    exclude: ["**/node_modules/**", "**/dist/**", "**/*.live.test.ts"],
  },
});
