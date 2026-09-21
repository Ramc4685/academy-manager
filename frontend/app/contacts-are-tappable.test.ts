import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Issue #865: "every phone number is tappable".
 *
 * The working pattern existed in exactly one place — the student header wraps
 * `parent_phone` in a `tel:` — and was never extracted, so the family header
 * and both Users layouts still printed numbers as plain text, and nothing
 * anywhere offered WhatsApp.
 *
 * These screens need auth and a live query client to render, so this guards
 * the source text the way `people-are-linked.test.ts` and
 * `admin-lists-are-phone-ready.test.ts` do. The tap behaviour at a real 400px
 * viewport stays the mobile Playwright projects' job.
 */

const APP = path.resolve(__dirname);
const FRONTEND = path.resolve(__dirname, "..");

function appSource(rel: string): string {
  return readFileSync(path.join(APP, rel), "utf8");
}

function source(rel: string): string {
  return readFileSync(path.join(FRONTEND, rel), "utf8");
}

describe("the shared contact links (#865)", () => {
  it("are exported from the design system, so no surface rolls its own", () => {
    expect(source("components/ds/index.ts")).toContain(
      'export { ContactLinks, contactMenuItems } from "./contact-links"',
    );
  });

  it("derive every href from the one tested helper module", () => {
    const src = source("components/ds/contact-links.tsx");
    expect(src).toContain('from "@/lib/contact-links"');
    // No second copy of the wa.me/tel/mailto string building.
    expect(src).not.toContain("https://wa.me/");
    expect(src).not.toMatch(/`tel:\$\{/);
  });

  it("render nothing at all when there is no phone and no email", () => {
    // A bare `tel:` or `https://wa.me/` is a dead link, so the component has
    // to branch on the helper returning undefined.
    const src = source("components/ds/contact-links.tsx");
    expect(src).toContain("telHref(phone)");
    expect(src).toContain("whatsappHref(phone)");
    expect(src).toContain("mailtoHref(email)");
  });
});

describe("the overflow menu can carry an external contact link (#865)", () => {
  const src = () => source("components/ds/menu.tsx");

  it("keeps internal items on next/link and routes tel:/mailto:/wa.me through a plain anchor", () => {
    // `MenuItem.href` is a typed `Route`; a `tel:` string neither type-checks
    // nor should be handed to the Next router.
    expect(src()).toContain("externalHref?: string");
    expect(src()).toContain("item.externalHref");
    expect(src()).toContain("rel=");
  });
});

describe("every people surface makes its numbers tappable (#865)", () => {
  it("family header: phone and email are links, not interpolated text", () => {
    const src = appSource("(admin)/admin/families/[parentId]/FamilyHeader.tsx");
    expect(src).toContain("ContactLinks");
    expect(src).toContain("phone={parent.phone}");
    // The plain-text interpolation this replaces.
    expect(src).not.toContain("` · ${parent.phone}`");
  });

  it("users list: desktop cell and phone row share one contact renderer", () => {
    const src = source("components/admin/AdminUsersDirectory.tsx");
    expect(src).toContain("ContactLinks");
    // Both layouts, so desktop and mobile can never disagree.
    expect(src.match(/<ContactLinks/g)?.length).toBeGreaterThanOrEqual(2);
    expect(src).not.toContain('<td className="px-2 py-3 text-rally-muted">{user.phone || "-"}</td>');
    expect(src).not.toContain('<div>{user.phone || "No phone on file"}</div>');
  });

  it("users list: the row menu carries the contact items", () => {
    expect(source("components/admin/AdminUsersDirectory.tsx")).toContain(
      "contact={{ phone: user.phone, email: user.email }}",
    );
  });

  it("user detail: the existing tel:/mailto: gains WhatsApp through the shared component", () => {
    const src = appSource("(admin)/admin/users/[userId]/page.tsx");
    expect(src).toContain("ContactLinks");
  });

  it("student header: the parent's number gains WhatsApp too", () => {
    const src = appSource("(admin)/admin/students/[studentId]/page.tsx");
    expect(src).toContain("ContactLinks");
    expect(src).not.toContain("href={`tel:${student.parent_phone}`}");
  });
});

describe("phone rows offer contact from their 44px menu (#865)", () => {
  it("PhoneListRow takes a contact and folds it into the same menu", () => {
    const src = source("components/ds/phone-row.tsx");
    expect(src).toContain("contact?:");
    expect(src).toContain("contactMenuItems");
  });

  it("the contact items are appended, so an existing first item stays first", () => {
    // #857's helpers pick menu items by exact label; specs that click the
    // first action must not suddenly land on "Call".
    const src = source("components/ds/phone-row.tsx");
    expect(src).toMatch(/\.\.\.\(actions \?\? \[\]\)[\s\S]{0,80}contactMenuItems/);
  });

  it("students and families rows pass the contact they already display", () => {
    expect(appSource("(admin)/admin/students/page.tsx")).toContain("contact={{");
    expect(appSource("(admin)/admin/families/page.tsx")).toContain("contact={{");
  });
});
