import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "./client";
import {
  checkPossibleDuplicates,
  duplicateKindLabel,
  duplicateProbe,
  sameProbe,
} from "./admin-people-duplicates";

afterEach(() => vi.restoreAllMocks());

describe("duplicate probe", () => {
  it("asks only when an email or a phone is usable", () => {
    expect(duplicateProbe({})).toBeNull();
    expect(duplicateProbe({ name: "Testparent One" })).toBeNull();
    expect(duplicateProbe({ email: "half-typed@" })).toBeNull();
    expect(duplicateProbe({ phone: "555-01" })).toBeNull();
    expect(duplicateProbe({ email: "  One@Example.TEST ", name: " Testparent   One " })).toEqual({
      email: "one@example.test",
      phone: null,
      name: "Testparent One",
    });
    expect(duplicateProbe({ phone: "(555) 010-2030" })).toEqual({
      email: null,
      phone: "(555) 010-2030",
      name: null,
    });
  });

  it("compares probes by value", () => {
    const a = duplicateProbe({ email: "a@example.test" });
    expect(sameProbe(a, duplicateProbe({ email: "A@example.test " }))).toBe(true);
    expect(sameProbe(a, duplicateProbe({ email: "b@example.test" }))).toBe(false);
    expect(sameProbe(null, null)).toBe(true);
    expect(sameProbe(a, null)).toBe(false);
  });

  it("labels every kind", () => {
    expect(duplicateKindLabel("family_contact")).toBe("family contact");
  });
});

describe("duplicate check client", () => {
  it("posts the probe and never an academy", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ matches: [] } as never);
    await checkPossibleDuplicates({ email: "one@example.test", phone: null, name: null });
    expect(spy.mock.calls[0]?.[0]).toBe("/admin/people/duplicate-check");
    const init = spy.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({ email: "one@example.test", phone: null, name: null });
    expect(body).not.toHaveProperty("academy_id");
  });
});
