import { describe, expect, it } from "vitest";

import { NO_DATA_TEXT, UNKNOWN_TEXT, finiteText, isSettled, statHint, statText } from "./load-state";

// Issue #837: a failed load must never render as "all clear". Every stat tile
// on the admin dashboard, the payments collections tiles and the People
// directory summary cards used to print the zero that a normalizer fills in
// for `undefined` data, which reads exactly like "nobody owes anything".

describe("isSettled", () => {
  it("is true only when the data actually arrived", () => {
    expect(isSettled({ isLoading: false, isError: false })).toBe(true);
    expect(isSettled({})).toBe(true);
  });

  it("is false while loading and after a failure", () => {
    expect(isSettled({ isLoading: true })).toBe(false);
    expect(isSettled({ isPending: true })).toBe(false);
    expect(isSettled({ isError: true })).toBe(false);
    // A refetch that failed is still a failure, even though nothing is pending.
    expect(isSettled({ isLoading: false, isError: true })).toBe(false);
  });
});

describe("statText", () => {
  it("shows a dash instead of a confident zero when the load failed", () => {
    expect(statText({ isError: true }, () => "$0.00")).toBe(UNKNOWN_TEXT);
    expect(statText({ isError: true }, () => "0")).toBe(UNKNOWN_TEXT);
  });

  it("shows a dash while the data is still in flight", () => {
    expect(statText({ isLoading: true }, () => "$0.00")).toBe(UNKNOWN_TEXT);
    expect(statText({ isPending: true }, () => "0")).toBe(UNKNOWN_TEXT);
  });

  it("never calls the formatter for data that did not arrive", () => {
    let calls = 0;
    statText({ isError: true }, () => {
      calls += 1;
      return "$0.00";
    });
    expect(calls).toBe(0);
  });

  it("shows the real value once the data is there — including a true zero", () => {
    expect(statText({ isLoading: false, isError: false }, () => "$0.00")).toBe("$0.00");
    expect(statText({}, () => "2")).toBe("2");
  });
});

describe("statHint", () => {
  it("withholds the supporting line until the data arrived", () => {
    expect(statHint({ isError: true }, () => "0 families")).toBeUndefined();
    expect(statHint({ isLoading: true }, () => "0 families")).toBeUndefined();
  });

  it("renders the hint once the data is there", () => {
    expect(statHint({}, () => "2 families")).toBe("2 families");
  });
});

describe("finiteText", () => {
  it("never renders NaN from an incomplete payload", () => {
    expect(finiteText(undefined, (n) => `$${n}`)).toBe(NO_DATA_TEXT);
    expect(finiteText(null, (n) => `$${n}`)).toBe(NO_DATA_TEXT);
    expect(finiteText(Number.NaN, (n) => `$${n}`)).toBe(NO_DATA_TEXT);
    expect(finiteText(Number.POSITIVE_INFINITY, (n) => `${n}%`)).toBe(NO_DATA_TEXT);
  });

  it("formats a real number, zero included", () => {
    expect(finiteText(0, (n) => `$${n}`)).toBe("$0");
    expect(finiteText(-250, (n) => `$${n}`)).toBe("$-250");
  });

  it("accepts a caller-chosen fallback", () => {
    expect(finiteText(Number.NaN, (n) => `$${n}`, UNKNOWN_TEXT)).toBe(UNKNOWN_TEXT);
  });
});
