import type { APIRoute } from "astro";

import { alterationsCsv } from "@/lib/csv";
import { dataset } from "@/lib/data";

export const GET: APIRoute = () =>
  new Response(alterationsCsv(dataset().statements), {
    headers: { "Content-Type": "text/csv; charset=utf-8" },
  });
