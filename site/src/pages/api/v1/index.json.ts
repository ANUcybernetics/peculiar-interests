import type { APIRoute } from "astro";

import { dataset, PARLIAMENT } from "@/lib/data";
import { withBase } from "@/lib/paths";

export const GET: APIRoute = ({ site }) => {
  const { statements, ledger, generatedAt } = dataset();
  const origin = site?.origin ?? "";
  const url = (p: string) => `${origin}${withBase(`/api/v1/${p}`)}`;
  return new Response(
    JSON.stringify(
      {
        name: "Peculiar Interests",
        description:
          "Registers of interests of Australian federal parliamentarians, extracted into one schema.",
        licence:
          "CC BY 4.0 (dataset); source documents are Parliament of Australia, CC BY-NC-ND 3.0 AU",
        parliament: PARLIAMENT,
        generated_at: generatedAt,
        counts: {
          statements: statements.length,
          interests: statements.reduce((n, s) => n + s.interests.length, 0),
          alterations: ledger.length,
        },
        endpoints: {
          people: url("people.json"),
          statements: url("statements.json"),
          statement: url("statements/{aph_id}.json"),
          interests_csv: url("interests.csv"),
          alterations_csv: url("alterations.csv"),
          ledger: url("ledger.json"),
          schema: url("schema.json"),
        },
      },
      null,
      1,
    ),
    { headers: { "Content-Type": "application/json; charset=utf-8" } },
  );
};
