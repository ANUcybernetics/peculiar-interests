// The one place the site touches the filesystem. Reads the committed data/
// tree at build time, validates it, and derives the cross-links (people ×
// statements, mentions, ledger) that every page draws on. Pure helpers live
// in derive.ts so they can be unit-tested without the files.
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { buildLedger, buildMentions, type LedgerEntry, type Mention } from "@/lib/derive";
import {
  PersonSchema,
  StatementSchema,
  type Chamber,
  type Person,
  type Statement,
} from "@/lib/schema";

const DATA_DIR = fileURLToPath(new URL("../../../data/", import.meta.url));
export const PARLIAMENT = 48;

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, "utf8"));
}

function loadStatements(chamber: Chamber): Statement[] {
  const dir = `${DATA_DIR}${PARLIAMENT}/${chamber}/`;
  let files: string[];
  try {
    files = readdirSync(dir).filter((f) => f.endsWith(".json"));
  } catch {
    return [];
  }
  return files.map((f) => StatementSchema.parse(readJson(dir + f)));
}

export interface Dataset {
  people: Person[];
  statements: Statement[];
  byId: Map<string, Statement>;
  personById: Map<string, Person>;
  ledger: LedgerEntry[];
  mentions: Mention[];
  generatedAt: string;
}

let cache: Dataset | undefined;

export function dataset(): Dataset {
  if (cache) return cache;
  const people = PersonSchema.array().parse(readJson(`${DATA_DIR}people.json`));
  const statements = [...loadStatements("house"), ...loadStatements("senate")].sort(
    (a, b) =>
      a.family_name.localeCompare(b.family_name, "en-AU") ||
      a.given_names.localeCompare(b.given_names, "en-AU"),
  );
  const byId = new Map(statements.map((s) => [s.aph_id, s]));
  const personById = new Map(people.map((p) => [p.aph_id, p]));
  cache = {
    people,
    statements,
    byId,
    personById,
    ledger: buildLedger(statements),
    mentions: buildMentions(statements),
    generatedAt: new Date().toISOString(),
  };
  return cache;
}
