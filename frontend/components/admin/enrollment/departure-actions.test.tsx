import { describe, expect, it } from "vitest";

import {
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
