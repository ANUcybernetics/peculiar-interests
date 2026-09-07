import type { APIRoute } from "astro";

import { dataset } from "@/lib/data";

export const GET: APIRoute = () =>
  new Response(JSON.stringify(dataset().ledger, null, 1), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
