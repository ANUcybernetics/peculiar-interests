import type { APIRoute, GetStaticPaths } from "astro";

import { dataset } from "@/lib/data";

export const getStaticPaths: GetStaticPaths = () =>
  dataset().statements.map((s) => ({ params: { aph_id: s.aph_id }, props: { statement: s } }));

export const GET: APIRoute = ({ props }) =>
  new Response(JSON.stringify(props.statement, null, 1), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
