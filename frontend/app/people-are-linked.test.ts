import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Issue #839: Students, Families and Users describe the same people, so every
 * one of them must be one click from the next.
 *
 * The acceptance bar is "student → family money → parent login in 3 clicks or
 * fewer, with no remembered names". That needs four links that did not exist:
 * the parent cell in the students list, the parent name in the student header,
 * an account link on the family header, and a family link on a parent's user
 * page. Plus a search box on Users, which had none at all.
 *
 * These screens need auth and a live query client to render, so this guards
 * the source text the way `failed-loads-not-all-clear.test.ts` does.
 */

const APP = path.resolve(__dirname);
const FRONTEND = path.resolve(__dirname, "..");

function appSource(rel: string): string {
  return readFileSync(path.join(APP, rel), "utf8");
}

function source(rel: string): string {
  return readFileSync(path.join(FRONTEND, rel), "utf8");
}

describe("People pages link to each other (#839)", () => {
  it("students list: the parent cell is a link to the family, not plain text", () => {
    const src = appSource("(admin)/admin/students/page.tsx");
    expect(src).toContain('data-testid={`admin-students-family-link-${student.student_id}`}');
    expect(src).toMatch(/href=\{`\/admin\/families\/\$\{encodeURIComponent\(student\.parent_id\)\}`\}/);
  });

  it("student header: the parent name is a link to the family (1 click, not via the Billing tab)", () => {
    const src = appSource("(admin)/admin/students/[studentId]/page.tsx");
    expect(src).toContain('data-testid="admin-student-parent-link"');
    expect(src).toContain("/admin/families/");
  });

  it("family header: an Account & login link reaches the parent's user page", () => {
    const src = appSource("(admin)/admin/families/[parentId]/FamilyHeader.tsx");
    expect(src).toContain('data-testid="family-account-link"');
    expect(src).toMatch(/href=\{`\/admin\/users\/\$\{encodeURIComponent\(parent\.parent_id\)\}`\}/);
  });

  it("user detail: a parent's page links back to their family", () => {
    const src = appSource("(admin)/admin/users/[userId]/page.tsx");
    expect(src).toContain('data-testid="admin-user-family-link"');
    expect(src).toContain("/admin/families/");
    // Only parents have a family page; a coach must not be sent to a 404.
    expect(src).toMatch(/roles\.includes\("parent"\)/);
  });
});

describe("Users directory is searchable (#839)", () => {
  const src = () => source("components/admin/AdminUsersDirectory.tsx");

  it("renders a labelled search input", () => {
    // #897: the markup is the shared `ToolbarSearch`, which owns the <label>;
    // the directory supplies the id and the label text.
    expect(src()).toContain('id="admin-users-search"');
    expect(src()).toContain('label="Search users"');
    expect(source("components/ds/list-toolbar.tsx")).toContain("htmlFor={id}");
  });

  it("filters the rows through the shared, tested predicate", () => {
    expect(src()).toContain("filterUsersBySearch");
  });

  it("opens its create dialog from ?add=1, so /admin/users/new has one form to forward to", () => {
    expect(src()).toContain('searchParams.get("add")');
  });
});
