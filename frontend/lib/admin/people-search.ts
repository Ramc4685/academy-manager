import type { AdminStudentView, AdminUserView, BillingSetupRow } from "@/lib/api/admin";

import { filterUsersBySearch } from "./user-search";

/**
 * Issue #865: the grouping behind the admin shell's one people search.
 *
 * Students, Families and Users each had their own search box on their own
 * page, so an admin who knew a name had to guess which of the three lists the
 * person lived in before they could look. This composes the three reads those
 * pages already make — `listAdminStudents({ search })`,
 * `fetchBillingSetup({ q })` and `listAdminUsers()` + a client filter — into
 * one grouped answer. No new endpoint, and no new route: the results render in
 * a dialog over whatever page the admin is on.
 *
 * Pure, so the grouping rules are unit-tested without a DOM.
 */

/** Below this, a keystroke is not worth three round trips. */
export const PEOPLE_SEARCH_MIN_CHARS = 2;

/** Per group. A search box that returns a whole page is the list page. */
export const PEOPLE_SEARCH_LIMIT = 5;

export type PeopleSearchGroupId = "students" | "families" | "staff";

export interface PeopleSearchHit {
  key: string;
  name: string;
  /** One supporting line — a parent's name, an email. */
  detail: string | null;
  href: string;
}

export interface PeopleSearchGroup {
  id: PeopleSearchGroupId;
  label: string;
  hits: PeopleSearchHit[];
}

export interface PeopleSearchInput {
  query: string;
  students?: readonly AdminStudentView[];
  families?: readonly BillingSetupRow[];
  users?: readonly AdminUserView[];
}

const GROUP_LABEL: Record<PeopleSearchGroupId, string> = {
  students: "Students",
  families: "Families",
  staff: "Staff",
};

export function peopleSearchGroups({
  query,
  students = [],
  families = [],
  users = [],
}: PeopleSearchInput): PeopleSearchGroup[] {
  if (query.trim().length < PEOPLE_SEARCH_MIN_CHARS) return [];

  const studentHits: PeopleSearchHit[] = students.slice(0, PEOPLE_SEARCH_LIMIT).map((student) => ({
    key: student.student_id,
    name: student.full_name,
    detail: student.parent_name,
    href: `/admin/students/${encodeURIComponent(student.student_id)}`,
  }));

  const familyHits: PeopleSearchHit[] = families.slice(0, PEOPLE_SEARCH_LIMIT).map((family) => ({
    key: family.parent_id,
    name: family.parent_name,
    detail: family.parent_email,
    href: `/admin/families/${encodeURIComponent(family.parent_id)}`,
  }));

  // `listAdminUsers` takes no query — the same client filter the Users
  // directory runs (#839), over the same fields it prints.
  //
  // Parent accounts are deliberately left out: a parent is already the
  // Families group, whose row leads to the page where their card, autopay and
  // balance live. Listing them twice would make one person two answers.
  const staffHits: PeopleSearchHit[] = filterUsersBySearch(users, query)
    .filter((user) => user.role !== "parent")
    .slice(0, PEOPLE_SEARCH_LIMIT)
    .map((user) => ({
      key: user.user_id,
      name: user.display_name,
      detail: user.email,
      href: `/admin/users/${encodeURIComponent(user.user_id)}`,
    }));

  return (
    [
      { id: "students" as const, hits: studentHits },
      { id: "families" as const, hits: familyHits },
      { id: "staff" as const, hits: staffHits },
    ]
      // A heading over nothing reads as "searched, found none here" only if
      // the admin knows the group was searched; empty groups are just noise.
      .filter((group) => group.hits.length > 0)
      .map((group) => ({ ...group, label: GROUP_LABEL[group.id] }))
  );
}
