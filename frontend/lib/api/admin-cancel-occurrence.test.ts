import { beforeEach, describe, expect, it, vi } from "vitest";

import { cancelSessionOccurrence } from "./admin";
import * as client from "./client";

describe("cancelSessionOccurrence (#671)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("POSTs the reason and notify flag to the occurrence cancel route", async () => {
    const spy = vi
      .spyOn(client, "apiFetch")
      .mockResolvedValue({ billing_result: "credited=3" } as never);

    await cancelSessionOccurrence("occ-1", {
      reason: "gym flooded",
      notify: true,
    });

    expect(spy).toHaveBeenCalledWith(
      "/admin/session-occurrences/occ-1/cancel",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ reason: "gym flooded", notify: true }),
      }),
    );
  });

  it("escapes the occurrence id so a slashed id cannot reach another route", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);

    await cancelSessionOccurrence("occ/1 2", { reason: "rain" });

    expect(spy.mock.calls[0][0]).toBe(
      "/admin/session-occurrences/occ%2F1%202/cancel",
    );
  });

  it("passes notify through when the admin has already told the families", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);

    await cancelSessionOccurrence("occ-1", {
      reason: "told them on WhatsApp",
      notify: false,
    });

    expect(JSON.parse(String(spy.mock.calls[0][1]?.body))).toEqual({
      reason: "told them on WhatsApp",
      notify: false,
    });
  });
});
