// Flat config (ESLint 9). package.json has declared `lint: eslint .` since the
// scaffold, but neither the tool nor a config existed, so the script failed on
// a clean checkout and CI had no frontend lint step. This supplies both.
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "node_modules"] },

  // Application and test sources. Type-checking rules are deliberately not
  // enabled: `npm run typecheck` already runs tsc over the same files, and
  // duplicating that here would only make the two disagree.
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // An unused name prefixed with _ is an intentional placeholder, most
      // often a positional callback argument that has to be named to reach
      // the one after it.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },

  // Build and tooling config files run in Node, not the browser.
  {
    files: ["*.config.{js,ts}", "vitest.live.config.ts"],
    languageOptions: { globals: globals.node },
  },
);
