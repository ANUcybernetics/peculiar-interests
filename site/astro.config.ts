import sitemap from "@astrojs/sitemap";
import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

// Deployed to GitHub Pages under the repository path until a custom domain is
// chosen; every internal href goes through withBase() in src/lib/paths.ts, so
// moving to a domain root is a two-line edit here (plus a CNAME in public/).
export default defineConfig({
  site: "https://anucybernetics.github.io",
  base: "/peculiar-interests",
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
