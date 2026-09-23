import { describe, expect, it } from "vitest";

import {
  ageSpan,
  formatAgeBand,
  formatAmount,
  formatClassDate,
  formatDays,
  formatPrice,
  formatPricePeriod,
  formatSeatBand,
  formatTimeRange,
  formatWhen,
  mapsSearchUrl,
  monogram,
  safeHexColor,
  safeHttpsUrl,
  truncate,
  weeklyClassCount,
} from "./format";

describe("price", () => {
  it("labels every period the backend allows", () => {
    expect(formatPricePeriod("month")).toBe("per month");
    expect(formatPricePeriod("class")).toBe("per class");
    expect(formatPricePeriod("term")).toBe("per term");
  });

  it("falls back to per month for an unknown or missing period", () => {
    expect(formatPricePeriod("fortnight")).toBe("per month");
    expect(formatPricePeriod(null)).toBe("per month");
  });

  it("drops cents on whole amounts and keeps them otherwise", () => {
    expect(formatAmount(12000, "USD")).toBe("$120");
    expect(formatAmount(4550, "USD")).toBe("$45.50");
    expect(formatAmount(123400, "USD")).toBe("$1,234");
  });

  it("formats the academy's own currency", () => {
    expect(formatAmount(12000, "EUR")).toBe("€120");
    expect(formatAmount(12000, "gbp")).toBe("£120");
  });

  it("never throws on a bad currency code", () => {
    expect(formatAmount(12000, "NOT-A-CODE")).toBe("120 NOT-A-CODE");
  });

  it("shows a zero price as Free with no period", () => {
    expect(formatPrice({ amount_cents: 0, period: "month" }, "USD")).toEqual({
      amount: "Free",
      period: "",
    });
  });

  it("pairs amount and period", () => {
    expect(formatPrice({ amount_cents: 7000, period: "class" }, "USD")).toEqual({
      amount: "$70",
      period: "per class",
    });
    expect(formatPrice({ amount_cents: 31000, period: "term" }, "USD")?.period).toBe("per term");
  });

  it("returns null when the price is hidden or missing", () => {
    expect(formatPrice(null, "USD")).toBeNull();
  });
});

describe("seat band", () => {
  it("labels an open class", () => {
    expect(formatSeatBand({ band: "open", seats_left: null })).toEqual({
      text: "Open",
      tone: "ok",
      full: false,
    });
  });

  it("shows the small number inside the few band", () => {
    expect(formatSeatBand({ band: "few", seats_left: 3 })?.text).toBe("3 spots left");
    expect(formatSeatBand({ band: "few", seats_left: 1 })?.text).toBe("1 spot left");
    expect(formatSeatBand({ band: "few", seats_left: 2 })?.tone).toBe("few");
  });

  it("does not invent a number when few arrives without one", () => {
    expect(formatSeatBand({ band: "few", seats_left: null })?.text).toBe("A few spots left");
    expect(formatSeatBand({ band: "few", seats_left: 0 })?.text).toBe("A few spots left");
  });

  it("shows a full class as exactly 'Full, join waitlist'", () => {
    expect(formatSeatBand({ band: "waitlist", seats_left: null })).toEqual({
      text: "Full, join waitlist",
      tone: "queue",
      full: true,
    });
  });

  it("hides availability when the academy turned it off or the band is unknown", () => {
    expect(formatSeatBand(null)).toBeNull();
    expect(formatSeatBand({ band: "mystery", seats_left: null })).toBeNull();
  });
});

describe("age band", () => {
  it("formats full, open-ended, capped and single-age bands", () => {
    expect(formatAgeBand({ min_age: 6, max_age: 8 })).toBe("Ages 6 to 8");
    expect(formatAgeBand({ min_age: 18, max_age: null })).toBe("Ages 18 and up");
    expect(formatAgeBand({ min_age: null, max_age: 12 })).toBe("Up to age 12");
    expect(formatAgeBand({ min_age: 10, max_age: 10 })).toBe("Age 10");
  });

  it("returns null when nothing is known", () => {
    expect(formatAgeBand(null)).toBeNull();
    expect(formatAgeBand({ min_age: null, max_age: null })).toBeNull();
  });

  it("spans every band and stays open-ended when any band is", () => {
    expect(ageSpan([{ min_age: 6, max_age: 8 }, { min_age: 13, max_age: 18 }, null])).toEqual({
      min_age: 6,
      max_age: 18,
    });
    expect(ageSpan([{ min_age: 6, max_age: 8 }, { min_age: 18, max_age: null }])).toEqual({
      min_age: 6,
      max_age: null,
    });
    expect(ageSpan([null, undefined])).toBeNull();
  });
});

describe("schedule", () => {
  it("spells out a single day and joins several", () => {
    expect(formatDays(["Sat"])).toBe("Saturday");
    expect(formatDays(["Mon", "Wed"])).toBe("Mon & Wed");
    expect(formatDays(["tue", "Thu", "Sat"])).toBe("Tue, Thu & Sat");
    expect(formatDays([])).toBe("");
  });

  it("formats a time range on a 12-hour clock", () => {
    expect(formatTimeRange("16:30", "17:30")).toBe("4:30 to 5:30 PM");
    expect(formatTimeRange("11:00", "12:15")).toBe("11 AM to 12:15 PM");
    expect(formatTimeRange("09:00", "10:00")).toBe("9 to 10 AM");
    expect(formatTimeRange("00:30", null)).toBe("12:30 AM");
    expect(formatTimeRange(null, null)).toBe("");
    expect(formatTimeRange("late", "later")).toBe("");
  });

  it("formats a one-off class date without shifting the day", () => {
    expect(formatClassDate("2026-10-03")).toBe("Sat, Oct 3");
    expect(formatClassDate("nope")).toBe("");
    expect(formatWhen({ days_of_week: [], starts_on: "2026-10-03" })).toBe("Sat, Oct 3");
    expect(formatWhen({ days_of_week: ["Fri"], starts_on: null })).toBe("Friday");
    expect(formatWhen({ days_of_week: [], starts_on: null })).toBe("Schedule to be confirmed");
  });

  it("counts weekly class meetings", () => {
    expect(weeklyClassCount([{ days_of_week: ["Mon", "Wed"] }, { days_of_week: ["Sat"] }])).toBe(3);
  });
});

describe("text and safety guards", () => {
  it("truncates at the budget with an ellipsis", () => {
    expect(truncate("Short", 60)).toBe("Short");
    const long = "A".repeat(70);
    const cut = truncate(long, 60);
    expect(cut).toHaveLength(60);
    expect(cut.endsWith("…")).toBe(true);
  });

  it("builds a two-letter monogram", () => {
    expect(monogram("Riverside Shuttle Club")).toBe("RS");
    expect(monogram("Rally")).toBe("RA");
    expect(monogram("   ")).toBe("?");
  });

  it("accepts only hex colours", () => {
    expect(safeHexColor("#0f766e", "#000")).toBe("#0f766e");
    expect(safeHexColor("red;background:url(x)", "#0f172a")).toBe("#0f172a");
    expect(safeHexColor(null, "#fff")).toBe("#fff");
  });

  it("accepts only https URLs", () => {
    expect(safeHttpsUrl("https://cdn.example/logo.png")).toBe("https://cdn.example/logo.png");
    expect(safeHttpsUrl("http://cdn.example/logo.png")).toBeNull();
    expect(safeHttpsUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpsUrl("not a url")).toBeNull();
  });

  it("encodes the maps search", () => {
    expect(mapsSearchUrl("214 Millbrook Road, Riverside")).toBe(
      "https://www.google.com/maps/search/?api=1&query=214%20Millbrook%20Road%2C%20Riverside",
    );
  });
});
