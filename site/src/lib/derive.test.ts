import { describe, expect, it } from "vitest";

import { buildLedger, buildMentions, splitNames } from "@/lib/derive";
import { slugify } from "@/lib/paths";
import type { Statement } from "@/lib/schema";

function statement(over: Partial<Statement>): Statement {
  return {
    aph_id: "X1",
    chamber: "house",
    parliament: 48,
    family_name: "Test",
    given_names: "Terry",
    display_name: "Test, Terry",
    honorific: null,
    party: null,
    state: null,
    electorate: null,
    date_lodged: null,
    last_updated: null,
    interests: [],
    alterations: [],
    notes: [],
    source: {
      url: "u",
      kind: "house-api-pdf",
      sha256: "s",
      fetched_at: "2026-01-01T00:00:00Z",
      raw_path: "r",
    },
    extraction: { method: "pdf-text", version: 1, notes: [] },
    ...over,
  };
}

describe("slugify", () => {
  it("normalises punctuation, case and ampersands", () => {
    expect(slugify("Commonwealth Bank of Australia")).toBe("commonwealth-bank-of-australia");
    expect(slugify("Qantas Chairman’s Lounge")).toBe("qantas-chairman-s-lounge");
    expect(slugify("A & B Pty Ltd")).toBe("a-and-b-pty-ltd");
  });
});

describe("splitNames", () => {
  it("splits joint declarations", () => {
    expect(splitNames("ING, Beyond Bank")).toEqual(["ING", "Beyond Bank"]);
    expect(splitNames("Westpac")).toEqual(["Westpac"]);
  });
});

describe("buildLedger", () => {
  it("orders newest first and prefers the processed date", () => {
    const s = statement({
      alterations: [
        {
          kind: "addition",
          category: "gifts",
          holder: "self",
          details: "old",
          fields: {},
          date_submitted: "2026-01-01",
          date_processed: "2026-01-05",
          sequence: 1,
          source_id: null,
        },
        {
          kind: "deletion",
          category: "gifts",
          holder: "self",
          details: "new",
          fields: {},
          date_submitted: "2026-02-01",
          date_processed: null,
          sequence: 2,
          source_id: null,
        },
      ],
    });
    const ledger = buildLedger([s]);
    expect(ledger.map((e) => [e.date, e.alteration.details])).toEqual([
      ["2026-02-01", "new"],
      ["2026-01-05", "old"],
    ]);
  });
});

describe("buildMentions", () => {
  it("groups spellings under one slug and ignores free-text categories", () => {
    const a = statement({
      aph_id: "A",
      interests: [
        {
          category: "liabilities",
          holder: "self",
          fields: { nature: "Mortgage", creditor: "Westpac" },
          source_id: null,
        },
        {
          category: "gifts",
          holder: "self",
          fields: { details: "Westpac umbrella" },
          source_id: null,
        },
      ],
    });
    const b = statement({
      aph_id: "B",
      interests: [
        {
          category: "accounts",
          holder: "spouse",
          fields: { nature: "Savings", institution: "WESTPAC" },
          source_id: null,
        },
      ],
    });
    const mentions = buildMentions([a, b]);
    expect(mentions).toHaveLength(1);
    expect(mentions[0]!.slug).toBe("westpac");
    expect(mentions[0]!.rows.map((r) => r.aph_id)).toEqual(["A", "B"]);
    expect(mentions[0]!.variants).toContain("WESTPAC");
  });
});
