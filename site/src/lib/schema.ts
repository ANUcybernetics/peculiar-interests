// zod mirror of src/pollie_watch/schema.py. Every file under data/ is parsed
// through these once at build time, so a drift between the Python writer and
// this reader fails the build rather than rendering blanks.
import { z } from "zod";

export const CATEGORIES = [
  "shareholdings",
  "trusts",
  "real-estate",
  "directorships",
  "partnerships",
  "liabilities",
  "investments",
  "accounts",
  "other-assets",
  "other-income",
  "gifts",
  "travel-hospitality",
  "memberships",
  "other-interests",
] as const;

export type Category = (typeof CATEGORIES)[number];

export const HOLDERS = ["self", "spouse", "dependent", "unspecified"] as const;
export type Holder = (typeof HOLDERS)[number];

export const CHAMBERS = ["house", "senate"] as const;
export type Chamber = (typeof CHAMBERS)[number];

export const EXTRACTION_METHODS = ["senate-api", "pdf-text", "ocr", "manual", "pending"] as const;
export type ExtractionMethod = (typeof EXTRACTION_METHODS)[number];

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

export const InterestSchema = z.object({
  category: z.enum(CATEGORIES),
  holder: z.enum(HOLDERS),
  fields: z.record(z.string(), z.string()),
  source_id: z.string().nullable(),
});
export type Interest = z.infer<typeof InterestSchema>;

export const AlterationSchema = z.object({
  kind: z.enum(["addition", "deletion"]),
  category: z.enum(CATEGORIES).nullable(),
  holder: z.enum(HOLDERS),
  details: z.string(),
  fields: z.record(z.string(), z.string()),
  date_submitted: isoDate.nullable(),
  date_processed: isoDate.nullable(),
  sequence: z.number().int(),
  source_id: z.string().nullable(),
});
export type Alteration = z.infer<typeof AlterationSchema>;

export const StatementSchema = z.object({
  aph_id: z.string(),
  chamber: z.enum(CHAMBERS),
  parliament: z.number().int(),
  family_name: z.string(),
  given_names: z.string(),
  display_name: z.string(),
  honorific: z.string().nullable(),
  party: z.string().nullable(),
  state: z.string().nullable(),
  electorate: z.string().nullable(),
  date_lodged: isoDate.nullable(),
  last_updated: isoDate.nullable(),
  interests: z.array(InterestSchema),
  alterations: z.array(AlterationSchema),
  notes: z.array(z.string()),
  source: z.object({
    url: z.string(),
    kind: z.enum(["senate-api", "house-api-pdf", "house-static-pdf"]),
    sha256: z.string(),
    fetched_at: z.string(),
    raw_path: z.string(),
  }),
  extraction: z.object({
    method: z.enum(EXTRACTION_METHODS),
    version: z.number().int(),
    notes: z.array(z.string()),
  }),
});
export type Statement = z.infer<typeof StatementSchema>;

export const PersonSchema = z.object({
  aph_id: z.string(),
  family_name: z.string(),
  given_names: z.string(),
  preferred_name: z.string().nullable(),
  honorific: z.string().nullable(),
  post_nominals: z.string().nullable(),
  gender: z.string().nullable(),
  chamber: z.enum(CHAMBERS),
  party: z.string().nullable(),
  party_code: z.string().nullable(),
  state: z.string().nullable(),
  electorate: z.string().nullable(),
  parliaments: z.array(z.number().int()),
  aph_url: z.string().nullable(),
});
export type Person = z.infer<typeof PersonSchema>;

/** The fourteen items as the form numbers and names them. `short` is the
 * rubric used in ledgers and headings; `label` is the fuller question. */
export const CATEGORY_INFO: Record<Category, { item: number; short: string; label: string }> = {
  shareholdings: {
    item: 1,
    short: "Shareholdings",
    label: "Shareholdings in public and private companies",
  },
  trusts: { item: 2, short: "Trusts", label: "Family and business trusts and nominee companies" },
  "real-estate": { item: 3, short: "Real estate", label: "Real estate, by location and purpose" },
  directorships: { item: 4, short: "Directorships", label: "Directorships of companies" },
  partnerships: { item: 5, short: "Partnerships", label: "Partnerships" },
  liabilities: { item: 6, short: "Liabilities", label: "Liabilities, and the creditor concerned" },
  investments: { item: 7, short: "Investments", label: "Bonds, debentures and like investments" },
  accounts: { item: 8, short: "Accounts", label: "Savings and investment accounts" },
  "other-assets": {
    item: 9,
    short: "Other assets",
    label: "Other assets each valued at over $7,500",
  },
  "other-income": { item: 10, short: "Other income", label: "Other substantial sources of income" },
  gifts: { item: 11, short: "Gifts", label: "Gifts" },
  "travel-hospitality": {
    item: 12,
    short: "Sponsored travel",
    label: "Sponsored travel or hospitality over $300",
  },
  memberships: {
    item: 13,
    short: "Memberships",
    label: "Membership of organisations where a conflict could arise",
  },
  "other-interests": {
    item: 14,
    short: "Other interests",
    label: "Any other interest that could give rise to a conflict",
  },
};

/** Canonical field order per category (schema.py CATEGORY_FIELDS). */
export const CATEGORY_FIELDS: Record<Category, readonly string[]> = {
  shareholdings: ["company"],
  trusts: ["name", "nature", "beneficial_interest", "role"],
  "real-estate": ["location", "purpose"],
  directorships: ["company", "activities"],
  partnerships: ["name", "nature", "activities"],
  liabilities: ["nature", "creditor"],
  investments: ["type", "body"],
  accounts: ["nature", "institution"],
  "other-assets": ["nature"],
  "other-income": ["nature"],
  gifts: ["details"],
  "travel-hospitality": ["details"],
  memberships: ["organisation"],
  "other-interests": ["nature"],
};

/** The fields present across a set of interests, in canonical order. */
export function fieldOrder(
  category: Category,
  interests: { fields: Record<string, string> }[],
): string[] {
  const present = new Set(interests.flatMap((i) => Object.keys(i.fields)));
  const ordered = CATEGORY_FIELDS[category].filter((f) => present.has(f));
  const extra = [...present].filter((f) => !CATEGORY_FIELDS[category].includes(f)).toSorted();
  return [...ordered, ...extra];
}

/** Field labels per canonical field name (schema.py CATEGORY_FIELDS). */
export const FIELD_LABELS: Record<string, string> = {
  company: "Company",
  name: "Name",
  nature: "Nature",
  beneficial_interest: "Beneficial interest",
  role: "Role",
  location: "Location",
  purpose: "Purpose",
  activities: "Activities",
  creditor: "Creditor",
  type: "Type",
  body: "Body",
  institution: "Institution",
  details: "Details",
  organisation: "Organisation",
};

export const HOLDER_LABELS: Record<Holder, string> = {
  self: "Self",
  spouse: "Spouse or partner",
  dependent: "Dependent children",
  unspecified: "",
};

export const CHAMBER_LABELS: Record<Chamber, { noun: string; member: string; plural: string }> = {
  house: { noun: "House", member: "Member", plural: "Members" },
  senate: { noun: "Senate", member: "Senator", plural: "Senators" },
};
