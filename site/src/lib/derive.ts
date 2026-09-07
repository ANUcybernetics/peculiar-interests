// Pure derivations over Statements: the cross-house ledger of alterations and
// the "mentions" index that turns every declared company, creditor,
// institution or sponsor into a page. No I/O; see data.ts for loading.
import { slugify } from "@/lib/paths";
import type { Alteration, Category, Interest, Statement } from "@/lib/schema";

export interface LedgerEntry {
  date: string; // ISO; processed date where the House stamps one, else submitted
  aph_id: string;
  chamber: Statement["chamber"];
  display_name: string;
  given_names: string;
  family_name: string;
  party: string | null;
  alteration: Alteration;
}

export function alterationDate(a: Alteration): string | null {
  return a.date_processed ?? a.date_submitted;
}

/** Every dated alteration across every statement, newest first, then by the
 * source document order so same-day entries keep their sequence. */
export function buildLedger(statements: Statement[]): LedgerEntry[] {
  const entries: LedgerEntry[] = [];
  for (const s of statements) {
    for (const alteration of s.alterations) {
      const date = alterationDate(alteration);
      if (!date) continue;
      entries.push({
        date,
        aph_id: s.aph_id,
        chamber: s.chamber,
        display_name: s.display_name,
        given_names: s.given_names,
        family_name: s.family_name,
        party: s.party,
        alteration,
      });
    }
  }
  return entries.toSorted(
    (a, b) =>
      b.date.localeCompare(a.date) ||
      a.family_name.localeCompare(b.family_name) ||
      b.alteration.sequence - a.alteration.sequence,
  );
}

/** Which fields name a thing worth a page of its own, per category. Free-text
 * fields (gift details, travel details, "nature") are not mentions. */
export const MENTION_FIELDS: Partial<Record<Category, string[]>> = {
  shareholdings: ["company"],
  trusts: ["name"],
  directorships: ["company"],
  partnerships: ["name"],
  liabilities: ["creditor"],
  investments: ["body"],
  accounts: ["institution"],
  memberships: ["organisation"],
};

export interface MentionRow {
  aph_id: string;
  chamber: Statement["chamber"];
  display_name: string;
  category: Category;
  holder: Interest["holder"];
  interest: Interest;
}

export interface Mention {
  slug: string;
  /** The most common spelling among the declarations grouped here. */
  name: string;
  variants: string[];
  rows: MentionRow[];
}

/** Split a comma- or semicolon-separated cell ("ING, Beyond Bank") into names. */
export function splitNames(value: string): string[] {
  return value
    .split(/[;,]|\band\b|&/)
    .map((v) => v.trim())
    .filter((v) => v.length > 1);
}

export function buildMentions(statements: Statement[]): Mention[] {
  const groups = new Map<string, { names: Map<string, number>; rows: MentionRow[] }>();
  for (const s of statements) {
    for (const interest of s.interests) {
      const fields = MENTION_FIELDS[interest.category];
      if (!fields) continue;
      for (const field of fields) {
        const value = interest.fields[field];
        if (!value) continue;
        for (const name of splitNames(value)) {
          const slug = slugify(name);
          if (!slug) continue;
          const group = groups.get(slug) ?? { names: new Map(), rows: [] };
          group.names.set(name, (group.names.get(name) ?? 0) + 1);
          group.rows.push({
            aph_id: s.aph_id,
            chamber: s.chamber,
            display_name: s.display_name,
            category: interest.category,
            holder: interest.holder,
            interest,
          });
          groups.set(slug, group);
        }
      }
    }
  }
  return [...groups.entries()]
    .map(([slug, g]) => {
      const variants = [...g.names.entries()].toSorted((a, b) => b[1] - a[1]).map(([n]) => n);
      return { slug, name: variants[0]!, variants, rows: g.rows };
    })
    .toSorted((a, b) => b.rows.length - a.rows.length || a.name.localeCompare(b.name));
}

/** Distinct people (by aph_id) among a mention's rows. */
export function mentionPeople(m: Mention): number {
  return new Set(m.rows.map((r) => r.aph_id)).size;
}

export function countByCategory(statements: Statement[]): Record<Category, number> {
  const counts = Object.create(null) as Record<Category, number>;
  for (const s of statements)
    for (const i of s.interests) counts[i.category] = (counts[i.category] ?? 0) + 1;
  return counts;
}
