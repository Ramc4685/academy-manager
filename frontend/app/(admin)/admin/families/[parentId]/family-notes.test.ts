import { describe, expect, it } from "vitest";

import type { AdminUserView } from "@/lib/api/admin";
import type { FollowUp } from "@/lib/api/admin-family-crm";

import {
  MAX_NOTE_BODY_LEN,
  bucketLabel,
  bucketVariant,
  dueLabel,
  followUpDraftError,
  noteDraftError,
  queueCounts,
  sortFollowUps,
  staffName,
  staffOptions,
} from "./family-notes";

function user(id: string, name: string, roles: AdminUserView["role"][], status = "active") {
  return {
    user_id: id,
    email: `${id}@example.test`,
    display_name: name,
    role: roles[0],
    roles,
    status,
  } as AdminUserView;
}

function fu(id: string, over: Partial<FollowUp> = {}): FollowUp {
  return {
    follow_up_id: id,
    parent_id: "p-1",
    family_name: null,
    title: id,
    due_on: "2026-09-23",
    assignee_user_id: "u-1",
    status: "open",
    bucket: "today",
    created_by: "u-1",
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-09-20T10:00:00Z",
    done_at: null,
    done_by: null,
    ...over,
  };
}

describe("staff options", () => {
  it("keeps active admins and owners, sorted by name", () => {
    const options = staffOptions([
      user("u-3", "Zed Staff", ["admin"]),
      user("u-1", "Amy Owner", ["owner", "admin"]),
      user("u-2", "Coach Only", ["coach"]),
      user("u-4", "Gone Admin", ["admin"], "removed"),
      user("u-5", "Parent Coach", ["parent", "admin"]),
    ]);
    expect(options.map((o) => o.userId)).toEqual(["u-1", "u-5", "u-3"]);
  });

  it("names you, a known staff member, or a fallback", () => {
    const options = [{ userId: "u-1", label: "Amy Owner" }];
    expect(staffName(options, "u-1", "u-1")).toBe("You");
    expect(staffName(options, "u-1", "u-2")).toBe("Amy Owner");
    expect(staffName(options, "u-9", "u-2")).toBe("A staff member");
    // An automatic follow-up with no owner to assign (roadmap L3c).
    expect(staffName(options, "", "u-2")).toBe("Unassigned");
  });
});

describe("draft validation", () => {
  it("needs a note body within the cap", () => {
    expect(noteDraftError("  ")).toMatch(/Write something/);
    expect(noteDraftError("a".repeat(MAX_NOTE_BODY_LEN + 1))).toMatch(/at most/);
    expect(noteDraftError("Called back")).toBeNull();
  });

  it("needs a title, a date and an assignee", () => {
    const ok = { title: "Call", dueOn: "2026-09-30", assigneeUserId: "u-1" };
    expect(followUpDraftError(ok)).toBeNull();
    expect(followUpDraftError({ ...ok, title: " " })).toMatch(/needs doing/);
    expect(followUpDraftError({ ...ok, dueOn: "" })).toMatch(/due date/);
    expect(followUpDraftError({ ...ok, assigneeUserId: "" })).toMatch(/who/);
  });
});

describe("follow-up ordering and labels", () => {
  it("puts open rows first by due date, then done rows newest first", () => {
    const rows = sortFollowUps([
      fu("done-old", { status: "done", bucket: "done", done_at: "2026-09-01T00:00:00Z" }),
      fu("later", { due_on: "2026-10-01", bucket: "upcoming" }),
      fu("done-new", { status: "done", bucket: "done", done_at: "2026-09-22T00:00:00Z" }),
      fu("late", { due_on: "2026-09-20", bucket: "overdue" }),
    ]);
    expect(rows.map((r) => r.follow_up_id)).toEqual(["late", "later", "done-new", "done-old"]);
  });

  it("labels buckets and dates without a timezone shift", () => {
    expect(bucketLabel("overdue")).toBe("Overdue");
    expect(bucketVariant("overdue")).toBe("overdue");
    expect(bucketVariant("done")).toBe("approved");
    expect(dueLabel("2026-09-01")).toBe("Sep 1");
    expect(dueLabel("bad")).toBe("bad");
  });

  it("counts overdue and due-today rows", () => {
    expect(
      queueCounts([fu("a", { bucket: "overdue" }), fu("b"), fu("c", { bucket: "overdue" })]),
    ).toEqual({ overdue: 2, today: 1 });
  });
});
