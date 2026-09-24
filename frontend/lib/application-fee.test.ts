import { describe, expect, it } from "vitest";

import {
  bpsToPercentInput,
  formatApplicationFee,
  percentInputToBps,
} from "./application-fee";

describe("application fee percent <-> basis points", () => {
  it("formats basis points as a percent", () => {
    expect(formatApplicationFee(0)).toBe("0%");
    expect(formatApplicationFee(250)).toBe("2.5%");
    expect(formatApplicationFee(125)).toBe("1.25%");
    expect(formatApplicationFee(1000)).toBe("10%");
  });

  it("round-trips the edit field", () => {
    expect(bpsToPercentInput(250)).toBe("2.5");
    expect(percentInputToBps(bpsToPercentInput(125), 1000)).toBe(125);
  });

  it("parses valid percents", () => {
    expect(percentInputToBps("0", 1000)).toBe(0);
    expect(percentInputToBps("2.5", 1000)).toBe(250);
    expect(percentInputToBps(" 1.25% ", 1000)).toBe(125);
    expect(percentInputToBps("10", 1000)).toBe(1000);
  });

  it("rejects anything that is not a valid fee", () => {
    expect(percentInputToBps("", 1000)).toBeNull();
    expect(percentInputToBps("abc", 1000)).toBeNull();
    expect(percentInputToBps("-1", 1000)).toBeNull();
    expect(percentInputToBps("1.234", 1000)).toBeNull();
    expect(percentInputToBps("10.01", 1000)).toBeNull();
  });
});
