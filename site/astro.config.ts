import sitemap from "@astrojs/sitemap";
import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

// Deployed to GitHub Pages at the domain root (custom domain to follow); every
// internal href still goes through withBase() in src/lib/paths.ts so a base
// change is a one-line edit.
export default defineConfig({
  site: "https://peculiarinterests.au",
  base: "/",
  trailingSlash: "ignore",
  output: "static",
  prefetch: { prefetchAll: true, defaultStrategy: "viewport" },
  vite: {
    css: { transformer: "lightningcss" },
    build: { cssMinify: "lightningcss" },
  },
  integrations: [
    svelte(),
    // The static API is machine-readable, not navigable.
    sitemap({ filter: (page) => !page.includes("/api/") }),
  ],
});
