import { describe, expect, it } from "vitest";

import {
  DEPARTURE_ACTION_DESCRIPTION,
  DEPARTURE_ACTION_LABEL,
  holdActionsFor,
  resolveDepartureActions,
  type DepartureAction,
} from "./departure-actions.logic";

describe("resolveDepartureActions", () => {
  it("renders exactly the passed actions, in order, with the vocabulary labels", () => {
    const actions: DepartureAction[] = ["transfer", "drop"];
    const resolved = resolveDepartureActions(actions, { isOwner: true, layout: "inline" });
    expect(resolved.map((r) => r.action)).toEqual(["transfer", "drop"]);
    expect(resolved.map((r) => r.label)).toEqual(["Transfer", "Drop"]);
  });

  it("never invents an action the caller did not supply", () => {
    const resolved = resolveDepartureActions(["transfer"], { isOwner: true, layout: "menu" });
    expect(resolved).toHaveLength(1);
    expect(resolved[0].action).toBe("transfer");
  });

  it("labels never say Cancel — that vocabulary is reserved for classes and dates", () => {
    for (const label of Object.values(DEPARTURE_ACTION_LABEL)) {
      expect(label.toLowerCase()).not.toContain("cancel");
    }
  });

  describe("owner gating", () => {
    it("disables delete for a non-owner but still renders it", () => {
      const [entry] = resolveDepartureActions(["delete"], { isOwner: false, layout: "menu" });
      expect(entry.disabled).toBe(true);
      expect(entry.ownerGated).toBe(true);
    });

    it("keeps delete owner-gated when the policy value has not loaded yet (#741)", () => {
      const [entry] = resolveDepartureActions(["delete"], {
        isOwner: false,
        layout: "menu",
        deleteRequiresOwner: undefined,
      });
      expect(entry.disabled).toBe(true);
      expect(entry.ownerGated).toBe(true);
    });

    it("lets a non-owner delete once the academy turns the toggle off (#741)", () => {
      const [entry] = resolveDepartureActions(["delete"], {
        isOwner: false,
        layout: "menu",
        deleteRequiresOwner: false,
      });
      expect(entry.disabled).toBe(false);
      expect(entry.ownerGated).toBe(false);
    });

    it("still gates delete for a non-owner when the toggle is on (#741)", () => {
      const [entry] = resolveDepartureActions(["delete"], {
        isOwner: false,
        layout: "menu",
        deleteRequiresOwner: true,
      });
      expect(entry.disabled).toBe(true);
      expect(entry.ownerGated).toBe(true);
    });

    it("enables delete for an owner", () => {
      const [entry] = resolveDepartureActions(["delete"], { isOwner: true, layout: "menu" });
      expect(entry.disabled).toBe(false);
      expect(entry.ownerGated).toBe(false);
    });

    it("never owner-gates a non-delete action", () => {
      const resolved = resolveDepartureActions(
        ["transfer", "hold", "return", "drop", "pause", "resume", "stop_all_classes"],
        { isOwner: false, layout: "inline" },
      );
      expect(resolved.every((entry) => !entry.ownerGated && !entry.disabled)).toBe(true);
    });
  });

  describe("overflow placement", () => {
    it("always places delete in the overflow menu, even in inline layout", () => {
      const [entry] = resolveDepartureActions(["delete"], { isOwner: true, layout: "inline" });
      expect(entry.inOverflow).toBe(true);
    });

    it("keeps non-delete actions inline in inline layout", () => {
      const resolved = resolveDepartureActions(["transfer", "drop"], {
        isOwner: true,
        layout: "inline",
      });
      expect(resolved.every((entry) => !entry.inOverflow)).toBe(true);
    });

    it("pushes every action into the overflow menu in menu layout", () => {
      const resolved = resolveDepartureActions(["transfer", "drop", "pause"], {
        isOwner: true,
        layout: "menu",
      });
      expect(resolved.every((entry) => entry.inOverflow)).toBe(true);
    });
  });

  describe("danger styling", () => {
    it("flags drop, delete and stop_all_classes as danger actions", () => {
      const resolved = resolveDepartureActions(["drop", "delete", "stop_all_classes"], {
        isOwner: true,
        layout: "menu",
      });
      expect(resolved.every((entry) => entry.danger)).toBe(true);
    });

    it("does not flag transfer, hold, return, pause or resume as danger", () => {
      const resolved = resolveDepartureActions(["transfer", "hold", "return", "pause", "resume"], {
        isOwner: true,
        layout: "inline",
      });
      expect(resolved.every((entry) => !entry.danger)).toBe(true);
    });
  });
});

describe("action descriptions (#859)", () => {
  const ALL_ACTIONS = Object.keys(DEPARTURE_ACTION_LABEL) as DepartureAction[];

  it("gives every action a one-line description that is not just the label", () => {
    for (const action of ALL_ACTIONS) {
      const description = DEPARTURE_ACTION_DESCRIPTION[action];
      expect(description.length).toBeGreaterThan(0);
      expect(description).not.toBe(DEPARTURE_ACTION_LABEL[action]);
    }
  });

  it("carries the description through resolveDepartureActions", () => {
    const resolved = resolveDepartureActions(["pause", "drop", "delete"], {
      isOwner: true,
      layout: "menu",
    });
    for (const entry of resolved) {
      expect(entry.description).toBe(DEPARTURE_ACTION_DESCRIPTION[entry.action]);
      expect(entry.description).not.toBe(entry.label);
    }
  });

  it("says whether the family is emailed, for every action", () => {
    for (const action of ALL_ACTIONS) {
      expect(DEPARTURE_ACTION_DESCRIPTION[action]).toMatch(/email/i);
    }
  });

  it("matches the notifications the backend actually sends", () => {
    // Family email: WithdrawEnrollment -> HoldNotifier.enrollment_dropped,
    // StartHold -> hold_started, ReturnFromHold -> enrollment_returned.
    for (const action of ["drop", "hold", "return", "stop_all_classes"] as DepartureAction[]) {
      expect(DEPARTURE_ACTION_DESCRIPTION[action]).toMatch(/the family is emailed/i);
    }
    // Coaches only (RosterChangeNotifier) — no family email on these paths.
    for (const action of [
      "delete",
      "transfer",
      "pause",
      "resume",
      "undo_scheduled_drop",
    ] as DepartureAction[]) {
      expect(DEPARTURE_ACTION_DESCRIPTION[action]).toMatch(/the family is not emailed/i);
    }
  });

  it("says what happens to the seat and to billing", () => {
    for (const action of ["hold", "drop", "pause", "resume", "delete"] as DepartureAction[]) {
      expect(DEPARTURE_ACTION_DESCRIPTION[action]).toMatch(/seat|billing/i);
    }
  });

  it("never reuses another action's label, which would make two menu items ambiguous", () => {
    // Playwright matches a menuitem's accessible name by substring, and the
    // description is part of that name: a description containing "Pause" would
    // make `getByRole("menuitem", { name: "Pause" })` strict-mode-fail against
    // a sibling item.
    for (const action of ALL_ACTIONS) {
      const description = DEPARTURE_ACTION_DESCRIPTION[action].toLowerCase();
      for (const other of ALL_ACTIONS) {
        if (other === action) continue;
        expect(description).not.toContain(DEPARTURE_ACTION_LABEL[other].toLowerCase());
      }
    }
  });
});

describe("holdActionsFor", () => {
  it("offers hold on an active row", () => {
    expect(holdActionsFor("active")).toEqual(["hold"]);
  });

  it("offers return on a held row — the #714 gap this slice closes", () => {
    expect(holdActionsFor("held")).toEqual(["return"]);
  });

  it("never offers hold on a held row, nor return on an active one", () => {
    expect(holdActionsFor("held")).not.toContain("hold");
    expect(holdActionsFor("active")).not.toContain("return");
  });

  it("leaves paused alone — Pause/Resume is untouched by this slice", () => {
    expect(holdActionsFor("paused")).toEqual([]);
  });

  it("adds nothing mid-reclaim", () => {
    expect(holdActionsFor("reclaim_pending")).toEqual([]);
  });

  it("adds nothing to a row that has already left", () => {
    for (const status of ["cancelled", "deleted", "withdrawn", "dropped"]) {
      expect(holdActionsFor(status)).toEqual([]);
    }
  });

  it("does not throw on an unknown status", () => {
    expect(holdActionsFor("something_new")).toEqual([]);
    expect(holdActionsFor("")).toEqual([]);
  });
});

describe("re_enroll (#827)", () => {
  it("is labelled Re-enroll and is not a destructive action", () => {
    const [resolved] = resolveDepartureActions(["re_enroll"], {
      isOwner: false,
      layout: "menu",
    });
    expect(resolved.label).toBe("Re-enroll");
    expect(resolved.danger).toBe(false);
  });

  it("stays open to admins — putting a student back needs no owner scope", () => {
    const [resolved] = resolveDepartureActions(["re_enroll"], {
      isOwner: false,
      layout: "menu",
      deleteRequiresOwner: true,
    });
    expect(resolved.disabled).toBe(false);
    expect(resolved.ownerGated).toBe(false);
  });
});
