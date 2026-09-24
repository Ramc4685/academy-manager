import { describe, expect, it } from "vitest";

import type { SetupChecklist, SetupChecklistItem } from "@/lib/api/admin";

import {
  setupChecklistProgress,
  setupChecklistRows,
  shouldShowSetupChecklist,
} from "./setup-checklist-view";

function item(partial: Partial<SetupChecklistItem>): SetupChecklistItem {
  return {
    key: "branding",
    label: "Branding",
    detail: "Add your logo.",
    status: "todo",
    href: "/admin/settings?panel=branding",
    owner_only: false,
    ...partial,
  };
}

function checklist(items: SetupChecklistItem[]): SetupChecklist {
  const done = items.filter((row) => row.status === "done").length;
  return { items, done_count: done, total: items.length, complete: done === items.length };
}

describe("shouldShowSetupChecklist", () => {
  it("hides a complete checklist", () => {
    expect(shouldShowSetupChecklist(checklist([item({ status: "done" })]))).toBe(false);
  });

  it("shows while any step is open or unknown", () => {
    expect(shouldShowSetupChecklist(checklist([item({ status: "done" }), item({ key: "waiver" })]))).toBe(true);
    expect(shouldShowSetupChecklist(checklist([item({ status: "unknown" })]))).toBe(true);
  });

  it("hides when there is no usable payload", () => {
    expect(shouldShowSetupChecklist(undefined)).toBe(false);
    expect(shouldShowSetupChecklist({} as SetupChecklist)).toBe(false);
  });
});

describe("setupChecklistRows", () => {
  const data = checklist([
    item({ key: "academy_profile", status: "done" }),
    item({ key: "stripe_connect", owner_only: true, href: "/admin/settings?panel=gateway" }),
    item({ key: "waiver", status: "unknown", href: "/admin/waivers" }),
  ]);

  it("puts open steps before done ones, keeping server order", () => {
    expect(setupChecklistRows(data, true).map((row) => row.key)).toEqual([
      "stripe_connect",
      "waiver",
      "academy_profile",
    ]);
  });

  it("drops the link on owner-only steps for a non-owner", () => {
    const rows = setupChecklistRows(data, false);
    expect(rows.find((row) => row.key === "stripe_connect")?.link).toBeNull();
    expect(rows.find((row) => row.key === "waiver")?.link).toBe("/admin/waivers");
    expect(setupChecklistRows(data, true).find((row) => row.key === "stripe_connect")?.link).toBe(
      "/admin/settings?panel=gateway",
    );
  });

  it("labels statuses in plain words", () => {
    expect(setupChecklistRows(data, true).map((row) => row.statusLabel)).toEqual([
      "To do",
      "Couldn't check",
      "Done",
    ]);
  });
});

it("summarises progress", () => {
  expect(setupChecklistProgress(checklist([item({ status: "done" }), item({})]))).toBe(
    "1 of 2 steps done",
  );
});
