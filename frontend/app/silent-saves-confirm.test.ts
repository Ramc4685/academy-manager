import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * S28: the saves persona testers could not see. Each mutation names its
 * success toast through `meta.success` (S03's MutationCache default), so the
 * toast cannot be forgotten in one onSuccess branch. These screens need auth
 * and a live query client to render, so this guards the source text.
 */

const FRONTEND = path.resolve(__dirname, "..");

const SAVES: Array<{ name: string; file: string; anchor: string; success: string }> = [
  {
    name: "replacement coach",
    file: "app/(admin)/admin/sessions/[id]/SessionEditing.tsx",
    anchor: "return updateSessionOccurrenceReplacement(",
    success: 'meta: { success: "Replacement saved" }',
  },
  {
    name: "coach roster note",
    file: "app/(coach)/coach/sessions/[id]/page.tsx",
    anchor: "createProgressNote(",
    success: 'meta: { success: "Note saved" }',
  },
  {
    name: "roster transfer",
    file: "app/(admin)/admin/sessions/[id]/dialogs.tsx",
    anchor: "transferEnrollment(enrollments[0]",
    success: 'meta: bulk ? undefined : { success: "Student moved" }',
  },
  {
    name: "student page move",
    file: "app/(admin)/admin/students/[studentId]/SessionsPanel.tsx",
    anchor: "transferEnrollment(moving!",
    success: 'meta: { success: "Student moved" }',
  },
  {
    name: "coach profile",
    file: "app/(coach)/coach/profile/page.tsx",
    anchor: "updateCoachProfile(payload)",
    success: 'meta: { success: "Profile saved" }',
  },
  {
    name: "parent profile",
    file: "app/(parent)/parent/profile/page.tsx",
    anchor: "updateParentProfile(",
    success: 'meta: { success: "Profile saved" }',
  },
  {
    name: "academy settings (profile and branding)",
    file: "components/admin/settings/academy-panel.tsx",
    anchor: "updateAdminAcademy(payload)",
    success: 'meta: { success: "Academy settings saved" }',
  },
  {
    name: "notification settings",
    file: "components/admin/settings/notify-panel.tsx",
    anchor: "updateAdminNotifications(payload)",
    success: 'meta: { success: "Notification settings saved" }',
  },
  {
    name: "self-service settings",
    file: "components/admin/settings/self-service-panel.tsx",
    anchor: "updateSelfServicePolicy(patch.payload)",
    success: 'meta: { success: "Self-service settings saved" }',
  },
];

describe("silent saves confirm (S28)", () => {
  it.each(SAVES)("$name declares its success toast on that mutation", ({ file, anchor, success }) => {
    const src = readFileSync(path.join(FRONTEND, file), "utf8");
    const at = src.indexOf(anchor);
    expect(at).toBeGreaterThan(-1);
    // The meta sits in the same useMutation call, just above its mutationFn.
    const call = src.slice(src.lastIndexOf("useMutation({", at), at);
    expect(call).toContain(success);
  });
});
