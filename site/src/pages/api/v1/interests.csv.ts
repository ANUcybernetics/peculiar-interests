import type { APIRoute } from "astro";

import { interestsCsv } from "@/lib/csv";
import { dataset } from "@/lib/data";

export const GET: APIRoute = () =>
  new Response(interestsCsv(dataset().statements), {
    headers: { "Content-Type": "text/csv; charset=utf-8" },
  });
