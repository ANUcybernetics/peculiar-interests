import { defineConfig } from "oxlint";

// oxlint does not lint .astro/.svelte files; those go through astro check and
// svelte-check instead.
export default defineConfig({
  categories: { correctness: "error", suspicious: "error", perf: "error" },
  env: { browser: true, builtin: true, es2024: true, node: true },
  ignorePatterns: ["dist/**", ".astro/**", "**/*.astro", "**/*.svelte"],
  plugins: ["typescript", "import", "unicorn"],
  rules: {
    "no-console": "off",
    eqeqeq: ["error", "always", { null: "ignore" }],
    "import-x/no-self-import": "error",
  },
});
