// Flat CSV views of the dataset for the static API. Pure: take Statements,
// return text.
import { alterationDate } from "@/lib/derive";
import { CATEGORY_INFO, type Statement } from "@/lib/schema";

export function csvEscape(value: string | number | null | undefined): string {
  const text = value == null ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function toCsv(header: string[], rows: (string | number | null | undefined)[][]): string {
  return [header, ...rows].map((r) => r.map(csvEscape).join(",")).join("\r\n") + "\r\n";
}

/** One row per (interest, field): long format, so any category fits. */
export function interestsCsv(statements: Statement[]): string {
  const rows: (string | number | null)[][] = [];
  for (const s of statements) {
    s.interests.forEach((i, n) => {
      for (const [field, value] of Object.entries(i.fields)) {
        rows.push([
          s.aph_id,
          s.chamber,
          s.family_name,
          s.given_names,
          s.party,
          s.electorate ?? s.state,
          CATEGORY_INFO[i.category].item,
          i.category,
          i.holder,
          n + 1,
          field,
          value,
        ]);
      }
    });
  }
  return toCsv(
    [
      "aph_id",
      "chamber",
      "family_name",
      "given_names",
      "party",
      "electorate_or_state",
      "item",
      "category",
      "holder",
      "row",
      "field",
      "value",
    ],
    rows,
  );
}

export function alterationsCsv(statements: Statement[]): string {
  const rows: (string | number | null)[][] = [];
  for (const s of statements) {
    for (const a of s.alterations) {
      rows.push([
        s.aph_id,
        s.chamber,
        s.family_name,
        s.given_names,
        s.party,
        alterationDate(a),
        a.date_submitted,
        a.date_processed,
        a.kind,
        a.category ? CATEGORY_INFO[a.category].item : null,
        a.category,
        a.holder,
        a.sequence,
        a.details,
      ]);
    }
  }
  return toCsv(
    [
      "aph_id",
      "chamber",
      "family_name",
      "given_names",
      "party",
      "date",
      "date_submitted",
      "date_processed",
      "kind",
      "item",
      "category",
      "holder",
      "sequence",
      "details",
    ],
    rows,
  );
}
