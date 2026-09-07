import { describe, expect, it } from "vitest";

import { csvEscape, toCsv } from "@/lib/csv";

describe("csv", () => {
  it("quotes only what needs quoting", () => {
    expect(csvEscape("plain")).toBe("plain");
    expect(csvEscape('say "hi", now')).toBe('"say ""hi"", now"');
    expect(csvEscape(null)).toBe("");
    expect(csvEscape(12)).toBe("12");
  });

  it("emits CRLF rows with a header", () => {
    expect(toCsv(["a", "b"], [["1", "x,y"]])).toBe('a,b\r\n1,"x,y"\r\n');
  });
});
