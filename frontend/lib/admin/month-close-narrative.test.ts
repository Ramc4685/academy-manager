import { describe, expect, it } from "vitest";

import {
  NARRATIVE_FOOTNOTE,
  fixFirstLinks,
  narrativeErrorCopy,
  narrativeForPeriod,
} from "@/lib/admin/month-close-narrative";

describe("month-close narrator card (B5)", () => {
  it("maps each refusal to its plain sentence", () => {
    expect(narrativeErrorCopy({ status: 503 })).toBe(
      "AI summaries are not enabled for this academy yet",
    );
    expect(narrativeErrorCopy({ status: 403 })).toBe("AI summaries are part of the Growth plan");
    expect(narrativeErrorCopy({ status: 429 })).toBe(
      "This academy has used its AI drafts for the month",
    );
    expect(narrativeErrorCopy({ status: 502 })).toBe(
      "The summary could not be checked against the numbers, try again",
    );
  });

  it("never shows a raw error for anything else", () => {
    for (const error of [new Error("boom"), { status: 500 }, null, "x"]) {
      expect(narrativeErrorCopy(error)).toBe("The summary could not be written, try again");
    }
  });

  it("turns fix_first into at most three ordered link rows, dropping blanks", () => {
    const links = fixFirstLinks({
      fix_first: [
        { text: " Add a card for the Whitfield family ", href: "/admin/families/par-0" },
        { text: "", href: "/admin/dues" },
        { text: "Chase failed charges", href: "/admin/payments" },
        { text: "Review dues", href: "/admin/dues" },
        { text: "Fourth", href: "/admin/reports" },
      ],
    });
    expect(links.map((l) => [l.text, l.href])).toEqual([
      ["Add a card for the Whitfield family", "/admin/families/par-0"],
      ["Chase failed charges", "/admin/payments"],
      ["Review dues", "/admin/dues"],
    ]);
    expect(new Set(links.map((l) => l.key)).size).toBe(3);
  });

  it("shows a narrative only for the month it was written for", () => {
    const result = { period: "2026-10", narrative: { summary: "October" } };
    expect(narrativeForPeriod(result, "2026-10")).toEqual({ summary: "October" });
    expect(narrativeForPeriod(result, "2026-11")).toBeNull();
    expect(narrativeForPeriod(undefined, "2026-11")).toBeNull();
  });

  it("says the summary never calculates money", () => {
    expect(NARRATIVE_FOOTNOTE).toContain("never calculates money");
  });
});
