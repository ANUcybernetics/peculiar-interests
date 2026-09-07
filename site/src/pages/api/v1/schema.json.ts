import { readFileSync } from "node:fs";

import type { APIRoute } from "astro";

import { DATA_DIR } from "@/lib/data";

// Written by the Python side (`peculiar schema`) from the pydantic models, so the
// published schema is the writer's, not a hand-maintained copy.
const SCHEMA_PATH = `${DATA_DIR}schema.json`;

export const GET: APIRoute = () =>
  new Response(readFileSync(SCHEMA_PATH, "utf8"), {
    headers: { "Content-Type": "application/schema+json; charset=utf-8" },
  });
