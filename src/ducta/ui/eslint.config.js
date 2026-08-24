// Minimal, deliberately narrow lint gate: correctness (typescript-eslint,
// react-hooks) and accessibility (jsx-a11y) only — no stylistic rules. This
// is meant to catch the class of bug the UI audit found by hand (inputs
// with no accessible label, hook dependency mistakes), not to be a full
// style guide. Widen it once this baseline is clean and enforced in CI.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import globals from "globals";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      ".storybook/**",
      "storybook-static/**",
      "src/stories/**",
      "src/generated/**", // unused codegen tool, see openapi-generator.ts's own docstring
      "ds-bundle/**",
      "*.config.{js,ts}",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2021 },
    },
    plugins: {
      "react-hooks": reactHooks,
      "jsx-a11y": jsxA11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.configs.recommended.rules,

      // TypeScript already enforces this; a leading underscore is this
      // codebase's convention for "intentionally unused" (see api client's
      // own `_data` callback params).
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
  {
    files: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    rules: {
      // Test doubles legitimately need `any` and throwaway unused params.
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
);
