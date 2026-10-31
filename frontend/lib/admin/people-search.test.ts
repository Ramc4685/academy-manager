import { describe, expect, it } from "vitest";

import type { AdminStudentView, AdminUserView, BillingSetupRow } from "@/lib/api/admin";
import {
  PEOPLE_SEARCH_LIMIT,
  PEOPLE_SEARCH_MIN_CHARS,
  peopleSearchGroups,
} from "./people-search";

/**
 * Issue #865: an admin who knows a name had no way to jump to that person.
 * Students, Families and Users each had their own search box on their own
 * page, so finding "Rao" meant guessing which of the three lists the person
 * lived in first. This is the grouping the shell's one search box renders;
 * the reads behind it are the three existing list endpoints.
 */

function student(id: string, name: string, parent: string | null): AdminStudentView {
  return {
    student_id: id,
    full_name: name,
    parent_id: "p-1",
    parent_name: parent,
    parent_email: null,
    lifecycle: "active",
    active_session_count: 0,
    last_seen_at: null,
    attendance_rate: null,
    dues_status: "current",
  };
}

function family(id: string, name: string): BillingSetupRow {
  return {
    parent_id: id,
    parent_name: name,
    parent_email: `${id}@example.com`,
    students: [],
    registration_state: "card_on_file",
    card_label: null,
    card_last4: null,
    autopay_active_count: 0,
    autopay_eligible_count: 0,
    outstanding_balance_cents: 0,
    charge_invoice_id: null,
    charge_amount_cents: 0,
    charge_autopay_eligible: false,
    last_invited_at: null,
  };
}

function user(id: string, name: string, role: AdminUserView["role"]): AdminUserView {
  return {
    user_id: id,
    email: `${id}@example.com`,
    display_name: name,
    role,
    status: "active",
  };
}

describe("peopleSearchGroups (#865)", () => {
  it("says nothing until the query is worth a round trip", () => {
    expect(PEOPLE_SEARCH_MIN_CHARS).toBeGreaterThanOrEqual(2);
    expect(
      peopleSearchGroups({
        query: "r",
        students: [student("s1", "Rao", null)],
        families: [family("f1", "Rao")],
        users: [user("u1", "Rao", "coach")],
      }),
    ).toEqual([]);
  });

  it("groups students, families and staff, each linking to its own detail page", () => {
    const groups = peopleSearchGroups({
      query: "rao",
      students: [student("s1", "Amit Rao", "Neha Rao")],
      families: [family("f1", "Neha Rao")],
      users: [user("u1", "Raoul Diaz", "coach")],
    });

    expect(groups.map((g) => g.id)).toEqual(["students", "families", "staff"]);
    expect(groups[0].hits[0]).toMatchObject({
      name: "Amit Rao",
      href: "/admin/students/s1",
      detail: "Neha Rao",
    });
    expect(groups[1].hits[0]).toMatchObject({ name: "Neha Rao", href: "/admin/families/f1" });
    expect(groups[2].hits[0]).toMatchObject({ name: "Raoul Diaz", href: "/admin/users/u1" });
  });

  it("drops a group that matched nothing rather than showing an empty heading", () => {
    const groups = peopleSearchGroups({
      query: "rao",
      students: [student("s1", "Amit Rao", null)],
      families: [],
      users: [],
    });
    expect(groups.map((g) => g.id)).toEqual(["students"]);
  });

  it("filters the users list on the client — that read takes no query", () => {
    const groups = peopleSearchGroups({
      query: "diaz",
      users: [user("u1", "Raoul Diaz", "coach"), user("u2", "Amit Rao", "admin")],
    });
    expect(groups[0].hits.map((h) => h.name)).toEqual(["Raoul Diaz"]);
  });

  it("leaves parent accounts to the Families group, so one person is not two hits", () => {
    const groups = peopleSearchGroups({
      query: "rao",
      families: [family("f1", "Neha Rao")],
      users: [user("f1", "Neha Rao", "parent")],
    });
    expect(groups.map((g) => g.id)).toEqual(["families"]);
  });

  it("caps each group, so the popover cannot become the list page", () => {
    const many = Array.from({ length: 20 }, (_, i) => student(`s${i}`, `Rao ${i}`, null));
    const groups = peopleSearchGroups({ query: "rao", students: many });
    expect(groups[0].hits).toHaveLength(PEOPLE_SEARCH_LIMIT);
    expect(PEOPLE_SEARCH_LIMIT).toBeLessThanOrEqual(8);
  });

  it("escapes an id before putting it in a href", () => {
    const groups = peopleSearchGroups({ query: "rao", students: [student("a b", "Rao", null)] });
    expect(groups[0].hits[0].href).toBe("/admin/students/a%20b");
  });
});
