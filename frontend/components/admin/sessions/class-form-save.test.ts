import { describe, expect, it, vi } from "vitest";

import type {
  AdminSessionView,
  CreateSessionRequest,
  EditSessionRequest,
} from "@/lib/api/admin";

import {
  CUSTOM_PRICE,
  classFormFromSession,
  type ClassFormValues,
} from "./class-form-logic";
import { saveClassCreate, saveClassEdit } from "./class-form-save";

function session(overrides: Partial<AdminSessionView> = {}): AdminSessionView {
  return {
    session_id: "s-1",
    status: "scheduled",
    coach_id: "coach-1",
    title: "Beginner",
    location: "YWCA",
    start_at: "2026-10-01T22:45:00Z",
    end_at: "2026-10-01T23:30:00Z",
    days_of_week: ["Wed"],
    start_time: "17:45",
    end_time: "18:30",
    timezone: "America/Chicago",
    capacity: 16,
    amount_cents: 6000,
    enrolled_count: 12,
    waitlist_count: 0,
    ...overrides,
  } as AdminSessionView;
}

/** A fake API that records every call in order, mirroring the real contract:
 * the link PUT refuses (409) a plan whose price is not the stored class fee. */
function fakeApi(
  opts: {
    stored?: AdminSessionView;
    planPrices?: Record<string, number>;
    failLink?: Error;
  } = {},
) {
  let stored = opts.stored ?? session();
  const calls: Array<[string, unknown]> = [];
  const api = {
    updateSession: vi.fn(async (id: string, payload: EditSessionRequest) => {
      calls.push(["update", { id, payload }]);
      const next = { ...stored, ...payload } as AdminSessionView;
      stored = next;
      return next;
    }),
    createSession: vi.fn(async (payload: CreateSessionRequest) => {
      calls.push(["create", payload]);
      stored = session({
        session_id: "s-new",
        amount_cents: payload.amount_cents ?? null,
      });
      return stored;
    }),
    setClassPlan: vi.fn(async (id: string, planId: string | null) => {
      calls.push(["link", { id, planId }]);
      if (opts.failLink) throw opts.failLink;
      if (planId && opts.planPrices?.[planId] !== stored.amount_cents) {
        throw new Error("Plan price does not match the class fee.");
      }
      return {};
    }),
  };
  return { api, calls, stored: () => stored };
}

function values(
  base: AdminSessionView,
  patch: Partial<ClassFormValues> = {},
): ClassFormValues {
  return { ...classFormFromSession(base), ...patch };
}

describe("saveClassEdit", () => {
  it("writes the plan's fee first, then links the class (so the link is not refused)", async () => {
    const base = session({ amount_cents: 6000 });
    const { api, calls, stored } = fakeApi({
      stored: base,
      planPrices: { "plan-b": 8000 },
    });
    const result = await saveClassEdit(
      {
        session: base,
        values: values(base, { amount_cents: 8000, reason: "new term" }),
        isOwner: true,
        pricingLoaded: true,
        initialChoice: CUSTOM_PRICE,
        choice: "plan-b",
      },
      api,
    );
    expect(calls.map(([kind]) => kind)).toEqual(["update", "link"]);
    expect(calls[0][1]).toMatchObject({
      payload: { amount_cents: 8000, reason: "new term" },
    });
    expect(calls[1][1]).toEqual({ id: "s-1", planId: "plan-b" });
    expect(result).toMatchObject({ linkError: null, pricingTouched: true });
    expect(stored().amount_cents).toBe(8000);
  });

  it("unlinks when the owner switches a linked class to Custom", async () => {
    const base = session({ amount_cents: 6000 });
    const { api, calls } = fakeApi({ stored: base });
    await saveClassEdit(
      {
        session: base,
        values: values(base, { amount_cents: 7000 }),
        isOwner: true,
        pricingLoaded: true,
        initialChoice: "plan-a",
        choice: CUSTOM_PRICE,
      },
      api,
    );
    expect(calls.map(([kind]) => kind)).toEqual(["update", "link"]);
    expect(calls[1][1]).toEqual({ id: "s-1", planId: null });
  });

  it("writes no link while the pricing overview has not loaded", async () => {
    const base = session();
    const { api, calls } = fakeApi({ stored: base });
    const result = await saveClassEdit(
      {
        session: base,
        values: values(base, { capacity: 20 }),
        isOwner: true,
        pricingLoaded: false,
        initialChoice: CUSTOM_PRICE,
        choice: "plan-b",
      },
      api,
    );
    expect(calls.map(([kind]) => kind)).toEqual(["update"]);
    expect(result.pricingTouched).toBe(false);
  });

  it("never links for a non-owner and never sends their fee", async () => {
    const base = session();
    const { api, calls } = fakeApi({ stored: base });
    await saveClassEdit(
      {
        session: base,
        values: values(base, { amount_cents: 1 }),
        isOwner: false,
        pricingLoaded: true,
        initialChoice: CUSTOM_PRICE,
        choice: "plan-b",
      },
      api,
    );
    expect(calls.map(([kind]) => kind)).toEqual(["update"]);
    expect(
      (calls[0][1] as { payload: EditSessionRequest }).payload,
    ).not.toHaveProperty("amount_cents");
  });

  it("returns the saved class and a link error when the link fails; a retry from it rewrites the fee", async () => {
    // Review finding: the dialog must rebase on the saved class after a
    // partial save. Class is Custom $60, owner picks plan B ($80), the link
    // fails, then the owner goes back to Custom $60.
    const base = session({ amount_cents: 6000 });
    const failing = fakeApi({
      stored: base,
      failLink: new Error("held by a scheduled change"),
    });
    const first = await saveClassEdit(
      {
        session: base,
        values: values(base, { amount_cents: 8000 }),
        isOwner: true,
        pricingLoaded: true,
        initialChoice: CUSTOM_PRICE,
        choice: "plan-b",
      },
      failing.api,
    );
    expect(first.linkError).toContain(
      "The class was saved, but the price plan was not updated",
    );
    expect(first.linkError).toContain("held by a scheduled change");
    expect(first.saved.amount_cents).toBe(8000);
    expect(first.pricingTouched).toBe(true);

    // Retry against the SAVED class (what the dialog now holds as baseline).
    const retry = fakeApi({ stored: first.saved });
    await saveClassEdit(
      {
        session: first.saved,
        values: values(first.saved, { amount_cents: 6000 }),
        isOwner: true,
        pricingLoaded: true,
        initialChoice: CUSTOM_PRICE,
        choice: CUSTOM_PRICE,
      },
      retry.api,
    );
    expect(
      (retry.calls[0][1] as { payload: EditSessionRequest }).payload
        .amount_cents,
    ).toBe(6000);
    expect(retry.stored().amount_cents).toBe(6000);
  });

  it("does not link when the PATCH itself fails", async () => {
    const base = session();
    const { api } = fakeApi({ stored: base });
    api.updateSession.mockRejectedValueOnce(new Error("boom"));
    await expect(
      saveClassEdit(
        {
          session: base,
          values: values(base, { amount_cents: 8000 }),
          isOwner: true,
          pricingLoaded: true,
          initialChoice: CUSTOM_PRICE,
          choice: "plan-b",
        },
        api,
      ),
    ).rejects.toThrow("boom");
    expect(api.setClassPlan).not.toHaveBeenCalled();
  });
});

describe("saveClassCreate", () => {
  const payload: CreateSessionRequest = {
    coach_id: "coach-1",
    title: "New",
    location: "YWCA",
    days_of_week: ["Wed"],
    start_time: "18:00",
    end_time: "18:45",
    timezone: "America/Chicago",
    capacity: 16,
    amount_cents: 8000,
  };

  it("creates with the plan's fee, then links the new class", async () => {
    const { api, calls } = fakeApi({ planPrices: { "plan-b": 8000 } });
    const result = await saveClassCreate(
      { payload, isOwner: true, choice: "plan-b", customChoice: CUSTOM_PRICE },
      api,
    );
    expect(calls.map(([kind]) => kind)).toEqual(["create", "link"]);
    expect(calls[1][1]).toEqual({ id: "s-new", planId: "plan-b" });
    expect(result.pricingTouched).toBe(true);
    expect(result.warning).toBeUndefined();
  });

  it("does not link a Custom price or a non-owner's class", async () => {
    const custom = fakeApi();
    await saveClassCreate(
      {
        payload,
        isOwner: true,
        choice: CUSTOM_PRICE,
        customChoice: CUSTOM_PRICE,
      },
      custom.api,
    );
    expect(custom.calls.map(([kind]) => kind)).toEqual(["create"]);

    const admin = fakeApi();
    const result = await saveClassCreate(
      {
        payload: { ...payload, amount_cents: null },
        isOwner: false,
        choice: "plan-b",
        customChoice: CUSTOM_PRICE,
      },
      admin.api,
    );
    expect(admin.calls.map(([kind]) => kind)).toEqual(["create"]);
    expect(result.pricingTouched).toBe(false);
  });

  it("returns a warning, not an error, when the link fails after create", async () => {
    const { api } = fakeApi({ failLink: new Error("network down") });
    const result = await saveClassCreate(
      { payload, isOwner: true, choice: "plan-b", customChoice: CUSTOM_PRICE },
      api,
    );
    expect(result.created.session_id).toBe("s-new");
    expect(result.warning).toContain(
      "The class was created, but it was not linked to the plan",
    );
    expect(result.warning).toContain("network down");
  });
});
