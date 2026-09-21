import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Issue #838: high-impact admin actions must ask a second time, in the app's
 * own dialog, naming the person/session and the consequence.
 *
 * Approve / Reject / Waitlist, pause Approve/Decline, level-up Approve,
 * session Cancel, waitlist Remove, "Skip this month", "Generate all" /
 * "Recompute all", the broadcast and email-campaign sends and the Owner-role /
 * deactivate saves all used to fire straight from the click — four of them
 * through a native `confirm()`, which has no consequence copy, no focus trap
 * and no Escape-returns-focus.
 *
 * These screens need auth and a live query client to render, so this guards
 * the source text the way `failed-loads-not-all-clear.test.ts` does.
 */

const FRONTEND = path.resolve(__dirname, "..");
const ADMIN = path.join(FRONTEND, "app", "(admin)");

function source(rel: string): string {
  return readFileSync(path.join(FRONTEND, rel), "utf8");
}

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) out.push(full);
  }
  return out;
}

/**
 * `confirm(` as a call, not as part of a longer identifier — `onConfirm(`,
 * `handleConfirm(` and friends must not match.
 */
const NATIVE_CONFIRM = /(?<![A-Za-z0-9_$.])(?:window\.)?confirm\s*\(/;

describe("no native confirm under app/(admin) (#838)", () => {
  const files = sourceFiles(ADMIN);

  it("scans a non-trivial number of admin files", () => {
    expect(files.length).toBeGreaterThan(20);
  });

  it.each(files.map((file) => ({ rel: path.relative(FRONTEND, file), file })))(
    "$rel uses the Rally dialog, not window.confirm",
    ({ file }) => {
      expect(readFileSync(file, "utf8")).not.toMatch(NATIVE_CONFIRM);
    },
  );
});

/** Every surface #838 names. Each must route its action through the dialog. */
const SURFACES: Array<{ name: string; file: string }> = [
  {
    name: "registrations decision",
    file: "app/(admin)/admin/registrations/[applicationId]/page.tsx",
  },
  { name: "payments collections", file: "app/(admin)/admin/payments/buckets/CollectionsTab.tsx" },
  { name: "sessions list", file: "app/(admin)/admin/sessions/page.tsx" },
  { name: "session detail", file: "app/(admin)/admin/sessions/[id]/page.tsx" },
  { name: "payouts", file: "app/(admin)/admin/payouts/page.tsx" },
  { name: "messages", file: "app/(admin)/admin/messages/page.tsx" },
  { name: "pathway", file: "app/(admin)/admin/pathway/page.tsx" },
  { name: "requests pauses", file: "components/admin/requests/PausesTab.tsx" },
  { name: "admissions level-ups", file: "components/admin/admissions/LevelUpsTab.tsx" },
  { name: "user detail", file: "app/(admin)/admin/users/[userId]/page.tsx" },
];

describe("high-impact admin actions confirm first (#838)", () => {
  it.each(SURFACES)("$name routes its action through ConfirmActionDialog", ({ file }) => {
    const src = source(file);
    expect(src).toContain("ConfirmActionDialog");
    expect(src).toContain("@/components/admin/confirm-action-dialog");
  });
});

describe("registration reject requires a typed reason (#838)", () => {
  const src = source("app/(admin)/admin/registrations/[applicationId]/page.tsx");

  it("never substitutes a canned reason for a blank one", () => {
    expect(src).not.toContain("Registration rejected by admin");
  });

  it("blocks the reject request until a reason is typed", () => {
    expect(src).toMatch(/!rejectReason\.trim\(\)/);
  });

  it("does not mutate straight from the panel button", () => {
    expect(src).not.toMatch(/onClick=\{\(\) => \{\s*setError\(null\);\s*rejectMutation\.mutate\(\)/);
  });
});

describe("mass sends state their audience before sending (#838)", () => {
  const src = source("app/(admin)/admin/messages/page.tsx");

  it("shows a recipient count in the confirmation", () => {
    expect(src).toContain("recipientCount");
  });
});

describe("the shared confirm dialog (#838)", () => {
  const src = source("components/admin/confirm-action-dialog.tsx");

  it("is built on the Rally modal so focus trap and Escape come for free", () => {
    expect(src).toContain("RallyModal");
    expect(src).toContain("@/components/ds/dialog-chrome");
  });

  it("states a consequence and restates the item being acted on", () => {
    expect(src).toContain("consequence");
    expect(src).toContain("subject");
  });

  it("can require a typed reason before the confirm button enables", () => {
    expect(src).toContain("reason");
    expect(src).toMatch(/disabled=\{/);
  });
});
