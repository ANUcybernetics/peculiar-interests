import { describe, expect, it } from "vitest";

import { buildLedger, buildMentions, giftTotal, giftValue, splitNames } from "@/lib/derive";
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

describe("giftValue", () => {
  it("reads the figure a member volunteered", () => {
    expect(giftValue("Book from Black Inc – received on 4 June 2025 – valued at $35")).toBe(35);
    expect(giftValue("RFDS Rug $370")).toBe(370);
    expect(giftValue("ETU contribution to catering (valued at $620.40)")).toBe(620.4);
  });

  it("multiplies a unit price by the count, ignoring the date", () => {
    expect(giftValue("Two tickets to Theatre Royal production valued at $99 each.")).toBe(198);
    expect(
      giftValue("23 Jun - five tickets to State of Origin from the NRL - value $184 each."),
    ).toBe(920);
    expect(giftValue("2 x $200 gift hampers from Lim's Pharmacy for fundraiser auction")).toBe(400);
  });

  it("prefers a stated total over the unit price beside it", () => {
    expect(giftValue("2 tickets to the Darwin Aboriginal Art Fair @ $75.00 = $150")).toBe(150);
    expect(giftValue("4 x Jerseys (Jerseys are worth $150.00 each). Total value $600.")).toBe(600);
  });

  it("reads nothing from an entry that names no value", () => {
    expect(giftValue("Membership of Qantas Chairman’s Lounge")).toBeNull();
    expect(giftValue("Various books. All less than $300.")).toBeNull();
    expect(giftValue("Registration for Women Deliver 2026, value $950 USD")).toBeNull();
    expect(giftValue("Laminated $2 Paper Note - Gifted by David Jochinke")).toBeNull();
  });

  it("ignores sums that prose quotes for something other than the gift", () => {
    const details =
      "Since 2020 Woolworths has raised $2.8 million dollars for WIRES to help support the " +
      "rescue and care of Australian wildlife, and this Christmas they expect to increase that " +
      "by $500,000 through the sale of limited edition chocolate loaf cakes. Jaimie Lovell from " +
      "the Woolworths group gifted my office our very own 620g cake – Value $25";
    expect(giftValue(details)).toBe(25);
  });
});

const gift = (details: string) => ({
  category: "gifts" as const,
  holder: "self" as const,
  fields: { details },
  source_id: null,
});

const added = (category: "gifts" | "travel-hospitality", details: string, sequence: number) => ({
  kind: "addition" as const,
  category,
  holder: "self" as const,
  details,
  fields: {},
  date_submitted: "2026-01-01",
  date_processed: null,
  sequence,
  source_id: null,
});

describe("giftTotal", () => {
  it("adds the lodged gifts to the ones notified since, and counts the silent ones", () => {
    const s = statement({
      interests: [gift("Hamper valued at $80"), gift("Signed cricket bat")],
      alterations: [
        added("gifts", "Tie from Sarina Russo - valued at $485", 1),
        added("travel-hospitality", "Grand final hospitality x 2", 2),
        { ...added("gifts", "Hamper valued at $80", 3), kind: "deletion" as const },
      ],
    });
    expect(giftTotal(s)).toEqual({ total: 565, valued: 2, entries: 3 });
  });

  it("reports nothing to add up when no entry names a value", () => {
    const s = statement({ interests: [gift("Membership of Qantas Chairman’s Lounge")] });
    expect(giftTotal(s)).toEqual({ total: 0, valued: 0, entries: 1 });
  });
});
