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
  type Group = { names: Map<string, number>; rows: MentionRow[] };
  const groups = new Map<string, Group>();
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
          const group: Group = groups.get(slug) ?? { names: new Map<string, number>(), rows: [] };
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

// --- Gift values -------------------------------------------------------------
// Neither register asks what a gift was worth, so a value exists only when the
// member volunteered one inside the free-text `details`. These functions read
// the figures that are there and count the entries that have none, so a page
// can show a floor rather than imply a total.

/** "$1,234.50" or "$2.8 million", with where it sits in the string. */
const AMOUNT = /\$\s?(\d[\d,]*(?:\.\d{1,2})?)(\s*(?:million|m\b))?/gi;
/** A figure that is explicitly a bound, not a value: "books, all less than $300". */
const BOUND_BEFORE = /\b(less than|under|below|up to|more than|over|at least|about)\s*$/i;
/** Words that mark the figure as the worth of the thing declared. */
const VALUE_CUE =
  /\b(value[ds]?|valuation|worth|costs?|priced?|amount|totall?(?:ing|ed)?|sum of|rrp|retail|est\.?|estimated|approx\.?|approximately|@|=|:|-|–|—)\s*[^$]{0,12}$/i;
/** The figure is the whole lot, so it wins over any per-item price beside it. */
const TOTAL_BEFORE = /\b(totall?(?:ing|ed)?|total|in the sum of|=)\b[^$]{0,28}$/i;
/** The figure is a unit price: multiply it by the count in the entry. */
const EACH_AFTER = /^\s*\.?\s*(each|ea\b|apiece|per (?:ticket|person|head|pax|guest))/i;
/** A count that governs a unit price: "5 x", "two tickets", "Nine bottles". */
const COUNT =
  /\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(?:x|×|[A-Za-z]{3,}s\b)/gi;
const WORD_NUMBERS: Record<string, number> = {
  one: 1,
  two: 2,
  three: 3,
  four: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  nine: 9,
  ten: 10,
  eleven: 11,
  twelve: 12,
};
/** Below this length an entry is a terse declaration, where a bare figure is
 * the value; above it the text is prose that may quote unrelated sums. */
const TERSE = 200;
/** What may follow a figure that no cue word introduced, if it is to be the
 * value of the gift: the end of a clause, or a preposition. A figure the noun
 * beside it belongs to is part of the gift ("Laminated $2 Paper Note"). */
const BARE_AFTER =
  /^\s*(?:$|[.,;:()[\]–—-]|\b(?:from|for|by|to|in|on|at|and|plus|per|each|inc\b|incl|approx|gifted|provided|courtesy|donated|via|with)\b)/i;
/** "2 x $200 gift hampers": the count comes before the unit price. */
const COUNT_BEFORE = /\d{1,2}\s*[x×]\s*$/i;

function count(text: string, before: number): number {
  COUNT.lastIndex = 0;
  for (const m of text.matchAll(COUNT)) {
    if (m.index >= before) break;
    const n = WORD_NUMBERS[m[1]!.toLowerCase()] ?? Number(m[1]);
    if (n > 1 && n <= 50) return n;
  }
  return 1;
}

/** The dollar value a gift entry states, or null when it states none. Reads
 * only figures the wording ties to the gift: a bare number counts in a terse
 * entry, but in long prose it must carry a cue like "valued at". */
export function giftValue(details: string): number | null {
  const text = details.replace(/\s+/g, " ");
  const totals: number[] = [];
  const each: number[] = [];
  const plain: number[] = [];
  for (const m of text.matchAll(AMOUNT)) {
    const start = m.index;
    const end = start + m[0].length;
    const before = text.slice(Math.max(0, start - 40), start);
    const after = text.slice(end, end + 25);
    if (BOUND_BEFORE.test(before)) continue;
    if (/^\s*(usd|us\$|euro|eur\b|gbp|nz)/i.test(after) || /\bus\s*$/i.test(before)) continue;
    const unit = COUNT_BEFORE.test(before);
    const cued = unit || VALUE_CUE.test(before);
    if (!cued && (text.length > TERSE || !BARE_AFTER.test(after))) continue;
    let amount = Number(m[1]!.replace(/,/g, ""));
    if (m[2]) amount *= 1_000_000;
    if (!Number.isFinite(amount) || amount <= 0) continue;
    if (TOTAL_BEFORE.test(before)) totals.push(amount);
    else if (unit || EACH_AFTER.test(after)) each.push(amount * count(text, start));
    else plain.push(amount);
  }
  const pick = totals.length ? totals : each.length ? each : plain;
  return pick.length ? Math.max(...pick) : null;
}

export interface GiftTotal {
  /** Sum of every stated value: a floor, never the worth of the gifts. */
  total: number;
  /** Entries that state a value, and entries in all (additions only). */
  valued: number;
  entries: number;
}

/** Gift entries for one person: the lodged item 11 rows plus every gift added
 * by alteration since. Deletions are left out — a withdrawn line is not a
 * negative gift. */
export function giftTotal(s: Statement): GiftTotal {
  const details = [
    ...s.interests.filter((i) => i.category === "gifts").map((i) => i.fields.details ?? ""),
    ...s.alterations
      .filter((a) => a.category === "gifts" && a.kind === "addition")
      .map((a) => a.details),
  ].filter((d) => d.trim());
  const values = details.map(giftValue).filter((v) => v !== null);
  return {
    total: values.reduce((a, b) => a + b, 0),
    valued: values.length,
    entries: details.length,
  };
}
